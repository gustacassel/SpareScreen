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
    // A small icon blown up looks blurry; crisp pixels suit it better (e.g. Minecraft's 32 px block).
    $("game-art").onload = function () { this.className = this.naturalWidth < 96 ? "pixel" : ""; };
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

  // Game FPS from PresentMon (Windows, once set up in the PC window); hidden otherwise.
  function renderFps(fps) {
    var on = !!(fps && fps.playing && fps.fps);
    $("g-fps").className = "game-fps" + (on ? " shown" : "");
    if (!on) return;
    $("g-fps-v").textContent = fps.fps;
    $("g-fps-sub").textContent = "1% low " + fps.low1 + " · " + fps.frametime + " ms";
  }
