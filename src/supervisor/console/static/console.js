/* Supervisor console glue (hand-written, no framework, no network calls of its own).
 * Loaded in <head> without defer so the saved theme applies before the first paint.
 * - htmx 1.x does not swap 4xx responses by default. The server answers user errors with
 *   HTTP 400 and a small message partial; show it in #flash instead of dropping it.
 * - Theme: light / dark / follow the system, remembered per browser (localStorage).
 * - Pill tabs: mark the clicked tab as the current one (htmx loads the partial). */
(function () {
  "use strict";
  var KEY = "sv_theme";
  function readTheme() {
    try { return window.localStorage.getItem(KEY) || ""; } catch (e) { return ""; }
  }
  function applyTheme(value) {
    var root = document.documentElement;
    if (value === "light" || value === "dark") { root.setAttribute("data-theme", value); }
    else { root.removeAttribute("data-theme"); }
  }
  applyTheme(readTheme());

  document.addEventListener("click", function (evt) {
    var t = evt.target.closest ? evt.target.closest("[data-theme-toggle]") : null;
    if (t) {
      var dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
      var cur = readTheme() || (dark ? "dark" : "light");
      var next = cur === "dark" ? "light" : "dark";
      try { window.localStorage.setItem(KEY, next); } catch (e) { /* private mode: session only */ }
      applyTheme(next);
      return;
    }
    var tab = evt.target.closest ? evt.target.closest(".tabs a[data-tab]") : null;
    if (tab) {
      var all = tab.parentNode.querySelectorAll("a[data-tab]");
      for (var i = 0; i < all.length; i++) {
        all[i].classList.remove("on");
        all[i].setAttribute("aria-selected", "false");
      }
      tab.classList.add("on");
      tab.setAttribute("aria-selected", "true");
    }
  });

  document.addEventListener("htmx:beforeSwap", function (evt) {
    var xhr = evt.detail.xhr;
    if (xhr && xhr.status === 400) {
      var flash = document.getElementById("flash");
      if (flash) {
        evt.detail.shouldSwap = true;
        evt.detail.isError = false;
        evt.detail.target = flash;
      }
    }
  });
  document.addEventListener("htmx:responseError", function (evt) {
    var flash = document.getElementById("flash");
    if (flash && evt.detail.xhr && evt.detail.xhr.status >= 500) {
      flash.innerHTML = '<div class="msg msg-error" role="alert">Server error (' +
        evt.detail.xhr.status + '). See the server log.</div>';
    }
  });
  document.addEventListener("htmx:sendError", function () {
    var flash = document.getElementById("flash");
    if (flash) {
      flash.innerHTML = '<div class="msg msg-error" role="alert">The server did not answer.</div>';
    }
  });
})();
