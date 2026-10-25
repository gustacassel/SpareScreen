  // ---- Settings (panel) ----------------------------------------------------

  var settingsOpen = false;
  var updateInfo = null;  // {"version", "latest"} from the PC (data.update)

  function chip(label, on, onTap, swatch) {
    var b = el("button", "chip" + (on ? " on" : ""));
    if (swatch) {
      var dot = el("span", "swatch");
      dot.style.background = swatch[0];
      dot.style.borderColor = swatch[1];
      b.appendChild(dot);
    }
    b.appendChild(document.createTextNode(label));
    b.addEventListener("click", onTap);
    return b;
  }

  function fillChips(id, chips) {
    var box = $(id);
    box.innerHTML = "";
    for (var i = 0; i < chips.length; i++) box.appendChild(chips[i]);
  }

  function renderSettings() {
    fillChips("set-theme", THEMES.map(function (name) {
      var info = THEME_INFO[name];
      return chip(info[0], name === cfg.theme, function () { saveConfig({ theme: name }); }, [info[1], info[2]]);
    }));
    fillChips("set-heat-alerts", [[true, "On"], [false, "Off"]].map(function (opt) {
      return chip(opt[1], cfg.heat_alerts === opt[0], function () { saveConfig({ heat_alerts: opt[0] }); });
    }));
    fillChips("set-game-mode", [[true, "On"], [false, "Off"]].map(function (opt) {
      return chip(opt[1], cfg.game_mode === opt[0], function () { saveConfig({ game_mode: opt[0] }); });
    }));
    fillChips("set-screens", ["hardware", "ai", "pc", "music"].map(function (name) {
      var on = cfg.screens.indexOf(name) >= 0;
      return chip(SCREEN_NAMES[name], on, function () {
        var list = cfg.screens.filter(function (s) { return s !== name; });
        if (!on) list.push(name);
        if (list.length) saveConfig({ screens: list });  // at least one screen
      });
    }));
    fillChips("set-rotate", ROTATE_OPTIONS.map(function (opt) {
      return chip(opt[1], cfg.rotate === opt[0], function () { saveConfig({ rotate: opt[0] }); });
    }));
    fillChips("set-notify", [[true, "On"], [false, "Off"]].map(function (opt) {
      return chip(opt[1], cfg.notify === opt[0], function () { saveConfig({ notify: opt[0] }); });
    }));
    fillChips("set-sound", [[true, "On"], [false, "Off"]].map(function (opt) {
      return chip(opt[1], cfg.sound === opt[0], function () {
        saveConfig({ sound: opt[0] });
        if (opt[0]) { unlockAudio(); chime(); }  // sound sample
      });
    }));
    renderFanFields();
    // Which fan to show on the CPU card: each motherboard plugs the cooler into a different header.
    var cpuFanChoices = [[null, "None"]].concat(fanKeys.filter(function (k) { return k !== "GPU"; })
      .map(function (k) { return [k, fanName(k)]; }));
    fillChips("set-cpu-fan", cpuFanChoices.map(function (opt) {
      return chip(opt[1], cfg.cpu_fan === opt[0], function () { saveConfig({ cpu_fan: opt[0] }); });
    }));
    // Headless check of Claude Code limits for desktop/IDE users (spends a tiny bit of quota).
    fillChips("set-claude-limits", [[false, "Off"], [true, "Every 10 min while in use"]].map(function (opt) {
      return chip(opt[1], cfg.claude_limits === opt[0], function () { saveConfig({ claude_limits: opt[0] }); });
    }));
    fillChips("set-burn-in", [[true, "On"], [false, "Off"]].map(function (opt) {
      return chip(opt[1], cfg.burn_in === opt[0], function () { saveConfig({ burn_in: opt[0] }); shiftContent(); });
    }));
    fillChips("set-night-mode", [["off", "Off"], ["dim", "Dim"], ["clock", "Clock only"]].map(function (opt) {
      return chip(opt[1], cfg.night_mode === opt[0], function () { saveConfig({ night_mode: opt[0] }); });
    }));
    fillChips("set-night-hours", [["22-7", "22:00–07:00"], ["23-7", "23:00–07:00"], ["0-8", "00:00–08:00"]].map(function (opt) {
      return chip(opt[1], cfg.night_hours === opt[0], function () { saveConfig({ night_hours: opt[0] }); });
    }));
    // Over USB the PC can turn the phone's real brightness down, or the screen off.
    fillChips("set-update-check", [[true, "On"], [false, "Off"]].map(function (opt) {
      return chip(opt[1], cfg.update_check === opt[0], function () { saveConfig({ update_check: opt[0] }); });
    }));
    $("set-update-note").textContent = !updateInfo ? "" : updateInfo.latest
      ? updateInfo.latest + " is out: update from the PC window"
      : "you have " + updateInfo.version;
    fillChips("set-usb-screen", [["keep", "Keep"], ["dim", "Dim"], ["off", "Off"]].map(function (opt) {
      return chip(opt[1], cfg.usb_screen === opt[0], function () { saveConfig({ usb_screen: opt[0] }); });
    }));
  }

  // One field per fan. Does not redraw while someone is typing.
  function renderFanFields() {
    var box = $("set-fans");
    if (box.contains(document.activeElement)) return;
    box.innerHTML = "";
    if (!fanKeys.length) box.appendChild(el("span", "detail", "no fans found"));
    fanKeys.forEach(function (key) {
      var field = el("label", "fan-field", key);
      var input = el("input");
      input.type = "text";
      input.maxLength = 16;
      input.placeholder = key;
      input.value = (cfg.fan_names && cfg.fan_names[key]) || "";
      input.addEventListener("change", function () {
        var names = {};
        for (var k in cfg.fan_names) names[k] = cfg.fan_names[k];
        if (input.value.trim()) names[key] = input.value.trim();
        else delete names[key];
        saveConfig({ fan_names: names });
      });
      input.addEventListener("keydown", function (e) { if (e.keyCode === 13) input.blur(); });  // Enter saves
      field.appendChild(input);
      box.appendChild(field);
    });
  }

  function openSettings() {
    settingsOpen = true;
    stopRotation();
    renderSettings();
    $("settings").className = "settings open";
    renderConnect();
  }

  // "Connect a phone": address and pairing code, only when this page runs on the PC itself
  // (the agent answers /info to this machine only).
  function renderConnect() {
    var box = $("set-connect");
    box.innerHTML = "";
    request("GET", "info", null, function (status, info) {
      if (status !== 200) return;
      var lines = [];
      if (info.phone_url) lines.push(["Phone address", info.phone_url]);
      if (info.code) lines.push(["Pairing code", info.code]);
      lines.push(["USB", "plug the phone in with USB debugging on"]);
      for (var i = 0; i < lines.length; i++) {
        var row = el("div", "connect-row");
        row.appendChild(el("span", "connect-label", lines[i][0]));
        row.appendChild(el("b", "", lines[i][1]));
        box.appendChild(row);
      }
      if (info.version) box.appendChild(el("div", "detail small", "SpareScreen " + info.version));
    });
  }

  function closeSettings() {
    settingsOpen = false;
    $("settings").className = "settings";
    startRotation();
  }

  $("gear").addEventListener("click", function (e) { e.stopPropagation(); openSettings(); });
  $("set-close").addEventListener("click", function (e) { e.stopPropagation(); closeSettings(); });
  $("settings").addEventListener("click", function (e) {
    e.stopPropagation();
    if (e.target === $("settings")) closeSettings();  // tapping outside the panel closes it
  });
