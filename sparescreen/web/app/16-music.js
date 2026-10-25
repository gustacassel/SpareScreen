  // ---- Music screen ----------------------------------------------------------

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
  }
