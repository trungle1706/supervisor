/* Guardian kit (GUARDIAN_KIT): the Copy buttons. One delegated handler, no inline handlers.
   A button has data-gk-copy="#id" (the element whose text is copied) and data-done (the label that
   shows for a moment). Safe to load twice (the block is swapped by htmx). */
(function () {
  "use strict";
  if (window.__gkitCopy) { return; }
  window.__gkitCopy = true;
  function fallback(text) {
    var ta = document.createElement("textarea");
    ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    document.body.removeChild(ta);
    return ok;
  }
  function done(btn) {
    var old = btn.getAttribute("data-label") || btn.textContent;
    btn.setAttribute("data-label", old);
    btn.textContent = btn.getAttribute("data-done") || old;
    btn.classList.add("done");
    window.setTimeout(function () { btn.textContent = old; btn.classList.remove("done"); }, 1600);
  }
  document.addEventListener("click", function (evt) {
    var t = evt.target;
    var btn = t && t.closest ? t.closest("[data-gk-copy]") : null;
    if (!btn) { return; }
    var src = document.querySelector(btn.getAttribute("data-gk-copy"));
    if (!src) { return; }
    var text = (src.textContent || "").replace(/ /g, " ").replace(/^ +$/, "");
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(function () { done(btn); }, function () { if (fallback(text)) { done(btn); } });
    } else if (fallback(text)) { done(btn); }
  });
})();
