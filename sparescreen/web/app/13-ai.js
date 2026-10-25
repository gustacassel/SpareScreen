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
