  // ---- Pairing ---------------------------------------------------------------
  // Devices on the network must type the code shown by the agent once; the PC
  // itself and phones on USB are trusted automatically.

  var pairingOpen = false;
  var events = null;
  var lastHeard = 0;          // when the stream last said anything: data or the agent's ping
  var SILENT_STREAM = 45000;  // ms; the agent pings every 15 s when there's nothing new

  function showPairing() {
    pairingOpen = true;
    stopRotation();
    $("pairing").className = "settings open";
  }

  function sendCode() {
    var code = $("pair-code").value.replace(/\D/g, "");
    if (code.length !== 6) { $("pair-msg").textContent = "The code has 6 digits."; return; }
    $("pair-msg").textContent = "";
    request("POST", "pair", { code: code }, function (status, data) {
      if (status === 200) {
        pairingOpen = false;
        $("pairing").className = "settings";
        $("pair-code").value = "";
        startEvents();
        startRotation();
      } else if (status === 429) {
        $("pair-msg").textContent = "Too many attempts. Try again in " + data.retry_in + " s.";
      } else if (status === 403) {
        $("pair-msg").textContent = "Wrong code. " + data.attempts_left + " attempts left.";
      } else {
        $("pair-msg").textContent = "Can't reach the PC. Is SpareScreen running?";
      }
    });
  }

  $("pair-send").addEventListener("click", function (e) { e.stopPropagation(); sendCode(); });
  $("pair-code").addEventListener("keydown", function (e) { if (e.keyCode === 13) sendCode(); });
  $("pairing").addEventListener("click", function (e) { e.stopPropagation(); });

  // EventSource reconnects on its own if the PC drops or the Wi-Fi flickers.
  // If the stream is refused, check whether this device still needs pairing.
  function startEvents() {
    if (events) events.close();
    events = new EventSource("events");
    lastHeard = Date.now();
    events.onopen = function () { lastHeard = Date.now(); $("status").className = "dot on"; };
    events.onmessage = function (e) { lastHeard = Date.now(); render(JSON.parse(e.data)); };
    events.addEventListener("ping", function () { lastHeard = Date.now(); });
    events.onerror = function () {
      $("status").className = "dot";
      request("GET", "auth", null, function (status, data) {
        if (status === 200 && !data.paired) {
          events.close();
          showPairing();
        }
      });
    };
  }

  request("GET", "auth", null, function (status, data) {
    if (status === 200 && !data.paired) showPairing();
    else startEvents();
  });

  // After the PC sleeps (or the Wi-Fi changes) the stream can stay "open" with nothing
  // coming through, and the browser doesn't notice for a long time: start it again.
  setInterval(function () {
    if (events && !pairingOpen && Date.now() - lastHeard > SILENT_STREAM) startEvents();
  }, 5000);

  // Keep the screen on: only exists in newer browsers (Chrome 84+) and
  // only in a secure context, such as http://localhost over USB. Old devices lack it;
  // there, use the agent's --stay-awake option.
  function keepAwake() {
    if (navigator.wakeLock && document.visibilityState === "visible") {
      navigator.wakeLock.request("screen").catch(function () {});
    }
  }
  keepAwake();
  document.addEventListener("visibilitychange", keepAwake);
