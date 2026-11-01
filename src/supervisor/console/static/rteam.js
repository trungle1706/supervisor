/* Red team report (W7, REDTEAM_TAB): the Print button and open replays when printing.
   No inline script anywhere (CSP). */
(function () {
  "use strict";
  var opened = [];
  document.addEventListener("click", function (evt) {
    var el = evt.target && evt.target.closest ? evt.target.closest("[data-rt-print]") : null;
    if (el) {
      evt.preventDefault();
      window.print();
    }
  });
  window.addEventListener("beforeprint", function () {
    opened = [];
    var all = document.querySelectorAll(".rt details");
    for (var i = 0; i < all.length; i++) {
      if (!all[i].open) { all[i].open = true; opened.push(all[i]); }
    }
  });
  window.addEventListener("afterprint", function () {
    for (var i = 0; i < opened.length; i++) { opened[i].open = false; }
    opened = [];
  });
})();
