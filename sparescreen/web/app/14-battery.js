  // ---- Phone battery ---------------------------------------------------------
  // Over USB the agent reads level and temperature with adb. On Wi-Fi only the
  // level the browser itself reports is available (where the browser supports it).

  var BATTERY_WARM = 38;
  var BATTERY_HOT = 42;    // alert from here on
  var BATTERY_RESET = 39;  // and again only after it cooled down below this
  var batteryAlerted = false;
  var browserBattery = null;
  if (navigator.getBattery) {
    try {
      navigator.getBattery().then(function (b) {
        // Desktops without a battery report "full and charging": not worth showing.
        var noBattery = b.level === 1 && b.charging && b.chargingTime === 0;
        if (!noBattery) browserBattery = b;
      }, function () {});
    } catch (e) { /* not allowed here */ }
  }

  function known(value) { return value !== null && value !== undefined; }
