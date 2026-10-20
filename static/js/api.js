/* Shared fetch helper. Normalises the {success, error} envelope both APIs use. */
(function (global) {
  "use strict";

  async function request(url, options) {
    const config = Object.assign({ headers: {} }, options || {});
    if (config.body && typeof config.body !== "string") {
      config.body = JSON.stringify(config.body);
      config.headers["Content-Type"] = "application/json";
    }

    let response;
    try {
      response = await fetch(url, config);
    } catch (err) {
      throw new ApiError("Could not reach the server. Is the application still running?", 0, "NETWORK_ERROR");
    }

    let payload = null;
    try {
      payload = await response.json();
    } catch (err) {
      if (!response.ok) {
        throw new ApiError("The server returned an unexpected response.", response.status, "BAD_RESPONSE");
      }
      return {};
    }

    if (!response.ok || payload.success === false) {
      const error = (payload && payload.error) || {};
      throw new ApiError(
        error.message || "Something went wrong.",
        response.status,
        error.code || "UNKNOWN",
        error.details || []
      );
    }
    return payload;
  }

  function ApiError(message, status, code, details) {
    this.name = "ApiError";
    this.message = message;
    this.status = status;
    this.code = code;
    this.details = details || [];
  }
  ApiError.prototype = Object.create(Error.prototype);

  /** Render an error (including field-level details) into a container. */
  function showError(element, err) {
    if (!element) return;
    element.innerHTML = "";
    const heading = document.createElement("strong");
    heading.textContent = err.message || "Something went wrong.";
    element.appendChild(heading);

    if (err.details && err.details.length) {
      const list = document.createElement("ul");
      err.details.forEach(function (item) {
        const li = document.createElement("li");
        const field = item.field ? item.field + ": " : "";
        li.textContent = field + item.issue;
        list.appendChild(li);
      });
      element.appendChild(list);
    }
    element.hidden = false;
  }

  function clearError(element) {
    if (element) {
      element.hidden = true;
      element.innerHTML = "";
    }
  }

  function escapeHtml(value) {
    if (value === null || value === undefined) return "";
    return String(value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function formatNumber(value, decimals) {
    if (value === null || value === undefined || isNaN(value)) return "-";
    return Number(value).toLocaleString(undefined, {
      minimumFractionDigits: decimals || 0,
      maximumFractionDigits: decimals === undefined ? 2 : decimals,
    });
  }

  function debounce(fn, wait) {
    let timer = null;
    return function () {
      const args = arguments;
      const self = this;
      clearTimeout(timer);
      timer = setTimeout(function () { fn.apply(self, args); }, wait || 300);
    };
  }

  global.API = {
    request: request,
    ApiError: ApiError,
    showError: showError,
    clearError: clearError,
    escapeHtml: escapeHtml,
    formatNumber: formatNumber,
    debounce: debounce,
  };
})(window);
