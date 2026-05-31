// Graph filter — toggles SVG nodes/edges by their formal status.
//
// This module is a no-op on pages that don't include the graph filter
// toolbar, so it's safe to load globally from base.html.j2.
(function () {
  "use strict";

  const toolbar = document.querySelector("[data-graph-filters]");
  const host = document.querySelector("[data-graph-host]");
  if (!toolbar || !host) {
    return;
  }
  const svg = host.querySelector("svg");
  if (!svg) {
    return;
  }
  const resetButton = toolbar.querySelector("[data-graph-filters-reset]");
  const countEl = toolbar.querySelector("[data-graph-filters-count]");

  // Index node groups by graph-source id (graphviz writes the source id
  // into a <title> element inside each node/edge <g>).
  const nodeGroups = new Map(); // id -> SVGGElement
  const edgeGroups = []; // {source, target, el}

  svg.querySelectorAll("g.node").forEach((el) => {
    const title = el.querySelector("title");
    if (title && title.textContent) {
      nodeGroups.set(title.textContent.trim(), el);
    }
  });
  svg.querySelectorAll("g.edge").forEach((el) => {
    const title = el.querySelector("title");
    if (!title || !title.textContent) {
      return;
    }
    const parts = title.textContent.split("->");
    if (parts.length !== 2) {
      return;
    }
    edgeGroups.push({
      source: parts[0].trim(),
      target: parts[1].trim(),
      el,
    });
  });

  // Resolve graph.json relative to the current page so this works under
  // any deploy prefix (GitHub Pages subpath, etc.).
  const graphJsonUrl = new URL("graph.json", window.location.href).toString();

  fetch(graphJsonUrl, { credentials: "same-origin" })
    .then((res) => (res.ok ? res.json() : Promise.reject(res.status)))
    .then((data) => {
      const statusById = new Map();
      (data.nodes || []).forEach((n) => {
        statusById.set(n.id, n.formal_status);
      });
      wireUp(statusById);
    })
    .catch(() => {
      // No graph.json or fetch blocked (e.g. file://). Disable the
      // filters so users don't see broken toggles.
      toolbar.querySelectorAll("input[type=checkbox]").forEach((cb) => {
        cb.disabled = true;
      });
      if (countEl) {
        countEl.textContent = "(filters unavailable)";
      }
    });

  function wireUp(statusById) {
    const checkboxes = Array.from(
      toolbar.querySelectorAll("input[type=checkbox][data-graph-formal]")
    );

    function apply() {
      const allowed = new Set(
        checkboxes.filter((c) => c.checked).map((c) => c.dataset.graphFormal)
      );
      let visibleNodes = 0;
      nodeGroups.forEach((el, nodeId) => {
        const status = statusById.get(nodeId) || "named";
        const visible = allowed.has(status);
        el.classList.toggle("is-dimmed", !visible);
        if (visible) {
          visibleNodes += 1;
        }
      });
      edgeGroups.forEach(({ source, target, el }) => {
        const srcStatus = statusById.get(source) || "named";
        const tgtStatus = statusById.get(target) || "named";
        const visible = allowed.has(srcStatus) && allowed.has(tgtStatus);
        el.classList.toggle("is-dimmed", !visible);
      });
      if (countEl) {
        countEl.textContent =
          visibleNodes + " of " + nodeGroups.size + " nodes shown";
      }
    }

    checkboxes.forEach((cb) => cb.addEventListener("change", apply));
    if (resetButton) {
      resetButton.addEventListener("click", () => {
        checkboxes.forEach((cb) => {
          cb.checked = true;
        });
        apply();
      });
    }
    apply();
  }
})();
