// The dashboard's script. The files in web/app/ are joined in order into app.js by the
// agent (server.app_js), inside one function, so they share their variables like a single
// file. Deliberately simple JS (no modules or recent syntax) so it runs on old phone browsers.
//
// Preferences (theme, screens, auto-switch, alerts, sound) are saved on the PC
// and arrive with the data; the gear in the top corner opens the screen to change them.
//
// URL parameters (for testing): ?screen=hardware|ai|pc pins a screen; ?theme=neon forces a theme.
// Gestures: tap = next screen; long press = next theme.

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
  var SCREEN_NAMES = { hardware: "Hardware", ai: "AI", pc: "PC", music: "Music", photos: "Photos" };
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
