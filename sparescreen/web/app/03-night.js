  // ---- Burn-in protection and night mode -----------------------------------
  // A dashboard shows the same things in the same place for hours, which can burn
  // into OLED screens. Every minute the whole page moves a few pixels (invisible to
  // the eye), and at night it can dim or show only a clock that wanders around.

  var nightOn = false;
  var nightWakeUntil = 0;  // a tap at night shows the dashboard for a while

  function shiftContent() {
    var x = cfg.burn_in ? Math.round(Math.random() * 6 - 3) : 0;
    var y = cfg.burn_in ? Math.round(Math.random() * 6 - 3) : 0;
    var t = "translate(" + x + "px," + y + "px)";
    document.body.style.webkitTransform = t;
    document.body.style.transform = t;
  }
  setInterval(shiftContent, 60000);

  function isNightTime(now) {
    var parts = (cfg.night_hours || "23-7").split("-");
    var start = Number(parts[0]), end = Number(parts[1]), h = now.getHours();
    return start > end ? (h >= start || h < end) : (h >= start && h < end);
  }

  function moveNightClock() {
    var t = $("night-time");
    t.style.left = Math.round(5 + Math.random() * 50) + "%";
    t.style.top = Math.round(10 + Math.random() * 50) + "%";
  }

  function updateNight(now) {
    var wasOn = nightOn;
    nightOn = cfg.night_mode !== "off" && isNightTime(now) && Date.now() > nightWakeUntil;
    $("night-dim").className = "night-dim" + (nightOn && cfg.night_mode === "dim" ? " on" : "");
    var clock = nightOn && cfg.night_mode === "clock";
    $("night-clock").className = "night-clock" + (clock ? " on" : "");
    if (clock) {
      $("night-time").textContent = pad(now.getHours()) + ":" + pad(now.getMinutes());
      if (!wasOn || now.getSeconds() === 0) moveNightClock();
    }
  }
