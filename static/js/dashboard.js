/* Dashboard: KPI cards + charts from /api/stats and /api/analytics. */
(function () {
  "use strict";

  var grid = document.getElementById("kpi-grid");
  var errorBox = document.getElementById("dashboard-error");
  if (!grid) return;

  function kpiCard(label, value, foot, tone) {
    const card = document.createElement("div");
    card.className = "card kpi" + (tone ? " is-" + tone : "");
    card.innerHTML =
      '<span class="kpi-accent"></span>' +
      '<div class="kpi-label">' + API.escapeHtml(label) + "</div>" +
      '<div class="kpi-value">' + API.escapeHtml(value) + "</div>" +
      '<div class="kpi-foot">' + foot + "</div>";
    return card;
  }

  function renderStats(stats) {
    grid.innerHTML = "";

    grid.appendChild(kpiCard(
      "Total Customers",
      API.formatNumber(stats.total_customers, 0),
      API.formatNumber(stats.avg_tenure, 1) + " months average tenure",
      "primary"
    ));

    grid.appendChild(kpiCard(
      "Churned",
      API.formatNumber(stats.churned, 0),
      API.formatNumber(stats.avg_monthly_charges, 2) + " avg monthly bill",
      "danger"
    ));

    grid.appendChild(kpiCard(
      "Retained",
      API.formatNumber(stats.retained, 0),
      "<span class='down'>" + stats.retention_rate + "%</span> retention rate",
      "success"
    ));

    grid.appendChild(kpiCard(
      "Churn Rate",
      stats.churn_rate + "%",
      "<span class='up'>$" + API.formatNumber(stats.revenue_at_risk, 0) + "</span> monthly revenue at risk",
      stats.churn_rate >= 25 ? "danger" : "warning"
    ));
  }

  function renderCharts(data) {
    Charts.barChart(document.getElementById("chart-contract"), data.by_contract);
    Charts.barChart(document.getElementById("chart-internet"), data.by_internet_service);
    Charts.barChart(document.getElementById("chart-payment"), data.by_payment_method);
    Charts.stackedChart(document.getElementById("chart-tenure"), data.by_tenure_band,
      { note: "bar height = customers, red = churned" });
    Charts.barChart(document.getElementById("chart-charges"), data.by_charges_band);
    Charts.barChart(document.getElementById("chart-support"), data.by_tech_support);
  }

  Promise.all([
    API.request("/api/stats"),
    API.request("/api/analytics"),
  ])
    .then(function (results) {
      renderStats(results[0].stats);
      renderCharts(results[1].analytics);
    })
    .catch(function (err) {
      grid.innerHTML = "";
      API.showError(errorBox, err);
    });
})();
