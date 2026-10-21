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
    if (xhr && (xhr.status === 400 || xhr.status === 403 || xhr.status === 413 || xhr.status === 429)) {
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
  /* WP-UX1 shell: sidebar collapse (remembered per browser), narrow-screen menu, row drawer
   * (open on htmx swap, Esc, focus return, Copy JSON) and arrow keys in the sidebar and tabs.
   * No inline script anywhere: the CSP stays script-src 'self'. */
  var SIDE = "sv_side", docEl = document.documentElement, lastRow = null;
  function sideSet(collapsed) {
    if (collapsed) { docEl.setAttribute("data-side", "collapsed"); } else { docEl.removeAttribute("data-side"); }
    var b = document.querySelector("[data-side-collapse]");
    if (b) { b.setAttribute("aria-expanded", collapsed ? "false" : "true"); }
    try { window.localStorage.setItem(SIDE, collapsed ? "collapsed" : ""); } catch (e) { /* session only */ }
  }
  try { if (window.localStorage.getItem(SIDE) === "collapsed") { docEl.setAttribute("data-side", "collapsed"); } } catch (e) { /* ignore */ }
  document.addEventListener("DOMContentLoaded", function () {
    var b = document.querySelector("[data-side-collapse]");
    if (b && docEl.getAttribute("data-side") === "collapsed") { b.setAttribute("aria-expanded", "false"); }
  });
  function drawer() { return document.getElementById("drawer"); }
  function closeDrawer() {
    var d = drawer();
    if (!d || d.hidden) { return false; }
    d.hidden = true; d.innerHTML = "";
    if (lastRow && document.contains(lastRow)) { lastRow.focus(); }
    lastRow = null;
    return true;
  }
  document.addEventListener("click", function (evt) {
    var el = evt.target.closest ? evt.target : null;
    if (!el) { return; }
    if (el.closest("[data-side-collapse]")) { sideSet(docEl.getAttribute("data-side") !== "collapsed"); return; }
    var open = el.closest("[data-side-open]");
    if (open || (docEl.hasAttribute("data-side-open") && !el.closest("#sidebar"))) {
      if (open) { docEl.toggleAttribute("data-side-open"); open.setAttribute("aria-expanded", docEl.hasAttribute("data-side-open") ? "true" : "false"); }
      else { docEl.removeAttribute("data-side-open"); }
      return;
    }
    if (el.closest("[data-drawer-close]")) { closeDrawer(); return; }
    var cp = el.closest("[data-copy]");
    if (cp) {
      var src = document.querySelector(cp.getAttribute("data-copy"));
      if (src && navigator.clipboard) { navigator.clipboard.writeText(src.textContent).catch(function () { /* blocked */ }); }
    }
  });
  document.addEventListener("htmx:afterSwap", function (evt) {
    var d = drawer();
    if (!d || evt.detail.target !== d) { return; }
    if (d.hidden) {
      var elt = evt.detail.requestConfig && evt.detail.requestConfig.elt;
      lastRow = elt && elt.closest ? elt.closest("a,button") : null;
      d.hidden = false;
    }
    var src = evt.detail.requestConfig && evt.detail.requestConfig.elt;
    var tab = src && src.getAttribute("role") === "tab" ? d.querySelector('[role=tab][data-tab="' + src.getAttribute("data-tab") + '"]') : null;
    var h = tab || document.getElementById("drawer-title");
    if (h) { h.focus(); }
  });
  /* WP39: a deep link (?event=, ?correlation=) opens the drawer on the server; take those
   * parameters out of the address bar so a reload or a shared URL shows the plain list. */
  document.addEventListener("DOMContentLoaded", function () {
    var d = drawer(), names = d ? (d.getAttribute("data-strip") || "") : "";
    if (!names || !window.history || !history.replaceState) { return; }
    var url = new URL(window.location.href);
    names.split(" ").forEach(function (n) { if (n) { url.searchParams.delete(n); } });
    history.replaceState(null, "", url.pathname + (url.search || "") + url.hash);
  });
  document.addEventListener("keydown", function (evt) {
    if (evt.key === "Escape") {
      var pop = document.getElementById("search-results");
      if (closeDrawer()) { return; }
      if (pop && pop.innerHTML) { pop.innerHTML = ""; }
      docEl.removeAttribute("data-side-open");
      return;
    }
    var dir = { ArrowDown: 1, ArrowUp: -1, ArrowRight: 1, ArrowLeft: -1, Home: -1e3, End: 1e3 }[evt.key];
    var host = evt.target.closest ? evt.target.closest("[data-sidenav], [role=tablist]") : null;
    if (!dir || !host) { return; }
    var vertical = host.hasAttribute("data-sidenav");
    if (Math.abs(dir) === 1 && vertical !== (evt.key === "ArrowDown" || evt.key === "ArrowUp")) { return; }
    var links = Array.prototype.slice.call(host.querySelectorAll("a[href]"));
    var at = links.indexOf(evt.target.closest("a")) + dir;
    var next = links[Math.max(0, Math.min(links.length - 1, at))];
    if (next) { evt.preventDefault(); next.focus(); }
  });
})();
