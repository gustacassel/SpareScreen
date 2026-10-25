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
