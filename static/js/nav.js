/* Sidebar toggle + backend health indicator, present on every page. */
(function () {
  "use strict";

  var sidebar = document.getElementById("sidebar");
  var scrim = document.getElementById("scrim");
  var toggle = document.getElementById("nav-toggle");

  function closeNav() {
    if (sidebar) sidebar.classList.remove("open");
    if (scrim) scrim.classList.remove("show");
  }

  if (toggle) {
    toggle.addEventListener("click", function () {
      if (!sidebar) return;
      sidebar.classList.toggle("open");
      if (scrim) scrim.classList.toggle("show", sidebar.classList.contains("open"));
    });
  }
  if (scrim) scrim.addEventListener("click", closeNav);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeNav();
  });

  var dot = document.getElementById("health-dot");
  var text = document.getElementById("health-text");

  fetch("/api/stats")
    .then(function (r) { return r.ok; })
    .then(function (ok) {
      if (!dot || !text) return;
      dot.classList.add(ok ? "dot-ok" : "dot-bad");
      dot.classList.remove(ok ? "dot-bad" : "dot-ok");
      text.textContent = ok ? "Database connected" : "Database unavailable";
    })
    .catch(function () {
      if (!dot || !text) return;
      dot.classList.add("dot-bad");
      dot.classList.remove("dot-ok");
      text.textContent = "Service unreachable";
    });
})();
