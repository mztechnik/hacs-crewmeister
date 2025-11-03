# Crewmeister für Home Assistant

Diese HACS-Integration bindet Crewmeister in Home Assistant ein. Nach der Einrichtung kannst du Stempelungen direkt aus Home Assistant auslösen, deinen aktuellen Arbeitsstatus überwachen und genehmigte Abwesenheiten im Kalender darstellen.

## Funktionsumfang

- **Buttons** zum Einstempeln, Pausieren und Ausstempeln (derzeit mit Einschränkungen, siehe Hinweise).
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

- Die Stempel-Buttons werden aktuell von einem Crewmeister-Backend-Fehler beeinträchtigt: Der API-Endpunkt `POST /time-tracking/stamps` antwortet mit `HTTP 400 Bad Request`, sobald Home Assistant versucht, eine Stempelung über die Buttons oder den Dienst `crewmeister.create_stamp` auszulösen. Die Stempelung wird daraufhin nicht übernommen und Home Assistant zeigt im Protokoll einen entsprechenden Fehler an. Bis Crewmeister die serverseitige Kette für Folge-Stempel wieder akzeptiert, können die Buttons nur den aktuellen Status anzeigen, aber keine vollständige Stempel-Workflows starten oder beenden.
- Als Workaround empfiehlt es sich, direkt in der Crewmeister-Weboberfläche oder der offiziellen App zu stempeln. Anschließend können die Status-Sensoren der Integration genutzt werden, um den angezeigten Zustand zu überprüfen oder Automatisierungen auf Basis der bereits vorhandenen Stempelungen zu betreiben.
- Die Integration authentifiziert sich per Benutzername/Passwort direkt an der Crewmeister-API und erneuert das Token automatisch.
- Abwesenheitstypen werden über die Crewmeister-API aufgelöst, sodass der Kalender sprechende Namen zeigt.
- Für eine zuverlässige Funktion muss der Crewmeister-Benutzer über die benötigten API-Berechtigungen verfügen.

## Fehlerbehebung

- **Fehlerbild:** Beim Betätigen eines Buttons oder Ausführen des Dienstes `crewmeister.create_stamp` erscheint ein Log-Eintrag wie `Crewmeister API returned 400` und die Aktion wird in Home Assistant als fehlgeschlagen markiert.
  - **Ursache:** Die Crewmeister-API weist aktuell Folge-Stempel (z. B. Pause oder Ausstempeln) zurück, wenn sie per API ausgelöst werden. Dadurch kann die Integration keine zusammenhängende Stempelkette mehr starten oder fortsetzen.
  - **Workaround:** Führe die gewünschte Stempelung in der offiziellen Crewmeister-App oder im Web-Portal aus. Die Integration synchronisiert anschließend den aktualisierten Status (Sensoren werden beim nächsten Update bzw. nach manuellem Refresh aktualisiert). Automatisierungen, die auf dem Dienst `crewmeister.create_stamp` basieren, sollten vorübergehend deaktiviert oder mit zusätzlichen Prüfungen versehen werden, bis die API das Stempeln wieder erlaubt.

Viel Spaß beim Automatisieren deiner Arbeitszeiterfassung!
