// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

/* Runs before first paint so there is no flash of the wrong theme, accent, language or direction. */
(function () {
  try {
    var p = JSON.parse(localStorage.getItem("gleanwise.prefs") || "{}");
    var dark = p.theme === "dark" || ((!p.theme || p.theme === "system") && matchMedia("(prefers-color-scheme: dark)").matches);
    var r = document.documentElement;
    r.dataset.theme = dark ? "dark" : "light";
    r.dataset.accent = p.accent || "indigo";
    var pref = localStorage.getItem("gleanwise.locale") || "auto";
    var langs = pref === "auto" ? navigator.languages || [navigator.language] : [pref];
    var loc = "en";
    for (var i = 0; i < langs.length; i++) {
      var b = String(langs[i]).toLowerCase().split("-")[0];
      if (b === "ar" || b === "en") { loc = b; break; }
    }
    r.lang = loc;
    r.dir = loc === "ar" ? "rtl" : "ltr";
  } catch (e) {}
})();
