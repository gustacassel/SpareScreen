  // ---- Disconnected screen --------------------------------------------------
  // The dot in the top bar is easy to miss on a phone across the desk: after a while
  // without data, cover the stale numbers with a clear message.

  var OFFLINE_AFTER = 30000;  // ms without data
  var pageStart = Date.now();
  var lastData = 0;           // when the last reading arrived (ms)
  var offlineOn = false;
  var pcAsleep = false;       // the last reading said the PC is going to sleep

  // A small wander every minute, around the center (burn-in).
  function moveOfflineBox() {
    var shift = "translate(" + Math.round((Math.random() - 0.5) * 60) + "px," +
                Math.round((Math.random() - 0.5) * 40) + "px)";
    var box = $("offline-box");
    box.style.webkitTransform = shift;
    box.style.transform = shift;
  }

  function updateOffline(now) {
    var since = lastData || pageStart;
    var wasOn = offlineOn;
    offlineOn = !pairingOpen && (pcAsleep || Date.now() - since > OFFLINE_AFTER);
    $("offline").className = "offline" + (offlineOn ? " on" : "") + (offlineOn && pcAsleep ? " asleep" : "");
    if (!offlineOn) return;
    $("offline-time").textContent = pad(now.getHours()) + ":" + pad(now.getMinutes());
    var last = new Date(lastData);
    var at = pad(last.getHours()) + ":" + pad(last.getMinutes());
    $("offline-status").textContent = pcAsleep ? "The PC is asleep" : "Disconnected from the PC";
    if (pcAsleep) $("offline-detail").textContent = "Since " + at + " · the dashboard comes back when it wakes up";
    else $("offline-detail").textContent = lastData ? "No data since " + at + " · trying again..." : "Waiting for the PC...";
    if (!wasOn || now.getSeconds() === 0) moveOfflineBox();
  }

  tickClock();
  setInterval(tickClock, 1000);
