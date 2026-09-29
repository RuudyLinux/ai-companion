// Shared across every page: CSRF-aware fetch, API error helpers, button ripple,
// mobile nav toggle, toast notifications.
(function () {
  // ---------------- CSRF: every same-origin unsafe fetch carries the page's token ----------------
  const csrfMeta = document.querySelector('meta[name="csrf-token"]');
  const csrfToken = csrfMeta ? csrfMeta.content : "";
  const nativeFetch = window.fetch.bind(window);
  window.fetch = function (input, init = {}) {
    const method = (init.method || (input instanceof Request ? input.method : "GET")).toUpperCase();
    const url = new URL(input instanceof Request ? input.url : input, window.location.href);
    if (csrfToken && url.origin === window.location.origin && !["GET", "HEAD", "OPTIONS"].includes(method)) {
      const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
      headers.set("X-CSRF-Token", csrfToken);
      init = { ...init, headers };
    }
    return nativeFetch(input, init);
  };

  // ---------------- shared helpers ----------------
  window.escapeHtml = function escapeHtml(value) {
    return String(value ?? "").replace(
      /[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
    );
  };

  // Turns an error response ({"error": {"code", "message"}}) into a readable message.
  window.apiErrorMessage = async function apiErrorMessage(res, fallback = "Something went wrong.") {
    try {
      const data = await res.clone().json();
      if (data && data.error && data.error.message) return data.error.message;
    } catch (_) {
      /* not JSON */
    }
    if (res.status === 401) return "Your session expired. Please sign in again.";
    if (res.status === 429) return "You're doing that too often. Please wait a moment.";
    return fallback;
  };

  // Polls a background job until it finishes; resolves with the job, rejects on failure.
  window.waitForJob = async function waitForJob(jobId, { signal, intervalMs = 800, timeoutMs = 180000 } = {}) {
    const started = Date.now();
    for (;;) {
      if (signal && signal.aborted) throw new DOMException("Aborted", "AbortError");
      const res = await fetch(`/api/jobs/${jobId}`, { signal });
      if (!res.ok) throw new Error(await window.apiErrorMessage(res, "Couldn't check job status."));
      const job = await res.json();
      if (job.status === "completed") return job;
      if (job.status === "failed") throw new Error((job.error && job.error.message) || "The job failed.");
      if (job.status === "cancelled") throw new DOMException("Cancelled", "AbortError");
      if (Date.now() - started > timeoutMs) throw new Error("This is taking too long. Please try again.");
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
  };

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
