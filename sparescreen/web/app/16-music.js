  // ---- Music screen ----------------------------------------------------------

  var musicStatus = "";  // "playing" or "paused", from the last reading (or the last press)

  function setPlayIcon() {
    $("mc-play").setAttributeNS("http://www.w3.org/1999/xlink", "xlink:href",
                                musicStatus === "paused" ? "#i-play" : "#i-pause");
  }

  // Previous, play/pause and next: sent to the PC, which passes them to the player.
  function pressMusic(action) {
    request("POST", "media", { action: action }, function () {});
    if (action === "play_pause") {  // show it right away; the next reading confirms it
      musicStatus = musicStatus === "paused" ? "playing" : "paused";
      setPlayIcon();
    }
    startRotation();  // pressing a button means staying here: start the countdown again
  }

  var musicButtons = $("music-controls").getElementsByTagName("button");
  for (var mb = 0; mb < musicButtons.length; mb++) {
    (function (button) {
      button.addEventListener("click", function (e) {
        e.stopPropagation();  // not a tap on the screen (next screen)
        if (!button.disabled) pressMusic(button.getAttribute("data-action"));
      });
      // Nor the start of a long press (next theme).
      button.addEventListener("touchstart", function (e) { e.stopPropagation(); });
      button.addEventListener("mousedown", function (e) { e.stopPropagation(); });
    })(musicButtons[mb]);
  }

  function renderControls(controls) {
    controls = controls || {};
    var any = false;
    for (var i = 0; i < musicButtons.length; i++) {
      var on = !!controls[musicButtons[i].getAttribute("data-action")];
      musicButtons[i].disabled = !on;
      any = any || on;
    }
    $("music-controls").style.display = any ? "" : "none";
    setPlayIcon();
  }

  function renderMusic(media) {
    if (!media || !media.playing || !media.title) return;
    var card = $("music-art").parentNode.parentNode;
    card.className = "card music" + (media.status === "paused" ? " paused" : "");
    setImage($("music-art"), $("music-art").parentNode, "has-art", media.art);
    setImage($("music-app-icon"), $("music-app-icon").parentNode, "has-icon", media.app_icon);
    $("music-app").textContent = media.app || "";
    $("music-title").textContent = media.title;
    $("music-artist").textContent = media.artist || "";
    $("music-album").textContent = media.album || "";
    var hasTime = known(media.position) && media.duration;
    $("music-bar").parentNode.style.display = hasTime ? "" : "none";
    $("music-bar").style.width = hasTime ? Math.min(100, 100 * media.position / media.duration) + "%" : "0";
    $("music-pos").textContent = hasTime ? minutes(media.position) : "";
    $("music-dur").textContent = hasTime ? minutes(media.duration) : (media.status === "paused" ? "paused" : "");
    musicStatus = media.status;
    renderControls(media.controls);
  }
