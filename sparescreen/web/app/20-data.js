  // ---- Data from the PC ----------------------------------------------------

  // The agent's code changed: reload the page so it matches. In dev mode (sparescreen --dev)
  // on every change, otherwise when SpareScreen was updated to a new version.
  var codeVersion = null;
  function checkVersion(version) {
    if (!version) return;
    if (codeVersion === null) codeVersion = version;
    else if (version !== codeVersion) location.reload();
  }

  function render(data) {
    lastData = Date.now();
    var wasAsleep = pcAsleep;
    pcAsleep = !!(data.power && data.power.asleep);
    if (offlineOn || pcAsleep !== wasAsleep) updateOffline(new Date());
    if (!namesTried) {
      namesTried = true;
      tryNames();
    }
    updateInfo = data.update || null;
    checkVersion(data.dev || (updateInfo && updateInfo.version));
    onServerConfig(data.config);
    renderHardware(data.system);
    checkHeat(data.system);
    renderAi(data, data.time);
    renderPc(data.system, data.activity, data.time);
    recordTrend(data);
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
      screensChanged();
    }
    watchPhotos(data.photos);
    renderBanner(cfg.banner);
    renderMusic(data.media);
    renderGame(data.system, data.activity, data.time);
    renderFps(data.fps);
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
