# Konfigurationsparameter verwalten

Dieses Dokument beschreibt, wie das Konfigurationssystem von BrunnenWeb funktioniert und wie neue Parameter hinzugefügt werden.

---

## Wie das Konfigurationssystem funktioniert

### Datei: `config/config.json`

Die aktive Konfiguration wird in `config/config.json` gespeichert. Diese Datei wird:
- Beim Start von Logger und Webapp automatisch geladen
- Bei Änderungen vom Logger automatisch neu eingelesen (innerhalb eines Messzyklus)
- Automatisch mit Standardwerten ergänzt, wenn ein Parameter fehlt
- Über das Web-Interface unter **Konfiguration** bearbeitet

### `DEFAULT_CONFIG` – Standardwerte

Beide Hauptdateien (`webapp.py` und `wasserstand_logger.py`) definieren ein `DEFAULT_CONFIG`-Dictionary. Beim Start prüft `load_config()`:
1. Welche Keys in `config.json` fehlen
2. Diese werden aus `DEFAULT_CONFIG` ergänzt
3. Die ergänzte Datei wird zurückgeschrieben
4. Unbekannte Keys (außer `NAME_*`-Prefixe) werden entfernt

### Konfiguration zur Laufzeit neu laden

Der Logger (`wasserstand_logger.py`) prüft bei jedem Messzyklus, ob sich die `mtime` der `config.json` geändert hat. Bei einer Änderung wird die Konfiguration neu geladen, ohne dass ein Neustart nötig ist.

Die Webapp schreibt nach dem Speichern eine Flag-Datei (`data/config_update.flag`), die dem Logger signalisiert, dass eine Aktualisierung vorliegt.

---

## Neuen Parameter hinzufügen

### Schritt 1 – Key benennen

Konvention:
- Kanal-spezifische Parameter: `PARAMETER_NAME_Ax` (z. B. `ALARM_MAX_TEMP_A1`)
- Globale Parameter: `PARAMETER_NAME` (z. B. `MQTT_BROKER`)
- Reed-spezifisch: `REED_1_PARAMETER` / `REED_2_PARAMETER`

### Schritt 2 – In `DEFAULT_CONFIG` eintragen

**In `webapp.py`** (im Block am Anfang der Datei):

```python
DEFAULT_CONFIG = {
    ...
    "MEIN_NEUER_PARAMETER": 42.0,  # Standardwert
    ...
}
```

**In `wasserstand_logger.py`** (im gleichen Block):

```python
DEFAULT_CONFIG = {
    ...
    "MEIN_NEUER_PARAMETER": 42.0,
    ...
}
```

**Wichtig:** Beide Dateien müssen denselben Default-Wert haben.

### Schritt 3 – Typ festlegen

Standardmäßig werden alle Parameter als `float` gespeichert, wenn sie numerisch sind.

Für **Text-Parameter** (z. B. Namen, URLs): Key zu `string_keys` in `update_config()` in `webapp.py` hinzufügen:

```python
string_keys = ["ADMIN_PIN", "WEB_USER", "WEB_PASS", "DEVICE_ID", "LOCATION",
               "REED_1_NAME", "REED_2_NAME",
               "MEIN_TEXT_PARAMETER"]  # ← hier eintragen
```

Für **Boolean-Parameter**: Key muss auf `_ENABLED` enden, oder in `bool_keys` aufgenommen werden:

```python
bool_keys = set(["BMP280_ENABLED"] + [k for k in cfg.keys() if k.endswith("_ENABLED")])
```

### Schritt 4 – Beschreibung für Web-GUI

In `webapp.py`, in der `index()`-Route, `base_descriptions` ergänzen:

```python
base_descriptions = {
    ...
    "MEIN_NEUER_PARAMETER": "Beschreibung, die unter dem Feld angezeigt wird.",
    ...
}
```

### Schritt 5 – Web-GUI Feld hinzufügen (optional)

