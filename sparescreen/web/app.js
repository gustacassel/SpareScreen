// Deliberately simple JS (no modules or recent syntax) so it runs
// on old phone browsers.
//
// Preferences (theme, screens, auto-switch, alerts, sound) are saved on the PC
// and arrive with the data; the gear in the top corner opens the screen to change them.
//
// URL parameters (for testing): ?screen=hardware|ai|pc pins a screen; ?theme=neon forces a theme.
// Gestures: tap = next screen; long press = next theme.
(function () {
  "use strict";

  var RING_LENGTH = 2 * Math.PI * 52;
  var THEMES = ["graphite", "oled", "terracotta", "neon", "terminal", "light"];
  var THEME_INFO = {  // name and colors of the sample dot (card background, accent)
    graphite: ["Graphite", "#151a20", "#4fa3ff"],
    oled: ["OLED", "#000000", "#4fa3ff"],
    terracotta: ["Terracotta", "#27211b", "#d97757"],
    neon: ["Neon", "#190a3a", "#00f5d4"],
    terminal: ["Terminal", "#04110a", "#39ff7a"],
    light: ["Light", "#ffffff", "#2f80ed"]
  };
  var SCREEN_NAMES = { hardware: "Hardware", ai: "AI", pc: "PC", music: "Music" };
  var ROTATE_OPTIONS = [[0, "Off"], [10, "10 s"], [20, "20 s"], [30, "30 s"], [60, "1 min"]];

  function $(id) { return document.getElementById(id); }
  function q(root, sel) { return root.querySelector(sel); }

  function pad(n) { return n < 10 ? "0" + n : "" + n; }

  function levelColor(pct) {
    if (pct >= 85) return "var(--hot)";
    if (pct >= 60) return "var(--warn)";
    return "var(--ok)";
  }

  function decimal(n) { return n.toFixed(1); }
  function gb(bytes) { return decimal(bytes / 1073741824); }

  function size(bytes) {
    if (bytes >= 1099511627776) return decimal(bytes / 1099511627776) + " TB";
    if (bytes >= 1073741824) return decimal(bytes / 1073741824) + " GB";
    return Math.round(bytes / 1048576) + " MB";
  }

  function rate(bytesPerSecond) {
    if (bytesPerSecond >= 1048576) return decimal(bytesPerSecond / 1048576) + " MB/s";
    if (bytesPerSecond >= 1024) return Math.round(bytesPerSecond / 1024) + " KB/s";
    return Math.round(bytesPerSecond) + " B/s";
  }

  // 1234567 -> "1.2M"; 45300 -> "45K"
  function shortNumber(n) {
    if (n >= 1e9) return decimal(n / 1e9) + "B";
    if (n >= 1e6) return decimal(n / 1e6) + "M";
    if (n >= 1e3) return Math.round(n / 1e3) + "K";
    return n + "";
  }

  function duration(seconds) {
    if (seconds < 60) return "less than 1 min";
    var h = Math.floor(seconds / 3600);
    var m = Math.floor((seconds % 3600) / 60);
    if (h >= 24) return Math.floor(h / 24) + "d " + (h % 24) + "h";
    return h ? h + "h " + pad(m) + "m" : m + " min";
  }

  function ago(seconds) {
    if (seconds < 60) return "now";
    if (seconds < 3600) return Math.floor(seconds / 60) + " min";
    return Math.floor(seconds / 3600) + " h";
  }

  function clockTime(epoch) {
    var d = new Date(epoch * 1000);
    return pad(d.getHours()) + ":" + pad(d.getMinutes());
  }

  function weekdayTime(epoch) {
    var d = new Date(epoch * 1000);
    return d.toLocaleDateString("en-US", { weekday: "short" }).replace(".", "") + ", " + clockTime(epoch);
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text) node.textContent = text;
    return node;
  }

  var SVG_NS = "http://www.w3.org/2000/svg";
  function icon(name) {
    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("class", "icon");
    var use = document.createElementNS(SVG_NS, "use");
    use.setAttributeNS("http://www.w3.org/1999/xlink", "xlink:href", "#i-" + name);
    svg.appendChild(use);
    return svg;
  }

  // A "name ........ value" row, with an optional small bar (0-100) below.
  function row(name, value, barPct, barColor, iconName) {
    var li = el("li");
    var line = el("div", "row-line");
    var label = el("span", "row-name");
    if (iconName) label.appendChild(icon(iconName));
    label.appendChild(document.createTextNode(name));
    line.appendChild(label);
    line.appendChild(el("span", "row-value", value));
    li.appendChild(line);
    if (barPct !== undefined && barPct !== null) {
      var bar = el("div", "bar");
      var fill = el("div", "bar-fill");
      fill.style.width = Math.min(barPct, 100) + "%";
      fill.style.background = barColor || "var(--accent)";
      fill.style.transition = "none";
      bar.appendChild(fill);
      li.appendChild(bar);
    }
    return li;
  }

  function fillList(list, items, emptyText) {
    list.innerHTML = "";
    if (!items.length) list.appendChild(el("li", "empty", emptyText));
    for (var i = 0; i < items.length; i++) list.appendChild(items[i]);
  }

  var params = new URLSearchParams(location.search);

  // ---- Configuration (comes from the PC) -----------------------------------

  var cfg = { theme: "graphite", screens: ["hardware", "ai", "pc", "music"], rotate: 20, notify: true, sound: true,
              game_mode: true,
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

  // ---- Clock (the phone's own time) ---------------------------------------

  function tickClock() {
    var now = new Date();
    $("time").textContent = pad(now.getHours()) + ":" + pad(now.getMinutes());
    var date = now.toLocaleDateString("en-US", { weekday: "long", day: "numeric", month: "long" });
    $("date").textContent = date.charAt(0).toUpperCase() + date.slice(1);
    updateNight(now);
    updateOffline(now);
  }

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

  // ---- Disconnected screen --------------------------------------------------
  // The dot in the top bar is easy to miss on a phone across the desk: after a while
  // without data, cover the stale numbers with a clear message.

  var OFFLINE_AFTER = 30000;  // ms without data
  var pageStart = Date.now();
  var lastData = 0;           // when the last reading arrived (ms)
  var offlineOn = false;

  function moveOfflineBox() {
    var box = $("offline-box");
    box.style.marginTop = Math.round(-90 + (Math.random() - 0.5) * 120) + "px";
    box.style.marginLeft = "calc(-40% + " + Math.round((Math.random() - 0.5) * 80) + "px)";
  }

  function updateOffline(now) {
    var since = lastData || pageStart;
    var wasOn = offlineOn;
    offlineOn = !pairingOpen && Date.now() - since > OFFLINE_AFTER;
    $("offline").className = "offline" + (offlineOn ? " on" : "");
    if (!offlineOn) return;
    var last = new Date(lastData);
    $("offline-detail").textContent = lastData
      ? "Last data at " + pad(last.getHours()) + ":" + pad(last.getMinutes()) + " · trying to reconnect..."
      : "Waiting for the PC...";
    if (!wasOn || now.getSeconds() === 0) moveOfflineBox();
  }

  tickClock();
  setInterval(tickClock, 1000);

  // ---- Toast on top of the screen ------------------------------------------

  var toastQueue = [];
  var toastBusy = false;

  // kind: "done" (green), "attention" (yellow) or "info" (accent color)
  function toast(kind, title, sub, iconName, seconds) {
    toastQueue.push({ kind: kind, title: title, sub: sub, icon: iconName, seconds: seconds || 8 });
    if (!toastBusy) nextToast();
  }

  function nextToast() {
    var t = toastQueue.shift();
    if (!t) {
      toastBusy = false;
      startRotation();
      return;
    }
    toastBusy = true;
    stopRotation();
    $("toast-icon").setAttributeNS("http://www.w3.org/1999/xlink", "xlink:href", "#i-" + t.icon);
    $("toast-title").textContent = t.title;
    $("toast-sub").textContent = t.sub;
    $("toast").className = "toast show " + t.kind;
    clearTimeout(nextToast.timer);
    nextToast.timer = setTimeout(hideToast, t.seconds * 1000);
  }

  function hideToast() {
    clearTimeout(nextToast.timer);
    $("toast").className = "toast";
    setTimeout(nextToast, 400);
  }

  // ---- Sound (only plays after the first tap: browser rule) ----------------

  var audio = null;
  function unlockAudio() {
    var Ctx = window.AudioContext || window.webkitAudioContext;
    if (!audio && Ctx) audio = new Ctx();
    if (audio && audio.resume) audio.resume();
  }

  function chime() {
    if (!audio || !cfg.sound) return;
    var notes = [880, 1318.5];  // A and E: a short "ding"
    for (var i = 0; i < notes.length; i++) {
      var osc = audio.createOscillator();
      var gain = audio.createGain();
      var at = audio.currentTime + i * 0.14;
      osc.frequency.value = notes[i];
      gain.gain.setValueAtTime(0.0001, at);
      gain.gain.exponentialRampToValueAtTime(0.25, at + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.5);
      osc.connect(gain);
      gain.connect(audio.destination);
      osc.start(at);
      osc.stop(at + 0.55);
    }
  }

  // ---- Screens -------------------------------------------------------------

  var allScreens = Array.prototype.slice.call(document.querySelectorAll(".screen"));
  var current = 0;
  var rotateTimer = null;
  var fixed = params.get("screen");

  var gameOn = false;   // a game is running and game mode is on: only the game screen
  var musicOn = false;  // something is playing: the music screen joins the rotation

  // Screens in the rotation: the one pinned in the URL, the game screen in game mode,
  // or the ones turned on in the settings (music only while something plays).
  function enabledScreens() {
    var list = [];
    for (var i = 0; i < allScreens.length; i++) {
      var name = allScreens[i].getAttribute("data-name");
      var on;
      if (fixed) on = name === fixed;
      else if (gameOn) on = name === "game";
      else on = name !== "game" && cfg.screens.indexOf(name) >= 0 && (name !== "music" || musicOn);
      if (on) list.push(allScreens[i]);
    }
    return list.length ? list : [allScreens[0]];
  }

  function show(index) {
    var screens = enabledScreens();
    current = (index + screens.length) % screens.length;
    for (var i = 0; i < allScreens.length; i++) {
      allScreens[i].className = "screen" + (allScreens[i] === screens[current] ? " active" : "");
    }
    var tabs = $("tabs");
    tabs.innerHTML = "";
    if (screens.length > 1) {
      for (var j = 0; j < screens.length; j++) tabs.appendChild(el("i", j === current ? "on" : ""));
    }
    $("screen-title").textContent = screens[current].getAttribute("data-title");
  }

  function showNamed(name) {
    var screens = enabledScreens();
    for (var i = 0; i < screens.length; i++) {
      if (screens[i].getAttribute("data-name") === name) show(i);
    }
  }

  function stopRotation() {
    if (rotateTimer) clearInterval(rotateTimer);
    rotateTimer = null;
  }

  function startRotation() {
    stopRotation();
    if (!fixed && cfg.rotate > 0 && !toastBusy && !settingsOpen && !pairingOpen && enabledScreens().length > 1) {
      rotateTimer = setInterval(function () { show(current + 1); }, cfg.rotate * 1000);
    }
  }

  // ---- Themes --------------------------------------------------------------

  var theme = null;

  function applyTheme(name) {
    if (THEMES.indexOf(name) < 0) name = "graphite";
    theme = name;
    document.documentElement.setAttribute("data-theme", name);
  }

  function nextTheme() {
    var name = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
    saveConfig({ theme: name });
    toast("info", "Theme", THEME_INFO[name][0], "palette", 2);
  }

  // ---- Settings (panel) ----------------------------------------------------

  var settingsOpen = false;

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

  // ---- Hardware ------------------------------------------------------------

  function setName(card, name) { q(card, ".hw-name").textContent = name || ""; }

  function setRing(card, pct) {
    var fill = q(card, ".ring-fill");
    if (pct === null || pct === undefined) {
      q(card, ".pct").textContent = "--";
      fill.style.strokeDashoffset = RING_LENGTH;
      return;
    }
    q(card, ".pct").textContent = Math.round(pct);
    fill.style.strokeDashoffset = RING_LENGTH * (1 - Math.min(pct, 100) / 100);
    fill.style.stroke = levelColor(pct);
  }

  function setTemp(card, temp, warn, hot) {
    var box = q(card, ".temp");
    if (temp === null || temp === undefined) {
      box.className = "temp na";
      q(box, ".temp-value").textContent = "--";
      box.style.color = "";
      return;
    }
    box.className = "temp";
    q(box, ".temp-value").textContent = Math.round(temp);
    box.style.color = temp >= hot ? "var(--hot)" : temp >= warn ? "var(--warn)" : "";
  }

  function setExtra(card, watts, fallback) {
    var box = q(card, ".extra");
    box.innerHTML = "";
    if (watts !== null && watts !== undefined) {
      box.appendChild(icon("bolt"));
      box.appendChild(document.createTextNode(Math.round(watts) + " W"));
    } else if (fallback) {
      box.textContent = fallback;
    }
  }

  // Cores in a 2-row grid (12 threads -> 6 per row).
  function renderCores(box, cores) {
    if (box.children.length !== cores.length) {
      box.innerHTML = "";
      var perRow = cores.length <= 8 ? cores.length : Math.ceil(cores.length / 2);
      for (var i = 0; i < cores.length; i++) {
        var core = el("div", "core");
        core.style.width = (100 / perRow) + "%";
        var tile = el("div", "core-box");
        tile.appendChild(el("i"));
        tile.appendChild(el("span"));
        core.appendChild(tile);
        box.appendChild(core);
      }
    }
    for (var j = 0; j < cores.length; j++) {
      var t = box.children[j].firstChild;
      t.firstChild.style.height = cores[j] + "%";
      t.firstChild.style.background = cores[j] >= 85 ? "var(--hot)" : cores[j] >= 60 ? "var(--warn)" : "var(--accent)";
      t.lastChild.textContent = Math.round(cores[j]);
    }
  }

  function ghz(mhz) { return decimal(mhz / 1000) + " GHz"; }

  function setRows(id, pairs) {
    var items = [];
    for (var i = 0; i < pairs.length; i++) {
      if (pairs[i][1] !== null && pairs[i][1] !== undefined && pairs[i][1] !== "") {
        items.push(row(pairs[i][0], pairs[i][1], null, null, pairs[i][2]));
      }
    }
    fillList($(id), items, "");
  }

  // Text for a fan, by the original name the system reported ("Fan 2", "GPU"...).
  function fanText(sys, key) {
    var fans = sys.fans || [];
    for (var i = 0; i < fans.length; i++) {
      var f = fans[i];
      if (f.name !== key) continue;
      if (f.gpu) return !f.percent && !f.rpm ? "stopped" : Math.round(f.percent || 0) + "%";
      return Math.round(f.rpm) + " rpm";
    }
    return null;
  }

  function renderHardware(sys) {
    if (!sys || sys.error) return;

    var cpu = $("cpu");
    setName(cpu, sys.cpu.name);
    setRing(cpu, sys.cpu.percent);
    setTemp(cpu, sys.cpu.temp, 75, 90);
    setExtra(cpu, sys.cpu.power, sys.cpu.temp === null ? sys.sensors_hint || "no temperature sensor" : "");
    renderCores(q(cpu, ".cores"), sys.cpu.cores);
    setRows("cpu-rows", [
      // average clock / fastest core
      ["Clock", sys.cpu.clock ? decimal(sys.cpu.clock / 1000) + (sys.cpu.clock_max ? " / " + ghz(sys.cpu.clock_max) : " GHz") : null],
      [cfg.cpu_fan ? fanName(cfg.cpu_fan) : "", cfg.cpu_fan ? fanText(sys, cfg.cpu_fan) : null, "fan"]
    ]);

    var gpu = $("gpu");
    var g = sys.gpu;
    setName(gpu, g && g.name);
    if (g) {
      setRing(gpu, g.percent);
      setTemp(gpu, g.temp, 75, 85);
      setExtra(gpu, g.power);
      if (g.mem_total) {
        var memPct = 100 * g.mem_used / g.mem_total;
        var fill = q(gpu, ".bar-fill");
        fill.style.width = memPct + "%";
        fill.style.background = levelColor(memPct);
        q(gpu, ".mem").textContent = "VRAM " + gb(g.mem_used) + " / " + gb(g.mem_total) + " GB";
      }
      setRows("gpu-rows", [
        ["Clock", g.clock ? Math.round(g.clock) + " MHz" : null],
        ["Memory", g.mem_clock ? Math.round(g.mem_clock) + " MHz" : null],
        [fanName("GPU"), fanText(sys, "GPU"), "fan"]
      ]);
    } else {
      setRing(gpu, null);
      setTemp(gpu, null);
      setExtra(gpu, null, "GPU not found");
    }

    var ram = $("ram");
    setName(ram, sys.ram.name);
    setRing(ram, sys.ram.percent);
    var mem = q(ram, ".mem");
    mem.innerHTML = "";
    mem.appendChild(document.createTextNode(gb(sys.ram.used)));
    mem.appendChild(el("small", "", "/ " + gb(sys.ram.total) + " GB"));
    setRows("ram-rows", [
      ["Available", sys.ram.available !== undefined ? size(sys.ram.available) : null],
      ["Swap", sys.ram.swap_total ? Math.round(sys.ram.swap_percent) + "% of " + size(sys.ram.swap_total) : null],
      ["Processes", sys.ram.processes]
    ]);
  }

  // ---- PC: what is going on ------------------------------------------------

  function renderPc(sys, act, now) {
    if (act && !act.error) {
      var game = act.game;
      // With game mode on the game has its own screen, so the block would only repeat it.
      $("game-block").style.display = cfg.game_mode ? "none" : "";
      $("game-name").textContent = game ? game.name : "No game running";
      $("game-name").className = "now-name" + (game ? "" : " none");
      $("game-meta").textContent = game
        ? "running for " + duration(now - game.since) + " · CPU " + Math.round(game.cpu) + "% · " + size(game.mem)
        : "";
      var focus = act.focus;
      // While playing, the app in focus is usually the game itself: skip the repeat to make room.
      $("focus-block").style.display = game && focus && focus.name === game.name ? "none" : "";
      $("focus-name").textContent = focus ? focus.name : "--";
      $("focus-meta").textContent = focus ? "CPU " + Math.round(focus.cpu) + "% · " + size(focus.mem) : "";
      fillList($("top-list"), act.top.map(function (p) {
        return row(p.name, Math.round(p.cpu) + "% · " + size(p.mem));
      }), "--");
    }
    if (!sys || sys.error) return;

    var fans = sys.fans || [];
    fanKeys = fans.map(function (f) { return f.name; });
    fillList($("fan-list"), fans.map(function (f) {
      if (f.gpu) {
        var stopped = !f.percent && !f.rpm;
        return row(fanName(f.name), stopped ? "stopped" : Math.round(f.percent || 0) + "%" + (f.rpm ? " · " + Math.round(f.rpm) + " rpm" : ""),
                   f.percent || 0);
      }
      // No % on the motherboard: the bar is the speed relative to 3000 rpm.
      return row(fanName(f.name), Math.round(f.rpm) + " rpm", f.percent !== null ? f.percent : f.rpm / 30);
    }), "no sensors (open LibreHardwareMonitor)");

    if (sys.net) {
      $("net-down").textContent = rate(sys.net.down);
      $("net-up").textContent = rate(sys.net.up);
    }
    $("uptime").textContent = sys.uptime ? "PC up for " + duration(sys.uptime) : "";

    var drives = sys.drives || [];
    var temps = drives.filter(function (d) { return d.temp !== null; })
      .map(function (d) { return Math.round(d.temp) + "°"; }).join(" · ");
    var rows = (sys.disks || []).map(function (d) {
      var color = d.percent >= 95 ? "var(--hot)" : d.percent >= 85 ? "var(--warn)" : "var(--accent)";
      return row(d.name, size(d.free) + " free", d.percent, color);
    });
    if (temps) rows.push(row("Temp.", temps));
    fillList($("disk-list"), rows, "--");
  }

  // ---- AI tools (Claude Code, Codex...) -------------------------------------
  // Each tool's source sends the same shape; only the installed ones get a card.

  var AI_TOOLS = ["claude", "codex"];

  function limitBlock(win, now) {
    var box = el("div", "limit");
    var head = el("div", "limit-head");
    head.appendChild(icon(win.weekly ? "calendar" : "clock"));
    head.appendChild(el("span", "limit-name", win.label));
    // Short reset time next to the name, used when two tools share the screen.
    if (win.resets_at) {
      head.appendChild(el("small", "limit-when", win.renewed ? "renewed" : duration(win.resets_at - now)));
    }
    head.appendChild(el("span", "limit-pct" + (win.renewed ? " na" : ""),
                        win.renewed ? "renewed" : Math.round(win.percent) + "%"));
    box.appendChild(head);
    var bar = el("div", "bar");
    var fill = el("div", "bar-fill");
    fill.style.transition = "none";  // rebuilt every second: no animation from zero
    if (!win.renewed) {
      fill.style.width = Math.min(win.percent, 100) + "%";
      fill.style.background = levelColor(win.percent);
    }
    bar.appendChild(fill);
    box.appendChild(bar);
    var reset = "";
    if (win.resets_at && win.renewed) {
      reset = "renewed " + (win.weekly ? weekdayTime(win.resets_at) : "at " + clockTime(win.resets_at));
    } else if (win.resets_at) {
      var left = win.resets_at - now;
      reset = "resets in " + duration(left) +
        (win.weekly && left > 86400 ? " (" + weekdayTime(win.resets_at) + ")" : " (" + clockTime(win.resets_at) + ")");
    }
    box.appendChild(el("div", "detail limit-reset", reset));
    return box;
  }

  // Alerts: compare each session's status with the previous reading.
  var lastStatus = {};
  var justDone = {};  // session id -> highlight until (ms)

  function watchSessions(tool, sessions) {
    for (var i = 0; i < sessions.length; i++) {
      var s = sessions[i];
      if (lastStatus[s.id] === "busy" && s.status !== "busy") {
        var done = s.status === "idle";
        justDone[s.id] = Date.now() + 20000;
        if (cfg.notify) {
          showNamed("ai");
          chime();
          toast(done ? "done" : "attention",
                tool.name + (done ? " · session finished" : " · session needs you"),
                s.name, done ? "check" : "alert");
        }
      }
      lastStatus[s.id] = s.status;
    }
  }

  function sessionList(sessions, now) {
    var list = el("ul", "sessions");
    if (!sessions.length) {
      list.appendChild(el("li", "empty", "No open sessions"));
      return list;
    }
    var STATUS = { busy: "working", idle: "idle" };
    for (var i = 0; i < sessions.length; i++) {
      var s = sessions[i];
      var highlight = justDone[s.id] && justDone[s.id] > Date.now() && s.status !== "busy";
      var li = el("li", highlight ? "done" : "");
      li.appendChild(el("span", "s-dot " + (highlight ? "done" : s.status)));
      var text = el("span", "s-text");
      text.appendChild(el("span", "s-name", s.name));
      var meta = (highlight ? "finished" : STATUS[s.status] || s.status) + " · " + ago(now - s.since);
      if (s.project && s.project !== s.name) meta = s.project + " · " + meta;
      text.appendChild(el("span", "s-meta", meta));
      li.appendChild(text);
      list.appendChild(li);
    }
    return list;
  }

  function toolCard(tool, now) {
    var card = el("div", "card ai-card");
    var t = tool.today;
    var h2 = el("h2");
    h2.appendChild(icon("terminal"));
    h2.appendChild(document.createTextNode(tool.name.toUpperCase()));
    h2.appendChild(el("span", "h2-right", shortNumber(t.input + t.output + t.cache_read) + " tokens today"));
    card.appendChild(h2);

    var body = el("div", "ai-body");
    var limits = el("div", "ai-limits");
    for (var i = 0; i < tool.limits.length; i++) limits.appendChild(limitBlock(tool.limits[i], now));
    if (tool.limits_hint) limits.appendChild(el("div", "detail small", tool.limits_hint));
    if (tool.week_models && tool.week_models.length) {
      var parts = tool.week_models.map(function (m) { return m.label + " " + shortNumber(m.tokens); });
      limits.appendChild(el("div", "detail small", "This week: " + parts.join(" · ")));
    }
    if (tool.limits_updated) {
      var age = now - tool.limits_updated;
      limits.appendChild(el("div", "detail small ai-updated", "limits updated " + (age < 60 ? "just now" : ago(age) + " ago")));
    }
    body.appendChild(limits);
    body.appendChild(sessionList(tool.sessions, now));
    card.appendChild(body);
    return card;
  }

  function renderAi(data, now) {
    var tools = [];
    for (var i = 0; i < AI_TOOLS.length; i++) {
      var tool = data[AI_TOOLS[i]];
      if (tool && tool.installed) tools.push(tool);
    }
    var grid = $("ai-grid");
    grid.className = "ai-grid " + (tools.length > 1 ? "dual" : "single");
    grid.innerHTML = "";
    if (!tools.length) {
      var empty = el("div", "card ai-card");
      empty.appendChild(el("h2", "", "AI TOOLS"));
      empty.appendChild(el("div", "detail", "No AI coding tool found on this PC. SpareScreen shows " +
                                            "Claude Code and Codex usage when they are installed."));
      grid.appendChild(empty);
      return;
    }
    for (var j = 0; j < tools.length; j++) {
      watchSessions(tools[j], tools[j].sessions);
      grid.appendChild(toolCard(tools[j], now));
    }
  }

  // ---- Phone battery ---------------------------------------------------------
  // Over USB the agent reads level and temperature with adb. On Wi-Fi only the
  // level the browser itself reports is available (where the browser supports it).

  var BATTERY_WARM = 38;
  var BATTERY_HOT = 42;    // alert from here on
  var BATTERY_RESET = 39;  // and again only after it cooled down below this
  var batteryAlerted = false;
  var browserBattery = null;
  if (navigator.getBattery) {
    try {
      navigator.getBattery().then(function (b) {
        // Desktops without a battery report "full and charging": not worth showing.
        var noBattery = b.level === 1 && b.charging && b.chargingTime === 0;
        if (!noBattery) browserBattery = b;
      }, function () {});
    } catch (e) { /* not allowed here */ }
  }

  function known(value) { return value !== null && value !== undefined; }

  // ---- Images (covers, game art, icons) -------------------------------------

  // Shows `url` in `img` and marks `holder` with `cls`; hides it when there's no image.
  function setImage(img, holder, cls, url) {
    if (url) {
      if (img.getAttribute("src") !== url) img.setAttribute("src", url);
      if ((" " + holder.className + " ").indexOf(" " + cls + " ") < 0) holder.className += " " + cls;
    } else {
      holder.className = (" " + holder.className + " ").replace(" " + cls + " ", " ").replace(/^\s+|\s+$/g, "");
    }
  }

  // ---- Music screen ----------------------------------------------------------

  function renderMusic(media) {
    if (!media || !media.playing || !media.title) return;
    var card = $("music-art").parentNode.parentNode;
    card.className = "card music" + (media.status === "paused" ? " paused" : "");
    setImage($("music-art"), $("music-art").parentNode, "has-art", media.art);
    setImage($("music-app-icon"), $("music-app-icon").parentNode, "has-icon", media.app_icon);
    $("music-app").textContent = media.app || "";
    $("music-title").textContent = media.title;
    $("music-artist").textContent = media.artist || "";
    $("music-album").textContent = media.album || "";
    var hasTime = known(media.position) && media.duration;
    $("music-bar").parentNode.style.display = hasTime ? "" : "none";
    $("music-bar").style.width = hasTime ? Math.min(100, 100 * media.position / media.duration) + "%" : "0";
    $("music-pos").textContent = hasTime ? minutes(media.position) : "";
    $("music-dur").textContent = hasTime ? minutes(media.duration) : (media.status === "paused" ? "paused" : "");
  }

  // ---- Game screen -----------------------------------------------------------

  function setStat(id, v1, v2, detail, unit, barPct) {
    var card = $(id);
    q(card, ".v1").textContent = v1;
    var second = q(card, ".v2");
    if (second) second.textContent = v2 || "";
    var det = q(card, ".stat-detail");
    if (det) det.textContent = detail || "";
    var u = q(card, ".unit");
    if (u) u.textContent = unit || "";
    var fill = q(card, ".bar-fill");
    if (fill && known(barPct)) {
      fill.style.width = Math.min(barPct, 100) + "%";
      fill.style.background = levelColor(barPct);
    }
  }

  function degrees(t) { return known(t) ? Math.round(t) + "°C" : ""; }

  function renderGame(sys, act, now) {
    var game = act && act.game;
    if (!game || !sys || sys.error) return;
    $("g-name").textContent = game.name;
    var meta = ["playing for " + duration(now - game.since)];
    if (known(game.cpu)) meta.push("CPU " + Math.round(game.cpu) + "%");
    $("g-meta").textContent = meta.join(" · ");
    // No store art: the game's own icon fills the space, big, over a blurred copy of itself.
    var asIcon = !game.art && game.icon;
    var holder = $("game-art").parentNode;
    holder.className = "game-art" + (asIcon ? " as-icon" : "");
    setImage($("game-art"), holder, "has-art", game.art || game.icon);
    $("game-art-bg").style.backgroundImage = asIcon ? "url(" + game.icon + ")" : "none";
    setImage($("game-icon"), $("game-icon"), "shown", asIcon ? null : game.icon);

    var g = sys.gpu;
    if (g) {
      var gpuDetail = [];
      if (g.clock) gpuDetail.push(Math.round(g.clock) + " MHz");
      if (known(g.power)) gpuDetail.push(Math.round(g.power) + " W");
      if (known(g.fan)) gpuDetail.push("fan " + Math.round(g.fan) + "%");
      setStat("st-gpu", known(g.percent) ? Math.round(g.percent) : "--", degrees(g.temp), gpuDetail.join(" · "),
              null, g.percent);
      if (g.mem_total) {
        setStat("st-vram", gb(g.mem_used), null, null, " / " + gb(g.mem_total) + " GB", 100 * g.mem_used / g.mem_total);
      }
    }
    var c = sys.cpu;
    var cpuDetail = [];
    if (c.clock) cpuDetail.push(decimal(c.clock / 1000) + " GHz");
    if (known(c.power)) cpuDetail.push(Math.round(c.power) + " W");
    if (!known(c.temp) && sys.sensors_hint) cpuDetail.push("no temperature: " + sys.sensors_hint);
    setStat("st-cpu", Math.round(c.percent), degrees(c.temp), cpuDetail.join(" · "), null, c.percent);
    setStat("st-ram", gb(sys.ram.used), null, null, " / " + gb(sys.ram.total) + " GB", sys.ram.percent);
  }

  // ---- Now playing (PC screen) ------------------------------------------------

  function minutes(seconds) {
    var s = Math.max(0, Math.round(seconds));
    return Math.floor(s / 60) + ":" + pad(s % 60);
  }

  function renderMedia(media) {
    var block = $("media-block");
    // Hidden while the music screen is on: it shows the same, bigger.
    if (cfg.screens.indexOf("music") >= 0 || !media || !media.available || !media.playing || !media.title) {
      block.style.display = "none";
      return;
    }
    block.style.display = "";
    block.className = "now-block" + (media.status === "paused" ? " paused" : "");
    $("media-title").textContent = media.title;
    var meta = [];
    if (media.artist) meta.push(media.artist);
    if (media.app) meta.push(media.app);
    if (media.status === "paused") meta.push("paused");
    var hasTime = known(media.position) && media.duration;
    if (hasTime) meta.push(minutes(media.position) + " / " + minutes(media.duration));
    $("media-meta").textContent = meta.join(" · ");
    var fill = $("media-bar");
    fill.style.transition = "none";
    fill.style.width = hasTime ? Math.min(100, 100 * media.position / media.duration) + "%" : "0";
    fill.parentNode.style.display = hasTime ? "" : "none";
  }

  function renderPhone(phone) {
    var box = $("phone-batt");
    var devices = phone && phone.devices ? phone.devices : [];
    var d = null;  // the hottest phone, if several are plugged in
    for (var i = 0; i < devices.length; i++) {
      if (!d || (devices[i].temp || 0) > (d.temp || 0)) d = devices[i];
    }
    box.innerHTML = "";
    if (!d && !browserBattery) {
      box.style.display = "none";
      return;
    }
    box.style.display = "inline";
    box.appendChild(icon("battery"));
    if (!d) {
      box.className = "phone-batt";
      box.appendChild(document.createTextNode(Math.round(browserBattery.level * 100) + "%"));
      return;
    }
    var text = known(d.level) ? d.level + "%" : "--";
    if (known(d.temp)) text += " · " + Math.round(d.temp) + "°C";
    box.appendChild(document.createTextNode(text));

    var hot = (known(d.temp) && d.temp >= BATTERY_HOT) || d.health === "overheat";
    box.className = "phone-batt" + (hot ? " hot" : known(d.temp) && d.temp >= BATTERY_WARM ? " warm" : "");
    if (hot && !batteryAlerted) {
      batteryAlerted = true;
      chime();
      toast("attention", "Phone battery is hot",
            (known(d.temp) ? Math.round(d.temp) + "°C · " : "") + "unplug it or give it more air", "alert", 15);
    } else if (!hot && known(d.temp) && d.temp < BATTERY_RESET) {
      batteryAlerted = false;
    }
  }

  // ---- Data from the PC ----------------------------------------------------

  // Dev mode (sparescreen --dev): if the code changed, reload the page automatically.
  var devVersion = null;
  function checkDev(version) {
    if (!version) return;
    if (devVersion === null) devVersion = version;
    else if (version !== devVersion) location.reload();
  }

  function render(data) {
    lastData = Date.now();
    if (offlineOn) updateOffline(new Date());
    if (!namesTried) {
      namesTried = true;
      tryNames();
    }
    checkDev(data.dev);
    onServerConfig(data.config);
    renderHardware(data.system);
    renderAi(data, data.time);
    renderPc(data.system, data.activity, data.time);
    renderPhone(data.phone);
    renderMedia(data.media);

    // Game mode and the music screen change which screens rotate.
    var wasGame = gameOn, wasMusic = musicOn;
    gameOn = !!(cfg.game_mode && data.activity && data.activity.game);
    musicOn = !!(data.media && data.media.playing && data.media.title);
    if (gameOn !== wasGame) {
      show(0);  // entering: the game screen; leaving: back to the first screen
      startRotation();
    } else if (musicOn !== wasMusic) {
      // The list changed: stay on the same screen (or its neighbor if music just left).
      var active = q(document, ".screen.active");
      var name = active && active.getAttribute("data-name");
      show(current);
      if (name) showNamed(name);
      startRotation();
    }
    renderMusic(data.media);
    renderGame(data.system, data.activity, data.time);
  }

  function request(method, url, body, done) {
    var xhr = new XMLHttpRequest();
    xhr.open(method, url);
    xhr.onload = function () {
      var data = {};
      try { data = JSON.parse(xhr.responseText); } catch (e) { /* not JSON */ }
      done(xhr.status, data);
    };
    xhr.onerror = function () { done(0, {}); };
    if (body) xhr.setRequestHeader("Content-Type", "application/json");
    xhr.send(body ? JSON.stringify(body) : null);
  }

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

  // ---- Pairing ---------------------------------------------------------------
  // Devices on the network must type the code shown by the agent once; the PC
  // itself and phones on USB are trusted automatically.

  var pairingOpen = false;
  var events = null;

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
    events.onopen = function () { $("status").className = "dot on"; };
    events.onmessage = function (e) { render(JSON.parse(e.data)); };
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
})();
