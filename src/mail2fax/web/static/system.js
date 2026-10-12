// Aktualisiert die Seite "System", solange eine Verwaltungsaktion laeuft.
// Waehrend eines Updates ist mail2fax kurz nicht erreichbar - Netzfehler
// werden daher still uebergangen und es wird weiter gefragt.
(function () {
  "use strict";
  var zuletzt = null;
  function pruefen() {
    fetch("/system/status", { credentials: "same-origin", redirect: "manual" })
      .then(function (antwort) {
        if (antwort.type === "opaqueredirect" || antwort.status === 401 || antwort.status === 303) {
          // Nach dem Neustart ist die Sitzung weg - zur Anmeldung.
          window.location.reload();
          return null;
        }
        return antwort.ok ? antwort.json() : null;
      })
      .then(function (daten) {
        if (!daten) { return; }
        var stand = JSON.stringify(daten);
        var laeuft = Object.keys(daten).some(function (k) { return daten[k].busy; });
        if (!laeuft || (zuletzt !== null && stand !== zuletzt)) {
          window.location.reload();
          return;
        }
        zuletzt = stand;
      })
      .catch(function () { /* Dienst startet gerade neu */ });
  }
  window.setInterval(pruefen, 4000);
})();
