  // ---- Screens -------------------------------------------------------------

  var allScreens = Array.prototype.slice.call(document.querySelectorAll(".screen"));
  var current = 0;
  var rotateTimer = null;
  var fixed = params.get("screen");

  var gameOn = false;   // a game is running and game mode is on: only the game screen
  var musicOn = false;  // something is playing: the music screen joins the rotation

  // Screens in the rotation: the one pinned in the URL, the game screen in game mode,
  // or the ones turned on in the settings (music only while something plays).
  function enabledScreens() {
    var list = [];
    for (var i = 0; i < allScreens.length; i++) {
      var name = allScreens[i].getAttribute("data-name");
      var on;
      if (fixed) on = name === fixed;
      else if (gameOn) on = name === "game";
      else on = name !== "game" && cfg.screens.indexOf(name) >= 0 && (name !== "music" || musicOn);
      if (on) list.push(allScreens[i]);
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
    if (!fixed && cfg.rotate > 0 && !toastBusy && !settingsOpen && !pairingOpen && enabledScreens().length > 1) {
      rotateTimer = setInterval(function () { show(current + 1); }, cfg.rotate * 1000);
    }
  }
