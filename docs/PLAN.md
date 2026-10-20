# Crewmeister-Integration – Machbarkeit & Ausbauplan

Stand: 19.10.2026 · Basis: `mztechnik/hacs-crewmeister` v0.2.1 (Commit `9e8d237`)

## Kurzfazit

Alle gewünschten Funktionen sind **ohne externe Abhängigkeiten** mit Bordmitteln von Home Assistant umsetzbar
(Zustandsänderungen von `person`/`zone` verfolgen, `mobile_app`-Benachrichtigungen mit Aktionen, Timer über
`async_track_point_in_time`, persistenter Zustand über `helpers.storage.Store`). Die Crewmeister-API liefert
alles Nötige: Stempel mit frei wählbarem Zeitstempel (`POST /timetracking/stamps`), Abwesenheiten, Schichten,
Salden und eine Aufgabe zum nachträglichen Einfügen einer Pause.

Größte Risiken liegen **nicht im Code**, sondern in:

1. **GPS-Ungenauigkeit** → Zonen „flattern“. Gegenmittel: Verweilzeiten, alternative Auslöser (WLAN-SSID, NFC).
2. **Serverseitige Regeln bei Crewmeister** (z. B. Fristen für rückdatierte Stempel, Berechtigung für die
   Pausen-Korrektur). Muss mit einem echten Konto getestet werden.
3. **Arbeitsrecht/Betriebsrat**: Ortsbasiertes Auto-Stempeln ist Standortverarbeitung. Deshalb: alles
   standardmäßig **aus**, Modus „Nachfragen“ als empfohlener Standard.

Empfehlung: zuerst die Wartbarkeit verbessern (Phase 0), weil die neuen Funktionen sonst auf einer schwer
testbaren Basis landen. Die Phasen 1–4 bauen aufeinander auf, jede ist für sich auslieferbar.

---

## Phase 0 – Wartbarkeit & Bugfixes (Grundlage) ✅ umgesetzt in 0.3.0

Abweichungen: Kein eigenes Repair-Issue nötig, weil `ConfigEntryAuthFailed` den Reauth-Hinweis von HA auslöst. Das Options-Menü folgt erst mit den Funktionen aus Phase 2–4. Eine `LICENSE` muss der Rechteinhaber festlegen.

### Bugs (aus der Code-Durchsicht)

| # | Problem | Fix |
|---|---|---|
| 1 | Reauth-Flow: `KeyError` auf Passwort, danach `already_configured`-Abbruch | Eigener `async_step_reauth_confirm` mit Passwortfeld, `async_update_reload_and_abort` |
| 2 | Kalender-`event` bleibt leer (überschriebenes `async_update` wird nie aufgerufen) | Eigener Abwesenheits-Coordinator, Kalender liest daraus |
| 3 | Kalendername doppelt (`_attr_name` + `has_entity_name`) | `_attr_name` entfernen, nur `translation_key` |
| 4 | Dienst ohne `config_entry_id` stempelt **alle** Konten; Fehler nicht als `HomeAssistantError` | Bei >1 Konto Pflichtfeld; `ServiceValidationError` mit Übersetzung |
| 5 | Button-Validierung gegen bis zu 30 min alten Status | Vor Prüfung frischen Stempel holen (1 Request) |
| 6 | HTTP-Responses nicht freigegeben, `async_timeout` veraltet | `async with session.request(...)`, `asyncio.timeout` |

### Struktur

- **`entry.runtime_data`** mit typisierter Dataclass statt `hass.data[DOMAIN][entry_id]`-Dicts.
- **`entity.py`** mit gemeinsamer Basisklasse (`device_info` ist aktuell 3× kopiert).
- **API-Client** in `api/` mit typisierten Modellen (`Stamp`, `Absence`, `Shift`, `Balance`) statt roher Dicts;
  Status als `StrEnum` (`WorkStatus.CLOCKED_IN` …), Übergangsregeln als eine reine Funktion
  (heute dupliziert zwischen Button und – fehlend – Dienst).
- **Options-Flow** mit HA-Selektoren (`NumberSelector`, `SelectSelector`, `EntitySelector`, `TimeSelector`) und
  Menü (`async_show_menu`): *Allgemein · Auto-Stempeln · Benachrichtigungen · Pausenassistent*.
  Das ersetzt ~100 Zeilen manuelles String-Sanitizing in `config_flow.py`.
