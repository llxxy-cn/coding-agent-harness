"use strict";

document.addEventListener("DOMContentLoaded", () => {
  for (const form of document.querySelectorAll("form[data-run-form]")) {
    form.addEventListener("submit", () => {
      const submitButton = form.querySelector(`button[type="submit"]`);
      const status = form.querySelector("[data-submit-status]");

      if (submitButton) {
        submitButton.disabled = true;
      }
      form.setAttribute("aria-busy", "true");
      if (status) {
        status.textContent = "Running fixed scenario…";
      }
    });
  }
});
