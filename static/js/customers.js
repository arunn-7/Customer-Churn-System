/* Customer directory: paginated, searchable, sortable table from /api/customers. */
(function () {
  "use strict";

  var table = document.getElementById("customer-table");
  if (!table) return;

  var body = document.getElementById("customer-body");
  var errorBox = document.getElementById("customer-error");
  var searchInput = document.getElementById("search-input");
  var churnFilter = document.getElementById("churn-filter");
  var perPageSelect = document.getElementById("per-page");
  var prevBtn = document.getElementById("prev-page");
  var nextBtn = document.getElementById("next-page");
  var pageLabel = document.getElementById("page-label");
  var resultCount = document.getElementById("result-count");

  var state = { page: 1, per_page: 20, sort: "customer_id", order: "asc", search: "", churn: "" };

  var COLUMNS = [
    "customer_id", "gender", "tenure", "contract",
    "internet_service", "payment_method", "monthly_charges", "total_charges", "churn"
  ];

  function money(value) {
    return "$" + API.formatNumber(value, 2);
  }

  function renderRows(customers) {
    body.innerHTML = "";

    if (!customers.length) {
      var row = document.createElement("tr");
      var cell = document.createElement("td");
      cell.colSpan = COLUMNS.length;
      cell.className = "muted";
      cell.style.textAlign = "center";
      cell.style.padding = "34px";
      cell.textContent = "No customers match your search.";
      row.appendChild(cell);
      body.appendChild(row);
      return;
    }

    customers.forEach(function (c) {
      var tr = document.createElement("tr");

      COLUMNS.forEach(function (key) {
        var td = document.createElement("td");
        var value = c[key];

        if (key === "monthly_charges" || key === "total_charges") {
          td.textContent = money(value);
        } else if (key === "churn") {
          var chip = document.createElement("span");
          chip.className = "chip " + (value === "Yes" ? "chip-yes" : "chip-no");
          chip.textContent = value === "Yes" ? "Churned" : "Retained";
          td.appendChild(chip);
        } else if (key === "tenure") {
          td.textContent = value + " mo";
        } else if (key === "payment_method") {
          td.textContent = API.escapeHtml(value);
        } else {
          td.textContent = API.escapeHtml(value);
        }
        tr.appendChild(td);
      });

      body.appendChild(tr);
    });
  }

  function renderPager(pagination) {
    var from = pagination.total === 0 ? 0 : (pagination.page - 1) * pagination.per_page + 1;
    var to = Math.min(pagination.page * pagination.per_page, pagination.total);

    resultCount.textContent = pagination.total === 0
      ? "No customers found"
      : "Showing " + from + "–" + to + " of " + pagination.total.toLocaleString() + " customers";

    pageLabel.textContent = "Page " + pagination.page + " of " + pagination.pages;
    prevBtn.disabled = !pagination.has_prev;
    nextBtn.disabled = !pagination.has_next;
  }

  function updateSortIndicators() {
    table.querySelectorAll("th.sortable").forEach(function (th) {
      var isSorted = th.dataset.sort === state.sort;
      th.classList.toggle("sorted", isSorted);
      th.classList.toggle("asc", isSorted && state.order === "asc");
      th.classList.toggle("desc", isSorted && state.order === "desc");
    });
  }

  function skeleton() {
    body.innerHTML = "";
    for (var i = 0; i < 6; i++) {
      var tr = document.createElement("tr");
      tr.className = "skeleton-row";
      var td = document.createElement("td");
      td.colSpan = COLUMNS.length;
      tr.appendChild(td);
      body.appendChild(tr);
    }
  }

  function load() {
    API.clearError(errorBox);
    skeleton();

    var params = new URLSearchParams({
      page: state.page,
      per_page: state.per_page,
      sort: state.sort,
      order: state.order,
      search: state.search,
      churn: state.churn,
    });

    API.request("/api/customers?" + params.toString())
      .then(function (data) {
        renderRows(data.customers);
        renderPager(data.pagination);
        updateSortIndicators();
      })
      .catch(function (err) {
        body.innerHTML = "";
        API.showError(errorBox, err);
      });
  }

  /* ------------------------------------------------------------- events -- */

  searchInput.addEventListener("input", API.debounce(function () {
    state.search = searchInput.value;
    state.page = 1;
    load();
  }, 320));

  churnFilter.addEventListener("change", function () {
    state.churn = churnFilter.value;
    state.page = 1;
    load();
  });

  perPageSelect.addEventListener("change", function () {
    state.per_page = parseInt(perPageSelect.value, 10) || 20;
    state.page = 1;
    load();
  });

  prevBtn.addEventListener("click", function () {
    if (state.page > 1) { state.page--; load(); }
  });

  nextBtn.addEventListener("click", function () {
    state.page++; load();
  });

  table.querySelectorAll("th.sortable").forEach(function (th) {
    th.addEventListener("click", function () {
      var column = th.dataset.sort;
      if (state.sort === column) {
        state.order = state.order === "asc" ? "desc" : "asc";
      } else {
        state.sort = column;
        state.order = "asc";
      }
      state.page = 1;
      load();
    });
  });

  load();
})();