- **Status-Sensor** als `SensorDeviceClass.ENUM` mit übersetzten Zuständen („Eingestempelt“, „Pause“, „Ausgestempelt“).
- **Diagnose-Download** (`diagnostics.py`, Passwort/Token geschwärzt) und **Repair-Issue** bei Anmeldefehlern.
- **Exception-Übersetzungen** (`strings.json` → `exceptions`), damit Fehler auf Deutsch in der UI erscheinen.

### Qualitätssicherung

- Tests mit `pytest-homeassistant-custom-component` (Config-/Options-Flow, Coordinator, Buttons, Dienst) und
  `aioresponses` für den API-Client. Die neue Logik (Phase 2–4) als reine Python-Funktionen → ohne HA testbar.
- GitHub Actions: `hassfest`, HACS-Validierung, `ruff`, `pytest`.
- Repo-Hygiene: OpenAPI-Specs nach `docs/api/`, `LICENSE`, `issue_tracker` im Manifest, `CHANGELOG.md`,
  `pyproject.toml` mit Ruff-Konfiguration.

---

## Phase 1 – Datenbasis & neue Sensoren ✅ teilweise umgesetzt in 0.4.0

Umgesetzt: Arbeitszeit/Pausenzeit heute, Binärsensoren Pause, Arbeitstag, Urlaub. Bewusst weggelassen: Feierabend-Prognose, Überstundensaldo, Resturlaub, Schichten (Schichtplaner wird nicht genutzt), Events.

Neuer **Tages-Coordinator** (Stempel von heute, `filter=userId==X;timestamp>=<heute 00:00>`), daraus lokal berechnet:

| Entität | Quelle | Nutzen |
|---|---|---|
| `sensor` Arbeitszeit heute | Stempelkette heute | Grundlage für Pausenassistent, Dashboards |
| `sensor` Pausenzeit heute | Stempelkette heute | Pausenassistent |
| `sensor` Voraussichtlicher Feierabend | Beginn + Soll-Stunden (Option) + Pause | Erinnerung, Dashboard |
| `sensor` Überstundensaldo | `GET /timetracking/duration-balances` | Info |
| `sensor` Resturlaub | `GET /absencemanager/entitlement-balances` | Info |
| `sensor` Nächste Schicht | `GET /shiftplanner/shifts` (nur falls Schichtplaner genutzt wird) | Erinnerung vor Schichtbeginn |
| `binary_sensor` Pause | Status | Automationen |
| `binary_sensor` Heute Arbeitstag | Wochentage (Option) − Abwesenheiten − Feiertage | Sperre fürs Auto-Stempeln |

Dazu **Events** `crewmeister_stamp_created` und `crewmeister_status_changed`, damit eigene Automationen
reagieren können (z. B. Licht im Büro, Musik bei Feierabend).

Polling-Last bleibt gering: Nach eigenen Stempeln wird der Zustand lokal fortgeschrieben; nur Saldo/Urlaub/Schichten
werden selten (z. B. stündlich) abgefragt.

---

## Phase 2 – Benachrichtigungen mit Antwortknöpfen ✅ umgesetzt in 0.4.0

**Machbarkeit: hoch.** Die HA Companion App (Android & iOS) unterstützt Aktionen über
`notify.mobile_app_<gerät>` mit `data.actions`. Ein Klick erzeugt das Event `mobile_app_notification_action`,
auf das die Integration hört.

- Konfiguration pro Konto: ein oder mehrere Ziel-Geräte (Auswahl der `notify.mobile_app_*`-Dienste).
- Aktions-IDs mit Präfix + Entry-ID (`CREWMEISTER_CLOCK_OUT_<entry_id>`), damit mehrere Nutzer sauber getrennt sind.
- `tag` pro Nutzer: neue Meldung ersetzt die alte; nach erledigter Aktion `clear_notification`.
- Knöpfe je nach Situation: *Einstempeln · Pause · Weiterarbeiten · Ausstempeln · In 30 min erinnern · Ignorieren*.
- Optional Texteingabe-Aktion (`behavior: textInput`) für eine Stempelnotiz.
- Plattform-Extras:
  - **Android**: dauerhafte Meldung „Eingestempelt seit 08:12“ mit laufender Stoppuhr (`chronometer`, `when`,
    `sticky`) und Knöpfen *Pause/Ausstempeln*; eigener Kanal (`channel`) für Erinnerungen.
  - **iOS**: `interruption-level: time-sensitive`, damit Erinnerungen durch den Fokus-Modus kommen.
