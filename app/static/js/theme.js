(function () {
  const root = document.documentElement;
  const STORAGE_KEY = "theme";

  function applyMeta(theme) {
    let meta = document.querySelector('meta[name="theme-color"]');
    if (!meta) {
      meta = document.createElement("meta");
      meta.name = "theme-color";
      document.head.appendChild(meta);
    }
    meta.content = theme === "dark" ? "#0e0e11" : "#ffffff";
  }

  function setTheme(theme, { persist = true, animate = false } = {}) {
    if (animate) {
      root.classList.add("theme-transition");
      window.setTimeout(() => root.classList.remove("theme-transition"), 400);
    }
    root.setAttribute("data-theme", theme);
    applyMeta(theme);
    if (persist) {
      try {
        localStorage.setItem(STORAGE_KEY, theme);
      } catch (err) {
        /* localStorage unavailable (private mode, etc.) — theme just won't persist */
      }
    }
    document.querySelectorAll("[data-theme-toggle]").forEach((btn) => {
      btn.setAttribute("aria-pressed", theme === "dark" ? "true" : "false");
      btn.setAttribute("aria-label", theme === "dark" ? "Switch to light mode" : "Switch to dark mode");
    });
  }

  function currentTheme() {
    return root.getAttribute("data-theme") === "dark" ? "dark" : "light";
  }

  document.addEventListener("DOMContentLoaded", () => {
    applyMeta(currentTheme());
    document.querySelectorAll("[data-theme-toggle]").forEach((btn) => {
      btn.setAttribute("aria-pressed", currentTheme() === "dark" ? "true" : "false");
      btn.addEventListener("click", () => {
        setTheme(currentTheme() === "dark" ? "light" : "dark", { animate: true });
      });
    });
  });

  window.__theme = { set: setTheme, current: currentTheme };
})();
