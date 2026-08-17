// Trend chart — a small dependency-free SVG view of coverage and problems.
// Embedded data is preferred so the generated site works from file://.
(function () {
  "use strict";

  const host = document.querySelector("[data-trend-chart-host]");
  const legend = document.querySelector("[data-trend-chart-legend]");
  if (!host) return;

  const dataScript = document.getElementById("trend-data");
  let embedded = null;
  if (dataScript) {
    try { embedded = JSON.parse(dataScript.textContent || "{}"); } catch (error) { embedded = null; }
  }

  const load = embedded && Array.isArray(embedded.entries)
    ? Promise.resolve(embedded)
    : fetch(new URL("trends.json", window.location.href).toString(), { credentials: "same-origin" })
        .then((res) => (res.ok ? res.json() : Promise.reject(res.status)));

  load.then((data) => {
    const entries = (data && data.entries) || [];
    if (!entries.length) {
      renderEmpty("No history yet.");
      return;
    }
    renderChart(entries);
  }).catch(() => renderEmpty("Could not load trend history."));

  function renderEmpty(message) {
    host.innerHTML = "";
    const p = document.createElement("p");
    p.className = "trend-chart-empty";
    p.textContent = message;
    host.appendChild(p);
  }

  function renderChart(entries) {
    const width = 760;
    const height = 300;
    const padding = { top: 24, right: 58, bottom: 48, left: 58 };
    const innerW = width - padding.left - padding.right;
    const innerH = height - padding.top - padding.bottom;
    const coverage = entries.map((entry) => typeof entry.coverage_percent === "number" ? entry.coverage_percent : 0);
    const problems = entries.map((entry) => typeof entry.problem_count === "number" ? entry.problem_count : 0);
    const maxProblems = Math.max(1, ...problems);
    const svgNs = "http://www.w3.org/2000/svg";

    function xFor(index) {
      return entries.length <= 1 ? padding.left + innerW / 2 : padding.left + (index / (entries.length - 1)) * innerW;
    }
    function yForCoverage(value) {
      return padding.top + innerH - (Math.max(0, Math.min(100, value)) / 100) * innerH;
    }
    function yForProblems(value) {
      return padding.top + innerH - (Math.max(0, value) / maxProblems) * innerH;
    }

    const svg = document.createElementNS(svgNs, "svg");
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    svg.setAttribute("class", "trend-chart-svg");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Coverage and problem counts over " + entries.length + " runs");
    const desc = document.createElementNS(svgNs, "desc");
    desc.textContent = "Blue shows proved coverage from 0 to 100 percent. Red dashed shows problem count from 0 to " + maxProblems + ".";
    svg.appendChild(desc);

    appendLine(svg, padding.left, padding.top, padding.left, padding.top + innerH, "trend-axis");
    appendLine(svg, padding.left + innerW, padding.top, padding.left + innerW, padding.top + innerH, "trend-axis trend-axis-right");
    appendLine(svg, padding.left, padding.top + innerH, padding.left + innerW, padding.top + innerH, "trend-axis");

    [0, 50, 100].forEach((value) => {
      const y = yForCoverage(value);
      appendText(svg, padding.left - 10, y + 4, value + "%", "trend-y-label");
      appendLine(svg, padding.left, y, padding.left + innerW, y, "trend-gridline");
    });
    [0, maxProblems].forEach((value) => {
      const y = yForProblems(value);
      appendText(svg, padding.left + innerW + 10, y + 4, String(value), "trend-y-label trend-y-label-right");
    });

    const coveragePath = document.createElementNS(svgNs, "path");
    coveragePath.setAttribute("d", pathFor(entries, xFor, (i) => yForCoverage(coverage[i])));
    coveragePath.setAttribute("class", "trend-line trend-line-coverage");
    coveragePath.setAttribute("fill", "none");
    svg.appendChild(coveragePath);
    const problemsPath = document.createElementNS(svgNs, "path");
    problemsPath.setAttribute("d", pathFor(entries, xFor, (i) => yForProblems(problems[i])));
    problemsPath.setAttribute("class", "trend-line trend-line-problems");
    problemsPath.setAttribute("fill", "none");
    svg.appendChild(problemsPath);

    entries.forEach((entry, index) => {
      appendCircle(svg, xFor(index), yForCoverage(coverage[index]), "trend-dot-coverage", entry, "coverage");
      appendCircle(svg, xFor(index), yForProblems(problems[index]), "trend-dot-problems", entry, "problems");
    });
    if (entries.length) {
      appendText(svg, padding.left, padding.top + innerH + 22, shortTimestamp(entries[0].timestamp), "trend-x-label");
      if (entries.length > 2) {
        appendText(svg, padding.left + innerW / 2, padding.top + innerH + 22, shortTimestamp(entries[Math.floor(entries.length / 2)].timestamp), "trend-x-label trend-x-label-middle");
      }
      if (entries.length > 1) appendText(svg, padding.left + innerW, padding.top + innerH + 22, shortTimestamp(entries[entries.length - 1].timestamp), "trend-x-label trend-x-label-end");
    }

    host.innerHTML = "";
    host.appendChild(svg);
    if (legend) {
      legend.innerHTML = "";
      [
        { label: "Coverage % (left axis)", className: "trend-legend-coverage" },
        { label: "Problems (right axis, max " + maxProblems + ")", className: "trend-legend-problems" },
      ].forEach((item) => {
        const span = document.createElement("span");
        span.className = "trend-legend-item " + item.className;
        span.textContent = item.label;
        legend.appendChild(span);
      });
    }

    function appendLine(parent, x1, y1, x2, y2, className) {
      const line = document.createElementNS(svgNs, "line");
      line.setAttribute("x1", x1); line.setAttribute("y1", y1); line.setAttribute("x2", x2); line.setAttribute("y2", y2); line.setAttribute("class", className);
      parent.appendChild(line);
    }
    function appendText(parent, x, y, text, className) {
      const label = document.createElementNS(svgNs, "text");
      label.setAttribute("x", x); label.setAttribute("y", y); label.setAttribute("class", className); label.textContent = text;
      parent.appendChild(label);
    }
    function appendCircle(parent, x, y, className, entry, metric) {
      const circle = document.createElementNS(svgNs, "circle");
      circle.setAttribute("cx", x); circle.setAttribute("cy", y); circle.setAttribute("r", 4); circle.setAttribute("class", className);
      const title = document.createElementNS(svgNs, "title");
      title.textContent = shortTimestamp(entry.timestamp) + " | coverage=" + entry.coverage_percent + "% | problems=" + entry.problem_count + " | selected=" + metric;
      circle.appendChild(title); parent.appendChild(circle);
    }
    function pathFor(items, x, y) {
      return items.map((_, index) => (index === 0 ? "M" : "L") + x(index) + " " + y(index)).join(" ");
    }
    function shortTimestamp(value) {
      return value ? String(value).replace("T", " ").slice(0, 16) : "";
    }
  }
})();
