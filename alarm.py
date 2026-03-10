#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
alarm.py – Email-Alarmierung für das Brunnen-Web-System.

Wird von wasserstand_logger.py (Sensoralarme) und
webapp.py (Output-Alarme) verwendet.
"""

import smtplib, ssl, time, socket
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

_ALARM_COOLDOWN_SECONDS = 3600  # max. 1 Email pro Alarm-Typ pro Stunde


def send_alarm_email(cfg: dict, subject: str, body: str) -> tuple:
    """
    Sendet eine Alarm-Email.
    Gibt (True, "") bei Erfolg oder (False, Fehlermeldung) zurück.
    """
    host = cfg.get("SMTP_HOST", "").strip()
    port = int(cfg.get("SMTP_PORT", 587))
    user = cfg.get("SMTP_USER", "").strip()
    password = cfg.get("SMTP_PASSWORD", "")
    from_addr = cfg.get("SMTP_FROM", "").strip() or user
    to_raw = cfg.get("SMTP_TO", "").strip()
    use_tls = bool(cfg.get("SMTP_TLS", True))

    if not host or not to_raw:
        return False, "SMTP nicht konfiguriert (Host oder Empfänger fehlt)."

    recipients = [r.strip() for r in to_raw.split(",") if r.strip()]
    if not recipients:
        return False, "Kein gültiger Empfänger konfiguriert."

    device_id = cfg.get("DEVICE_ID", socket.gethostname())

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"BrunnenWeb <{from_addr}>"
    msg["To"] = ", ".join(recipients)

    text_body = f"{body}\n\n---\nGeräte-ID: {device_id}\nZeit: {time.strftime('%Y-%m-%d %H:%M:%S')}"
    msg.attach(MIMEText(text_body, "plain", "utf-8"))

    try:
        context = ssl.create_default_context()
        # SSL auf Port 465, STARTTLS sonst
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=context, timeout=15) as s:
                if user:
                    s.login(user, password)
                s.sendmail(from_addr, recipients, msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=15) as s:
                if use_tls:
                    s.starttls(context=context)
                if user:
                    s.login(user, password)
                s.sendmail(from_addr, recipients, msg.as_string())
        return True, ""
    except smtplib.SMTPAuthenticationError:
        return False, "Authentifizierung fehlgeschlagen (Benutzer/Passwort prüfen)."
    except smtplib.SMTPConnectError:
        return False, f"Verbindung zu {host}:{port} fehlgeschlagen."
    except Exception as e:
        return False, str(e)


def smtp_configured(cfg: dict) -> bool:
    return bool(cfg.get("SMTP_HOST") and cfg.get("SMTP_TO"))


def check_and_send(cfg: dict, channel: str, value: float,
                   sensor_name: str, unit: str,
                   last_sent: dict) -> dict:
    """
    Prüft Schwellwerte für einen Kanal und sendet bei Bedarf eine Alarm-Email.

    channel:    z.B. "A0"
    value:      aktueller Messwert
    sensor_name: Anzeigename des Sensors
    unit:       Einheit
    last_sent:  Dict {alarm_key: timestamp} für Rate-Limiting (wird in-place aktualisiert)

    Gibt das aktualisierte last_sent-Dict zurück.
    """
    now = time.time()
    ch = channel.upper()

    if not smtp_configured(cfg):
        return last_sent

    # Min-Alarm
    if cfg.get(f"ALARM_{ch}_MIN_EN"):
        threshold = float(cfg.get(f"ALARM_{ch}_MIN", 0.0))
        key = f"{ch}_min"
        if value < threshold:
            last_time = last_sent.get(key, 0)
            if now - last_time >= _ALARM_COOLDOWN_SECONDS:
                subject = f"[BrunnenWeb] ⚠️ {sensor_name}: Wert unter Minimum"
                body = (f"Sensor: {sensor_name} ({ch})\n"
                        f"Aktueller Wert: {value:.3f} {unit}\n"
                        f"Minimum-Grenze: {threshold:.3f} {unit}")
                ok, _ = send_alarm_email(cfg, subject, body)
                if ok:
                    last_sent[key] = now

    # Max-Alarm
    if cfg.get(f"ALARM_{ch}_MAX_EN"):
        threshold = float(cfg.get(f"ALARM_{ch}_MAX", 0.0))
        key = f"{ch}_max"
        if value > threshold:
            last_time = last_sent.get(key, 0)
            if now - last_time >= _ALARM_COOLDOWN_SECONDS:
                subject = f"[BrunnenWeb] ⚠️ {sensor_name}: Wert über Maximum"
                body = (f"Sensor: {sensor_name} ({ch})\n"
                        f"Aktueller Wert: {value:.3f} {unit}\n"
                        f"Maximum-Grenze: {threshold:.3f} {unit}")
                ok, _ = send_alarm_email(cfg, subject, body)
                if ok:
                    last_sent[key] = now

    return last_sent


def check_sensor_fail(cfg: dict, channel: str, sensor_name: str,
                      fail_counts: dict, last_sent: dict,
                      fail_threshold: int = 3) -> tuple:
    """
    Zählt aufeinanderfolgende Sensor-Fehler. Sendet Alarm nach fail_threshold Fehlern.
    Gibt (fail_counts, last_sent) zurück.
    """
    now = time.time()
    ch = channel.upper()
    fail_counts[ch] = fail_counts.get(ch, 0) + 1

    if not cfg.get("ALARM_SENSOR_FAIL_EN") or not smtp_configured(cfg):
        return fail_counts, last_sent

    if fail_counts[ch] >= fail_threshold:
        key = f"{ch}_fail"
        last_time = last_sent.get(key, 0)
        if now - last_time >= _ALARM_COOLDOWN_SECONDS:
            subject = f"[BrunnenWeb] ❌ Sensorausfall: {sensor_name}"
            body = (f"Sensor: {sensor_name} ({ch})\n"
                    f"Fehler bei {fail_counts[ch]} aufeinanderfolgenden Messungen.")
            ok, _ = send_alarm_email(cfg, subject, body)
            if ok:
                last_sent[key] = now

    return fail_counts, last_sent


def reset_sensor_fail(fail_counts: dict, channel: str) -> dict:
    """Setzt den Fehlerzähler nach einer erfolgreichen Messung zurück."""
    fail_counts[channel.upper()] = 0
    return fail_counts
