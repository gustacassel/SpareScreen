  // ---- Clock (the phone's own time) ---------------------------------------

  function tickClock() {
    var now = new Date();
    $("time").textContent = pad(now.getHours()) + ":" + pad(now.getMinutes());
    var date = now.toLocaleDateString("en-US", { weekday: "long", day: "numeric", month: "long" });
    $("date").textContent = date.charAt(0).toUpperCase() + date.slice(1);
    updateNight(now);
    updateOffline(now);
  }
