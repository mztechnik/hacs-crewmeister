# Crewmeister-Integration – Version 2 (Entwurf)

Stand: 09.11.2026 · Basis: Branch `feature/assistant` (0.4.0) · Status: **umgesetzt (Schritte 1–3), Doku fertig; Test in echter HA-Instanz offen**

## Ziel

Gleicher Funktionsumfang wie 0.4.0 in den wichtigen Teilen, aber **verlässlicher** und **einfacher einzurichten**.

Kernfunktionen:

1. Automatisches Ein- und Ausstempeln über **WLAN** und/oder **Standort (Zone)**, außerdem Homeoffice über PC-Aktivität
2. **Wegzeit (Offset)**: Kommen = Auslösezeit **+** X min, Gehen = Auslösezeit **−** Y min
3. **Feste Zeiträume statt Rätselraten**: Gehen im *Pausenzeitraum* = Pause, Gehen im *Feierabend-Zeitraum* = Ausstempeln, sonst nie automatisch ausstempeln
4. **Urlaub/Abwesenheit** aus Crewmeister, einem **Kalender** oder einem **Binärsensor**
5. Live-Anzeige, Pausenassistent und Feierabend-Erinnerungen bleiben, werden aber zusammengelegt und vereinfacht

## Abgestimmte Entscheidungen

| Thema | Entscheidung |
|---|---|
| Live-Anzeige, Homeoffice, Pausenassistent, Feierabend-Erinnerungen | bleiben |
| Gehen im Pausenzeitraum | Pause stempeln, beim Zurückkommen weiterarbeiten |
| Gehen im Feierabend-Zeitraum | ausstempeln (Aus / Nachfragen / Automatisch) |
| Gehen außerhalb dieser Zeiträume | **nie ausstempeln**; optional Nachfrage, die nach einstellbarer Zeit verfällt |
| Modus *Nachfragen* | bleibt |
| Ort am Stempel | bleibt |
| Pause nachtragen | Beim Ausstempeln mit fehlender Pause per Push fragen, wie lang die Pause war; ohne Antwort einen einstellbaren Standardwert eintragen |
| NFC-Tags | entfällt (per Automation `tag_scanned` → Button *Nächster Schritt*) |
| Soll-Stunden je Wochentag | entfällt, nur noch ein Tageswert |
| Bestehende 0.4-Installationen | Einstellungen werden migriert |

## Befund 0.4.0: warum es unzuverlässig ist

| Problem | Folge |
|---|---|
| `unavailable`/`unknown` zählt als „nicht am Arbeitsplatz“ | Companion App verliert kurz die Verbindung oder HA startet neu → falsches Gehen |
| WLAN als alleinige Quelle | Energiesparmodus trennt das WLAN → Ausstempeln oder Kurzpause |
| Crewmeister beim Bestätigen nicht erreichbar | Kommen/Gehen wird still verworfen; fehlgeschlagene Stempel werden nicht wiederholt |
| Ankommen während HA-Neustart | wird nie erkannt, es gibt keinen Abgleich beim Start |
| Gehen wird nur über Dauer gedeutet | Kurz weg = Pause, länger = Ausstempeln. Eine lange Mittagspause stempelt aus, ein Arzttermin wird zur Pause |
| Versteckte Regeln | „Einmal pro Tag“ macht aus *Automatisch* stillschweigend *Nachfragen*; „Kurze Abwesenheit als Pause“ verlängert heimlich die Verzögerung |
| Keine Rückmeldung | Warum nicht gestempelt wurde, sieht man nirgends |
| Zwei getrennte Automatiken | Büro und Homeoffice haben eigene Modi, Zeitfenster, Pausenregeln und Zustände (doppelter Code, ~70 Optionen) |

## Erkennung

### Ein Modell für Büro und Homeoffice

Es gibt **eine** Zustandsmaschine. Sie bekommt nur „am Arbeitsplatz: ja / nein / keine Aussage“ und den Ort (*Büro* oder *Homeoffice*). Büro und Homeoffice sind nur verschiedene Quellen. Dieselben Regeln für Wegzeit, Pausen- und Feierabend-Zeitraum gelten für beide.

| Quelle | Da | Weg | Keine Aussage |
|---|---|---|---|
| Zone (Büro) | `person.*` ist in einer der Zonen | Person in keiner der Zonen | `unknown`/`unavailable` |
| WLAN (Büro) | `sensor.*_wifi_connection` ist eine der SSIDs | andere SSID oder getrennt | `unknown`/`unavailable` |
| PC-Aktivität (Homeoffice) | Person `home` und Leistung > Schwelle bzw. Präsenzmelder `on` | Person nicht `home` oder Leistung/Präsenz aus | Sensor `unknown`/`unavailable` |

