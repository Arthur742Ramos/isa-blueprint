// Interactive dependency graph controls.
//
// Graph data is embedded in graph.html first, with graph.json as a backwards-
// compatible fallback. Embedding keeps the generated site useful from file://
// and avoids making a static dashboard depend on a local web server. When the
// optional Graphviz binary is absent, the same data drives a small built-in SVG
// layout so the graph remains useful rather than falling back to raw DOT only.
(function () {
  "use strict";

  const toolbar = document.querySelector("[data-graph-filters]");
  const host = document.querySelector("[data-graph-host]");
  const svg = host && host.querySelector("svg");
  if (!toolbar || !host || !svg) {
    return;
  }

  const resetButton = toolbar.querySelector("[data-graph-filters-reset]");
  const countEl = toolbar.querySelector("[data-graph-filters-count]");
  const focusPanel = document.querySelector("[data-graph-focus]");
  const focusTitle = document.querySelector("[data-graph-focus-title]");
  const focusSummary = document.querySelector("[data-graph-focus-summary]");
  const focusLink = document.querySelector("[data-graph-focus-link]");
  const focusClear = document.querySelector("[data-graph-focus-clear]");

  const dataScript = document.getElementById("graph-data");
  let embeddedData = null;
  if (dataScript) {
    try {
      embeddedData = JSON.parse(dataScript.textContent || "{}");
    } catch (error) {
      embeddedData = null;
    }
  }

  function loadData() {
    if (embeddedData && Array.isArray(embeddedData.nodes)) {
      return Promise.resolve(embeddedData);
    }
    const graphJsonUrl = new URL("graph.json", window.location.href).toString();
    return fetch(graphJsonUrl, { credentials: "same-origin" }).then((res) => {
      if (!res.ok) throw new Error(String(res.status));
      return res.json();
    });
  }

  loadData().then((data) => {
    if (svg.matches("[data-graph-fallback-svg]")) {
      renderFallback(data, svg);
    }
    wireUp(data, svg);
  }).catch(() => {
    toolbar.querySelectorAll("input[type=checkbox]").forEach((cb) => {
      cb.disabled = true;
    });
    if (countEl) countEl.textContent = "Graph data unavailable";
  });

  function svgElement(name, attributes) {
    const element = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.entries(attributes || {}).forEach(([key, value]) => {
      element.setAttribute(key, String(value));
    });
    return element;
  }

  function shorten(value, length) {
    const text = String(value || "");
    return text.length > length ? text.slice(0, Math.max(1, length - 1)) + "…" : text;
  }

  function labelColor(hex) {
    const match = /^#([0-9a-f]{6})$/i.exec(String(hex || ""));
    if (!match) return "#ffffff";
    const value = Number.parseInt(match[1], 16);
    const red = (value >> 16) & 255;
    const green = (value >> 8) & 255;
    const blue = value & 255;
    return (red * 299 + green * 587 + blue * 114) / 1000 > 155 ? "#111827" : "#ffffff";
  }

  function graphLayers(data) {
    const nodes = Array.isArray(data.nodes) ? data.nodes : [];
    const ids = nodes.map((node) => node.id);
    const known = new Set(ids);
    const dependencies = new Map(ids.map((id) => [id, new Set()]));
    (data.edges || []).forEach(({ source, target }) => {
      if (known.has(source) && known.has(target)) dependencies.get(source).add(target);
    });
    const remaining = new Set(ids);
    const placed = new Set();
    const layers = [];
    while (remaining.size) {
      const ready = [...remaining]
        .filter((id) => [...dependencies.get(id)].every((dep) => placed.has(dep)))
        .sort();
      const layer = ready.length ? ready : [...remaining].sort();
      layers.push(layer);
      layer.forEach((id) => {
        remaining.delete(id);
        placed.add(id);
      });
    }
    return layers.length ? layers : [[]];
  }

  function renderFallback(data, target) {
    const nodes = Array.isArray(data.nodes) ? data.nodes : [];
    const edges = Array.isArray(data.edges) ? data.edges : [];
    const layers = graphLayers(data);
    const cardWidth = 190;
    const cardHeight = 66;
    const columnGap = 28;
    const rowGap = 74;
    const marginX = 36;
    const marginY = 40;
    const widestLayer = Math.max(1, ...layers.map((layer) => layer.length));
    const width = Math.max(760, marginX * 2 + widestLayer * cardWidth + (widestLayer - 1) * columnGap);
    const height = Math.max(360, marginY * 2 + layers.length * cardHeight + (layers.length - 1) * rowGap);
    const positions = new Map();

    while (target.firstChild) target.removeChild(target.firstChild);
    target.setAttribute("viewBox", `0 0 ${width} ${height}`);
    target.setAttribute("preserveAspectRatio", "xMidYMin meet");

    const defs = svgElement("defs");
    const marker = svgElement("marker", {
      id: "graph-fallback-arrow",
      markerWidth: 8,
      markerHeight: 8,
      refX: 7,
      refY: 4,
      orient: "auto",
      markerUnits: "strokeWidth",
    });
    marker.appendChild(svgElement("path", { d: "M 0 0 L 8 4 L 0 8 z", fill: "#94a3b8" }));
    defs.appendChild(marker);
    target.appendChild(defs);
    const title = svgElement("title");
    title.textContent = "Interactive dependency graph";
    target.appendChild(title);

    layers.forEach((layer, level) => {
      const y = height - marginY - cardHeight - level * (cardHeight + rowGap);
      const totalWidth = layer.length * cardWidth + Math.max(0, layer.length - 1) * columnGap;
      const startX = (width - totalWidth) / 2;
      layer.forEach((id, index) => {
        positions.set(id, {
          x: startX + index * (cardWidth + columnGap),
          y,
          cx: startX + index * (cardWidth + columnGap) + cardWidth / 2,
          cy: y + cardHeight / 2,
        });
      });
    });

    const edgeLayer = svgElement("g", { class: "edge-layer", "aria-hidden": "true" });
    edges.forEach(({ source, target: dependency }) => {
      const from = positions.get(source);
      const to = positions.get(dependency);
      if (!from || !to) return;
      const edge = svgElement("g", { class: "edge" });
      const edgeTitle = svgElement("title");
      edgeTitle.textContent = `${source}->${dependency}`;
      edge.appendChild(edgeTitle);
      const midY = (from.cy + to.cy) / 2;
      edge.appendChild(svgElement("path", {
        d: `M ${from.cx} ${from.cy} C ${from.cx} ${midY}, ${to.cx} ${midY}, ${to.cx} ${to.cy}`,
        fill: "none",
        stroke: "#94a3b8",
        "stroke-width": 1.6,
        "marker-end": "url(#graph-fallback-arrow)",
      }));
      edgeLayer.appendChild(edge);
    });
    target.appendChild(edgeLayer);

    nodes.forEach((node) => {
      const position = positions.get(node.id);
      if (!position) return;
      const group = svgElement("g", { class: "node", "data-node-id": node.id });
      const nodeTitle = svgElement("title");
      nodeTitle.textContent = node.id;
      group.appendChild(nodeTitle);
      group.appendChild(svgElement("rect", {
        x: position.x,
        y: position.y,
        width: cardWidth,
        height: cardHeight,
        rx: 10,
        fill: node.color || "#9ca3af",
        stroke: "#1f2937",
        "stroke-width": 1,
      }));
      const text = svgElement("text", {
        x: position.cx,
        y: position.y + 26,
        fill: labelColor(node.color),
        "text-anchor": "middle",
        "font-family": "system-ui, sans-serif",
        "font-size": 12,
        "font-weight": 700,
      });
      text.textContent = shorten(node.id, 27);
      group.appendChild(text);
      const subtitle = svgElement("text", {
        x: position.cx,
        y: position.y + 46,
        fill: labelColor(node.color),
        "text-anchor": "middle",
        "font-family": "system-ui, sans-serif",
        "font-size": 11,
        opacity: 0.9,
      });
      subtitle.textContent = shorten(node.title || node.kind || "node", 27);
      group.appendChild(subtitle);
      target.appendChild(group);
    });
  }

  function wireUp(data, activeSvg) {
    const statusById = new Map();
    const nodeById = new Map();
    (data.nodes || []).forEach((node) => {
      statusById.set(node.id, node.formal_status || "named");
      nodeById.set(node.id, node);
    });
    const nodeGroups = new Map();
    const edgeGroups = [];
    activeSvg.querySelectorAll("g.node").forEach((el) => {
      const title = el.querySelector("title");
      if (!title || !title.textContent) return;
      nodeGroups.set(title.textContent.trim(), el);
    });
    activeSvg.querySelectorAll("g.edge").forEach((el) => {
      const title = el.querySelector("title");
      if (!title || !title.textContent) return;
      const parts = title.textContent.split("->");
      if (parts.length !== 2) return;
      edgeGroups.push({ source: parts[0].trim(), target: parts[1].trim(), el });
    });
    const neighbors = new Map();
    (data.edges || []).forEach(({ source, target }) => {
      if (!neighbors.has(source)) neighbors.set(source, new Set());
      if (!neighbors.has(target)) neighbors.set(target, new Set());
      neighbors.get(source).add(target);
      neighbors.get(target).add(source);
    });

    nodeGroups.forEach((el, nodeId) => {
      const node = nodeById.get(nodeId);
      el.setAttribute("tabindex", "0");
      el.setAttribute("role", "button");
      el.setAttribute("aria-label", node ? `${nodeId}: ${node.title}; formal ${node.formal_status}` : nodeId);
      el.addEventListener("click", () => selectNode(nodeId));
      el.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          selectNode(nodeId);
        }
      });
    });

    const checkboxes = Array.from(toolbar.querySelectorAll("input[type=checkbox][data-graph-formal]"));
    let selectedId = null;

    function selectedSet() {
      if (!selectedId) return null;
      return new Set([selectedId, ...(neighbors.get(selectedId) || [])]);
    }

    function apply() {
      const allowed = new Set(
        checkboxes.filter((checkbox) => checkbox.checked).map((checkbox) => checkbox.dataset.graphFormal),
      );
      const focused = selectedSet();
      let visibleNodes = 0;
      nodeGroups.forEach((el, nodeId) => {
        const status = statusById.get(nodeId) || "named";
        const statusVisible = allowed.has(status);
        const focusVisible = !focused || focused.has(nodeId);
        const visible = statusVisible && focusVisible;
        el.classList.toggle("is-dimmed", !visible);
        el.classList.toggle("is-focused", selectedId === nodeId);
        el.classList.toggle("is-neighbor", Boolean(focused && focused.has(nodeId) && selectedId !== nodeId));
        if (visible) visibleNodes += 1;
      });
      edgeGroups.forEach(({ source, target, el }) => {
        const statusVisible = allowed.has(statusById.get(source) || "named") && allowed.has(statusById.get(target) || "named");
        const focusVisible = !focused || (focused.has(source) && focused.has(target));
        el.classList.toggle("is-dimmed", !(statusVisible && focusVisible));
        el.classList.toggle("is-focused", Boolean(selectedId && (source === selectedId || target === selectedId)));
      });
      if (countEl) countEl.textContent = visibleNodes + " of " + nodeGroups.size + " nodes shown";
      persistFilterState();
    }

    function selectNode(nodeId) {
      const node = nodeById.get(nodeId);
      selectedId = selectedId === nodeId ? null : nodeId;
      if (!selectedId || !node) {
        clearSelection();
        apply();
        return;
      }
      if (focusPanel) focusPanel.hidden = false;
      if (focusTitle) focusTitle.textContent = node.title || node.id;
      if (focusSummary) focusSummary.textContent = `${node.id} · ${node.kind} · formal ${node.formal_status} · agent ${node.agent_status}`;
      if (focusLink) {
        focusLink.href = node.href || `nodes/${encodeURIComponent(node.id)}.html`;
        focusLink.textContent = "Open node";
      }
      apply();
    }

    function clearSelection() {
      selectedId = null;
      if (focusPanel) focusPanel.hidden = true;
    }

    checkboxes.forEach((checkbox) => checkbox.addEventListener("change", apply));
    if (resetButton) {
      resetButton.addEventListener("click", () => {
        checkboxes.forEach((checkbox) => { checkbox.checked = true; });
        clearSelection();
        apply();
      });
    }
    if (focusClear) {
      focusClear.addEventListener("click", () => {
        clearSelection();
        apply();
      });
    }

    restoreFilterState(checkboxes);
    apply();

    function persistFilterState() {
      const enabled = checkboxes.filter((checkbox) => checkbox.checked).map((checkbox) => checkbox.dataset.graphFormal);
      const all = checkboxes.map((checkbox) => checkbox.dataset.graphFormal);
      const hash = enabled.length === all.length ? "" : "#graph-status=" + encodeURIComponent(enabled.join(","));
      if (location.hash !== hash && !location.hash.startsWith("#filters:")) {
        history.replaceState(null, "", location.pathname + location.search + hash);
      }
    }

    function restoreFilterState(items) {
      const prefix = "#graph-status=";
      if (!location.hash.startsWith(prefix)) return;
      const raw = decodeURIComponent(location.hash.slice(prefix.length));
      const enabled = new Set(raw.split(","));
      items.forEach((checkbox) => { checkbox.checked = enabled.has(checkbox.dataset.graphFormal); });
    }
  }
})();
