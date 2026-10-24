// Deliberately simple JS (no modules or recent syntax) so it runs
// on old phone browsers.
//
// Preferences (theme, screens, auto-switch, alerts, sound) are saved on the PC
// and arrive with the data; the gear in the top corner opens the screen to change them.
//
// URL parameters (for testing): ?screen=hardware|claude|pc pins a screen; ?theme=neon forces a theme.
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
  var SCREEN_NAMES = { hardware: "Hardware", claude: "Claude", pc: "PC" };
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

  var cfg = { theme: "graphite", screens: ["hardware", "claude", "pc"], rotate: 20, notify: true, sound: true,
              fan_names: {}, cpu_fan: null };
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

  // Screens in the rotation: the one pinned in the URL, or the ones enabled in the config.
  function enabledScreens() {
    var list = [];
    for (var i = 0; i < allScreens.length; i++) {
      var name = allScreens[i].getAttribute("data-name");
      if (fixed ? name === fixed : cfg.screens.indexOf(name) >= 0) list.push(allScreens[i]);
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
    if (!fixed && cfg.rotate > 0 && !toastBusy && !settingsOpen && enabledScreens().length > 1) {
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
    fillChips("set-screens", ["hardware", "claude", "pc"].map(function (name) {
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
    if (settingsOpen) return;
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
    setExtra(cpu, sys.cpu.power, sys.cpu.temp === null ? "no temperature sensor" : "");
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
      $("game-name").textContent = game ? game.name : "No game running";
      $("game-name").className = "now-name" + (game ? "" : " none");
      $("game-meta").textContent = game
        ? "running for " + duration(now - game.since) + " · CPU " + Math.round(game.cpu) + "% · " + size(game.mem)
        : "";
      var focus = act.focus;
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

  // ---- Claude --------------------------------------------------------------

  function renderLimit(id, win, now, weekly) {
    var box = $(id);
    var pct = q(box, ".limit-pct");
    var fill = q(box, ".bar-fill");
    var reset = q(box, ".limit-reset");
    if (!win) {
      pct.textContent = "--";
      pct.className = "limit-pct na";
      fill.style.width = "0";
      reset.textContent = "no data";
      return;
    }
    if (win.renewed) {
      pct.textContent = "renewed";
      pct.className = "limit-pct na";
      fill.style.width = "0";
      reset.textContent = "renewed " + (weekly ? weekdayTime(win.resets_at) : "at " + clockTime(win.resets_at));
      return;
    }
    pct.textContent = Math.round(win.percent) + "%";
    pct.className = "limit-pct";
    fill.style.width = Math.min(win.percent, 100) + "%";
    fill.style.background = levelColor(win.percent);
    var left = win.resets_at - now;
    reset.textContent = "resets in " + duration(left) +
      (weekly && left > 86400 ? " (" + weekdayTime(win.resets_at) + ")" : " (" + clockTime(win.resets_at) + ")");
  }

  // Alerts: compare each session's status with the previous reading.
  var lastStatus = {};
  var justDone = {};  // session id -> highlight until (ms)

  function watchSessions(sessions) {
    for (var i = 0; i < sessions.length; i++) {
      var s = sessions[i];
      if (lastStatus[s.id] === "busy" && s.status !== "busy") {
        var done = s.status === "idle";
        justDone[s.id] = Date.now() + 20000;
        if (cfg.notify) {
          showNamed("claude");
          chime();
          toast(done ? "done" : "attention",
                done ? "Session finished" : "Session needs you",
                s.name, done ? "check" : "alert");
        }
      }
      lastStatus[s.id] = s.status;
    }
  }

  function renderSessions(sessions, now) {
    var list = $("cl-sessions");
    list.innerHTML = "";
    if (!sessions.length) {
      list.appendChild(el("li", "empty", "No open sessions"));
      return;
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
  }

  function renderClaude(cl, now) {
    if (!cl || cl.error) return;
    var limits = cl.limits;
    renderLimit("lim-5h", limits && limits.five_hour, now, false);
    renderLimit("lim-week", limits && limits.seven_day, now, true);
    var age = limits && limits.updated_at ? now - limits.updated_at : null;
    $("lim-updated").textContent = age === null
      ? "Limits come from the status line: open Claude Code in a terminal."
      : "limits updated " + (age < 60 ? "just now" : ago(age) + " ago");

    var f = cl.fable_week;
    $("fable-tokens").textContent = shortNumber(f.input + f.output + f.cache_read);
    $("fable-detail").textContent = "tokens · " + f.responses + " responses · Claude Code on this PC";

    var t = cl.today;
    $("cl-today").textContent = shortNumber(t.input + t.output + t.cache_read);
    watchSessions(cl.sessions);
    renderSessions(cl.sessions, now);
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
    checkDev(data.dev);
    onServerConfig(data.config);
    renderHardware(data.system);
    renderClaude(data.claude, data.time);
    renderPc(data.system, data.activity, data.time);
  }

  // EventSource reconnects on its own if the PC drops or the Wi-Fi flickers.
  var events = new EventSource("events");
  events.onopen = function () { $("status").className = "dot on"; };
  events.onerror = function () { $("status").className = "dot"; };
  events.onmessage = function (e) { render(JSON.parse(e.data)); };

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
