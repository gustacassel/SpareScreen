  // ---- Themes --------------------------------------------------------------

  var theme = null;

  function applyTheme(name) {
    if (THEMES.indexOf(name) < 0) name = "graphite";
    theme = name;
    document.documentElement.setAttribute("data-theme", name);
  }

  function nextTheme() {
    var name = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
    saveConfig({ theme: name });
    toast("info", "Theme", THEME_INFO[name][0], "palette", 2);
  }
