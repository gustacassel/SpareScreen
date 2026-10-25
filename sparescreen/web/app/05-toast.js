  // ---- Toast on top of the screen ------------------------------------------

  var toastQueue = [];
  var toastBusy = false;

  // kind: "done" (green), "attention" (yellow) or "info" (accent color)
  function toast(kind, title, sub, iconName, seconds) {
    toastQueue.push({ kind: kind, title: title, sub: sub, icon: iconName, seconds: seconds || 8 });
    if (!toastBusy) nextToast();
  }

  function nextToast() {
    var t = toastQueue.shift();
    if (!t) {
      toastBusy = false;
      startRotation();
      return;
    }
    toastBusy = true;
    stopRotation();
    $("toast-icon").setAttributeNS("http://www.w3.org/1999/xlink", "xlink:href", "#i-" + t.icon);
    $("toast-title").textContent = t.title;
    $("toast-sub").textContent = t.sub;
    $("toast").className = "toast show " + t.kind;
    clearTimeout(nextToast.timer);
    nextToast.timer = setTimeout(hideToast, t.seconds * 1000);
  }

  function hideToast() {
    clearTimeout(nextToast.timer);
    $("toast").className = "toast";
    setTimeout(nextToast, 400);
  }