**„Keine Aussage“ ändert nichts**, der letzte Zustand bleibt. Damit fällt der häufigste Fehlalarm weg.

### Kombination Zone + WLAN (eine Einstellung, nur sichtbar wenn beide eingerichtet)

- **Eine Quelle reicht** (Standard): Kommen, sobald eine Quelle „da“ meldet. Gehen erst, wenn **alle** „weg“ melden. WLAN erkennt das Ankommen schnell, die Zone verhindert Fehlalarme bei WLAN-Abbrüchen.
- **Beide müssen zutreffen**: Kommen erst, wenn beide „da“ melden. Gehen, sobald eine „weg“ meldet. Für Büros, deren WLAN bis auf den Parkplatz reicht.

Ist man im Büro erkannt, beendet der PC zu Hause nichts (wie bisher).

### Zustandsmaschine (gespeichert, übersteht Neustarts)

```
WEG ──da──▶ KOMMT (seit T) ──Bestätigungszeit vorbei──▶ DA   → Regel „Kommen“ mit T
 ▲            │ wieder weg: verwerfen                   │
 │            ▼                                          weg
 └──────── GEHT (seit T) ◀──────────────────────────────┘
              │ wieder da: verwerfen
              └── Bestätigungszeit vorbei → WEG          → Regel „Gehen“ mit T
```

- **Bestätigungszeit** (Standard Kommen 2 min, Gehen 10 min) filtert GPS-Sprünge und WLAN-Abbrüche. Der Stempel bekommt trotzdem die Zeit T.
- **Abgleich beim Start:** Nach dem HA-Start wird die aktuelle Anwesenheit mit dem gespeicherten Zustand verglichen. Gespeichert WEG, jetzt da → Kommen mit `last_changed` der Quelle (höchstens Startzeit). Gespeichert DA, jetzt weg → Gehen entsprechend.

## Regeln

### Kommen (T = erkannter Zeitpunkt)

| Status in Crewmeister | Aktion |
|---|---|
| Ausgestempelt | Einstempeln mit **T + Wegzeit Kommen** – nur an Arbeitstagen, ohne Urlaub, im Arbeitszeitfenster (Standard 05:00–22:00) |
| Pause | Weiterarbeiten mit **T + Wegzeit Kommen** (auch außerhalb des Pausenzeitraums) |
| Eingestempelt | nichts |

Crewmeister nimmt keine Zukunftsstempel an, deshalb wird erst zum Zeitpunkt T + Wegzeit gestempelt.

### Gehen (Stempelzeit = T − Wegzeit Gehen, nie vor dem letzten Stempel)

| Wann | Aktion |
|---|---|
| im **Pausenzeitraum** (z. B. 11:30–13:30) und eingestempelt | Pause starten (*Aus / Nachfragen / Automatisch*) |
| im **Feierabend-Zeitraum** | Ausstempeln (*Aus / Nachfragen / Automatisch*) |
| sonst | **nie ausstempeln**; optional Nachfrage „Du hast den Arbeitsplatz um 10:12 verlassen“ mit *Pause* / *Ausstempeln*; sie verfällt nach X min (Standard 30) und wird dann entfernt |

**Feierabend-Zeitraum** beginnt, sobald eine der Bedingungen erfüllt ist:

- ab einer Uhrzeit (z. B. 15:00), und/oder
- sobald die Soll-Arbeitszeit des Tages erreicht ist (Arbeitsbeginn + Soll + Pflichtpause)

**Nachholen** (Standard an): Ist man vor dem Feierabend-Zeitraum gegangen und beim Beginn des Zeitraums immer noch weg, gilt das als Gehen zum ursprünglichen Zeitpunkt. Damit ist z. B. ein Arzttermin am Nachmittag ohne Rückkehr korrekt ausgestempelt.

### Nach dem Ausstempeln nur noch Nachfrage

Wurde heute schon ausgestempelt (von Hand, am Terminal oder automatisch), stempelt ein späteres Kommen am selben Tag nicht automatisch ein, sondern fragt nach („Wieder bei der Arbeit … Einstempeln?“). Das verhindert z. B. ein Einstempeln, wenn abends der PC zu Hause wieder läuft, und ersetzt „Einmal pro Tag“. Am nächsten Tag gilt wieder der eingestellte Modus.

### Zuverlässiges Stempeln

