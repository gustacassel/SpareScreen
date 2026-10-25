  // ---- Heat alerts ------------------------------------------------------------
  // A part that stays in the red for a while (not a single spike) gets one alert with a
  // chime; it can alert again once it has cooled down to the yellow line.

  var HEAT_AFTER = 30000;  // ms in the red before alerting
  var heat = {};           // part -> {since, alerted}

  function checkHeat(sys) {
    if (!sys || sys.error) return;
    var parts = [{ id: "cpu", name: "CPU", temp: sys.cpu.temp, limit: sys.cpu.temp_limit, warn: 75, hot: 90 }];
    if (sys.gpu) parts.push({ id: "gpu", name: "GPU", temp: sys.gpu.temp, limit: sys.gpu.temp_limit, warn: 75, hot: 85 });
    var drives = sys.drives || [];
    for (var i = 0; i < drives.length; i++) {
      parts.push({ id: "drive" + i, name: drives[i].name || "Drive", temp: drives[i].temp,
                   limit: drives[i].temp_limit, warn: 60, hot: 70 });
    }
    var now = Date.now();
    for (var j = 0; j < parts.length; j++) {
      var p = parts[j];
      if (!known(p.temp)) continue;
      var levels = tempLevels(p.limit, p.warn, p.hot);
      var state = heat[p.id] || (heat[p.id] = { since: null, alerted: false });
      if (p.temp >= levels[1]) {
        if (state.since === null) state.since = now;
        if (!state.alerted && now - state.since >= HEAT_AFTER && cfg.heat_alerts) {
          state.alerted = true;
          chime();
          toast("attention", p.name + " is very hot",
                Math.round(p.temp) + "°C" + (known(p.limit) ? " · it slows down at " + Math.round(p.limit) + "°C" : ""),
                "alert", 15);
        }
      } else {
        state.since = null;
        if (p.temp < levels[0]) state.alerted = false;
      }
    }
  }
