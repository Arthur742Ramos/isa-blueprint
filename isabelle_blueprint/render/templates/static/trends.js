// Trend chart — renders a vanilla SVG line chart of coverage and problem
// counts over time using the project's trends.json.
//
// No-op on pages without the trend chart host.
(function () {
  "use strict";

  const host = document.querySelector("[data-trend-chart-host]");
  const legend = document.querySelector("[data-trend-chart-legend]");
  if (!host) {
    return;
  }
  const trendsUrl = new URL("trends.json", window.location.href).toString();

  fetch(trendsUrl, { credentials: "same-origin" })
    .then((res) => (res.ok ? res.json() : Promise.reject(res.status)))
    .then((data) => {
      const entries = (data && data.entries) || [];
      if (!entries.length) {
        renderEmpty("No history yet.");
        return;
      }
      renderChart(entries);
    })
    .catch(() => {
      renderEmpty("Could not load trends.json.");
    });

  function renderEmpty(message) {
    host.innerHTML = "";
    const p = document.createElement("p");
    p.className = "trend-chart-empty";
    p.textContent = message;
    host.appendChild(p);
  }

  function renderChart(entries) {
    const width = 720;
    const height = 280;
    const padding = { top: 20, right: 50, bottom: 40, left: 50 };
    const innerW = width - padding.left - padding.right;
    const innerH = height - padding.top - padding.bottom;

    const coverage = entries.map((e) =>
      typeof e.coverage_percent === "number" ? e.coverage_percent : 0
    );
    const problems = entries.map((e) =>
      typeof e.problem_count === "number" ? e.problem_count : 0
    );
    const maxProblems = Math.max(1, ...problems);

    function xFor(i) {
      if (entries.length <= 1) {
        return padding.left + innerW / 2;
      }
      return padding.left + (i / (entries.length - 1)) * innerW;
    }
    function yForCoverage(v) {
      return padding.top + innerH - (Math.max(0, Math.min(100, v)) / 100) * innerH;
    }
    function yForProblems(v) {
      return padding.top + innerH - (Math.max(0, v) / maxProblems) * innerH;
    }

    const svgNs = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNs, "svg");
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    svg.setAttribute("class", "trend-chart-svg");
    svg.setAttribute("role", "img");
    svg.setAttribute(
      "aria-label",
      "Coverage and problem counts over " + entries.length + " runs"
    );

    // Axes
    appendLine(svg, padding.left, padding.top, padding.left, padding.top + innerH, "trend-axis");
    appendLine(
      svg,
      padding.left,
      padding.top + innerH,
      padding.left + innerW,
      padding.top + innerH,
      "trend-axis"
    );

    // Y-axis labels (coverage 0/50/100 on the left)
    [0, 50, 100].forEach((v) => {
      const y = yForCoverage(v);
      appendText(svg, padding.left - 8, y + 4, v + "%", "trend-y-label");
      appendLine(svg, padding.left, y, padding.left + innerW, y, "trend-gridline");
    });

    // Coverage path
    const covPath = pathFor(entries, xFor, (i) => yForCoverage(coverage[i]));
    const covEl = document.createElementNS(svgNs, "path");
    covEl.setAttribute("d", covPath);
    covEl.setAttribute("class", "trend-line trend-line-coverage");
    covEl.setAttribute("fill", "none");
    svg.appendChild(covEl);

    // Problem path
    const probPath = pathFor(entries, xFor, (i) => yForProblems(problems[i]));
    const probEl = document.createElementNS(svgNs, "path");
    probEl.setAttribute("d", probPath);
    probEl.setAttribute("class", "trend-line trend-line-problems");
    probEl.setAttribute("fill", "none");
    svg.appendChild(probEl);

    // Markers
    entries.forEach((entry, i) => {
      appendCircle(svg, xFor(i), yForCoverage(coverage[i]), "trend-dot-coverage", entry);
      appendCircle(svg, xFor(i), yForProblems(problems[i]), "trend-dot-problems", entry);
    });

    // X labels (first / last)
    if (entries.length > 0) {
      appendText(
        svg,
        padding.left,
        padding.top + innerH + 20,
        shortTimestamp(entries[0].timestamp),
        "trend-x-label"
      );
      if (entries.length > 1) {
        appendText(
          svg,
          padding.left + innerW,
          padding.top + innerH + 20,
          shortTimestamp(entries[entries.length - 1].timestamp),
          "trend-x-label trend-x-label-end"
        );
      }
    }

    host.innerHTML = "";
    host.appendChild(svg);

    if (legend) {
      legend.innerHTML = "";
      const items = [
        { label: "Coverage %", className: "trend-legend-coverage" },
        { label: "Problems (right scale, max " + maxProblems + ")", className: "trend-legend-problems" },
      ];
      items.forEach((it) => {
        const span = document.createElement("span");
        span.className = "trend-legend-item " + it.className;
        span.textContent = it.label;
        legend.appendChild(span);
      });
    }

    function appendLine(parent, x1, y1, x2, y2, cls) {
      const el = document.createElementNS(svgNs, "line");
      el.setAttribute("x1", x1);
      el.setAttribute("y1", y1);
      el.setAttribute("x2", x2);
      el.setAttribute("y2", y2);
      el.setAttribute("class", cls);
      parent.appendChild(el);
    }

    function appendText(parent, x, y, text, cls) {
      const el = document.createElementNS(svgNs, "text");
      el.setAttribute("x", x);
      el.setAttribute("y", y);
      el.setAttribute("class", cls);
      el.textContent = text;
      parent.appendChild(el);
    }

    function appendCircle(parent, x, y, cls, entry) {
      const el = document.createElementNS(svgNs, "circle");
      el.setAttribute("cx", x);
      el.setAttribute("cy", y);
      el.setAttribute("r", 3.5);
      el.setAttribute("class", cls);
      const title = document.createElementNS(svgNs, "title");
      title.textContent =
        entry.timestamp +
        " | coverage=" +
        entry.coverage_percent +
        "% | problems=" +
        entry.problem_count;
      el.appendChild(title);
      parent.appendChild(el);
    }

    function pathFor(items, x, y) {
      const parts = items.map((_, i) => (i === 0 ? "M" : "L") + x(i) + " " + y(i));
      return parts.join(" ");
    }

    function shortTimestamp(s) {
      if (!s) {
        return "";
      }
      // Strip seconds + TZ for compactness.
      return String(s).replace("T", " ").slice(0, 16);
    }
  }
})();