- **Warteschlange mit Wiederholung:** Scheitert ein Stempel an Netzwerk/Server, wird er mit dem ursprünglichen Zeitpunkt gespeichert und wiederholt (1, 2, 5, 10, 30 min, danach stündlich bis 24 h). Ab dem 3. Fehlversuch kommt eine Benachrichtigung.
- Ist der Status nicht abrufbar, wird das Ereignis **nicht verworfen**, sondern ebenfalls wiederholt.
- Vor dem Senden wird der Status frisch geholt. Gibt es den Übergang schon (z. B. am Terminal gestempelt), wird nichts gesendet.
- Nachfrage-Knöpfe verfallen (Zeitstempel im Knopf), veraltete Knöpfe werden abgelehnt.

## Urlaub / Abwesenheit

Binärsensor „Urlaub / Abwesenheit“ ist an, wenn **eine** Quelle zutrifft (Attribut `source` nennt sie):

| Quelle | Bedingung |
|---|---|
| Crewmeister (immer) | ganztägige Abwesenheit im eingestellten Status (Standard: genehmigt, vorgenehmigt) |
| Kalender (optional) | Termin heute über den ganzen Tag; optional nur mit Stichwort im Titel (z. B. „Urlaub“) |
| Binärsensor / `input_boolean` (optional) | `on` |

An solchen Tagen wird nicht automatisch eingestempelt und es gibt keine Erinnerungen. Ausstempeln bleibt möglich.

## Pausenassistent (zusammengelegt)

| 0.4.0 | V2 |
|---|---|
| Mittagspause zu Uhrzeit, Weiterarbeiten-Erinnerung zu Uhrzeit, Homeoffice-Kurzpause, Kurze Abwesenheit als Pause | **ein Pausenzeitraum** (gilt für Büro und Homeoffice). Optional: „Im Pausenzeitraum automatisch Pause, auch ohne Gehen“ (ersetzt die feste Mittagspause), Erinnerung ans Weiterarbeiten am Ende des Zeitraums |
| Pausenerinnerung nach X h | bleibt |
| Pausenende nach X min / automatisch weiterarbeiten | bleibt |
| Pausenprüfung + Knopf „30 min nachtragen“ | **Nachfrage mit Dauer**: Knöpfe *15 / 30 / 45 min* und *Keine Pause*. Ohne Antwort nach X min (Standard 60) wird der **Standardwert** (Standard 30 min) eingetragen. Prüfung nach ArbZG wie bisher (nur Blöcke ab 15 min) |

## Feierabend-Erinnerungen (bleiben)

- Feierabend nach Soll-Arbeitszeit + Pflichtpause + Karenz
- Höchstarbeitszeit (Standard 10 h)
- Erinnerung zu einer festen Uhrzeit
- Vergessenes Ausstempeln am nächsten Morgen, mit Gehzeit als Vorschlag

## Live-Anzeige (bleibt)

Unverändert in der Funktion, inklusive der stillen Knopf-Benachrichtigung für iOS. Die eigenständige Android-Statusbenachrichtigung (Option `notify_status`) entfällt, weil die Live-Anzeige sie auf aktuellen Android-Apps ersetzt. Symbole bleiben einstellbar, aber eingeklappt.

## Neue Entitäten für Durchblick

- Binärsensor **„Am Arbeitsplatz“** mit Attributen `location` (Büro/Homeoffice), `since`, `sources` (welche Quelle was meldet). Ersetzt den Sensor „Arbeitsort“; der Zustand *Büro/Homeoffice* steht im Attribut. ⚠ Ändert eine Entität; alternativ bleibt „Arbeitsort“ als Enum-Sensor bestehen.
- Sensor **„Automatik“**: letzte Entscheidung mit Grund, z. B. *Eingestempelt 07:52 (WLAN, +5 min)*, *Nicht gestempelt: Urlaub (Kalender)*, *Wartet bis 07:52*, *Stempel in Warteschlange (Crewmeister nicht erreichbar)*.

## Bedienung (Options-Dialog)

Feineinstellungen sind eingeklappt und haben Standardwerte, die für die meisten passen. (Ein Ein-Schalter, der Felder ein- und ausblendet, ist in Home-Assistant-Formularen nicht möglich; leere Felder bedeuten „aus“.) Widersprüchliche Eingaben werden mit einer Fehlermeldung abgelehnt.

