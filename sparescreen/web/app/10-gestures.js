  // ---- Gestures: tap = next screen; long press = next theme ----------------

  var pressTimer = null;
  var longPressed = false;

  function pressStart() {
    if (settingsOpen || pairingOpen) return;
    longPressed = false;
    clearTimeout(pressTimer);
    pressTimer = setTimeout(function () { longPressed = true; nextTheme(); }, 700);
  }
  function pressEnd() { clearTimeout(pressTimer); }

  document.addEventListener("touchstart", pressStart);
  document.addEventListener("touchend", pressEnd);
  document.addEventListener("touchmove", pressEnd);
  document.addEventListener("mousedown", pressStart);
  document.addEventListener("mouseup", pressEnd);

  document.addEventListener("click", function () {
    unlockAudio();
    if (longPressed) { longPressed = false; return; }
    if (nightOn) {  // at night a tap just wakes the dashboard up for a minute
      nightWakeUntil = Date.now() + 60000;
      updateNight(new Date());
      return;
    }
    // Fullscreen is requested on the frame (index.html), so it survives reloads of this page.
    var doc = window.parent !== window ? parent.document : document;
    var root = doc.documentElement;
    var req = root.requestFullscreen || root.webkitRequestFullscreen;
    if (req && !(doc.fullscreenElement || doc.webkitFullscreenElement)) {
      try {
        var p = req.call(root);
        if (p && p.catch) p.catch(function () {});
      } catch (e) { /* no fullscreen in this browser */ }
    }
    if (toastBusy) { hideToast(); return; }  // tap closes the toast
    if (!fixed) {
      show(current + 1);
      startRotation();
    }
  });

  applyTheme(params.get("theme") || cfg.theme);
  show(0);
  startRotation();
