# Changelog

## 0.4.0 – unveröffentlicht

### Neu
- Sensoren **Arbeitszeit heute** und **Pausenzeit heute** (zählen minütlich mit, ohne zusätzliche API-Abfragen), Binärsensoren **Pause**, **Arbeitstag** und **Urlaub / Abwesenheit**.
- **Assistent** pro Konto, komplett optional:
  - Actionable Notifications für Android und iOS über die Companion App, optional dauerhafte Statusanzeige mit Stoppuhr (Android).
  - Automatisches Ein- und Ausstempeln bzw. Nachfragen per Zone/Person, WLAN-SSID, Binärsensoren oder NFC-Tag; Verzögerungen, Zeitfenster, Arbeitstage, Rückdatieren, kurze Abwesenheit als Pause, Homeoffice-Nachfrage; Schalter zum Pausieren.
  - Ausstempel-Erinnerungen (beim Verlassen, Uhrzeit, Höchstarbeitszeit, Schlummern) und Erkennung von vergessenem Ausstempeln mit rückwirkendem Ausstempeln.
  - Pausenassistent: Pausenerinnerung, Pausenende/automatisch weiterarbeiten, automatische Mittagspause, Pausenprüfung nach ArbZG mit Nachtragen der fehlenden Pause in Crewmeister.
- **Homeoffice-Erkennung** über Steckdose mit Leistungsmessung und Präsenzmelder/PC-Status (Person zu Hause, Arbeitstag, Zeitfenster) mit automatischem bzw. nachfragendem Ein- und Ausstempeln und Pause bei kurzer Inaktivität. Ersetzt die Homeoffice-Nachfrage zu fester Uhrzeit.
- Sensor **Arbeitsort** (Büro / Homeoffice / Nicht bei der Arbeit).
- Optional **Ort am Stempel** („Büro“ / „Homeoffice“, Texte anpassbar).
- Ist am selben Tag schon automatisch eingestempelt worden, wird beim nächsten Arbeitsbeginn nachgefragt statt nichts zu tun.
- Options-Dialog als Menü mit sieben Bereichen (Arbeitszeit, Benachrichtigungen, Büro, Homeoffice, Erinnerungen, Pausen, Erweitert), Kurzbeschreibungen im Menü, Gruppen innerhalb der Formulare und Hinweis, wenn für eine Funktion noch kein Handy ausgewählt ist.
- **Feierabend-Erinnerung**: Arbeitsbeginn + Soll-Arbeitszeit + Pflichtpause + Karenzzeit, mit Soll-Arbeitszeit pro Wochentag. Die Arbeitszeit-Sensoren zeigen Soll-Arbeitszeit und voraussichtlichen Feierabend als Attribute.
- **Live-Anzeige** über iOS Live Activities / Android Live Updates (Companion App, HA ≥ 2026.7) mit laufender Uhr, Fortschritt zur Soll-Arbeitszeit und voraussichtlichem Feierabend. Arbeit (blau) und Pause (gelb) sind farblich getrennt, auf Android mit Knöpfen *Pause*, *Weiterarbeiten* und *Ausstempeln*.

### Sicherheit
- Die Benutzer-ID wird nur noch aus dem Token gelesen. Bisher wurde ersatzweise der neueste sichtbare Stempel verwendet; bei Vorgesetzten oder Admins konnte das der Stempel eines Kollegen sein, für den dann gestempelt wurde.
- Weiterleitungen der API werden nicht befolgt, damit Passwort und Token nicht über `http://` gesendet werden können.
- Antwortknöpfe und NFC-Scans anderer Home-Assistant-Benutzer werden ignoriert (jedes Companion-App-Gerät kann beliebige Events auslösen). Ohne eingestellte Person und ohne Benachrichtigungs-Gerät darf jeder Benutzer per NFC stempeln.
- Zeitpunkte aus Antwortknöpfen müssen in den letzten drei Tagen und nicht in der Zukunft liegen; nachgetragene Pausen sind auf 2 h und eigene Stempel begrenzt.
- Die API-URL muss HTTPS verwenden, sonst wird weder eingerichtet noch gestartet.

