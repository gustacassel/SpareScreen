  // ---- Sound (only plays after the first tap: browser rule) ----------------

  var audio = null;
  function unlockAudio() {
    var Ctx = window.AudioContext || window.webkitAudioContext;
    if (!audio && Ctx) audio = new Ctx();
    if (audio && audio.resume) audio.resume();
  }

  function chime() {
    if (!audio || !cfg.sound) return;
    var notes = [880, 1318.5];  // A and E: a short "ding"
    for (var i = 0; i < notes.length; i++) {
      var osc = audio.createOscillator();
      var gain = audio.createGain();
      var at = audio.currentTime + i * 0.14;
      osc.frequency.value = notes[i];
      gain.gain.setValueAtTime(0.0001, at);
      gain.gain.exponentialRampToValueAtTime(0.25, at + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.5);
      osc.connect(gain);
      gain.connect(audio.destination);
      osc.start(at);
      osc.stop(at + 0.55);
    }
  }
