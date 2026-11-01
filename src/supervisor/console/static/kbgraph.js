/* Regulation graph: select a node without a page load. The server renders everything (nodes are
   links to ?sel=..., the detail of every node is in the page, hidden); this file only toggles the
   highlight and the panel, and keeps the address in step. No network call. */
(function () {
  "use strict";
  var root = document.getElementById("kbgraph");
  if (!root) return;
  var svg = root.querySelector("[data-kg='svg']");
  if (!svg) return;
  var panel = root.querySelector("[data-kg='panel']");
  var none = panel.querySelector(".kg-d-none");
  var nodes = svg.querySelectorAll("a.kg-n");
  var edges = svg.querySelectorAll(".kg-e");
  var byId = {};
  nodes.forEach(function (n) { byId[n.getAttribute("data-id")] = n; });
  var details = {};
  panel.querySelectorAll(".kg-d").forEach(function (d) { details[d.getAttribute("data-for")] = d; });

  function neighbours(id) {
    var set = {};
    set[id] = true;
    edges.forEach(function (e) {
      var a = e.getAttribute("data-a"), b = e.getAttribute("data-b");
      if (a === id) set[b] = true;
      if (b === id) set[a] = true;
    });
    return set;
  }

  function select(id) {
    var on = id && byId[id] ? id : "";
    var near = on ? neighbours(on) : {};
    nodes.forEach(function (n) {
      var nid = n.getAttribute("data-id");
      n.classList.toggle("sel", nid === on);
      n.classList.toggle("hl", !!near[nid]);
      if (nid === on) n.setAttribute("aria-current", "true"); else n.removeAttribute("aria-current");
    });
    edges.forEach(function (e) {
      e.classList.toggle("hl", !!on && (e.getAttribute("data-a") === on || e.getAttribute("data-b") === on));
    });
    svg.classList.toggle("has-sel", !!on);
    Object.keys(details).forEach(function (k) { details[k].hidden = k !== on; });
    if (none) none.hidden = !!on;
    root.setAttribute("data-selected", on);
    try {
      var u = new URL(window.location.href);
      if (on) u.searchParams.set("sel", on); else u.searchParams.delete("sel");
      window.history.replaceState(null, "", u.pathname + u.search);
    } catch (err) { /* the address is a convenience only */ }
  }

  root.addEventListener("click", function (ev) {
    if (ev.defaultPrevented || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
    var t = ev.target.closest ? ev.target.closest("a[data-id], a[data-act='clear']") : null;
    if (!t || !root.contains(t)) return;
    ev.preventDefault();
    if (t.getAttribute("data-act") === "clear") { select(""); return; }
    select(t.getAttribute("data-id"));
    var n = byId[t.getAttribute("data-id")];
    if (n && t.closest(".kg-panel")) n.focus();
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && root.getAttribute("data-selected")) select("");
  });
})();