### Behoben (Review)
- Mehrere gleichzeitige Auslöser (z. B. Knopf auf Handy und Uhr, NFC und Ankunft) konnten doppelt stempeln.
- Das Homeoffice-Ende stempelte auch eine Schicht aus, die inzwischen im Büro weiterlief.
- Pausenprüfung nach ArbZG: Nur Pausen ab 15 Minuten zählen. Eine nachgetragene Pause wird bei doppeltem Tippen nicht zweimal eingetragen.
- Vergessenes Ausstempeln bot einen Zeitpunkt in der Zukunft oder einen zu alten Zeitpunkt an, der beim Tippen abgelehnt wurde.
- Der Arbeitstag-Sensor und der Assistent rechneten nach mehr als 24 h ohne Verbindung weiter mit alten Abwesenheiten.
- Schlug schon das erste Laden der Abwesenheiten fehl, gab es erst nach einer Stunde einen neuen Versuch.
- Der Zustand des Assistenten wird beim Neuladen sofort gespeichert; eine noch nicht bestätigte Ankunft geht nicht mehr verloren.
- Tokens ohne Ablaufzeit lösten vor jeder Anfrage einen neuen Login aus.
- Nach der erneuten Anmeldung wurde die Integration zweimal neu geladen.
- `crewmeister.create_stamp` akzeptiert `time_account_id: 0` nicht mehr stillschweigend.

### Geändert
- Schlägt das Laden der Abwesenheiten fehl, bleiben Kalender und Urlaubssensor mit den letzten Daten bis zu 24 h verfügbar; neuer Versuch alle 10 Minuten, auch wenn schon der erste Abruf scheitert. Um Mitternacht wird nicht mehr extra abgefragt.
- Der Status wird aus den letzten 50 Stempeln ermittelt (eine Anfrage pro Aktualisierung wie bisher).
- Mindestversion Home Assistant 2026.2.


## 0.3.0 – unveröffentlicht

### Behoben
- Erneute Anmeldung (Reauth) funktionierte nicht (`KeyError` auf das Passwort bzw. Abbruch mit „already_configured“). Es gibt jetzt einen eigenen Schritt, der nur nach dem neuen Passwort fragt und prüft, dass es dasselbe Konto ist.
- Kalender: Status und Attribute der nächsten Abwesenheit blieben leer, weil die Daten nie geladen wurden. Abwesenheiten laufen jetzt über einen eigenen Coordinator (stündlich).
- Kalender hieß doppelt („Max Muster Max Muster absences“) und ignorierte die Übersetzung.
- Buttons prüften gegen einen bis zu 30 Minuten alten Status; jetzt wird vorher aktualisiert.
- Ein Serverfehler beim Login (5xx) wurde als ungültiges Passwort gewertet und startete die erneute Anmeldung.
- HTTP-Antworten wurden nicht freigegeben; parallele Anfragen konnten mehrfach einloggen.

### Geändert
- Dienst `crewmeister.create_stamp`: Bei mehreren Konten ist `config_entry_id` jetzt Pflicht (vorher wurde für **alle** Konten gestempelt). Auswahl per Konto-Selektor, Fehler erscheinen übersetzt in der Oberfläche.
- Status-Sensor ist ein Enum-Sensor mit übersetzten Zuständen (Eingestempelt / Pause / Ausgestempelt) und eigenen Icons.
- Options-Dialog mit HA-Selektoren und Beschreibungen; bestehende Optionen (auch ältere String-Formate) werden übernommen.
- Mindestversion Home Assistant 2025.3.

### Neu
- Diagnose-Download mit geschwärzten Zugangsdaten.
- Tests (pytest, 84 Tests) und GitHub-Actions für hassfest, HACS-Validierung, Ruff und pytest.

### Intern
- API-Client als Paket `api/` mit typisierten Modellen (`Stamp`, `Absence`, `WorkStatus`, `StampType`) und zentraler Übergangsprüfung.
- `entry.runtime_data`, gemeinsame Basis-Entity, Dienst in `services.py`.
- OpenAPI-Specs nach `docs/api/` verschoben.
