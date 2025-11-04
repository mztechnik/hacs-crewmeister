# 🧭 HACS Crewmeister Integration für Home Assistant

Diese Integration ermöglicht es dir, [Crewmeister](https://www.crewmeister.com/) direkt mit Home Assistant zu verbinden.  
Damit kannst du Arbeitszeiten automatisieren, den aktuellen Status abrufen und Stempelungen (Ein-/Ausstempeln) direkt aus deinen Automationen oder Blueprints ausführen.

---

## ⚙️ Installation

### 🚀 Über HACS installieren

[![Open HACS Repository in My Home Assistant](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mztechnik&repository=hacs-crewmeister&category=integration)

> Klicke auf den Button oben, um das Repository direkt in deiner Home Assistant-Instanz zu öffnen.  
> Stelle sicher, dass [HACS](https://hacs.xyz/) bereits installiert ist.

Alternativ manuell:

1. Lade dieses Repository herunter.  
2. Kopiere den Inhalt des Verzeichnisses `custom_components/crewmeister` nach  
   ```
   config/custom_components/crewmeister
   ```
3. Home Assistant neu starten.

---

## 💼 Funktionen

- **Ein- & Ausstempeln** über Service-Aufrufe (`crewmeister.create_stamp`)
- **Abfrage des Arbeitsstatus** („Eingestempelt“ / „Ausgestempelt“) als Binary Sensor
- **Unterstützung mehrerer Crewmeister-Konten**
- **Integration mit Automationen & Blueprints**
- **Notizen, Orte und Zeitkonten** direkt in Automatisierungen nutzbar

---

## 🧩 Blueprint-Unterstützung

Im Verzeichnis [`blueprints/automation/crewmeister`](blueprints/automation/crewmeister) findest du zwei komfortable Blueprints, um das automatische Ein- und Ausstempeln zu konfigurieren.

### 🕓 Automatisches Einstempeln
[![Import Blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Fmztechnik%2Fhacs-crewmeister%2Fmain%2Fblueprints%2Fautomation%2Fcrewmeister%2Fclock_in.yaml)

> **Beispiel:** Automatisches Einstempeln beim Verbinden mit dem Firmen-WLAN, beim Betreten der Zone „Büro“ oder beim Scannen eines NFC-Tags.

### 🕔 Automatisches Ausstempeln
[![Import Blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Fmztechnik%2Fhacs-crewmeister%2Fmain%2Fblueprints%2Fautomation%2Fcrewmeister%2Fclock_out.yaml)

> **Beispiel:** Automatisches Ausstempeln beim Verlassen des WLANs, beim Verlassen einer Zone oder zu einer festen Uhrzeit.

#### 🔗 Fallback-Links (RAW)
Falls der Button-Import nicht funktioniert:
- [Einstempeln (clock_in.yaml)](https://raw.githubusercontent.com/mztechnik/hacs-crewmeister/main/blueprints/automation/crewmeister/clock_in.yaml)
- [Ausstempeln (clock_out.yaml)](https://raw.githubusercontent.com/mztechnik/hacs-crewmeister/main/blueprints/automation/crewmeister/clock_out.yaml)

> In Home Assistant:  
> **Einstellungen → Automatisierungen & Szenen → Blueprints → Blueprint importieren → URL einfügen**

### 📋 Funktionsübersicht der Blueprints
- **Auslöser-Auswahl per UI:** WLAN, Zonen, NFC-Tags, Zeitpunkte  
- **Zeitfenster:** Optional (z. B. 07:00–11:00 Uhr oder 14:00–21:00 Uhr)  
- **Sperr-Schalter:** `input_boolean` oder `switch` kann automatische Stempelung blockieren  
- **Crewmeister-Kontoauswahl:** Unterstützt mehrere Konten  
- **Minimale HA-Version:** `2025.1.0` (entsprechend `min_version` im Blueprint)

---

## 🧠 Beispiele für Automatisierungen

**Einstempeln beim Betreten der Zone "Büro"**
```yaml
trigger:
  - platform: zone
    entity_id: person.max
    zone: zone.buero
    event: enter
action:
  - service: crewmeister.create_stamp
    data:
      stamp_type: START_WORK
```

**Ausstempeln beim Verlassen des WLANs**
```yaml
trigger:
  - platform: state
    entity_id: sensor.pixel_wlan
    from: "WLAN-Firma"
    to: "not_connected"
action:
  - service: crewmeister.create_stamp
    data:
      stamp_type: CLOCK_OUT
```

---

## 🧾 Lizenz

Dieses Projekt steht unter der [MIT-Lizenz](LICENSE).

---

## 💬 Feedback & Support

Fehler, Featurewünsche oder Verbesserungsvorschläge?  
➡️ [Eröffne ein Issue auf GitHub](https://github.com/mztechnik/hacs-crewmeister/issues)

---

**Erstellt mit ❤️ von [mztechnik](https://github.com/mztechnik)**  
Unterstützt die Zeiterfassung direkt aus Home Assistant – einfach, sicher und smart.
