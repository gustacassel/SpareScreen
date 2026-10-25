// The PC window: polls /panel/state every 2 s and sends the buttons to /panel/action.
// Plain ES5 like the dashboard, so the same rules apply to every script of the page.
(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function request(method, path, body, done) {
    var xhr = new XMLHttpRequest();
    xhr.open(method, path);
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.onload = function () {
      var data = null;
      try { data = JSON.parse(xhr.responseText); } catch (e) { data = null; }
      if (done) done(xhr.status, data);
    };
    xhr.onerror = function () { if (done) done(0, null); };
    xhr.send(body ? JSON.stringify(body) : null);
  }

  function ago(seconds) {
    if (seconds < 60) return "just now";
    if (seconds < 3600) return Math.floor(seconds / 60) + " min";
    if (seconds < 86400) return Math.floor(seconds / 3600) + " h";
    return Math.floor(seconds / 86400) + " days";
  }

  function spaced(code) { return code ? code.slice(0, 3) + " " + code.slice(3) : "------"; }

  function act(action, extra) {
    var body = extra || {};
    body.action = action;
    request("POST", "panel/action", body, function () { refresh(); });
  }

  function row(status, title, detail, button) {
    var li = el("li");
    li.appendChild(el("span", "dot " + (status || "")));
    var main = el("div", "main");
    main.appendChild(el("div", "title", title));
    if (detail) main.appendChild(el("div", "detail", detail));
    li.appendChild(main);
    if (button) {
      var btn = el("button", "btn small", button.label);
      btn.addEventListener("click", button.onclick);
      li.appendChild(btn);
    }
    return li;
  }

  function fill(list, items, empty) {
    list.innerHTML = "";
    if (!items.length) list.appendChild(el("li", "empty", empty));
    for (var i = 0; i < items.length; i++) list.appendChild(items[i]);
  }

  var KIND = { usb: "USB", wifi: "Wi-Fi", pc: "This PC" };

  function renderDevices(devices) {
    var items = [];
    var i;
    for (i = 0; i < devices.usb.length; i++) {
      var phone = devices.usb[i];
      var battery = [];
      if (phone.level !== null && phone.level !== undefined) battery.push(phone.level + "%");
      if (phone.temp !== null && phone.temp !== undefined) battery.push(Math.round(phone.temp) + " °C");
      items.push(row("ok", phone.model, "USB cable" + (battery.length ? " · battery " + battery.join(" · ") : "")));
    }
    for (i = 0; i < devices.paired.length; i++) {
      (function (paired, index) {
        var detail = "Paired over Wi-Fi" + (paired.address ? " · " + paired.address : "");
        if (paired.added) detail += " · since " + new Date(paired.added * 1000).toLocaleDateString();
        items.push(row("ok", paired.name, detail,
                       { label: "Remove", onclick: function () { act("unpair", { index: index }); } }));
      })(devices.paired[i], i);
    }
    for (i = 0; i < devices.open.length; i++) {
      var open = devices.open[i];
      if (open.kind === "usb" && devices.usb.length) continue;  // already listed by model
      items.push(row(open.kind === "pc" ? "" : "ok", open.name,
                     "Dashboard open · " + KIND[open.kind] + (open.kind === "wifi" ? " · " + open.address : "") +
                     " · " + ago(open.since)));
    }
    fill($("devices"), items, "No device connected yet.");
  }

  var FOUND_BY = { library: "found in a game store's library", mine: "in your games", auto: "detected automatically" };

  function fileName(path) { return path.replace(/^.*[\\\/]/, ""); }

  function renderGames(games) {
    var now = games.current;
    if (now) {
      fill($("game-now"), [row("ok", "Playing: " + now.name, FOUND_BY[now.source] || "",
        { label: "Not a game", onclick: function () { act("not_game_add"); } })], "");
    } else {
      fill($("game-now"), [row("", "No game running",
        games.auto ? "Any game in full screen is detected by itself (FPS in games is on)."
                   : "Games from Steam, Epic, GOG, Xbox, EA, Ubisoft, Riot and Battle.net are found by " +
                     "themselves. Others: add them below, or turn on FPS in games to detect them automatically.")], "");
    }
    var mine = [];
    var i;
    for (i = 0; i < games.mine.length; i++) {
      (function (game) {
        mine.push(row("ok", game.name || fileName(game.exe), fileName(game.exe),
          { label: "Remove", onclick: function () { act("game_remove", { exe: game.exe }); } }));
      })(games.mine[i]);
    }
    fill($("my-games"), mine, "None yet.");
    var running = [];
    for (i = 0; i < games.running.length; i++) {
      (function (prog) {
        running.push(row("", prog.name, fileName(prog.exe),
          { label: "It's a game", onclick: function () { act("game_add", { exe: prog.exe, name: prog.name }); } }));
      })(games.running[i]);
    }
    fill($("running-apps"), running, "Nothing to show.");
    var others = [];
    for (i = 0; i < games.not_games.length; i++) {
      (function (prog) {
        others.push(row("", prog.name, "Never taken for a game",
          { label: "Undo", onclick: function () { act("not_game_remove", { exe: prog.exe }); } }));
      })(games.not_games[i]);
    }
    fill($("not-games"), others, "");
    $("not-games-card").className = "card" + (others.length ? "" : " empty");
  }

  function renderChecks(checks) {
    var items = [];
    for (var i = 0; i < checks.length; i++) {
      (function (check) {
        var button = check.action ? { label: check.action.label, onclick: function () { act(check.action.id); } } : null;
        items.push(row(check.status, check.title, check.detail, button));
      })(checks[i]);
    }
    fill($("checks"), items, "");
  }

  // ---- Update -----------------------------------------------------------------

  var updating = false;  // downloading or restarting: the agent going away is expected

  function renderUpdate(update) {
    updating = !!update && (update.status === "downloading" || update.status === "restarting");
    $("update").className = "update" + (update && update.latest ? " shown" : "");
    if (!update) return;
    $("update-auto").checked = update.enabled;
    if (!update.latest) return;
    var title = "SpareScreen " + update.latest + " is available";
    var detail = "You have " + update.current + ".";
    if (update.status === "downloading") {
      title = "Downloading " + update.latest + "..." + (update.progress !== null ? " " + update.progress + "%" : "");
      detail = "SpareScreen restarts by itself when it's ready.";
    } else if (update.status === "restarting") {
      title = "Restarting with " + update.latest + "...";
      detail = "This window reloads by itself.";
    } else if (update.status === "failed") {
      detail = update.error;
    } else if (!update.can_install) {
      detail += " " + update.how;
    }
    $("update-title").textContent = title;
    $("update-detail").textContent = detail;
    $("update-install").style.display = update.can_install || updating ? "" : "none";
    $("update-install").disabled = updating;
    $("update-install").textContent = update.status === "failed" ? "Try again" : "Update";
  }

  // An update restarts SpareScreen: wait for the new version, then load its window.
  function waitForNewVersion() {
    var tries = 0;
    $("running").textContent = "Restarting with the new version...";
    (function poll() {
      request("GET", "panel/state", null, function (status) {
        if (status === 200) location.reload();
        else if (++tries < 60) setTimeout(poll, 2000);
        else $("running").textContent = "SpareScreen didn't come back after the update. Start it again.";
      });
    })();
  }

  // ---- Tabs -------------------------------------------------------------------

  var TAB_KEY = "sparescreen_panel_tab";
  var tabs = document.querySelectorAll(".tab");
  var pages = document.querySelectorAll(".page");
  var currentTab = null;

  function showTab(name) {
    currentTab = name;
    for (var i = 0; i < tabs.length; i++) {
      tabs[i].className = "tab" + (tabs[i].getAttribute("data-tab") === name ? " on" : "");
    }
    for (var j = 0; j < pages.length; j++) {
      pages[j].className = "page" + (pages[j].getAttribute("data-page") === name ? " on" : "");
    }
    try { localStorage.setItem(TAB_KEY, name); } catch (e) { /* not saved, no harm */ }
  }

  for (var t = 0; t < tabs.length; t++) {
    tabs[t].addEventListener("click", function () { showTab(this.getAttribute("data-tab")); });
  }

  function dot(id, level) { $(id).className = "tab-dot" + (level ? " " + level : ""); }

  // The worst check on the Status tab; the Phone tab when a device asks to pair.
  function updateDots(state) {
    var worst = "";
    for (var i = 0; i < state.checks.length; i++) {
      if (state.checks[i].status === "error") worst = "error";
      else if (state.checks[i].status === "warn" && !worst) worst = "warn";
    }
    dot("dot-status", worst);
    dot("dot-phone", state.waiting ? "info" : "");
  }

  var wasWaiting = false;

  var messageTimer = null;

  function showMessage(text) {
    $("message").textContent = text;
    $("message").className = "message shown";
    clearTimeout(messageTimer);
    messageTimer = setTimeout(function () { $("message").className = "message"; }, 8000);
  }

  function render(state) {
    $("version").textContent = state.version ? "v" + state.version : "";
    $("running").textContent = "Running · " + state.local_url.replace("http://", "");
    // A name that a phone already reached survives the router changing the PC's IP: show it first.
    var names = state.names || [];
    var working = names.length && names[0].works ? names[0].url : null;
    $("phone-url").textContent = working || state.phone_url || "Wi-Fi off (this PC only)";
    if (working) {
      $("names").textContent = "Works on your phone and keeps working if the IP changes. By IP: " + state.phone_url;
    } else if (names.length) {
      var urls = [];
      for (var n = 0; n < names.length; n++) urls.push(names[n].url);
      $("names").textContent = "The phone also tries " + urls.join(" and ") +
        " and switches to it if it works (keeps working if the IP changes).";
    } else {
      $("names").textContent = "";
    }
    $("code").textContent = spaced(state.code);
    var waiting = state.waiting;
    $("waiting-card").className = "card" + (waiting ? " shown" : "");
    if (waiting) {
      $("waiting-name").textContent = waiting.name;
      $("waiting-address").textContent = waiting.address;
      $("waiting-code").textContent = spaced(state.code);
    }
    renderDevices(state.devices);
    if (state.games) renderGames(state.games);
    renderChecks(state.checks);
    renderUpdate(state.update);
    $("autostart").checked = state.autostart;
    $("autostart-label").textContent = state.autostart_label;
    if (state.message) showMessage(state.message);
    updateDots(state);
    if (waiting && !wasWaiting) showTab("phone");  // someone needs the code: show it
    wasWaiting = !!waiting;
  }

  function refresh() {
    request("GET", "panel/state", null, function (status, state) {
      if (status === 200 && state) render(state);
      else if (!updating) $("running").textContent = "SpareScreen isn't running. Start it again to use this window.";
    });
  }

  // Quitting SpareScreen (tray > Quit) drops this stream: close the window with it.
  // A quick restart (--dev) is back within a moment, so check once before closing.
  function watchAgent() {
    if (!window.EventSource) return;
    var alive = new EventSource("panel/events");
    alive.onerror = function () {
      alive.close();
      if (updating) {
        waitForNewVersion();
        return;
      }
      setTimeout(function () {
        request("GET", "panel/state", null, function (status) {
          if (status === 200) {
            watchAgent();
            return;
          }
          window.close();
          $("running").textContent = "SpareScreen was closed. You can close this window.";
        });
      }, 1500);
    };
  }

  $("open-dashboard").addEventListener("click", function () { act("dashboard"); });
  watchAgent();
  $("autostart").addEventListener("change", function () { act("autostart", { on: $("autostart").checked }); });
  $("update-auto").addEventListener("change", function () { act("update_auto", { on: $("update-auto").checked }); });
  $("update-install").addEventListener("click", function () { act("update_install"); });
  $("update-notes").addEventListener("click", function () { act("update_notes"); });

  var savedTab = null;
  try { savedTab = localStorage.getItem(TAB_KEY); } catch (e) { savedTab = null; }
  showTab(savedTab === "games" || savedTab === "status" ? savedTab : "phone");
  refresh();
  setInterval(refresh, 2000);
})();
