  // ---- Configuration (comes from the PC) -----------------------------------

  var cfg = { theme: "graphite", screens: ["hardware", "ai", "pc", "music", "photos"], rotate: 20, notify: true, sound: true,
              photo_seconds: 10, banner: "",
              game_mode: true, heat_alerts: true, usb_screen: "keep",
              fan_names: {}, cpu_fan: null, claude_limits: false,
              burn_in: true, night_mode: "off", night_hours: "23-7" };
  var fanKeys = [];  // original fan names from the last reading ("Fan 1", "GPU"...)

  function fanName(key) { return (cfg.fan_names && cfg.fan_names[key]) || key; }
  var cfgJson = "";

  function applyConfig(newCfg) {
    cfg = newCfg;
    applyTheme(params.get("theme") || cfg.theme);
    show(current);
    startRotation();
    if (settingsOpen) renderSettings();
  }

  function onServerConfig(serverCfg) {
    var json = JSON.stringify(serverCfg || null);
    if (!serverCfg || json === cfgJson) return;
    cfgJson = json;
    applyConfig(serverCfg);
  }

  function saveConfig(changes) {
    var next = {};
    for (var k in cfg) next[k] = cfg[k];
    for (var c in changes) next[c] = changes[c];
    applyConfig(next);
    var xhr = new XMLHttpRequest();
    xhr.open("POST", "config");
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.send(JSON.stringify(changes));
  }
