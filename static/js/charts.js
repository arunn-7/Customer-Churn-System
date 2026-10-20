/* Dependency-free SVG chart primitives.
   Everything scales with viewBox so charts stay sharp on any screen. */
(function (global) {
  "use strict";

  const PALETTE = {
    primary: "#4f8cff",
    danger: "#f2555a",
    success: "#34c98b",
    warning: "#f0a13c",
    accent: "#8b7cff",
    grid: "#24314f",
    text: "#94a3c4",
  };

  const SERIES = [PALETTE.primary, PALETTE.danger, PALETTE.success, PALETTE.warning, PALETTE.accent];

  function empty(container, message) {
    container.innerHTML = '<p class="muted">' + (message || "No data available.") + "</p>";
  }

  function svgEl(name, attrs) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.keys(attrs || {}).forEach(function (key) {
      node.setAttribute(key, attrs[key]);
    });
    return node;
  }

  /** Horizontal bar chart showing churn rate % per category, with counts. */
  function barChart(container, rows, options) {
    const opts = options || {};
    if (!rows || !rows.length) return empty(container);

    const width = 560;
    const rowHeight = 34;
    const labelWidth = 150;
    const valueWidth = 96;
    const barWidth = width - labelWidth - valueWidth;
    const height = rows.length * rowHeight + 8;
    const max = Math.max.apply(null, rows.map(function (r) { return r.churn_rate; })) || 1;

    const svg = svgEl("svg", { viewBox: "0 0 " + width + " " + height, role: "img" });

    rows.forEach(function (row, i) {
      const y = i * rowHeight + 4;
      const barH = 18;
      const barY = y + (rowHeight - barH) / 2 - 4;
      const w = Math.max(2, (row.churn_rate / max) * barWidth);
      const colour = row.churn_rate >= 40 ? PALETTE.danger
                   : row.churn_rate >= 20 ? PALETTE.warning
                   : PALETTE.success;

      const label = svgEl("text", { x: 0, y: barY + 14, fill: PALETTE.text, "font-size": 12 });
      label.textContent = row.label.length > 21 ? row.label.slice(0, 20) + "…" : row.label;
      svg.appendChild(label);

      svg.appendChild(svgEl("rect", {
        x: labelWidth, y: barY, width: barWidth, height: barH,
        rx: 4, fill: PALETTE.grid, opacity: 0.55,
      }));

      const rect = svgEl("rect", {
        x: labelWidth, y: barY, width: 0, height: barH, rx: 4, fill: colour,
      });
      svg.appendChild(rect);
      requestAnimationFrame(function () {
        rect.style.transition = "width .6s cubic-bezier(.22,1,.36,1)";
        rect.setAttribute("width", w);
      });

      const value = svgEl("text", {
        x: width - 4, y: barY + 14, fill: PALETTE.text,
        "font-size": 12, "text-anchor": "end",
      });
      value.textContent = row.churn_rate.toFixed(1) + "%  ·  " + row.count.toLocaleString();
      svg.appendChild(value);
    });

    container.innerHTML = "";
    container.appendChild(svg);
  }

  /** Stacked column chart: retained vs churned counts per category. */
  function stackedChart(container, rows, options) {
    const opts = options || {};
    if (!rows || !rows.length) return empty(container);

    const width = 560;
    const height = 230;
    const padTop = 14;
    const padBottom = 54;
    const padLeft = 8;
    const padRight = 8;
    const plotW = width - padLeft - padRight;
    const plotH = height - padTop - padBottom;

    const totals = rows.map(function (r) { return r.count; });
    const max = Math.max.apply(null, totals) || 1;
    const slot = plotW / rows.length;
    const barW = Math.min(52, slot * 0.6);

    const svg = svgEl("svg", { viewBox: "0 0 " + width + " " + height, role: "img" });

    for (let g = 0; g <= 4; g++) {
      const y = padTop + (plotH / 4) * g;
      svg.appendChild(svgEl("line", {
        x1: padLeft, y1: y, x2: width - padRight, y2: y,
        stroke: PALETTE.grid, "stroke-width": 1, opacity: 0.6,
      }));
    }

    rows.forEach(function (row, i) {
      const x = padLeft + slot * i + (slot - barW) / 2;
      const fullH = (row.count / max) * plotH;
      const churnH = row.count ? (row.churned / row.count) * fullH : 0;

      svg.appendChild(svgEl("rect", {
        x: x, y: padTop + plotH - fullH, width: barW, height: fullH,
        rx: 4, fill: PALETTE.primary, opacity: 0.8,
      }));
      svg.appendChild(svgEl("rect", {
        x: x, y: padTop + plotH - churnH, width: barW, height: churnH,
        rx: 4, fill: PALETTE.danger,
      }));

      const label = svgEl("text", {
        x: x + barW / 2, y: height - padBottom + 18,
        fill: PALETTE.text, "font-size": 11, "text-anchor": "middle",
      });
      const text = String(row.label);
      label.textContent = text.length > 13 ? text.slice(0, 12) + "…" : text;
      svg.appendChild(label);

      const rate = svgEl("text", {
        x: x + barW / 2, y: padTop + plotH - fullH - 6,
        fill: PALETTE.text, "font-size": 10.5, "text-anchor": "middle",
      });
      rate.textContent = row.churn_rate.toFixed(0) + "%";
      svg.appendChild(rate);
    });

    container.innerHTML = "";
    container.appendChild(svg);

    const legend = document.createElement("div");
    legend.className = "chart-legend";
    legend.innerHTML =
      '<span><i style="background:' + PALETTE.primary + '"></i>Retained</span>' +
      '<span><i style="background:' + PALETTE.danger + '"></i>Churned</span>' +
      (opts.note ? "<span>" + opts.note + "</span>" : "");
    container.appendChild(legend);
  }

  /** Donut chart for a single split (e.g. churned vs retained). */
  function donutChart(container, segments, centreValue, centreLabel) {
    if (!segments || !segments.length) return empty(container);

    const size = 200;
    const radius = 78;
    const stroke = 26;
    const circumference = 2 * Math.PI * radius;
    const total = segments.reduce(function (sum, s) { return sum + s.value; }, 0) || 1;

    const svg = svgEl("svg", { viewBox: "0 0 " + size + " " + size, role: "img" });
    let offset = 0;

    segments.forEach(function (segment) {
      const share = segment.value / total;
      const circle = svgEl("circle", {
        cx: size / 2, cy: size / 2, r: radius,
        fill: "none", stroke: segment.colour, "stroke-width": stroke,
        "stroke-dasharray": (share * circumference) + " " + circumference,
        "stroke-dashoffset": -offset * circumference,
        transform: "rotate(-90 " + size / 2 + " " + size / 2 + ")",
      });
      svg.appendChild(circle);
      offset += share;
    });

    const value = svgEl("text", {
      x: size / 2, y: size / 2 + 2, "text-anchor": "middle",
      fill: "#e8edf7", "font-size": 30, "font-weight": 700,
    });
    value.textContent = centreValue;
    svg.appendChild(value);

    const label = svgEl("text", {
      x: size / 2, y: size / 2 + 26, "text-anchor": "middle",
      fill: PALETTE.text, "font-size": 12,
    });
    label.textContent = centreLabel || "";
    svg.appendChild(label);

    container.innerHTML = "";
    container.appendChild(svg);
  }

  /** Semicircular gauge for a single probability (0-100). */
  function gauge(container, percent, level) {
    const size = 150;
    const radius = 56;
    const stroke = 14;
    const ratio = Math.max(0, Math.min(100, percent)) / 100;
    const cy = radius + stroke / 2 + 2;

    const colour = level === "high" ? PALETTE.danger
                 : level === "medium" ? PALETTE.warning
                 : PALETTE.success;

    // SVG's y axis points down, so a semicircle opening upward runs from
    // 180deg (left) through 270deg (top) to 360deg (right).
    const height = cy + stroke + 6;
    const svg = svgEl("svg", { viewBox: "0 0 " + size + " " + height, role: "img" });

    svg.appendChild(svgEl("path", {
      d: describeArc(size / 2, cy, radius, 180, 360),
      fill: "none", stroke: PALETTE.grid, "stroke-width": stroke, "stroke-linecap": "round",
    }));

    svg.appendChild(svgEl("path", {
      d: describeArc(size / 2, cy, radius, 180, 180 + 180 * ratio),
      fill: "none", stroke: colour, "stroke-width": stroke, "stroke-linecap": "round",
    }));

    const value = svgEl("text", {
      x: size / 2, y: cy - 4, "text-anchor": "middle",
      fill: colour, "font-size": 27, "font-weight": 700,
    });
    value.textContent = percent.toFixed(1) + "%";
    svg.appendChild(value);

    const label = svgEl("text", {
      x: size / 2, y: cy + 13, "text-anchor": "middle",
      fill: PALETTE.text, "font-size": 10.5,
    });
    label.textContent = "churn probability";
    svg.appendChild(label);

    container.innerHTML = "";
    container.appendChild(svg);
  }

  function polar(cx, cy, r, angleDeg) {
    const rad = (angleDeg * Math.PI) / 180;
    return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
  }

  function describeArc(cx, cy, r, startAngle, endAngle) {
    const start = polar(cx, cy, r, startAngle);
    const end = polar(cx, cy, r, endAngle);
    const large = endAngle - startAngle <= 180 ? 0 : 1;
    return "M " + start.x + " " + start.y +
           " A " + r + " " + r + " 0 " + large + " 0 " + end.x + " " + end.y;
  }

  global.Charts = {
    PALETTE: PALETTE,
    SERIES: SERIES,
    barChart: barChart,
    stackedChart: stackedChart,
    donutChart: donutChart,
    gauge: gauge,
    empty: empty,
  };
})(window);
