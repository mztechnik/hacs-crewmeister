# Crewmeister für Home Assistant

Diese HACS-Integration bindet Crewmeister in Home Assistant ein. Nach der Einrichtung kannst du Stempelungen direkt aus Home Assistant auslösen, deinen aktuellen Arbeitsstatus überwachen und genehmigte Abwesenheiten im Kalender darstellen.

## Funktionsumfang

- **Buttons** zum Einstempeln, Pausieren und Ausstempeln direkt aus Home Assistant.
- **Sensoren** für den aktuellen Status und den Zeitstempel der letzten Stempelung.
- **Binärsensor** „Eingestempelt“ zur Verwendung in Automatisierungen.
- **Kalender** mit den eigenen Abwesenheiten (z. B. Urlaub oder Krankheit), inklusive Unterstützung für Teil-Tag-Abwesenheiten.
- **Dienst** `crewmeister.create_stamp`, um Stempelungen inkl. optionaler Notiz, Ort oder Zeitpunkt automatisiert zu erstellen.


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
4. Nach erfolgreicher Anmeldung werden die Entities erstellt. Der Nutzername wird als eindeutige ID verwendet, sodass mehrere Konten möglich sind.

## Optionen

Über die Optionen der Integration kannst du das Abfrageintervall (in Sekunden), die berücksichtigten Abwesenheitsstatus (z. B. nur genehmigte Urlaube) sowie eine Standard-Notiz und eine optionale `time_account_id` für Stempelungen hinterlegen.

## Automatisierungen

### Blueprint-Unterstützung

Im Verzeichnis [`blueprints/automation/crewmeister`](blueprints/automation/crewmeister) findest du zwei Automations-Blueprints für das automatische Ein- und Ausstempeln. Die Blueprints führen dich komfortabel durch alle wichtigen Einstellungen:

- **Auslöser-Auswahl per UI:** Hinterlege beliebige Trigger wie WLAN-Verbindungen, Geofencing (Zone betreten/verlassen), NFC-Tags oder feste Zeitpunkte.
- **Zeitfenster:** Lege optional fest, wann frühestens bzw. spätestens automatisch gestempelt werden soll – inklusive Unterstützung für Zeiträume über Mitternacht.
- **Status- und Sperr-Abfragen:** Nutze den Crewmeister-Binärsensor „Eingestempelt“ sowie optionale Helfer (`input_boolean`/Schalter), um Doppelstempelungen oder unerwünschte Ausführungen zu verhindern.
- **Zusatzfelder:** Übergib Notizen, Orte, Zeitkonten oder wähle bei mehreren Integrationen gezielt das richtige Crewmeister-Konto aus.

Nach dem Import der Blueprints über **Einstellungen → Automatisierungen & Szenen → Blueprint importieren** kannst du beliebig viele Automatisierungen darauf basierend erstellen und individuell anpassen. Für den Import kannst du direkt folgende Links verwenden, die das YAML ohne HTML-Anteil ausliefern:

- Einstempeln: <https://github.com/crewmeister/hacs-crewmeister/blob/main/blueprints/automation/crewmeister/clock_in.yaml?raw=1>
- Ausstempeln: <https://github.com/crewmeister/hacs-crewmeister/blob/main/blueprints/automation/crewmeister/clock_out.yaml?raw=1>

### Direkte Service-Nutzung

Alternativ kannst du den Dienst `crewmeister.create_stamp` manuell verwenden, um z. B. beim Eintreffen in einem Geofence automatisch zu stempeln:

```yaml
service: crewmeister.create_stamp
data:
  stamp_type: START_WORK
  note: "Automatisches Einstempeln"
```

Optional lassen sich `timestamp`, `location`, `time_account_id` (wenn sie nicht global gesetzt ist) und `config_entry_id` (bei mehreren Konten) angeben.

## Hinweise

- Die Integration authentifiziert sich per Benutzername/Passwort direkt an der Crewmeister-API und erneuert das Token automatisch.
- Abwesenheitstypen werden über die Crewmeister-API aufgelöst, sodass der Kalender sprechende Namen zeigt.
- Für eine zuverlässige Funktion muss der Crewmeister-Benutzer über die benötigten API-Berechtigungen verfügen.
- Diese Integration wurde komplett von Codex entwickelt (daher keine Haftung).

## Fehlerbehebung

- **Fehlerbild:** Beim Betätigen eines Buttons oder Ausführen des Dienstes `crewmeister.create_stamp` erscheint ein Log-Eintrag wie `Crewmeister API returned 401`.
  - **Ursache:** Die Zugangsdaten sind ungültig oder das Token konnte nicht erneuert werden.
  - **Lösung:** Prüfe Benutzername und Passwort in den Integrations-Einstellungen und starte ggf. den Reauthentifizierungsprozess.

Viel Spaß beim Automatisieren deiner Arbeitszeiterfassung!