Wenn der Parameter im bestehenden Konfigurationsbereich angezeigt werden soll, ist nichts weiter nötig – er erscheint automatisch im Kanal-Block, wenn er mit `_A0` bis `_A3` endet.

Für einen neuen globalen Parameter: in `templates/index.html` einen passenden Abschnitt ergänzen. Beispiel für einen neuen Block:

```html
<!-- Mein neuer Bereich -->
<div class="bg-white p-6 rounded-xl shadow mb-6">
  <h2 class="text-xl font-bold mb-4">🔧 Mein neuer Bereich</h2>
  <div class="mb-4">
    <label class="block font-semibold text-gray-700 mb-1">MEIN_NEUER_PARAMETER</label>
    <input name="MEIN_NEUER_PARAMETER"
           value="{{ config.get('MEIN_NEUER_PARAMETER', '') }}"
           class="border p-2 w-full rounded focus:ring-2 focus:ring-blue-400 outline-none" />
    <p class="text-gray-500 text-sm mt-1">{{ descriptions.get("MEIN_NEUER_PARAMETER") }}</p>
  </div>
</div>
```

### Schritt 6 – Parameter im Logger verwenden

In `wasserstand_logger.py` den Parameter aus der aktuellen Konfiguration lesen:

```python
# In der Hauptschleife (config ist das aktuell geladene Dict):
mein_wert = float(cfg.get("MEIN_NEUER_PARAMETER", 42.0))
```

Wenn der Parameter in `reload_config_if_changed()` als Modul-Variable verfügbar sein soll:

```python
# 1. Modul-Variable deklarieren
MEIN_NEUER_PARAMETER = config.get("MEIN_NEUER_PARAMETER", 42.0)

# 2. In reload_config_if_changed() global deklarieren und aktualisieren
def reload_config_if_changed():
    global MEIN_NEUER_PARAMETER
    ...
    MEIN_NEUER_PARAMETER = config.get("MEIN_NEUER_PARAMETER", MEIN_NEUER_PARAMETER)
```

### Schritt 7 – Aktivieren

```bash
# Dienste neu starten (oder über Web-Interface → Dienste)
sudo systemctl restart brunnen_web.service brunnen_logger.service
```

Beim nächsten Start wird `config.json` automatisch um den neuen Parameter mit dem Standardwert ergänzt.

---

## Kanal-spezifische Parameter

Kanal-spezifische Parameter enden immer auf `_A0`, `_A1`, `_A2` oder `_A3`. Sie werden im Kanal-Block der Konfigurationsseite automatisch angezeigt.

**Beispiel für alle 4 Kanäle gleichzeitig definieren:**

```python
for ch in ["A0", "A1", "A2", "A3"]:
    DEFAULT_CONFIG.setdefault(f"ALARM_MAX_{ch}", 100.0)
    DEFAULT_CONFIG.setdefault(f"ALARM_MIN_{ch}", 0.0)
```

Im Logger dann pro Kanal:
```python
alarm_max = float(cfg.get(f"ALARM_MAX_{ch_name}", 100.0))
alarm_min = float(cfg.get(f"ALARM_MIN_{ch_name}", 0.0))
```

---

## Vollständige Parameterliste

Eine vollständige, aktuelle Parameterliste ist in der [README.md](../README.md#konfigurationsparameter) zu finden.

---

## Bekannte Einschränkungen

- `config.json` erlaubt nur Keys, die entweder in `DEFAULT_CONFIG` stehen oder mit `NAME_` beginnen. Alle anderen Keys werden beim nächsten Laden entfernt.
- Boolean-Werte werden intern als Python-`bool` gespeichert, in JSON aber als `true`/`false`.
- `BMP280_ADDRESS` wird als Integer (Hex) gespeichert und muss in der Form `0x76` oder `118` angegeben werden.
- Die Webapp führt keine tiefe Typvalidierung für alle Parameter durch. Kritische Werte (z. B. `MESSINTERVAL`, `BMP280_ADDRESS`) werden explizit geprüft.
