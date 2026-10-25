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
    $("phone-url").textContent = state.phone_url || "Wi-Fi off (this PC only)";
    $("code").textContent = spaced(state.code);
    var waiting = state.waiting;
    $("waiting-card").className = "card" + (waiting ? " shown" : "");
    if (waiting) {
      $("waiting-name").textContent = waiting.name;
      $("waiting-address").textContent = waiting.address;
      $("waiting-code").textContent = spaced(state.code);
    }
    renderDevices(state.devices);
    renderChecks(state.checks);
    $("autostart").checked = state.autostart;
    $("autostart-label").textContent = state.autostart_label;
    if (state.message) showMessage(state.message);
  }

  function refresh() {
    request("GET", "panel/state", null, function (status, state) {
      if (status === 200 && state) render(state);
      else $("running").textContent = "SpareScreen isn't running. Start it again to use this window.";
    });
  }

  $("open-dashboard").addEventListener("click", function () { act("dashboard"); });
  $("autostart").addEventListener("change", function () { act("autostart", { on: $("autostart").checked }); });

  refresh();
  setInterval(refresh, 2000);
})();
