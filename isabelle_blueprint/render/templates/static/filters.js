/* IsabelleBlueprint - status table filtering.
 *
 * Loaded on every page from base.html.j2 (so per-node pages don't 404 on it),
 * but only does anything when the page contains both:
 *   - a `.filters` block with `[data-filter-dim][data-filter-value]` buttons
 *   - a `.status-table` whose <tr>s carry matching `data-{dim}` attributes.
 *
 * Behaviour:
 *   - Click a pill to toggle it; multiple selections within the same dimension
 *     are OR'd together; selections across dimensions are AND'd together.
 *   - The "Clear" button resets everything.
 *   - Hidden rows get the `.is-hidden` class so we can lean on a single CSS rule
 *     instead of fighting jinja for inline `display:` overrides.
 */
(function () {
  "use strict";

  function init() {
    var filters = document.querySelector(".filters");
    var table = document.querySelector(".status-table");
    if (!filters || !table) {
      return;
    }

    var rows = Array.prototype.slice.call(table.querySelectorAll("tbody tr"));
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

    var active = Object.create(null);

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

      if (matchCount) {
        var shown = rows.filter(function (row) {
          return !row.classList.contains("is-hidden");
        }).length;
        matchCount.textContent = shown + " / " + totalCount;
      }

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
      });
    }

    if (searchInput) {
      searchInput.addEventListener("input", apply);
    }

    apply();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