- Rückmeldung nach jeder Aktion („Ausgestempelt um 17:05 – 8 h 21 min, Pause 45 min“) bzw. Fehlermeldung.
- Benachrichtigungen landen automatisch auch auf Wear OS / Apple Watch.

### Ausstempel-Erinnerung

Auslöser (einzeln aktivierbar):

- Zone/Arbeitsort verlassen, aber noch eingestempelt (falls Auto-Ausstempeln aus ist oder auf „Nachfragen“ steht)
- feste Uhrzeit (z. B. 18:00) bzw. voraussichtlicher Feierabend + Karenz
- Höchstarbeitszeit erreicht (Option, Standard 10 h nach ArbZG § 3)
- Schichtende + Karenz (falls Schichtplaner)
- **Vergessen**: am nächsten Morgen noch eingestempelt → „Du hast gestern um 17:42 das Büro verlassen.
  Mit dieser Uhrzeit ausstempeln?“ (rückdatierter Stempel über `timestamp`)

Snooze-Zustand und geplante Erinnerungen werden in einem `Store` gespeichert, damit sie einen HA-Neustart überleben.

---

## Phase 3 – Automatisches Ein- und Ausstempeln ✅ umgesetzt in 0.4.0

**Machbarkeit: hoch, Zuverlässigkeit hängt vom Auslöser ab.**

### Konfiguration pro Nutzer (= pro Config-Entry)

- **Person** (`person.*`) – sie ist bereits pro HA-Nutzer und bündelt mehrere Tracker.
- **Arbeitsorte**: eine oder mehrere Zonen (z. B. „Büro“, „Lager“). Umsetzung als *Config-Subentries*
  (HA ≥ 2025.3), damit jeder Ort eigene Einstellungen haben kann.
- **Modus** je Richtung (Kommen/Gehen): *Aus · Nachfragen (Benachrichtigung) · Automatisch*.
- **Verweilzeit** vor dem Stempeln (Standard Kommen 2 min, Gehen 5 min) gegen GPS-Sprünge.
- **Zeitfenster & Wochentage** (z. B. Mo–Fr 06:00–20:00).
- **Rückdatieren**: Stempelzeit = Zeitpunkt des Zonen-Ereignisses statt Zeitpunkt der Bestätigung.
- **Schalter-Entität** „Automatisches Stempeln“ pro Nutzer, um es z. B. per Dashboard kurz auszusetzen.

### Schutzregeln

- Nichts stempeln bei Abwesenheit (Urlaub/Krank), an Feiertagen oder außerhalb der Arbeitstage.
- Höchstens ein automatisches Einstempeln pro Tag (optional), Mindest-Schichtlänge vor Auto-Ausstempeln.
- Vor jedem Stempel aktuellen Status frisch holen (wurde vielleicht schon per App/Terminal gestempelt).
- Kurzes Verlassen (Mittagspause außer Haus) → optional als **Pause** statt Ausstempeln werten, wenn
  Rückkehr innerhalb von X Minuten.

### Weitere Auslöser (zuverlässiger als GPS)

- **WLAN-SSID** (Sensor der Companion App) – sehr robust für Büro-Ankunft.
- **NFC-Tag** am Arbeitsplatz (`tag_scanned`) → „Tag scannen = stempeln/umschalten“.
- **Homeoffice**: Zone „Zuhause“ + Arbeitstag + Zeitfenster → nur *Nachfragen* („Heute Homeoffice? Einstempeln“),
  optional ausgelöst durch einen PC-Aktivitäts-Sensor (z. B. HASS.Agent / Companion App auf dem PC).
- Generisch: beliebige `binary_sensor`/`input_boolean` als Auslöser.

---

## Phase 4 – Pausenassistent ✅ umgesetzt in 0.4.0

Grundlage: ArbZG § 4 (mehr als 6 h → 30 min, mehr als 9 h → 45 min Pause; Blöcke ≥ 15 min). Werte konfigurierbar,
weil Arbeitszeitmodelle in Crewmeister eigene Regeln/automatischen Abzug haben können.

- **Erinnerung „Pause fällig“** nach X h ohne Pause (Standard 5 h 30 min) mit Knöpfen *Pause starten · Später*.
- **Pausenende**: nach gewählter Dauer „Pause vorbei“ mit *Weiterarbeiten* (→ `START_WORK`). Optional
  automatisch weiterstempeln.