| Bereich | Sichtbar | Eingeklappt |
|---|---|---|
| **Arbeitszeit & Urlaub** | Wochentage, Soll-Arbeitszeit/Tag, Workday-Sensor, Urlaubskalender (+ Stichwort), Urlaubs-Sensor | Abwesenheitsstatus aus Crewmeister, Arbeitszeitfenster |
| **Büro** | Person + Zonen, WLAN-Sensor + SSIDs, Kombination | Bestätigungszeiten |
| **Homeoffice** | Leistungssensor + Schwelle, Präsenzmelder | Bestätigungszeiten |
| **Stempelregeln** (für beide) | Kommen: Modus + Wegzeit · Pausenzeitraum + Modus · Feierabend ab Uhrzeit / Soll erreicht + Modus + Wegzeit · Nachfrage beim Gehen + Ablauf | Nachholen |
| **Benachrichtigungen** | Geräte, Bestätigungen, Live-Anzeige | Symbole |
| **Pausen & Erinnerungen** | Pausenerinnerung, Pausenende, Pausenprüfung + Standardwert, Feierabend-Erinnerung, Höchstarbeitszeit, Uhrzeit, Morgen-Check | Karenz, Snooze, Pausenregeln 6 h / 9 h |
| **Erweitert** | Ort am Stempel (+ Texte, als Notiz), Abfrageintervall, Standardnotiz, Zeitkonto-ID | – |

Wegfallende Optionen: `once_per_day`, `short_leave_break`, `nfc_tags`, `hours_<tag>`, `notify_status`, `lunch_break_time`, `resume_reminder_time`, `home_office_short_break`, `home_office_window_*`, getrennte Homeoffice-Modi, `backdate` (immer rückdatiert, Wegzeit regelt die Verschiebung), `remind_on_leave` (wird zur „Nachfrage beim Gehen“). Etwa 45 statt 70 Optionen, die meisten davon eingeklappt.

Fehlende Angaben werden im Formular erklärt (z. B. „Für Zonen wird eine Person benötigt“).

## Architektur

```
custom_components/crewmeister/
  api/                  unverändert
  logic/                rein, ohne HA, voll getestet
    sources.py          Quellen → da / weg / keine Aussage, Kombination Zone+WLAN
    presence.py         Zustandsmaschine KOMMT/DA/GEHT/WEG mit Bestätigungszeiten
    rules.py            Kommen/Gehen → Aktion (Wegzeit, Pausen-/Feierabend-Zeitraum, Schutzregeln) + Grund
    absence.py          Urlaubsquellen zusammenführen
    breaks.py           ArbZG-Prüfung, fehlende Pause
    worktime.py, texts.py
  assistant/            HA-Anbindung, je Aufgabe eine Datei statt 1455 Zeilen
    __init__.py         Lebenszyklus, Store, Listener
    autostamp.py        Quellen beobachten, Timer, Regeln anwenden
    queue.py            Stempel-Warteschlange mit Wiederholung
    reminders.py        Pausenassistent, Feierabend-Erinnerungen, Morgen-Check
    live.py             Live-Anzeige
  notifications.py      Versand, Knöpfe mit Ablaufzeit
```

## Migration

- Version **1.0.0**, Config-Entry-Version 2 mit `async_migrate_entry`:
  - Person, Zonen, WLAN, Präsenz-Entitäten, Bestätigungszeiten, Wochentage, Workday-Sensor, Soll-Stunden, Geräte, Live-Optionen, Pausen- und Erinnerungsoptionen, Ort am Stempel, Erweitert: unverändert übernommen
  - `clock_in_mode` → Kommen-Modus; `clock_out_mode` → Feierabend-Modus; `remind_on_leave` → Nachfrage beim Gehen
  - `lunch_break_time` → Pausenzeitraum ab dieser Uhrzeit (Dauer = Pausendauer); `resume_reminder_time` → Ende des Pausenzeitraums
  - Homeoffice-Modi: wenn sie vom Büro abweichen, gilt *Nachfragen* (kein Repair-Issue, der Hinweis steht in README und CHANGELOG)
  - Feierabend-Zeitraum: Standard „Soll-Arbeitszeit erreicht“
  - Übrige Optionen werden entfernt
- Entfallene Entitäten werden aus der Entity Registry gelöscht; die übrigen Entitäts-IDs bleiben.

## Umsetzung in Schritten

1. ✅ `logic/` neu: Quellen, Zustandsmaschine, Regeln, Urlaub, Pausen – mit Tests (Szenarien: WLAN-Abbruch, GPS-Sprung, Neustart, Mittag außer Haus, Arzttermin, Urlaub per Kalender)
2. ✅ `assistant/` aufteilen, Warteschlange, Abgleich beim Start (Optionen schon im neuen Format; der Options-Dialog schreibt bis Schritt 3 noch die alten Schlüssel)
3. ✅ Options-Flow neu, Migration, Sensor „Automatik“ (der Sensor „Arbeitsort“ bleibt und zeigt zusätzlich Phase und Quellen; kein eigener Binärsensor „Am Arbeitsplatz“, damit keine Entität wegfällt)
4. ✅ README/CHANGELOG, Version 1.0.0 · ⏳ Test in echter HA-Instanz mit echtem Konto (rückdatierte Stempel, Pause nachtragen)
