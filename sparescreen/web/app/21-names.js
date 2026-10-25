  // ---- Reaching the PC by name -----------------------------------------------
  // On Wi-Fi the page is opened by IP, which the router can change. Only the phone knows
  // which of the PC's names it can resolve (name.local, name...), so try them from here
  // and move to the first one that answers, carrying the pairing over with a one-time code.

  var IPV4 = /^\d{1,3}(\.\d{1,3}){3}$/;
  var NAMES_KEY = "sparescreen_names_checked";
  var namesTried = false;

  function probe(base, id, done) {
    var finished = false;
    function end(ok) { if (!finished) { finished = true; done(ok); } }
    try {
      var xhr = new XMLHttpRequest();
      xhr.open("GET", base + "/whoami");
      xhr.timeout = 3000;
      xhr.onload = function () {
        var data = null;
        try { data = JSON.parse(xhr.responseText); } catch (e) { data = null; }
        end(xhr.status === 200 && !!data && data.id === id);  // this agent, not another machine
      };
      xhr.onerror = function () { end(false); };
      xhr.ontimeout = function () { end(false); };
      xhr.send();
    } catch (e) {
      end(false);
    }
  }

  function tryNames() {
    if (!IPV4.test(location.hostname) || fixed) return;
    var checked = 0;
    try { checked = +localStorage.getItem(NAMES_KEY) || 0; } catch (e) { checked = 0; }
    if (Date.now() - checked < 24 * 3600 * 1000) return;  // none worked lately: not on every load
    request("GET", "names", null, function (status, data) {
      if (status !== 200 || !data.names) return;
      var i = 0;
      (function next() {
        if (i >= data.names.length) {
          try { localStorage.setItem(NAMES_KEY, String(Date.now())); } catch (e) { /* private mode */ }
          return;
        }
        var name = data.names[i++];
        var base = "http://" + name + ":" + data.port;
        probe(base, data.id, function (ok) {
          if (!ok) { next(); return; }
          request("POST", "names/works", { name: name }, function () {
            request("POST", "handoff", {}, function (status2, hand) {
              var code = status2 === 200 && hand.code ? "?handoff=" + encodeURIComponent(hand.code) : "";
              top.location.href = base + "/" + code;
            });
          });
        });
      })();
    });
  }
