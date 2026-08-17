/* IsabelleBlueprint filtering and copy affordances.
 *
 * The site is intentionally static, so filters use the URL hash rather than
 * a framework router. The same state can be bookmarked, shared, or opened
 * directly from disk.
 */
(function () {
  "use strict";

  function init() {
    var filters = document.querySelector(".filters");
    if (!filters) {
      return;
    }

    var table = document.querySelector(".status-table");
    var rows = table
      ? Array.prototype.slice.call(table.querySelectorAll("tbody tr"))
      : Array.prototype.slice.call(document.querySelectorAll("[data-filter-item]"));
    if (!rows.length) {
      return;
    }

    var pills = Array.prototype.slice.call(
      filters.querySelectorAll("button[data-filter-dim][data-filter-value]")
    );
    var clearButton = filters.querySelector("button[data-filter-clear]");
    var searchInput = filters.querySelector("input[data-filter-search]");
    var matchCount = filters.querySelector("[data-filter-count]");
    var totalCount = rows.length;
    var scope = filters.getAttribute("data-filter-scope") || location.pathname.split("/").pop() || "filters";
    var active = Object.create(null);
    var empty = filters.parentNode.querySelector("[data-filter-empty]");
    if (!empty) {
      empty = document.createElement("p");
      empty.className = "filter-empty empty-state";
      empty.setAttribute("data-filter-empty", "");
      empty.setAttribute("role", "status");
      empty.hidden = true;
      empty.textContent = "No nodes match these filters. Clear a filter or try a broader search.";
      filters.parentNode.appendChild(empty);
    }
    var announcement = filters.querySelector("[data-filter-announcement]");

    restoreState();

    function apply() {
      rows.forEach(function (row) {
        var visible = true;
        for (var dim in active) {
          if (!Object.prototype.hasOwnProperty.call(active, dim)) continue;
          var picks = active[dim];
          if (!picks || !picks.length) continue;
          var rowValue = row.getAttribute("data-" + dim);
          if (picks.indexOf(rowValue) === -1) {
            visible = false;
            break;
          }
        }
        if (visible && searchInput && searchInput.value.trim()) {
          var haystack = row.getAttribute("data-search") || row.textContent || "";
          visible = haystack.toLowerCase().indexOf(searchInput.value.trim().toLowerCase()) !== -1;
        }
        row.classList.toggle("is-hidden", !visible);
      });

      var shown = rows.filter(function (row) {
        return !row.classList.contains("is-hidden");
      }).length;
      if (matchCount) {
        matchCount.textContent = shown + " / " + totalCount;
      }
      if (empty) {
        empty.hidden = shown !== 0;
      }
      if (announcement) {
        announcement.textContent = shown + " of " + totalCount + " nodes shown";
      }
      persistState();

      pills.forEach(function (pill) {
        var dim = pill.getAttribute("data-filter-dim");
        var value = pill.getAttribute("data-filter-value");
        var picks = active[dim] || [];
        var on = picks.indexOf(value) !== -1;
        pill.classList.toggle("is-active", on);
        pill.setAttribute("aria-pressed", on ? "true" : "false");
      });
    }

    pills.forEach(function (pill) {
      pill.setAttribute("aria-pressed", "false");
      pill.addEventListener("click", function (event) {
        event.preventDefault();
        var dim = pill.getAttribute("data-filter-dim");
        var value = pill.getAttribute("data-filter-value");
        var picks = active[dim] || (active[dim] = []);
        var idx = picks.indexOf(value);
        if (idx === -1) {
          picks.push(value);
        } else {
          picks.splice(idx, 1);
        }
        apply();
      });
    });

    if (clearButton) {
      clearButton.addEventListener("click", function (event) {
        event.preventDefault();
        active = Object.create(null);
        if (searchInput) {
          searchInput.value = "";
        }
        apply();
        if (searchInput) {
          searchInput.focus();
        }
      });
    }

    if (searchInput) {
      searchInput.addEventListener("input", apply);
    }

    apply();

    function persistState() {
      var params = [];
      for (var dim in active) {
        if (!Object.prototype.hasOwnProperty.call(active, dim)) continue;
        var picks = active[dim];
        if (picks && picks.length) {
          params.push(encodeURIComponent(dim) + "=" + encodeURIComponent(picks.join(",")));
        }
      }
      if (searchInput && searchInput.value.trim()) {
        params.push("q=" + encodeURIComponent(searchInput.value.trim()));
      }
      var hash = params.length ? "#filters:" + encodeURIComponent(scope) + ":" + params.join("&") : "";
      if (location.hash !== hash) {
        history.replaceState(null, "", location.pathname + location.search + hash);
      }
    }

    function restoreState() {
      var prefix = "#filters:" + encodeURIComponent(scope) + ":";
      if (!location.hash || location.hash.indexOf(prefix) !== 0) {
        return;
      }
      var raw = location.hash.slice(prefix.length);
      raw.split("&").forEach(function (part) {
        if (!part) return;
        var eq = part.indexOf("=");
        var key;
        var value;
        try {
          key = decodeURIComponent(eq === -1 ? part : part.slice(0, eq));
          value = decodeURIComponent(eq === -1 ? "" : part.slice(eq + 1));
        } catch (error) {
          return;
        }
        if (key === "q" && searchInput) {
          searchInput.value = value;
        } else if (key) {
          active[key] = value ? value.split(",") : [];
        }
      });
    }
  }

  function initCopyButtons() {
    var buttons = Array.prototype.slice.call(document.querySelectorAll("[data-copy-text]"));
    buttons.forEach(function (button) {
      var original = button.textContent || "Copy";
      button.setAttribute("data-copy-label", original);
      button.addEventListener("click", function () {
        var value = button.getAttribute("data-copy-text") || "";
        if (!value || button.disabled) return;
        button.disabled = true;
        copyText(value).then(function () {
          button.textContent = button.getAttribute("data-copy-success") || "Copied";
          button.setAttribute("aria-label", "Copied");
        }).catch(function () {
          button.textContent = "Copy unavailable";
          button.setAttribute("aria-label", "Copy unavailable");
        }).then(function () {
          window.setTimeout(function () {
            button.textContent = button.getAttribute("data-copy-label") || original;
            button.removeAttribute("aria-label");
            button.disabled = false;
          }, 1600);
        });
      });
    });
  }

  function copyText(value) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(value);
    }
    return Promise.reject(new Error("Clipboard API unavailable"));
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      init();
      initCopyButtons();
    });
  } else {
    init();
    initCopyButtons();
  }
})();
