// Shared across every page: button ripple, mobile nav toggle, toast notifications.
(function () {
  // ---------------- button ripple ----------------
  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".btn, .icon-btn");
    if (!btn) return;
    const rect = btn.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height);
    const ripple = document.createElement("span");
    ripple.className = "ripple";
    ripple.style.width = ripple.style.height = `${size}px`;
    ripple.style.left = `${e.clientX - rect.left - size / 2}px`;
    ripple.style.top = `${e.clientY - rect.top - size / 2}px`;
    btn.appendChild(ripple);
    ripple.addEventListener("animationend", () => ripple.remove());
  });

  // ---------------- mobile nav toggle ----------------
  document.addEventListener("DOMContentLoaded", () => {
    const navToggle = document.querySelector(".nav-toggle");
    const navLinks = document.querySelector(".nav-links");
    if (navToggle && navLinks) {
      navToggle.addEventListener("click", () => {
        const open = navLinks.classList.toggle("open");
        navToggle.setAttribute("aria-expanded", open ? "true" : "false");
      });
      navLinks.querySelectorAll("a").forEach((a) =>
        a.addEventListener("click", () => navLinks.classList.remove("open"))
      );
    }
  });

  // ---------------- toast notifications ----------------
  window.showToast = function showToast(message, type = "success", timeout = 3200) {
    const stack = document.getElementById("toast-stack");
    if (!stack) return;
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.textContent = message;
    stack.appendChild(toast);
    window.setTimeout(() => {
      toast.classList.add("leaving");
      toast.addEventListener("animationend", () => toast.remove(), { once: true });
    }, timeout);
  };
})();
