# BrunnenWeb – Raspberry Pi Brunnenmesssystem

Vollständiges IoT-Messsystem zur **Überwachung von Brunnen und Wasserzählern** auf Raspberry Pi.
Entwickelt für den Einsatz in der Umgebung von Reber Brunnenbau – skalierbar auf mehrere Kunden und Standorte.

---

## Inhaltsverzeichnis

1. [Funktionsübersicht](#funktionsübersicht)
2. [Hardware](#hardware)
3. [Softwarearchitektur](#softwarearchitektur)
4. [Web-Interface & API](#web-interface--api)
5. [Konfigurationsparameter](#konfigurationsparameter)
6. [Multi-Tenant Setup (Mehrere Kunden)](#multi-tenant-setup-mehrere-kunden)
7. [InfluxDB & Grafana](#influxdb--grafana)
8. [Installation](#installation)
9. [Dienste verwalten](#dienste-verwalten)
10. [System-Update via GitHub](#system-update-via-github)
11. [Entwicklung: Neue Parameter hinzufügen](#entwicklung-neue-parameter-hinzufügen)

---

## Funktionsübersicht

- **4-kanalige 4–20 mA Messung** via ADS1115 ADC (Wasserstand, Temperatur, Durchfluss, Analog)
- **BMP280 Barometer** – Luftdruck und Temperatur (optional)
- **2× Reedkontakt-Impulszähler** für Wasserzähler (GPIO 25, GPIO 27)
- **6× MOSFET-Ausgänge** mit Zeitsteuerung (GPIO 4, 17, 18, 22, 23, 24)
- **OLED-Display** (SH1106 128×64) zur lokalen Anzeige
- **SQLite Offline-Puffer** – Messwerte werden lokal gespeichert und bei InfluxDB-Ausfall nachgesendet
- **InfluxDB-Integration** – automatische Übertragung mit Offline-Fallback
- **Grafana-kompatibel** – vollständige Tag-Struktur mit `device_id` und `location`
- **Flask-Webinterface** – responsive Konfiguration, Anzeige, Steuerung
- **PIN-geschützter Login** mit Rate-Limiting
- **Automatisches Config-Reload** – Änderungen werden ohne Neustart übernommen
- **Systemd-Integration** – automatischer Start nach Booten
- **GitHub Auto-Update** direkt aus dem Web-Interface

---

## Hardware

### Komponenten

| Komponente | Beschreibung | Schnittstelle |
|-----------|-------------|--------------|
| Raspberry Pi 3/4/5 | Hauptrechner | – |
| ADS1115 | 16-Bit ADC für 4–20 mA Sensoren (4 Kanäle) | I²C |
| BMP280 | Barometer (Luftdruck + Temperatur) | I²C |
| SH1106 OLED | 128×64 Pixel Display | I²C |
| 4–20 mA Sensoren | Wasserstand, Temperatur, Durchfluss etc. | ADS1115 A0–A3 |
| 150 Ω Shunt-Widerstand | Strom-Spannungs-Wandlung | je Kanal |
| MOSFET-Platine | 6 schaltbare Ausgänge | GPIO |
| Reedkontakte | 2 Impulseingänge für Wasserzähler | GPIO |

### GPIO-Belegung

| GPIO | Funktion | Richtung |
|------|---------|---------|
| 2 (SDA) | I²C Daten | bidirektional |
| 3 (SCL) | I²C Takt | bidirektional |
| 4 | MOSFET Kanal 1 | Ausgang |
| 17 | MOSFET Kanal 2 | Ausgang |
| 18 | MOSFET Kanal 3 | Ausgang |
| 22 | MOSFET Kanal 4 | Ausgang |
| 23 | MOSFET Kanal 5 | Ausgang |
| 24 | MOSFET Kanal 6 | Ausgang |
| 25 | Reedkontakt / Wasserzähler 1 | Eingang (Pull-Up) |
| 27 | Reedkontakt / Wasserzähler 2 | Eingang (Pull-Up) |

### Verdrahtung 4–20 mA Sensor

```
24 V+ ──── Sensor (+) ──── Sensor (–) ──┐
                                         │
                                      150 Ω Shunt
                                         │
ADS1115 A0 ─────────────────────────────┘
ADS1115 GND ──── 24 V– (gemeinsame Masse) ──── RPi GND
ADS1115 SDA/SCL ──── RPi GPIO 2/3
ADS1115 VCC ──── RPi 3.3 V
```

**Formel:** `Strom (mA) = Spannung (V) / 0.150 Ω × 1000`

### Verdrahtung Reedkontakt

```
RPi GPIO 25 (oder 27) ──── Reed Kontakt ──── RPi GND
(interner Pull-Up aktiv – kein externer Widerstand nötig)
```

Bei geschlossenem Kontakt: fallende Flanke → Impuls gezählt.

---

## Softwarearchitektur

### Dateistruktur

```
BrunnenWeb/
├── wasserstand_logger.py    # Hauptlogger: Messung, SQLite, InfluxDB
├── webapp.py                # Flask-Webserver: UI, API, Konfiguration
├── mosfet_control.py        # GPIO-Steuerung für 6 MOSFET-Ausgänge
├── reed_contact.py          # Reedkontakt-Impulszähler (GPIO 25, 27)
├── display_controller.py    # OLED-Anzeige (SH1106)
├── requirements.txt         # Python-Abhängigkeiten
├── install.sh               # Vollautomatische Installation
├── config/
│   ├── config.json          # Aktive Konfiguration (automatisch erstellt)
│   ├── config.template.json # Vorlage für Konfiguration
│   ├── output_schedule.json # Zeitpläne für MOSFET-Ausgänge
│   └── output_names.json    # Kanalnamen für MOSFET-Ausgänge
├── data/
│   ├── offline_cache.db     # SQLite Offline-Puffer
│   ├── latest_measurement.json  # Letzte Messwerte (für Web-GUI)
│   ├── reed_counts.json     # Persistente Reedkontakt-Zählerstände
│   └── config_update.flag   # Signal für Logger: Konfig neu laden
├── logs/
│   ├── wasserstand.log      # Logger-Ausgaben
│   ├── logger.err.log       # Systemd stderr Logger
│   └── webapp.err.log       # Systemd stderr Webapp
├── templates/               # Flask HTML-Templates
│   ├── base.html            # Basistemplate mit Navigation
│   ├── index.html           # Konfigurationsseite
│   ├── measurements.html    # Aktuelle Messwerte
│   ├── barometer.html       # BMP280-Anzeige
│   ├── reed.html            # Wasserzähler-Anzeige
│   ├── outputs.html         # MOSFET-Steuerung & Zeitplan
│   ├── database.html        # InfluxDB-Konfiguration
│   ├── logs.html            # Log-Viewer
│   ├── service.html         # Dienstverwaltung
│   └── systemstatus.html    # Systemstatus
├── scripts/
│   └── update_repo.sh       # GitHub Auto-Update Skript
└── deploy/
    └── systemd/
        └── brunnen_display.service  # Display-Service Unit
```

### Module im Detail

#### `wasserstand_logger.py` – Hauptlogger

Der Logger läuft als eigenständiger `systemd`-Dienst und führt zyklisch folgende Aufgaben aus:

1. **Konfiguration prüfen** – bei Änderung automatisch neu laden (mtime-basiert)
2. **4 Analogkanäle messen** (ADS1115 A0–A3):
   - Spannung → Strom (mA) über Shunt-Widerstand
   - Strom → physikalischer Messwert (linear 4–20 mA)
   - Bei Typ `LEVEL`: Berechnung von Wassertiefe, Wasseroberfläche, NN-Höhe, Pegeldifferenz
3. **BMP280 einlesen** – Luftdruck (hPa) und Temperatur (°C); automatische Neuinitialisierung bei Fehler
4. **Reedkontakte abfragen** – Impulsstand und berechnetes Volumen (Liter) für beide Wasserzähler
5. **SQLite-Queue** – jede Messung wird sofort lokal gepuffert
6. **InfluxDB senden** – Queue wird in Batches (max. 500) gesendet; bei Offline-Betrieb werden Werte akkumuliert und später nachgesendet
7. **`latest_measurement.json` schreiben** – atomarer Write (temp-Datei + rename) für die Web-GUI

**Messintervall:** Konfigurierbar über `MESSINTERVAL` (Standard: 5 Sekunden)

#### `webapp.py` – Webserver

Flask-Anwendung mit:
- **PIN-Login** mit Rate-Limiting (5 Versuche, dann 60 s gesperrt)
- **Konfigurationsverwaltung** – Laden/Speichern von `config.json`, Validierung
- **Messwert-API** – liest `latest_measurement.json` und liefert Daten per JSON
- **Reed-API** – liest `reed_counts.json`, berechnet Liter-Volumina
- **MOSFET-Steuerung** – Kanäle schalten, Zeitpläne verwalten
- **Systemsteuerung** – Dienste neu starten, Log-Anzeige, Systemstatus
- **WiFi-Konfiguration** – schreibt in `wpa_supplicant.conf` (mit Validierung)
- **GitHub-Update** – startet `update_repo.sh` mit Timeout
- **Scheduler-Thread** – prüft jede Minute MOSFET-Zeitpläne

#### `mosfet_control.py` – GPIO-Steuerung

- 6 MOSFET-Ausgänge: GPIO 4, 17, 18, 22, 23, 24
- Thread-sicher via `threading.Lock()`
- Status-Cache für sofortige Rückmeldung
- Initialisierung on-demand (kein separater init-Aufruf nötig)

#### `reed_contact.py` – Reedkontakt-Impulszähler

- Polling-Schleife mit 10 ms Intervall (ausreichend für Wasserzähler)
- 50 ms Entprellzeit (Debouncing)
- Fallende Flanke = 1 Impuls
- **Persistente Speicherung** in `data/reed_counts.json` (alle 30 s + bei jeder Änderung)
- **Zähler-Reset** via Flag-Datei (`data/reed_reset_XX.flag`) – race-condition-frei zwischen Webapp und Logger
- `init(count_file)` – Modul starten
- `get_counts()` – aktuellen Impulsstand lesen
- `reset_count(gpio)` – Zähler zurücksetzen
- `shutdown()` – Thread und GPIO-Chip sauber schließen

#### `display_controller.py` – OLED-Anzeige

- SH1106 OLED (128×64, I²C)
- Zeigt aktuelle Messwerte, Systemstatus und Service-Zustand
- Läuft als separater `systemd`-Dienst (`brunnen_display.service`)

---

## Web-Interface & API

### Seiten

| URL | Seite | Beschreibung |
|-----|-------|-------------|
| `/` | Konfiguration | Alle Konfigurationsparameter bearbeiten |
| `/measurements` | Messwerte | Aktuelle Sensorwerte aller Kanäle (5 s Auto-Refresh) |
| `/barometer` | Barometer | BMP280 Luftdruck und Temperatur |
| `/reed` | Wasserzähler | Reedkontakt-Zählerstände, Liter-Volumen, Reset |
| `/outputs` | Ausgänge | MOSFET-Kanäle schalten, Kanalnamen, Zeitsteuerung |
| `/database` | Datenbank | InfluxDB-Verbindungseinstellungen |
| `/systemstatus` | Systemstatus | CPU, RAM, Disk, Temperatur, IP, WLAN |
| `/service` | Dienste | Logger und Webapp neu starten |
| `/logs` | Logs | Logger- und Webapp-Logs anzeigen, Log-Level setzen |
| `/login` | Login | PIN-Eingabe (Rate-Limiting: 5 Versuche / 60 s) |

### API-Endpunkte

| Methode | URL | Beschreibung |
|--------|-----|-------------|
| GET | `/api/measurements` | Aktuelle Messwerte aller Kanäle als JSON-Array |
| GET | `/api/barometer` | BMP280-Daten als JSON |
| GET | `/api/reed` | Reedkontakt-Zählerstände und Liter als JSON |
| POST | `/reed/reset/<gpio>` | Zähler für GPIO 25 oder 27 zurücksetzen |
| POST | `/update` | Konfiguration speichern |
| POST | `/logs/level` | Log-Level setzen (DEBUG/INFO/WARNING/ERROR/CRITICAL) |
| POST | `/service/action` | Dienst starten/Status abfragen |
| POST | `/outputs/set/<ch>/<state>` | MOSFET-Kanal schalten (0=AUS, 1=EIN) |
| GET | `/outputs/state` | Status aller MOSFET-Kanäle als JSON-Array |
| GET/POST/DELETE | `/outputs/schedule` | Zeitpläne verwalten |
| GET/POST | `/outputs/names` | Kanalnamen lesen/setzen |
| POST | `/wifi/configure` | WLAN-Zugangsdaten konfigurieren |
| POST | `/update-system` | GitHub Auto-Update starten |

### Beispiel API-Antwort `/api/reed`

```json
[
  {
    "gpio": 25,
    "name": "Wasserzähler 1",
    "impulse": 1234,
    "liter": 123.4,
    "liter_pro_impuls": 0.1
  },
  {
    "gpio": 27,
    "name": "Wasserzähler 2",
    "impulse": 567,
    "liter": 56.7,
    "liter_pro_impuls": 0.1
  }
]
```

### Beispiel API-Antwort `/api/measurements`

```json
[
  {
    "channel": "A0",
    "name": "Nordbrunnen",
    "timestamp": "2025-01-01T10:00:00+00:00",
    "type": "LEVEL",
    "unit": "m",
    "current_mA": 12.5,
    "value": 1.5,
    "level_m": 1.5,
    "wasser_oberflaeche_m": 3.5,
    "messwert_NN": 96.5,
    "pegel_diff": -0.5
  }
]
```

---

## Konfigurationsparameter

Alle Parameter werden in `config/config.json` gespeichert und können über das Web-Interface bearbeitet werden. Fehlende Parameter werden beim Start automatisch mit Standardwerten ergänzt.

### Gerät & Standort

| Parameter | Standard | Beschreibung |
|-----------|---------|-------------|
| `DEVICE_ID` | Hostname | Eindeutige Geräte-ID für InfluxDB-Tags (z. B. `pi-brunnen-nord`) |
| `LOCATION` | `""` | Standortbeschreibung (z. B. `Liegenschaft Bachstrasse 12`) |

### Allgemein

| Parameter | Standard | Beschreibung |
|-----------|---------|-------------|
| `MESSINTERVAL` | `5` | Messintervall in Sekunden |
| `ADMIN_PIN` | `1234` | PIN für Web-Login (als Text gespeichert) |
| `LOG_LEVEL` | `ERROR` | Log-Level: DEBUG / INFO / WARNING / ERROR / CRITICAL |

### Sensor-Kanäle (A0–A3)

Jeder Kanal hat eigene Parameter mit Suffix `_A0`, `_A1`, `_A2`, `_A3`:

| Parameter | Beispiel | Beschreibung |
|-----------|---------|-------------|
| `NAME_Ax` | `Nordbrunnen ABC` | Anzeigename des Kanals |
| `SENSOR_TYP_Ax` | `LEVEL` | Sensor-Typ: `LEVEL`, `TEMP`, `FLOW`, `ANALOG` |
| `SENSOR_EINHEIT_Ax` | `m` | Einheit des Messwerts |
| `WERT_4mA_Ax` | `0.0` | Physikalischer Wert bei 4 mA (untere Grenze) |
| `WERT_20mA_Ax` | `3.0` | Physikalischer Wert bei 20 mA (obere Grenze) |
| `SHUNT_OHMS_Ax` | `150.0` | Shunt-Widerstand in Ohm |
| `STARTABSTICH_Ax` | `100.0` | Abstand Gelände → Wasseroberfläche bei Inbetriebnahme (m) |
| `INITIAL_WASSERTIEFE_Ax` | `25.0` | Initiale Wassertiefe bei Inbetriebnahme (m) |
| `MESSWERT_NN_Ax` | `100.0` | Geländehöhe über Normalnull (m ü. NN) |

**Hinweis:** `STARTABSTICH`, `INITIAL_WASSERTIEFE` und `MESSWERT_NN` werden nur für den Sensor-Typ `LEVEL` ausgewertet.

**Berechnungsformeln (Typ LEVEL):**

```
Messwert = WERT_4mA + (Strom_mA - 4) × (WERT_20mA - WERT_4mA) / 16
Wasseroberfläche_m = STARTABSTICH + (INITIAL_WASSERTIEFE - Wassertiefe)
Messwert_NN = MESSWERT_NN - Wasseroberfläche_m
Pegel_Differenz = STARTABSTICH - Wasseroberfläche_m
```

### Barometer (BMP280)

| Parameter | Standard | Beschreibung |
|-----------|---------|-------------|
| `BMP280_ENABLED` | `true` | BMP280 aktivieren / deaktivieren |
| `BMP280_ADDRESS` | `0x76` | I²C-Adresse: `0x76` oder `0x77` |
| `NAME_BMP280` | `Barometer` | Anzeigename |

### Wasserzähler (Reedkontakte)

| Parameter | Standard | Beschreibung |
|-----------|---------|-------------|
| `REED_1_NAME` | `Wasserzähler 1` | Name für GPIO 25 |
| `REED_1_LITER_PRO_IMPULS` | `1.0` | Liter pro Impuls für Zähler 1 (z. B. `0.1` für 1/10 Liter) |
| `REED_2_NAME` | `Wasserzähler 2` | Name für GPIO 27 |
| `REED_2_LITER_PRO_IMPULS` | `1.0` | Liter pro Impuls für Zähler 2 |

### InfluxDB

| Parameter | Standard | Beschreibung |
|-----------|---------|-------------|
| `INFLUX_URL` | `""` | URL der InfluxDB-Instanz (z. B. `http://192.168.1.50:8086`) |
| `INFLUX_TOKEN` | `""` | API-Token (Write-Berechtigung erforderlich) |
| `INFLUX_ORG` | `""` | Organisation in InfluxDB |
| `INFLUX_BUCKET` | `""` | Ziel-Bucket für Messdaten |

---

## Multi-Tenant Setup (Mehrere Kunden)

Das System unterstützt mehrere Kunden mit je eigenen Geräten. Die Trennung erfolgt auf zwei Ebenen:

### InfluxDB: Eine Organisation pro Kunde

```
InfluxDB-Instanz
├── Organisation: "kunde_meier"
│   └── Bucket: "brunnen_messdaten"
│       ├── device_id: "pi-brunnen-nord"
│       └── device_id: "pi-brunnen-sued"
└── Organisation: "kunde_mueller"
    └── Bucket: "brunnen_messdaten"
        └── device_id: "pi-brunnen-1"
```

- Jede Organisation hat einen eigenen API-Token → vollständige Datenisolation
- Der Raspberry Pi bekommt nur den Token für die Organisation seines Kunden

### Grafana: Eine Organisation pro Kunde

- Jeder Kunde bekommt einen eigenen Grafana-Login in seiner Grafana-Organisation
- Dashboards und Datenquellen sind org-isoliert
- Als Admin kann über „Switch Org" zwischen Kunden gewechselt werden

### Konfiguration pro Gerät

Jeder Raspberry Pi muss mit folgenden Werten konfiguriert sein:

| Parameter | Beispiel | Bedeutung |
|-----------|---------|-----------|
| `DEVICE_ID` | `pi-brunnen-nord` | Eindeutige ID des Geräts |
| `LOCATION` | `Bachstrasse 12, Musterstadt` | Physischer Standort |
| `INFLUX_ORG` | `kunde_meier` | Zugehörige InfluxDB-Organisation |
| `INFLUX_TOKEN` | `abc123...` | API-Token dieser Organisation |
| `INFLUX_BUCKET` | `brunnen_messdaten` | Ziel-Bucket |

### Neuen Kunden anlegen (Schritt für Schritt)

```bash
# 1. InfluxDB: Neue Organisation anlegen
#    InfluxDB UI → Organizations → Create Organization → "kunde_xyz"
#    → Bucket anlegen → API-Token generieren (Write-Berechtigung)

# 2. Grafana: Neue Organisation anlegen
#    Grafana → Admin → Organizations → New Org → "Kunde XYZ"
#    → Data Source konfigurieren (InfluxDB, Org "kunde_xyz")
#    → Standard-Dashboard importieren/klonen
#    → Benutzer anlegen

# 3. Raspberry Pi konfigurieren
#    Web-Interface öffnen → Konfiguration
#    DEVICE_ID = "pi-brunnen-kunde-xyz"
#    LOCATION  = "Standort des Brunnens"
#    INFLUX_ORG, INFLUX_TOKEN, INFLUX_BUCKET eintragen
```

---

## InfluxDB & Grafana

### InfluxDB-Datenstruktur

Alle Messungen werden mit folgenden **Tags** versehen:

| Tag | Beispiel | Quelle |
|-----|---------|--------|
| `device_id` | `pi-brunnen-nord` | Konfigurationsparameter `DEVICE_ID` |
| `location` | `Bachstrasse 12` | Konfigurationsparameter `LOCATION` |
| `channel` | `A0`, `BMP280`, `REED1` | Kanalbezeichnung |
| `name` | `Nordbrunnen ABC` | Konfigurierter Kanalname |
| `type` | `LEVEL`, `TEMP`, `FLOW`, `PRESSURE`, `COUNTER` | Sensor-Typ |
| `unit` | `m`, `°C`, `m3/h`, `hPa`, `L` | Einheit |

**Measurements (Tabellen) in InfluxDB:**

| Measurement | Sensor-Typen | Felder |
|------------|-------------|--------|
| `wasserstand` | LEVEL, TEMP, FLOW, COUNTER, ANALOG | `Wassertiefe`, `Startabstich`, `Messwert_NN`, `Pegel_Differenz`, `Strom_in_mA`, `Durchfluss`, `Liter_gesamt`, `Impulse_gesamt` |
| `barometer` | PRESSURE | `Luftdruck_hPa`, `Temperatur` |

### Beispiel Flux-Abfragen (Grafana)

**Wasserstand eines Geräts:**
```flux
from(bucket: "brunnen_messdaten")
  |> range(start: -24h)
  |> filter(fn: (r) => r["_measurement"] == "wasserstand")
  |> filter(fn: (r) => r["device_id"] == "pi-brunnen-nord")
  |> filter(fn: (r) => r["channel"] == "A0")
  |> filter(fn: (r) => r["_field"] == "Wassertiefe")
```

**Wasserzähler (Liter):**
```flux
from(bucket: "brunnen_messdaten")
  |> range(start: -30d)
  |> filter(fn: (r) => r["_measurement"] == "wasserstand")
  |> filter(fn: (r) => r["type"] == "COUNTER")
  |> filter(fn: (r) => r["device_id"] == "pi-brunnen-nord")
  |> filter(fn: (r) => r["_field"] == "Liter_gesamt")
```

**Alle Geräte eines Kunden (über device_id filtern):**
```flux
from(bucket: "brunnen_messdaten")
  |> range(start: -1h)
  |> filter(fn: (r) => r["_measurement"] == "wasserstand")
  |> filter(fn: (r) => r["_field"] == "Wassertiefe")
  |> group(columns: ["device_id", "channel"])
```

---

## Installation

### Voraussetzungen

- Raspberry Pi OS (Bookworm oder Bullseye, 64-Bit empfohlen)
- I²C aktiviert (`raspi-config`)
- Internetzugang beim ersten Start

### Automatische Installation

```bash
# Repository klonen und Installationsskript ausführen (als root)
git clone https://github.com/zulasch/BrunnenWeb /opt/brunnen_web
cd /opt/brunnen_web
sudo bash install.sh
```

Das Installationsskript führt folgende Schritte durch:

1. **Systempakete installieren** – Python, I²C-Tools, SQLite, OpenVPN u. a.
2. **Benutzer anlegen** – `brunnen` (System-User, kein Login)
3. **Gruppen zuweisen** – `i2c`, `gpio`
4. **Sudoers konfigurieren** – nur explizit benötigte Befehle ohne Passwort
5. **Logrotate einrichten** – max. 5 MB, 7 Rotationen
6. **Python-Virtualenv** erstellen und Abhängigkeiten installieren
7. **Beispielkonfiguration** anlegen (wenn noch keine vorhanden)
8. **Systemd-Dienste** erstellen und aktivieren (webapp, logger)
9. **Zufälligen SECRET_KEY** generieren und in den Webapp-Service einbinden
10. **I²C aktivieren** via `raspi-config`
11. **WLAN-Dienste** starten
12. **Dienste starten** und Status anzeigen

### Nach der Installation

Das Web-Interface ist erreichbar unter:
```
http://<IP-Adresse>:8080
```

Standard-PIN: `1234` (sofort ändern unter Konfiguration → ADMIN_PIN!)

### Python-Abhängigkeiten

```
flask
psutil
influxdb-client
adafruit-circuitpython-ads1x15
adafruit-blinka
adafruit-circuitpython-bmp280
RPi.GPIO
gunicorn
lgpio
luma.oled
pillow
```

---

## Dienste verwalten

Das System läuft als drei `systemd`-Dienste:

| Dienst | Datei | Beschreibung |
|--------|-------|-------------|
| `brunnen_web.service` | `webapp.py` via Gunicorn | Webinterface auf Port 8080 |
| `brunnen_logger.service` | `wasserstand_logger.py` | Messdatenerfassung |
| `brunnen_display.service` | `display_controller.py` | OLED-Anzeige |

### Häufige Befehle

```bash
# Status anzeigen
sudo systemctl status brunnen_web.service brunnen_logger.service

# Neu starten
sudo systemctl restart brunnen_web.service brunnen_logger.service

# Logs anzeigen
tail -f /opt/brunnen_web/logs/logger.err.log
tail -f /opt/brunnen_web/logs/webapp.err.log
tail -f /opt/brunnen_web/logs/wasserstand.log

# Dienste aktivieren/deaktivieren
sudo systemctl enable brunnen_web.service brunnen_logger.service
sudo systemctl disable brunnen_web.service brunnen_logger.service
```

### Log-Level zur Laufzeit ändern

Im Web-Interface unter **Logs** kann das Log-Level direkt geändert werden.
Der Logger übernimmt die Einstellung innerhalb weniger Sekunden ohne Neustart.

---

## System-Update via GitHub

### Über das Web-Interface

Im Web-Interface unter **Dienste** → **System aktualisieren** wird das Update gestartet.

### Manuell

```bash
sudo /opt/brunnen_web/scripts/update_repo.sh
```

Das Update-Skript führt folgende Schritte durch:

1. `git reset --hard HEAD` – lokale Änderungen verwerfen
2. `git pull` – neuesten Code laden
3. `pip install -r requirements.txt` – Python-Abhängigkeiten aktualisieren
4. `brunnen_display.service` Systemd-Unit deployen (aus `deploy/systemd/`)
5. `systemctl daemon-reload`
6. Alle drei Dienste neu starten (mit 3 Sekunden Verzögerung)

Das Update-Log wird nach `/opt/brunnen_web/logs/update.log` geschrieben.

---

## Entwicklung: Neue Parameter hinzufügen

Vollständige Anleitung in [docs/config-parameter-management.md](docs/config-parameter-management.md).

**Kurzfassung:**

1. Neuen Key in `DEFAULT_CONFIG` in `webapp.py` und `wasserstand_logger.py` eintragen
2. Falls Text (kein Float): Key zu `string_keys` in `update_config()` in `webapp.py` hinzufügen
3. Beschreibung in `base_descriptions` in der `index()`-Route ergänzen
4. Falls nötig: Abschnitt in `templates/index.html` hinzufügen

Beim nächsten Start wird `config.json` automatisch um den neuen Parameter erweitert.

---

## Sicherheitshinweise

- **ADMIN_PIN** sofort nach Installation ändern (Standard: `1234`)
- **WEBAPP_SECRET** wird bei Installation automatisch zufällig generiert
- **InfluxDB-Tokens** werden in `config.json` im Klartext gespeichert – Dateizugriffsrechte beachten
- Das System ist **nicht für direkten Internetzugang** konzipiert – nur im lokalen Netz oder per VPN betreiben
- **WiFi-Passwörter** dürfen keine Anführungszeichen, Backslashes oder Zeilenumbrüche enthalten

---

## Lizenz

MIT License – siehe [LICENSE](LICENSE)

© 2025 Reber Brunnenbau
