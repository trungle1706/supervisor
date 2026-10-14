/* Supervisor console glue (hand-written, no framework, no network calls of its own).
 * htmx 1.x does not swap 4xx responses by default. The server answers user errors with
 * HTTP 400 and a small message partial; show it in #flash instead of dropping it. */
(function () {
  "use strict";
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
