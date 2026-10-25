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

  // Yellow and red relative to where the part starts to throttle, when the PC knows it
  // (the chip's own limit); otherwise the fixed fallbacks given.
  function tempLevels(limit, warn, hot) {
    return known(limit) ? [limit - 15, limit - 5] : [warn, hot];
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
    var cpuLevels = tempLevels(sys.cpu.temp_limit, 75, 90);
    setTemp(cpu, sys.cpu.temp, cpuLevels[0], cpuLevels[1]);
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
      var gpuLevels = tempLevels(g.temp_limit, 75, 85);
      setTemp(gpu, g.temp, gpuLevels[0], gpuLevels[1]);
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
