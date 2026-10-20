/* Prediction form.
   Field list, labels and options come from GET /predict/schema, so the form
   always matches the persisted model instead of a hardcoded copy. */
(function () {
  "use strict";

  var form = document.getElementById("predict-form");
  if (!form) return;

  var groupsEl = document.getElementById("form-groups");
  var submitBtn = document.getElementById("submit-btn");
  var resetBtn = document.getElementById("reset-btn");

  var resultCard = document.getElementById("result-card");
  var resultEmpty = document.getElementById("result-empty");
  var resultLoading = document.getElementById("result-loading");
  var resultError = document.getElementById("result-error");

  var schema = null;

  /* ------------------------------------------------------------- schema -- */

  function buildForm(payload) {
    schema = payload;
    groupsEl.innerHTML = "";
    var fields = payload.fields || [];

    payload.groups.forEach(function (group) {
      var inGroup = fields.filter(function (f) { return f.group === group.key; });
      if (!inGroup.length) return;

      var title = document.createElement("div");
      title.className = "field-group-title";
      title.textContent = group.title;
      groupsEl.appendChild(title);

      var grid = document.createElement("div");
      grid.className = "field-grid";

      inGroup.forEach(function (field) {
        grid.appendChild(buildField(field));
      });
      groupsEl.appendChild(grid);
    });
  }

  function buildField(field) {
    var wrapper = document.createElement("div");
    wrapper.className = "field";
    wrapper.dataset.field = field.key;

    var id = "f-" + field.key;
    var label = document.createElement("label");
    label.setAttribute("for", id);
    label.innerHTML = API.escapeHtml(field.label) + (field.required ? ' <span class="req">*</span>' : "");
    wrapper.appendChild(label);

    var control;
    if (field.type === "select") {
      control = document.createElement("select");
      control.id = id;
      field.options.forEach(function (option) {
        var opt = document.createElement("option");
        opt.value = option.value;
        opt.textContent = option.label;
        control.appendChild(opt);
      });
    } else {
      control = document.createElement("input");
      control.id = id;
      control.type = "number";
      control.step = field.step || 1;
      if (field.min !== undefined) control.min = field.min;
      if (field.max !== undefined) control.max = field.max;
      control.placeholder = field.min !== undefined ? String(field.min) + " - " + field.max : "";
    }
    control.name = field.key;
    control.dataset.type = field.type;
    wrapper.appendChild(control);

    if (field.help) {
      var hint = document.createElement("span");
      hint.className = "hint";
      hint.textContent = field.help;
      wrapper.appendChild(hint);
    }

    var error = document.createElement("span");
    error.className = "err-msg";
    wrapper.appendChild(error);

    control.addEventListener("input", function () { clearFieldError(wrapper); });
    control.addEventListener("change", function () { clearFieldError(wrapper); });

    return wrapper;
  }

  function clearFieldError(wrapper) {
    if (!wrapper) return;
    wrapper.classList.remove("invalid");
    var msg = wrapper.querySelector(".err-msg");
    if (msg) msg.textContent = "";
  }

  /* ---------------------------------------------------------- validation -- */

  function collect() {
    var payload = {};
    var invalid = false;

    (schema.fields || []).forEach(function (field) {
      var wrapper = groupsEl.querySelector('[data-field="' + field.key + '"]');
      var control = wrapper ? wrapper.querySelector("input, select") : null;
      if (!control) return;

      var raw = control.value;

      if (field.type === "number") {
        if (raw === "") {
          if (field.required) {
            markInvalid(wrapper, field.label + " is required");
            invalid = true;
          }
          return;
        }
        var num = Number(raw);
        if (isNaN(num)) {
          markInvalid(wrapper, field.label + " must be a number");
          invalid = true;
          return;
        }
        if (field.min !== undefined && num < field.min) {
          markInvalid(wrapper, field.label + " must be at least " + field.min);
          invalid = true;
          return;
        }
        if (field.max !== undefined && num > field.max) {
          markInvalid(wrapper, field.label + " must be at most " + field.max);
          invalid = true;
          return;
        }
        payload[field.key] = num;
        return;
      }

      if (field.required && (raw === "" || raw === null)) {
        markInvalid(wrapper, field.label + " is required");
        invalid = true;
        return;
      }
      payload[field.key] = raw;
    });

    return { payload: payload, invalid: invalid };
  }

  function markInvalid(wrapper, message) {
    if (!wrapper) return;
    wrapper.classList.add("invalid");
    var msg = wrapper.querySelector(".err-msg");
    if (msg) msg.textContent = message;
  }

  function markServerErrors(err) {
    clearAllFieldErrors();
    (err.details || []).forEach(function (item) {
      if (!item.field) return;
      var key = keyForLabel(item.field);
      var wrapper = key ? groupsEl.querySelector('[data-field="' + key + '"]') : null;
      if (wrapper) markInvalid(wrapper, item.issue);
    });
  }

  function keyForLabel(label) {
    var match = (schema.fields || []).filter(function (f) { return f.label === label; });
    return match.length ? match[0].key : null;
  }

  function clearAllFieldErrors() {
    groupsEl.querySelectorAll(".field").forEach(clearFieldError);
  }

  /* ------------------------------------------------------------ rendering -- */

  /** Toggle the submit button + spinner only. Panel visibility is handled by callers. */
  function setLoading(on) {
    resultLoading.hidden = !on;
    submitBtn.disabled = on;
    submitBtn.querySelector(".spinner").hidden = !on;
    submitBtn.querySelector(".btn-label").textContent = on ? "Predicting…" : "Predict churn risk";
  }

  function renderResult(data) {
    var prediction = data.prediction;
    var risk = data.risk;

    var badge = document.getElementById("risk-badge");
    badge.className = "badge badge-level-" + risk.level;
    badge.textContent = risk.label;

    document.getElementById("result-verdict").textContent =
      prediction.churn === "Yes" ? "Likely to churn" : "Likely to stay";

    document.getElementById("result-action").textContent = risk.action;
    document.getElementById("result-prob").textContent = prediction.churn_probability + "%";
    document.getElementById("result-label").textContent = prediction.churn === "Yes" ? "Yes" : "No";

    Charts.gauge(
      document.getElementById("result-gauge"),
      prediction.churn_probability,
      risk.level
    );

    renderFactors(data.factors || []);

    resultEmpty.hidden = true;
    resultCard.hidden = false;
  }

  function renderFactors(factors) {
    var list = document.getElementById("factor-list");
    list.innerHTML = "";
    if (!factors.length) {
      list.innerHTML = '<li class="muted">No contributing factors returned.</li>';
      return;
    }

    var max = factors.reduce(function (acc, f) {
      return Math.max(acc, Math.abs(f.impact));
    }, 0) || 1;

    factors.forEach(function (factor) {
      var up = factor.impact > 0;
      var width = Math.max(3, (Math.abs(factor.impact) / max) * 100);

      var li = document.createElement("li");
      li.className = "factor";

      var top = document.createElement("div");
      top.className = "factor-top";

      var name = document.createElement("span");
      name.className = "factor-name";
      name.textContent = factor.label;

      var impact = document.createElement("span");
      impact.className = "factor-impact " + (up ? "up" : "down");
      impact.textContent = (up ? "+" : "") + factor.impact.toFixed(1) + " pp";

      top.appendChild(name);
      top.appendChild(impact);

      var detail = document.createElement("div");
      detail.className = "factor-val";
      detail.textContent = factor.value +
        " (baseline: " + factor.baseline + ") · " +
        (up ? "raises churn risk" : "reduces churn risk");

      var bar = document.createElement("div");
      bar.className = "factor-bar";
      var fill = document.createElement("span");
      fill.className = up ? "up" : "down";
      fill.style.width = width + "%";
      bar.appendChild(fill);

      li.appendChild(top);
      li.appendChild(detail);
      li.appendChild(bar);
      list.appendChild(li);
    });
  }

  /* ---------------------------------------------------------------- submit -- */

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (!schema) return;

    API.clearError(resultError);
    clearAllFieldErrors();

    var check = collect();
    if (check.invalid) {
      var firstBad = groupsEl.querySelector(".field.invalid input, .field.invalid select");
      if (firstBad) firstBad.focus();
      return;
    }

    setLoading(true);
    resultCard.hidden = true;
    resultEmpty.hidden = true;

    // POST /predict gives the canonical result; /predict/explain adds the
    // risk band and the factor breakdown for the same payload.
    Promise.all([
      API.request("/predict", { method: "POST", body: check.payload }),
      API.request("/predict/explain", { method: "POST", body: check.payload }),
    ])
      .then(function (results) {
        setLoading(false);
        renderResult(results[1]);
      })
      .catch(function (err) {
        setLoading(false);
        resultCard.hidden = true;
        resultEmpty.hidden = false;
        if (err.code === "VALIDATION_ERROR") {
          markServerErrors(err);
        }
        API.showError(resultError, err);
      });
  });

  resetBtn.addEventListener("click", function () {
    form.reset();
    clearAllFieldErrors();
    API.clearError(resultError);
    resultCard.hidden = true;
    resultEmpty.hidden = false;
    resultLoading.hidden = true;
  });

  /* ------------------------------------------------------------------ init -- */

  API.request("/predict/schema")
    .then(buildForm)
    .catch(function (err) {
      API.showError(resultError, err);
    });
})();
