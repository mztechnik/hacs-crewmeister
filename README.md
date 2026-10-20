# Crewmeister für Home Assistant

Diese HACS-Integration bindet Crewmeister in Home Assistant ein. Nach der Einrichtung kannst du Stempelungen direkt aus Home Assistant auslösen, deinen aktuellen Arbeitsstatus überwachen und genehmigte Abwesenheiten im Kalender darstellen.

## Funktionsumfang

### Entitäten

- **Buttons** zum Einstempeln, Pausieren und Ausstempeln direkt aus Home Assistant. Dazu **Nächster Schritt**: stempelt je nach Status ein, startet die Pause oder arbeitet weiter, ideal für ein einzelnes Widget (siehe [Widgets](#widgets-android--ios)). Bei eingeschalteter Live-Anzeige gibt es außerdem **Live-Anzeige anzeigen**.
- **Sensoren** für den aktuellen Status, die letzte Stempelung sowie **Arbeitszeit heute** und **Pausenzeit heute** (zählen live mit; Attribute: Arbeitsbeginn, Arbeit seit letzter Pause, vorgeschriebene und fehlende Pause).
- **Binärsensoren** „Eingestempelt“, „Pause“, „Arbeitstag“ (Wochentage, optionaler Workday-Sensor für Feiertage, ganztägige Abwesenheit) und „Urlaub / Abwesenheit“.
- **Kalender** mit den eigenen Abwesenheiten (z. B. Urlaub oder Krankheit), inklusive Unterstützung für Teil-Tag-Abwesenheiten.
- **Schalter** „Automatisches Stempeln“, sobald Büro- oder Homeoffice-Erkennung eingerichtet ist.
- **Sensor „Arbeitsort“** (*Büro* / *Homeoffice* / *Nicht bei der Arbeit*) aus der Erkennung, unabhängig vom Stempelstatus – ideal als Auslöser für eigene Automationen (z. B. Arbeitszimmer heizen).

### Assistent (alles optional, standardmäßig aus)

Eingerichtet wird alles pro Crewmeister-Konto unter **Einstellungen → Geräte & Dienste → Crewmeister → Konfigurieren**. Das Menü ist in Bereiche gegliedert; selten benötigte Feineinstellungen sind innerhalb der Formulare eingeklappt. Jeder Bereich wird beim Absenden gespeichert.

| Bereich | Funktion |
|---|---|
| **Arbeitszeit** | Wochentage, optionaler Arbeitstag-Sensor (z. B. [Workday](https://www.home-assistant.io/integrations/workday/) für Feiertage), tägliche Soll-Arbeitszeit und optional eine eigene Soll-Arbeitszeit pro Wochentag (z. B. Freitag 5,5 h) |
| **Benachrichtigungen** | Geräte mit der Companion App (Android und iOS). Benachrichtigungen haben Antwortknöpfe, z. B. *Einstempeln*, *Pause*, *Ausstempeln* oder *In 30 min erinnern*. Optional gibt es Bestätigungen nach jeder Stempelung und eine **Live-Anzeige** (iOS Live Activity / Android Live Update): Arbeitszeit mit laufender Uhr, Fortschrittsbalken bis zur Soll-Arbeitszeit und voraussichtlicher Feierabend auf dem Sperrbildschirm. Ersatzweise gibt es auf Android eine dauerhafte Statusanzeige mit Knöpfen |
| **Büro** | *Erkennung:* HA-Person mit Arbeitsort-Zonen, WLAN-Sensor der Companion App mit SSIDs, beliebige Binärsensoren/Eingabe-Schalter, NFC-Tags (Scannen stempelt ein bzw. aus) *Verhalten:* Für Ankommen und Gehen getrennt: *Aus*, *Nachfragen* (Benachrichtigung mit Knöpfen) oder *Automatisch*. Verzögerungen gegen GPS-Sprünge, Zeitfenster, nur einmal am Tag, Rückdatieren auf den tatsächlichen Zeitpunkt, kurze Abwesenheiten als Pause. Kein automatisches Einstempeln an freien Tagen, Feiertagen (über Arbeitstag-Sensor) oder bei Urlaub |
| **Homeoffice** | Erkennung über eine **Steckdose mit Leistungsmessung** (PC zieht mehr als z. B. 30 W) und/oder **Präsenzmelder bzw. PC-Status**, während die Person zu Hause ist – nur an Arbeitstagen und im Zeitfenster. Einstempeln *Aus/Nachfragen/Automatisch* (rückdatiert auf den Beginn der Aktivität), bei Inaktivität *Aus/Nachfragen/Automatisch* ausstempeln (rückdatiert auf den Beginn der Inaktivität). Kurze Inaktivität (Standard bis 60 min) wird als Pause gestempelt. Bist du inzwischen im Büro (Büro-Erkennung eingerichtet), beendet der PC zu Hause die Schicht nicht |
| **Erinnerungen** | **Feierabend-Erinnerung** nach Arbeitsbeginn + Soll-Arbeitszeit + Pflichtpause + Karenzzeit (bereits genommene Pausen zählen mit), Erinnerung beim Verlassen des Arbeitsorts, tägliche Erinnerung zu einer Uhrzeit, Warnung bei Höchstarbeitszeit. **Vergessenes Ausstempeln:** Läuft morgens noch die Schicht vom Vortag, bietet der Assistent an, rückwirkend auszustempeln – mit der Uhrzeit, zu der du den Arbeitsort verlassen hast, sonst mit Arbeitsbeginn + tägliche Arbeitszeit + Pause |
| **Pausen** | Erinnerung nach X Stunden ohne Pause, Benachrichtigung am Pausenende (oder automatisch weiterarbeiten), automatische Mittagspause zu einer Uhrzeit, Erinnerung ans Weiterarbeiten zu einer festen Uhrzeit (mit Knopf *Weiterarbeiten*, nur wenn du dann noch in der Pause bist). Beim Ausstempeln wird die Pause nach Arbeitszeitgesetz geprüft (es zählen nur Pausen ab 15 Minuten); fehlt Pause, kann sie per Knopf in Crewmeister **nachgetragen** werden |
| **Erweitert** | Abfrageintervall, im Kalender angezeigte Abwesenheitsstatus, Standardnotiz und Zeitkonto-ID für Stempelungen. Optional **Ort am Stempel**: „Büro“ bzw. „Homeoffice“ (Texte anpassbar) wird bei jeder Stempelung über Home Assistant mitgesendet und ist in Crewmeister auch für den Arbeitgeber sichtbar. Darf dein Konto den Ort nicht setzen (Fehler beim Stempeln), sendet die Option *Ort als Notiz senden* ihn stattdessen in der Notiz mit |

Hinweise zur Anwesenheitserkennung:

- Eine Zone zählt, wenn die gewählte Person laut Zone darin ist (Attribut `persons`).
- Der WLAN-Sensor der Companion App (`sensor.<gerät>_wifi_connection`) ist meist zuverlässiger als GPS.
- Ist die Zeit zwischen Gehen und Wiederkommen kürzer als die Verzögerung beim Gehen, passiert nichts. Mit „Kurze Abwesenheit als Pause“ wird eine Abwesenheit bis zu dieser Dauer rückwirkend als Pause gestempelt, eine längere als Ausstempeln zum Zeitpunkt des Gehens.
- Veraltete Knöpfe (z. B. eine alte Ausstempel-Nachfrage, nachdem schon neu gestempelt wurde) werden abgelehnt.

Hinweise zum Homeoffice:

- Die Person muss zu Hause sein (`home`), und es muss ein Arbeitstag im eingestellten Zeitfenster sein (Standard 06:00–19:00). Abends oder am Wochenende am PC zählt nicht.
- Die Leistungsschwelle muss über dem Standby-Verbrauch von PC/Monitor liegen. Läuft der PC über Nacht mit hoher Leistung, beginnt am nächsten Arbeitstag zum Fensterbeginn eine Sitzung.
- Ist am selben Tag schon automatisch eingestempelt worden (z. B. vor einem langen Mittag), fragt der Assistent beim nächsten Arbeitsbeginn nach, statt erneut automatisch einzustempeln. Das gilt auch fürs Büro.

Hinweise zur Live-Anzeige:

- Voraussetzungen laut [Companion-App-Doku](https://companion.home-assistant.io/docs/notifications/live-activities): Home Assistant 2026.7, iOS 17.2 (dort noch als Beta gekennzeichnet) bzw. eine aktuelle Android-App; Statusleisten-Chip und Always-on-Display ab Android 16.
- Die Uhr läuft auf dem Handy selbst; Home Assistant aktualisiert die Anzeige bei jedem Statuswechsel und sonst alle 15 Minuten.
- **Weggewischt?** Auf Android lässt sich die Live-Anzeige wegwischen. Die Integration merkt das und schickt sie nicht alle 15 Minuten neu, sondern erst beim nächsten Statuswechsel (Pause, Weiterarbeiten, nächster Arbeitstag). Sofort zurück holt sie der Button **Live-Anzeige anzeigen** oder der Dienst `crewmeister.show_live`, z. B. als Widget oder Schnellkachel. Mit mehreren Geräten gilt das Wegwischen für alle, weil die App nicht mitsendet, von welchem Gerät es kam.
- Auf iOS ersetzt die laufende Uhr den Text: Dort sind Uhr, Fortschritt in Prozent und Balken zu sehen, der voraussichtliche Feierabend nur auf Android bzw. im Sensor „Arbeitszeit heute“.
- iOS beendet Live Activities nach spätestens 8 Stunden. Die Integration startet die Anzeige deshalb nach 7,5 Stunden neu.
- Für iOS-Updates unterwegs braucht die App eine Verbindung zu Home Assistant (Fernzugriff).
- Arbeit und Pause sind farblich getrennt: Arbeit blau, Pause gelb. Android färbt Symbol, Uhr und Balken immer in einer Farbe, die mit dem Status wechselt; im Text sind Arbeits- und Pausenzeit zusätzlich farbig. Auf iOS wechselt die Hintergrundfarbe der Karte.
- Auf Android hat die Live-Anzeige Knöpfe: *Pause* und *Ausstempeln* bei der Arbeit, *Weiterarbeiten* und *Ausstempeln* in der Pause. iOS erlaubt in Live Activities keine Knöpfe; deshalb bekommen iOS-Geräte zusätzlich eine stille Statusbenachrichtigung (ohne Ton und Banner) mit denselben Knöpfen. Sie wird bei jedem Statuswechsel ersetzt und beim Ausstempeln entfernt.
- Animierte Bilder (GIF) unterstützt die Live-Anzeige auf keiner Plattform, nur Symbole. Die Symbole für Arbeit und Pause sind unter *Benachrichtigungen* einstellbar, z. B. `mdi:account-hard-hat` (Bauarbeiter) und `mdi:pretzel` (Brezel).

### Dienste & Optionen

- **Dienst** `crewmeister.create_stamp`, um Stempelungen inkl. optionaler Notiz, Ort oder Zeitpunkt automatisiert zu erstellen.
- **Dienst** `crewmeister.show_live`, um die Live-Anzeige wieder anzuzeigen.
- **Integration-Optionen** für Abfrageintervall, Filterung nach Abwesenheitsstatus, Standardnotiz sowie `time_account_id` für Stempelungen.
- **Mehrbenutzer-Support**: Die Crewmeister-Benutzer-ID dient als eindeutige ID, sodass mehrere Konten parallel eingerichtet werden können.
- **Diagnose-Download** (Zugangsdaten werden geschwärzt) für Fehlerberichte.


### Widgets (Android & iOS)

Eine eigene App ist nicht nötig: Die Companion App bringt Widgets mit, die direkt die Entitäten der Integration nutzen. Ein Widget kann dort allerdings entweder anzeigen oder einen Knopf haben; man kombiniert also eine Anzeige mit ein bis drei Knöpfen. Die Entitäts-IDs stehen unter *Einstellungen › Geräte & Dienste › Crewmeister › Gerät*; in den Beispielen heißt das Gerät `max_muster`. Wurde Home Assistant auf Deutsch eingerichtet, sind die IDs deutsch, z. B. `sensor.max_muster_arbeitszeit_heute` oder `button.max_muster_nachster_schritt`.

**Android** (Widget lange antippen bzw. Startbildschirm › Widgets › Home Assistant):

| Widget | Einstellung |
|---|---|
| **Vorlage** (Template), z. B. 3×1 | Status, Arbeitszeit und Feierabend, Vorlage unten. Antippen aktualisiert. |
| **Knopf** (Button) | Aktion `button.press`, Entität `button.max_muster_next_step`. Für einen Knopf je Aktion stattdessen *Einstempeln*, *Pause*, *Ausstempeln*. Optional „Authentifizierung erforderlich“. |
| **Knopf** | Aktion `crewmeister.show_live`, um die weggewischte Live-Anzeige zurückzuholen. |
| **Entität** (Entity State) | Alternativ zur Vorlage: `sensor.max_muster_status` oder Arbeitszeit heute, ohne eigene Formatierung. |

Die Schnellkacheln (*Einstellungen › Companion App › Kacheln verwalten*) können ebenfalls eine Button-Entität drücken, z. B. *Nächster Schritt* direkt aus der Benachrichtigungsleiste.

Vorlage für das Android-Widget (einfaches HTML wie `<b>`, `<br>` und `<font color>` wird dargestellt):

```jinja
{% set s = 'sensor.max_muster_status' %}
{% set w = 'sensor.max_muster_work_time_today' %}
{% set status = states(s) %}
{% set min = states(w) | float(0) | int %}
{% set ende = state_attr(w, 'expected_end') %}
{% if status == 'clocked_in' %}<font color="#03A9F4"><b>Bei der Arbeit</b></font>
{% elif status == 'on_break' %}<font color="#F9A825"><b>Pause</b></font>
{% else %}<b>Ausgestempelt</b>{% endif %}<br>
Arbeitszeit {{ min // 60 }}:{{ '%02d' % (min % 60) }} h
{% if ende and status != 'clocked_out' %} · Feierabend ca. {{ as_timestamp(ende) | timestamp_custom('%H:%M') }}{% endif %}
```

Die Vorlage wird von der App aktualisiert, wenn sie mit Home Assistant verbunden ist; die Arbeitszeit springt dabei minutenweise, nicht sekundengenau wie die Uhr der Live-Anzeige.

**iOS** (Companion App 2024.x oder neuer):

- **Eigenes Widget**: in der App unter *Einstellungen › Widgets* ein Widget anlegen und `sensor.max_muster_status`, Arbeitszeit heute sowie die Buttons *Nächster Schritt* und *Ausstempeln* (oder *Einstempeln*, *Pause*, *Ausstempeln*) hinzufügen. Ab iOS 17 lösen die Buttons direkt im Widget aus, auf Wunsch mit Bestätigung. Danach auf dem Home-Bildschirm das Widget *Home Assistant › Eigene* wählen.
- **Steuerelemente** (iOS 18, Kontrollzentrum und Sperrbildschirm): *Button* mit `button.max_muster_next_step` oder `…_clock_out`.
- **Sperrbildschirm**: *Details* mit einer kurzen Vorlage (z. B. Status und Arbeitszeit) oder *Messanzeige* mit der Arbeitszeit.
- Den Status mit laufender Uhr zeigt auf iOS die Live-Anzeige (Live Activity).

### 🚀 Über HACS installieren

[![Open HACS Repository in My Home Assistant](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mztechnik&repository=hacs-crewmeister&category=integration)

> Klicke auf den Button oben, um das Repository direkt in deiner Home Assistant-Instanz zu öffnen.  
> Stelle sicher, dass [HACS](https://hacs.xyz/) bereits installiert ist.

Alternative Installation über HACS
1. Öffne HACS in Home Assistant und wähle **Integrationen**.
2. Klicke auf das Menü (⋮) und anschließend auf **Benutzerdefiniertes Repository hinzufügen**.
3. Gib die URL dieses Repositories an und wähle den Typ **Integration**.
4. Installiere „Crewmeister“ und starte Home Assistant neu.

## Einrichtung

1. Navigiere zu **Einstellungen → Geräte & Dienste → Integration hinzufügen**.
2. Suche nach „Crewmeister“ und wähle die Integration aus.
3. Gib die Crewmeister-API-URL (Standard: `https://api.crewmeister.com`), deine Crewmeister-E-Mail-Adresse sowie dein Passwort ein.
4. Nach erfolgreicher Anmeldung werden die Entities erstellt. Die Crewmeister-Benutzer-ID wird als eindeutige ID verwendet, sodass mehrere Konten möglich sind.

Mindestens erforderlich ist Home Assistant 2026.2.

## Automatisierungen

Nutze den Dienst `crewmeister.create_stamp`, um z. B. beim Eintreffen in einem Geofence automatisch zu stempeln:

```yaml
service: crewmeister.create_stamp
data:
  stamp_type: START_WORK
  note: "Automatisches Einstempeln"
```

Optional lassen sich `timestamp`, `location` und `time_account_id` angeben (überschreiben die Standardwerte aus den Optionen). Sind mehrere Konten eingerichtet, ist `config_entry_id` Pflicht – ohne Angabe wird nicht mehr für alle Konten gleichzeitig gestempelt.

## Hinweise

- Die Integration authentifiziert sich per Benutzername/Passwort direkt an der Crewmeister-API und erneuert das Token automatisch.
- Abwesenheitstypen werden über die Crewmeister-API aufgelöst, sodass der Kalender sprechende Namen zeigt.
- Für eine zuverlässige Funktion muss der Crewmeister-Benutzer über die benötigten API-Berechtigungen verfügen.
- Nachtschichten werden vom Assistenten nicht unterstützt: Hat die Schicht vor Mitternacht begonnen, entfallen Feierabend-Erinnerung, Höchstarbeitszeit, Pausenerinnerung und Pausenende. Morgens greift dann die Prüfung auf vergessenes Ausstempeln.

## Sicherheit

- Die Verbindung zu Crewmeister muss HTTPS verwenden; eine `http://`-Adresse wird abgelehnt. Weiterleitungen der API werden nicht befolgt.
- Das Passwort liegt – wie bei allen Home-Assistant-Integrationen mit Benutzername/Passwort – unverschlüsselt in `.storage/core.config_entries`. Backups von Home Assistant enthalten es ebenfalls.
- Antwortknöpfe und NFC-Tags werden nur von der eingestellten Person und den Besitzern der ausgewählten Benachrichtigungs-Geräte akzeptiert. Andere Home-Assistant-Benutzer können darüber nicht für dich stempeln. Ist weder eine Person noch ein Benachrichtigungs-Gerät eingestellt, darf jeder Home-Assistant-Benutzer per NFC stempeln.
- Rückdatierte Knöpfe sind nur gültig, wenn der Zeitpunkt höchstens drei Tage zurück und nicht in der Zukunft liegt; nachgetragene Pausen sind auf 2 Stunden und eigene Stempel begrenzt.
- Buttons und der Dienst `crewmeister.create_stamp` können – wie bei Home Assistant üblich – von jedem angemeldeten Home-Assistant-Benutzer ausgelöst werden.

## Entwicklung & Haftungsausschluss

- Diese Custom Integration wurde komplett durch KI erstellt: ursprünglich mit Codex, die Erweiterungen ab Version 0.3.0 mit Claude Code.
- Nutzung auf eigene Gefahr: Es besteht **keine Haftung** für Schäden oder Datenverluste.
- Das Projekt befindet sich aktuell noch in Entwicklung, daher können jederzeit Fehler auftreten.
- Die Entwicklung ist **inoffiziell** und steht in **keinem Zusammenhang** mit Crewmeister bzw. der ATOSS Aloud GmbH.

## Fehlerbehebung

- **Fehlerbild:** Beim Betätigen eines Buttons oder Ausführen des Dienstes `crewmeister.create_stamp` erscheint ein Log-Eintrag wie `Crewmeister API returned 401`.
  - **Ursache:** Die Zugangsdaten sind ungültig oder das Token konnte nicht erneuert werden.
  - **Lösung:** Werden die Zugangsdaten abgelehnt, startet Home Assistant automatisch die erneute Anmeldung. Gib dort dein aktuelles Passwort ein.

## Entwicklung

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest
```

Die OpenAPI-Beschreibungen der Crewmeister-API liegen unter [`docs/api/`](docs/api/), der Ausbauplan unter [`docs/PLAN.md`](docs/PLAN.md).

Viel Spaß beim Automatisieren deiner Arbeitszeiterfassung!
