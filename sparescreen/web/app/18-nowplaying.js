  // ---- Now playing (PC screen) ------------------------------------------------

  function minutes(seconds) {
    var s = Math.max(0, Math.round(seconds));
    return Math.floor(s / 60) + ":" + pad(s % 60);
  }

  function renderMedia(media) {
    var block = $("media-block");
    // Hidden while the music screen is on: it shows the same, bigger.
    if (cfg.screens.indexOf("music") >= 0 || !media || !media.available || !media.playing || !media.title) {
      block.style.display = "none";
      return;
    }
    block.style.display = "";
    block.className = "now-block" + (media.status === "paused" ? " paused" : "");
    $("media-title").textContent = media.title;
    var meta = [];
    if (media.artist) meta.push(media.artist);
    if (media.app) meta.push(media.app);
    if (media.status === "paused") meta.push("paused");
    var hasTime = known(media.position) && media.duration;
    if (hasTime) meta.push(minutes(media.position) + " / " + minutes(media.duration));
    $("media-meta").textContent = meta.join(" · ");
    var fill = $("media-bar");
    fill.style.transition = "none";
    fill.style.width = hasTime ? Math.min(100, 100 * media.position / media.duration) + "%" : "0";
    fill.parentNode.style.display = hasTime ? "" : "none";
  }

  function renderPhone(phone) {
    var box = $("phone-batt");
    var devices = phone && phone.devices ? phone.devices : [];
    var d = null;  // the hottest phone, if several are plugged in
    for (var i = 0; i < devices.length; i++) {
      if (!d || (devices[i].temp || 0) > (d.temp || 0)) d = devices[i];
    }
    box.innerHTML = "";
    if (!d && !browserBattery) {
      box.style.display = "none";
      return;
    }
    box.style.display = "inline";
    box.appendChild(icon("battery"));
    if (!d) {
      box.className = "phone-batt";
      box.appendChild(document.createTextNode(Math.round(browserBattery.level * 100) + "%"));
      return;
    }
    var text = known(d.level) ? d.level + "%" : "--";
    if (known(d.temp)) text += " · " + Math.round(d.temp) + "°C";
    box.appendChild(document.createTextNode(text));

    var hot = (known(d.temp) && d.temp >= BATTERY_HOT) || d.health === "overheat";
    box.className = "phone-batt" + (hot ? " hot" : known(d.temp) && d.temp >= BATTERY_WARM ? " warm" : "");
    if (hot && !batteryAlerted) {
      batteryAlerted = true;
      chime();
      toast("attention", "Phone battery is hot",
            (known(d.temp) ? Math.round(d.temp) + "°C · " : "") + "unplug it or give it more air", "alert", 15);
    } else if (!hot && known(d.temp) && d.temp < BATTERY_RESET) {
      batteryAlerted = false;
    }
  }
