/* Small, dependency-free theme controller for generated sites. */
(function () {
  "use strict";

  var root = document.documentElement;
  var toggle = document.querySelector("[data-theme-toggle]");
  var label = document.querySelector("[data-theme-label]");
  var storageKey = "isabelle-blueprint-theme";

  function systemTheme() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }

  function apply(theme, persist) {
    root.setAttribute("data-theme", theme);
    root.style.colorScheme = theme;
    if (persist) {
      try {
        window.localStorage.setItem(storageKey, theme);
      } catch (error) {
        // Private browsing and locked-down static hosting can deny storage.
      }
    }
    if (toggle) {
      var next = theme === "dark" ? "light" : "dark";
      toggle.setAttribute("aria-pressed", theme === "dark" ? "true" : "false");
      toggle.setAttribute("title", "Switch to " + next + " theme");
      if (label) {
        label.textContent = theme === "dark" ? "Light" : "Dark";
      }
    }
  }

  var saved = null;
  try {
    saved = window.localStorage.getItem(storageKey);
  } catch (error) {
    saved = null;
  }
  apply(saved === "dark" || saved === "light" ? saved : systemTheme(), false);

  if (toggle) {
    toggle.addEventListener("click", function () {
      apply(root.getAttribute("data-theme") === "dark" ? "light" : "dark", true);
    });
  }
})();
