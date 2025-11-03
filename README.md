# Crewmeister für Home Assistant

Diese HACS-Integration bindet Crewmeister in Home Assistant ein. Nach der Einrichtung kannst du Stempelungen direkt aus Home Assistant auslösen, deinen aktuellen Arbeitsstatus überwachen und genehmigte Abwesenheiten im Kalender darstellen.

## Funktionsumfang

- **Buttons** zum Einstempeln, Pausieren und Ausstempeln.
- **Sensoren** für den aktuellen Status und den Zeitstempel der letzten Stempelung.
- **Binärsensor** „Eingestempelt“ zur Verwendung in Automatisierungen.
- **Kalender** mit den eigenen Abwesenheiten (z. B. Urlaub oder Krankheit), inklusive Unterstützung für Teil-Tag-Abwesenheiten.
- **Dienst** `crewmeister.create_stamp`, um Stempelungen inkl. optionaler Notiz, Ort oder Zeitpunkt automatisiert zu erstellen.

## Installation über HACS

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

Über die Optionen der Integration kannst du das Abfrageintervall (in Sekunden) und die berücksichtigten Abwesenheitsstatus (z. B. nur genehmigte Urlaube) anpassen.

## Automatisierungen

Nutze den Dienst `crewmeister.create_stamp`, um z. B. beim Eintreffen in einem Geofence automatisch zu stempeln:

```yaml
service: crewmeister.create_stamp
data:
  stamp_type: START_WORK
  note: "Automatisches Einstempeln"
```

Optional lassen sich `timestamp`, `location` und `config_entry_id` (bei mehreren Konten) angeben.

## Hinweise

- Die Integration authentifiziert sich per Benutzername/Passwort direkt an der Crewmeister-API und erneuert das Token automatisch.
- Abwesenheitstypen werden über die Crewmeister-API aufgelöst, sodass der Kalender sprechende Namen zeigt.
- Für eine zuverlässige Funktion muss der Crewmeister-Benutzer über die benötigten API-Berechtigungen verfügen.

Viel Spaß beim Automatisieren deiner Arbeitszeiterfassung!
