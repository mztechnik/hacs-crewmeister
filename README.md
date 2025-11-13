# Crewmeister für Home Assistant

Diese HACS-Integration bindet Crewmeister in Home Assistant ein. Nach der Einrichtung kannst du Stempelungen direkt aus Home Assistant auslösen, deinen aktuellen Arbeitsstatus überwachen und genehmigte Abwesenheiten im Kalender darstellen.

## Funktionsumfang

### Entitäten

- **Buttons** zum Einstempeln, Pausieren und Ausstempeln direkt aus Home Assistant.
- **Sensoren** für den aktuellen Status und den Zeitstempel der letzten Stempelung.
- **Binärsensor** „Eingestempelt“ zur Verwendung in Automatisierungen.
- **Kalender** mit den eigenen Abwesenheiten (z. B. Urlaub oder Krankheit), inklusive Unterstützung für Teil-Tag-Abwesenheiten.

### Dienste & Optionen

- **Dienst** `crewmeister.create_stamp`, um Stempelungen inkl. optionaler Notiz, Ort oder Zeitpunkt automatisiert zu erstellen.
- **Integration-Optionen** für Abfrageintervall, Filterung nach Abwesenheitsstatus, Standardnotiz sowie `time_account_id` für Stempelungen.
- **Mehrbenutzer-Support**: Der Benutzername dient als eindeutige ID, sodass mehrere Konten parallel eingerichtet werden können.


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

## Automatisierungen

Nutze den Dienst `crewmeister.create_stamp`, um z. B. beim Eintreffen in einem Geofence automatisch zu stempeln:

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

## Entwicklung & Haftungsausschluss

- Diese Custom Integration wurde komplett durch eine KI (Codex) erstellt.
- Nutzung auf eigene Gefahr: Es besteht **keine Haftung** für Schäden oder Datenverluste.
- Das Projekt befindet sich aktuell noch in Entwicklung, daher können jederzeit Fehler auftreten.
- Die Entwicklung ist **inoffiziell** und steht in **keinem Zusammenhang** mit Crewmeister bzw. der ATOSS Aloud GmbH.

## Fehlerbehebung

- **Fehlerbild:** Beim Betätigen eines Buttons oder Ausführen des Dienstes `crewmeister.create_stamp` erscheint ein Log-Eintrag wie `Crewmeister API returned 401`.
  - **Ursache:** Die Zugangsdaten sind ungültig oder das Token konnte nicht erneuert werden.
  - **Lösung:** Prüfe Benutzername und Passwort in den Integrations-Einstellungen und starte ggf. den Reauthentifizierungsprozess.

Viel Spaß beim Automatisieren deiner Arbeitszeiterfassung!
