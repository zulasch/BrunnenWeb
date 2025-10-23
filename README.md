# 💧 Brunnenmesssystem – Raspberry Pi 4–20 mA Pegelüberwachung

Ein vollständiges Messsystem zur **Überwachung des Wasserstands eines Brunnens**
mit einem **4–20 mA-Sensor**, **ADS1115 ADC** und **Raspberry Pi**.  
Die Anwendung umfasst:


- 🌊 Kontinuierliche Messung der Wassertiefe  
- 💾 Lokale Datenspeicherung in SQLite (Offline-Puffer)  
- ☁️ Automatische Übertragung an InfluxDB (wenn verfügbar)  
- 🌐 Modernes Webinterface (Flask) zur Anzeige, Konfiguration & Steuerung  
- 📊 Diagramme & Systemstatus direkt im Browser  
- ⚙️ Automatische Hintergrundausführung via `systemd`

---

## 🧠 Projektübersicht

### Hauptkomponenten

| Datei | Zweck |
|-------|-------|
| `wasserstand_logger.py` | Hauptprogramm zur Messdatenerfassung & Speicherung |
| `webapp.py` | Flask-Webserver für Oberfläche & API |
| `config/config.json` | Konfigurationsdatei mit Sensor- & Systemparametern |
| `data/offline_cache.db` | SQLite-Puffer (Offline-Datenspeicher) |
| `data/latest_measurement.json` | Letzter Messwert für die Weboberfläche |
| `logs/` | Log-Dateien |
| `templates/` | HTML-Templates für Flask |
| `scripts/start_brunnen.sh` | Startskript für systemd |
| `install.sh` | Automatische Systeminstallation (Pakete, Dienste etc.) |

---

## ⚙️ Hardwareaufbau

**Sensor:** 4–20 mA-Sonde mit externer 24 V-Versorgung  
**ADC:** ADS1115 (I²C)  
**Raspberry:** Pi 3 / 4 / 5

🪛 **Anschlussprinzip:**

24 V+ → Sensor + 24 V– → Sensor – Sensor OUT (4–20 mA) → 150 Ω Shunt → ADS1115 A0 GND (Raspberry) → ADS1115 GND → 24 V– (gemeinsame Masse) SDA, SCL → Raspberry (Pins 3, 5)
VCC (ADS1115) → 3.3 V Raspberry


---

## 🧩 Softwarearchitektur

### 1️⃣ `wasserstand_logger.py`

Liest zyklisch den ADS1115 aus und berechnet:

- Strom (mA)
- Wassertiefe (m)
- Wasseroberfläche unter Gelände (m)
- Messwert über NN (m)
- Pegeldifferenz (m)

Speichert:

- **Lokal in SQLite**
- **Optional in InfluxDB**
- **Aktuellsten Wert als JSON**

Die **Konfiguration** wird bei Änderung automatisch neu geladen.

---

### 2️⃣ `webapp.py`

Startet eine Weboberfläche mit folgenden Bereichen:

| Seite | URL | Beschreibung |
|-------|-----|---------------|
| 🏠 Start | `/` | Anzeige & Bearbeitung der Konfiguration |
| 📊 Verlauf | `/chart` | Pegelverlauf der letzten 24 h (Diagramm) |
| 📦 Logs | `/logs` | Einsicht in Logdateien |
| ⚙️ Dienste | `/service` | Start/Stopp von Systemdiensten |
| 🧩 API | `/api/*` | Schnittstellen (z. B. letzter Messwert, Chartdaten) |

Alle Seiten sind durch einen **Login geschützt** (`WEB_USER`, `WEB_PASS` in `config.json`).

---

## 🔧 Installation

### Voraussetzungen

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip git i2c-tools sqlite3
sudo raspi-config  # I²C aktivieren!


cd /root
git clone https://github.com/dein-repo/brunnen_web.git
cd brunnen_web
chmod +x install.sh
./install.sh

