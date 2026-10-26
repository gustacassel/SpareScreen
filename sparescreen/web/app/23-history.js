  // ---- History: small charts of the last minutes -----------------------------
  // CPU, GPU and RAM usage faint behind their cards, each temperature next to its number,
  // and the network speed. The agent keeps the last minutes (one point every 2 s) and
  // hands them over when the stream opens; between those, the page adds the live readings.

  var TREND_WINDOW = 300;           // seconds shown (the agent's history.WINDOW)
  var TREND_STEP = 2;               // seconds between points
  var TREND_GAP = 3 * TREND_STEP;   // a longer hole (PC asleep, no connection) breaks the line
  var TREND_NET_FLOOR = 65536;      // the network chart's top is at least 64 KB/s
  var trend = {};                   // series name -> [[time, value], ...], oldest first
  var trendAt = 0;                  // time of the last live point
  var trendSums = {};               // readings since then, averaged into the next point

  function trimTrend(list, now) {
    while (list.length && list[0][0] < now - TREND_WINDOW) list.shift();
  }

  // Adds points to a series, keeping it in time order without duplicates (the agent's
  // points and the page's own can overlap).
  function mergeTrend(name, points, now) {
    var all = (trend[name] || []).concat(points);
    all.sort(function (a, b) { return a[0] - b[0]; });
    var kept = [];
    for (var i = 0; i < all.length; i++) {
      if (!kept.length || all[i][0] - kept[kept.length - 1][0] >= TREND_STEP / 2) kept.push(all[i]);
    }
    trimTrend(kept, now);
    trend[name] = kept;
  }

  function addTrend(t, values) {
    for (var name in values) {
      if (!trend[name]) trend[name] = [];
      if (typeof values[name] === "number") trend[name].push([t, values[name]]);
      trimTrend(trend[name], t);
    }
  }

  // Points as an SVG path in the 100 x 100 box: x from the time, y from the value between
  // lo and hi. `area` closes each stretch down to the bottom, for a filled shape.
  function trendPath(points, now, lo, hi, area) {
    var d = "", first = null, lastX = 0, lastT = null;
    var span = hi - lo || 1;
    function close() { if (area && first !== null) d += "L" + lastX + " 100L" + first + " 100Z"; }
    for (var i = 0; i < points.length; i++) {
      var x = Math.round((points[i][0] - now + TREND_WINDOW) / TREND_WINDOW * 1000) / 10;
      var v = Math.max(lo, Math.min(hi, points[i][1]));
      var y = Math.round((100 - (v - lo) / span * 100) * 10) / 10;
      if (lastT === null || points[i][0] - lastT > TREND_GAP) {
        close();
        d += "M" + x + " " + y;
        first = x;
      } else {
        d += "L" + x + " " + y;
      }
      lastX = x;
      lastT = points[i][0];
    }
    close();
    return d;
  }

  function setPath(svg, selector, d) {
    var path = svg && q(svg, selector);
    if (path) path.setAttribute("d", d);
  }

  function drawUsage(card, points, now) {
    var svg = q(card, ".hw-spark");
    setPath(svg, ".spark-line", trendPath(points, now, 0, 100, false));
    setPath(svg, ".spark-area", trendPath(points, now, 0, 100, true));
  }

  // A temperature's own scale, at least 10 °C tall so small wobbles stay small.
  function drawTemp(card, points, now) {
    var lo = Infinity, hi = -Infinity;
    for (var i = 0; i < points.length; i++) {
      lo = Math.min(lo, points[i][1]);
      hi = Math.max(hi, points[i][1]);
    }
    var mid = (lo + hi) / 2, half = Math.max((hi - lo) / 2 + 1, 5);
    setPath(q(card, ".temp-spark"), ".spark-line",
            points.length ? trendPath(points, now, mid - half, mid + half, false) : "");
  }

  function drawNet(now) {
    var down = trend.net_down || [], up = trend.net_up || [];
    var peak = 0, i;
    for (i = 0; i < down.length; i++) peak = Math.max(peak, down[i][1]);
    for (i = 0; i < up.length; i++) peak = Math.max(peak, up[i][1]);
    var top = Math.max(peak, TREND_NET_FLOOR);
    var svg = q(document, ".net-spark");
    setPath(svg, ".spark-area.down", trendPath(down, now, 0, top, true));
    setPath(svg, ".spark-line.down", trendPath(down, now, 0, top, false));
    setPath(svg, ".spark-line.up", trendPath(up, now, 0, top, false));
    $("net-peak").textContent = down.length || up.length ? rate(peak) : "--";
  }

  function drawTrend(now) {
    drawUsage($("cpu"), trend.cpu || [], now);
    drawUsage($("gpu"), trend.gpu || [], now);
    drawUsage($("ram"), trend.ram || [], now);
    drawTemp($("cpu"), trend.cpu_temp || [], now);
    drawTemp($("gpu"), trend.gpu_temp || [], now);
    drawNet(now);
  }

  // From render(): one point every TREND_STEP seconds, the average of the readings since
  // the previous one (like the agent's), so a one-second blip doesn't make the line jump.
  function recordTrend(data) {
    var s = data.system, t = data.time;
    if (!s || s.error || !t) return;
    var values = {
      cpu: s.cpu.percent, cpu_temp: s.cpu.temp,
      gpu: s.gpu ? s.gpu.percent : null, gpu_temp: s.gpu ? s.gpu.temp : null,
      ram: s.ram.percent, net_down: s.net.down, net_up: s.net.up
    };
    var name;
    for (name in values) {
      if (!trendSums[name]) trendSums[name] = [0, 0];
      if (typeof values[name] === "number") {
        trendSums[name][0] += values[name];
        trendSums[name][1] += 1;
      }
    }
    if (t - trendAt < TREND_STEP) return;
    trendAt = t;
    for (name in values) {
      var sum = trendSums[name];
      values[name] = sum[1] ? sum[0] / sum[1] : null;
      trendSums[name] = [0, 0];
    }
    addTrend(t, values);
    drawTrend(t);
  }

  // When the stream opens: the agent's points fill the chart (and any hole while the
  // phone was away). Older agents don't have /history: the chart just starts empty.
  function loadTrend() {
    request("GET", "history", null, function (status, data) {
      if (status !== 200 || !data || !data.points || !data.series || !data.points.length) return;
      var now = data.points[data.points.length - 1][0];
      for (var j = 0; j < data.series.length; j++) {
        var points = [];
        for (var i = 0; i < data.points.length; i++) {
          var row = data.points[i];
          if (typeof row[j + 1] === "number") points.push([row[0], row[j + 1]]);
        }
        mergeTrend(data.series[j], points, Math.max(now, trendAt));
      }
      drawTrend(Math.max(now, trendAt));
    });
  }