- **Check beim Ausstempeln**: reicht die Pause nicht → Hinweis mit Knopf „30 min Pause nachtragen“ über
  `POST /timetracking/set-break-in-stamp-chain-tasks` (`stampIdInStampChain`, `duration`).
  ⚠️ Berechtigung und Verhalten vorher mit echtem Konto prüfen; falls nicht erlaubt, nur Hinweis.
- **Feste Pausenzeit**: optional „Mittagspause automatisch 12:00–12:30“, nur wenn eingestempelt.
- Sensor/Attribut „Pause noch erforderlich: 15 min“.

---

## Architektur der neuen Funktionen

```
custom_components/crewmeister/
  api/            client.py, models.py, errors.py
  assistant/      reine Logik, ohne HA testbar
    workday.py      Arbeitstag? (Wochentage, Abwesenheit, Feiertag)
    breaks.py       Pausenregeln, erforderliche Pause, Restzeit
    presence.py     Zustandsmaschine Zone → Aktion (Verweilzeit, Modus, Schutzregeln)
    reminders.py    Planung von Erinnerungen
  notify.py       Versand + Aktions-Event-Handler (Android/iOS-Payload)
  manager.py      verbindet HA-Ereignisse, Timer, Store und Client pro Config-Entry
  coordinator.py  Status-, Tages- und Abwesenheits-Coordinator
  entity.py, sensor.py, binary_sensor.py, switch.py, button.py, calendar.py
  config_flow.py  Setup, Reauth, Options-Menü, Subentries (Arbeitsorte)
  diagnostics.py
tests/
```

Alles Neue ist **optional** und standardmäßig deaktiviert; ohne Konfiguration verhält sich die Integration wie heute.

---

## Grobe Aufwandsschätzung

| Phase | Inhalt | Aufwand |
|---|---|---|
| 0 | Refactoring, Bugfixes, Tests, CI | mittel |
| 1 | Tages-Coordinator, neue Sensoren, Events | klein–mittel |
| 2 | Benachrichtigungen + Ausstempel-Erinnerung | mittel |
| 3 | Auto-Stempeln (Zonen, Person, WLAN/NFC, Schutzregeln) | groß |
| 4 | Pausenassistent | mittel |

## Entscheidungen (19.10.2026)

1. Umsetzung in der Integration, nicht als Blueprints (die haben nicht gut funktioniert).
2. Schichtplaner wird nicht genutzt → keine Schicht-Funktionen.
3. Rückdatierte Stempel und Pausen-Korrektur sind erlaubt und eingebaut.
4. Entwicklung lokal im Fork; ein PR an das Original ggf. später von Hand.
5. Mindestversion HA 2026.2 (getestet mit 2026.2.3; genutzt wird 2026.10.2).

Abweichungen vom Plan: Arbeitsorte als Mehrfachauswahl von Zonen statt Config-Subentries (einfacher, reicht für einen Nutzer pro Konto). Läuft eine Schicht seit einem Vortag, gibt es nur die Prüfung auf vergessenes Ausstempeln, keine Pausen-/Höchstzeit-Erinnerungen.

## Nachträge

- Feierabend-Erinnerung (Arbeitsbeginn + Soll-Arbeitszeit + Pflichtpause + Karenz, Soll-Arbeitszeit pro Wochentag) ✅
- Live-Anzeige über iOS Live Activities / Android Live Updates ✅ (Neustart nach 7,5 h wegen der iOS-Grenze von 8 h, keine Knöpfe laut Doku)

- Homeoffice-Erkennung (Steckdose mit Leistungsmessung, Präsenzmelder; Ausstempeln automatisch, einstellbar), Sensor „Arbeitsort“, optional Ort am Stempel ✅

## Ursprüngliche offene Fragen

1. Umsetzung **in der Integration** (empfohlen: pro Nutzer konfigurierbar, testbar, keine YAML) oder als
   **Blueprints** (wurden in PR #30 entfernt – gab es dafür einen Grund?).
2. Wird der **Schichtplaner** genutzt? Sonst entfallen Schicht-Sensor und -Erinnerungen.
3. Erlaubt das Crewmeister-Konto **rückdatierte Stempel** und die **Pausen-Korrektur**? (Testen mit echtem Konto.)
4. Wo soll entwickelt werden: direkt in `mztechnik/hacs-crewmeister` (bist du der Maintainer?) oder in einem Fork?
5. Mindest-HA-Version festlegen (Subentries brauchen ≥ 2025.3).
