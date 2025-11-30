➕ Neue Parameter hinzufügen
Schritt 1 – Key definieren (Beispiel)
ALARM_MAX_TEMP_A1

Schritt 2 – In DEFAULT_CONFIG in Webapp und Logger eintragen

Datei:
/opt/brunnen_web/webapp.py:

etwa ab Zeile 25
DEFAULT_CONFIG.setdefault("ALARM_MAX_TEMP_A1", 60.0)

Datei:
/opt/brunnen_web/wasserstand_logger.py:

etwa ab Zeile 40
DEFAULT_CONFIG.setdefault("ALARM_MAX_TEMP_A1", 60.0)

Datei 
/opt/brunnen_web/config/config.template.json
ergänzen
"ALARM_MAX_TEMP_A1": 60.0


Optional in Web-GUI beschreiben
(Im base_descriptions in webapp.py)

"ALARM_MAX_TEMP_A1": "Maximal erlaubte Temperatur für Kanal A1."


Beim nächsten Neustart: config.json wird automatisch ergänzt.

git pull
sudo systemctl restart brunnen_web.service
sudo systemctl restart brunnen_logger.service
