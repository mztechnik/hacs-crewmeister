# Test 1.0.0 in echter Home-Assistant-Instanz

Checkliste zum Abhaken. Gestempelt wird mit dem echten Crewmeister-Konto; Teststempel danach in Crewmeister korrigieren.

## Vorbereitung

- [ ] **Backup** von Home Assistant anlegen. Die Migration auf Config-Entry-Version 2 lässt sich nicht rückgängig machen; ein Zurück auf 0.5 braucht das Backup.
- [ ] Screenshot der aktuellen Optionen (alle Bereiche), um die Migration zu prüfen.
- [ ] Ordner `custom_components/crewmeister` aus Branch `feature/v2` nach `/config/custom_components/crewmeister` kopieren (Samba-, SSH- oder File-Editor-Add-on; alten Ordner vorher ersetzen, nicht zusammenführen).
- [ ] Home Assistant neu starten. Im Log (`Einstellungen › System › Protokolle`, Filter „crewmeister“) steht `Migrating Crewmeister options of … to version 2` (Log-Level `info`, ggf. über `logger` einschalten), keine Fehler.

## 1. Migration

- [ ] Integration lädt, alle Entitäten haben dieselben IDs wie vorher.
- [ ] **Stempelregeln**: Kommen-Modus wie vorher; Feierabend-Modus = altes „Beim Gehen“; „Ab erreichter Soll-Arbeitszeit“ an.
- [ ] Mittagspause von früher steht als Pausenzeitraum drin (falls genutzt).
- [ ] Person, Zonen, WLAN, Homeoffice-Sensoren, Geräte, Live-Anzeige unverändert.
- [ ] Neue Sensoren „Automatik“ und Attribute `phase`/`sources` am Sensor „Arbeitsort“ vorhanden.

## 2. Einstellungen

- [ ] Jeden Bereich einmal öffnen und speichern – keine Fehlermeldung.
- [ ] Zonen ohne Person → Meldung „Für Zonen muss eine Person ausgewählt sein“.
- [ ] Pausen-Modus ohne Pausenzeitraum → Meldung.

## 3. Büro (Modus zuerst „Nachfragen“, später „Automatisch“)

- [ ] **Ankommen**: nach Bestätigungszeit kommt die Nachfrage; *Einstempeln* stempelt mit Ankunftszeit + Wegzeit (in Crewmeister prüfen).
- [ ] Automatisch: Stempel erst zum Zeitpunkt Ankunft + Wegzeit, Sensor „Automatik“ zeigt vorher „Wartet auf Wegzeit“.
- [ ] **Kurz weg** (WLAN aus, < 10 min): nichts passiert.
- [ ] **Gehen vormittags** (außerhalb Pausen-/Feierabend-Zeitraum): kein Ausstempeln; Nachfrage (falls an) verschwindet nach Ablauf.
- [ ] **Gehen im Pausenzeitraum**: Pause mit Gehzeit − Wegzeit; Zurückkommen beendet die Pause.
- [ ] **Gehen im Feierabend-Zeitraum**: Ausstempeln mit Gehzeit − Wegzeit.
- [ ] Nach dem Ausstempeln erneut ankommen: nur Nachfrage, kein automatisches Einstempeln.
- [ ] Handy kurz in Flugmodus (Sensor `unavailable`): kein Gehen.

## 4. Homeoffice (falls eingerichtet)

- [ ] PC an (über Schwelle) an einem Arbeitstag zu Hause → Kommen ohne Wegzeit.
- [ ] PC aus länger als „Inaktiv nach“ außerhalb der Zeiträume → kein Ausstempeln.
- [ ] Abends PC an nach dem Ausstempeln → nur Nachfrage.

## 5. Urlaub

- [ ] Urlaubs-Schalter an → Binärsensor „Urlaub / Abwesenheit“ an, `source` = Sensor; Ankommen stempelt nicht, „Automatik“ zeigt „Urlaub / Abwesenheit“.
- [ ] Ganztägiger Kalendertermin heute (mit Stichwort) → ebenso, `source` = Kalender.

## 6. Pause nachtragen (rückdatierte Stempel)

- [ ] Mehr als 6 h ohne Pause eingestempelt (oder Pflichtpause testweise auf 1 h stellen) und ausstempeln → Benachrichtigung mit *15 / 30 / 45 min* und *Keine Pause*.
- [ ] *30 min* → in Crewmeister erscheint eine Pause von 30 min vor dem Ausstempeln.
- [ ] Nicht antworten → nach „Antwort abwarten“ wird der Standardwert eingetragen.
- [ ] *Keine Pause* → nichts wird eingetragen.

## 7. Zuverlässigkeit

- [ ] HA neu starten, während sich die Anwesenheit ändert (z. B. WLAN verbinden während des Neustarts) → danach Kommen mit dem Zeitpunkt der Änderung.
- [ ] Internet von HA kurz trennen und Stempel auslösen → „Automatik“ zeigt Warteschlange; nach Wiederverbindung wird mit Originalzeit gestempelt.
- [ ] Schalter „Automatisches Stempeln“ aus → keine automatischen Stempel, Erinnerungen bleiben.

## 8. Live-Anzeige und Erinnerungen

- [ ] Live-Anzeige erscheint beim Einstempeln, wechselt bei Pause, verschwindet beim Ausstempeln.
- [ ] Feierabend-Erinnerung und Pausenerinnerung kommen wie bisher.
- [ ] Morgens mit laufender Schicht vom Vortag → Angebot, mit der Gehzeit auszustempeln.

## Bei Fehlern

Diagnose herunterladen (`Geräte & Dienste › Crewmeister › ⋮ › Diagnose herunterladen`) und Log-Auszug mit „crewmeister“ sichern. Attribute des Sensors „Automatik“ (Grund, Zeit, Ergebnis) notieren.
