  // ---- Photos screen and the scrolling message -------------------------------
  // The PC says how many photos there are and a version of the list (data.photos); the
  // list itself (ids, never the PC's paths) is fetched only when that version changes.
  // Each photo stays cfg.photo_seconds while the Photos screen is showing, in shuffled
  // order; the next one loads first, then fades in over the last.

  var photoIds = [];
  var photoVersion = "";
  var photoIndex = -1;
  var photoShownAt = 0;
  var photoFront = null;   // the <img> showing now
  var photoLoading = false;

  function shuffle(list) {
    for (var i = list.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var t = list[i];
      list[i] = list[j];
      list[j] = t;
    }
    return list;
  }

  function setPhotosOn() {
    var was = photosOn;
    photosOn = photoIds.length > 0;
    if (photosOn !== was) screensChanged();
  }

  // From render(): fetch the list again only when the PC says it changed.
  function watchPhotos(info) {
    var version = info && info.count ? info.version : "";
    if (version === photoVersion) return;
    photoVersion = version;
    if (!version) {
      photoIds = [];
      setPhotosOn();
      return;
    }
    request("GET", "photos", null, function (status, data) {
      if (status !== 200 || !data || !data.photos || data.version !== photoVersion) return;
      photoIds = shuffle(data.photos.slice());
      photoIndex = -1;
      setPhotosOn();
      nextPhoto();
    });
  }

  function nextPhoto() {
    if (!photoIds.length || photoLoading) return;
    photoLoading = true;
    photoIndex = (photoIndex + 1) % photoIds.length;
    var back = photoFront === $("photo-a") ? $("photo-b") : $("photo-a");
    var done = function (ok) {
      back.onload = back.onerror = null;
      photoLoading = false;
      photoShownAt = Date.now();
      if (!ok) return;  // a photo that won't load (deleted, unreadable): the next one comes next time
      back.className = "photo on";
      if (photoFront) photoFront.className = "photo";
      photoFront = back;
    };
    back.onload = function () { done(true); };
    back.onerror = function () { done(false); };
    back.src = "photo/" + photoIds[photoIndex];
  }

  // Only while the Photos screen shows: elsewhere no photo is loaded for nothing.
  setInterval(function () {
    var screen = q(document, '.screen[data-name="photos"]');
    if (!photosOn || !screen || screen.className.indexOf("active") < 0) return;
    if (Date.now() - photoShownAt >= (cfg.photo_seconds || 10) * 1000) nextPhoto();
  }, 1000);

  // The message from the PC window. It moves at the same speed whatever its length.
  var bannerShown = null;
  var BANNER_SPEED = 70;  // px per second

  function renderBanner(text) {
    text = text || "";
    if (text === bannerShown) return;
    bannerShown = text;
    var box = $("banner"), span = $("banner-text");
    span.textContent = text;
    box.className = "banner" + (text ? " on" : "");
    if (!text) return;
    var seconds = Math.max(6, span.offsetWidth / BANNER_SPEED);  // its width includes the box's (padding)
    span.style.webkitAnimationDuration = seconds + "s";
    span.style.animationDuration = seconds + "s";
  }
