(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  async function requestJson(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
    });
    const text = await response.text();
    const payload = text ? JSON.parse(text) : null;
    if (!response.ok) {
      const detail = payload && payload.detail ? payload.detail : response.statusText;
      throw new Error(detail);
    }
    return payload;
  }

  async function init() {
    const health = await requestJson("/api/health");
    $("apiStatus").textContent = `${health.service}: ${health.status}`;
  }

  document.addEventListener("DOMContentLoaded", () => {
    init().catch((error) => {
      $("apiStatus").textContent = error.message;
    });
  });
})();
