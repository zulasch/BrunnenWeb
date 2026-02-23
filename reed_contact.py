#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reedkontakt-Modul: Zählt Impulse auf GPIO 25 und GPIO 27.
Jeder Impuls (fallende Flanke) entspricht einer konfigurierbaren Liter-Menge.
Zählerstände werden persistent in einer JSON-Datei gespeichert.
"""

import lgpio
import threading
import json
import os
import logging
import time

REED_GPIOS = [25, 27]        # GPIO-Pins der Reedkontakte
DEBOUNCE_S = 0.05            # 50 ms Entprellzeit
POLL_INTERVAL_S = 0.01       # 10 ms Abfrageintervall
SAVE_INTERVAL_S = 30.0       # Automatische Speicherung alle 30 s

_chip = None
_counts: dict = {}
_lock = threading.Lock()
_last_pulse: dict = {}
_prev_state: dict = {}
_running = False
_thread = None
_count_file: str = None


def _load_counts(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path) as f:
                return {int(k): int(v) for k, v in json.load(f).items()}
        except Exception as e:
            logging.warning(f"Reed: Zählerstand konnte nicht geladen werden: {e}")
    return {g: 0 for g in REED_GPIOS}


def _save_counts(path: str):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump({str(k): v for k, v in _counts.items()}, f)
    os.replace(tmp, path)


def _check_reset_flags():
    """Prüft ob ein Reset-Flag für einen GPIO gesetzt wurde (von der Webapp)."""
    if not _count_file:
        return
    data_dir = os.path.dirname(_count_file)
    for gpio in REED_GPIOS:
        flag = os.path.join(data_dir, f"reed_reset_{gpio}.flag")
        if os.path.exists(flag):
            try:
                os.remove(flag)
                with _lock:
                    _counts[gpio] = 0
                    _save_counts(_count_file)
                logging.info(f"Reed GPIO{gpio}: Zähler zurückgesetzt")
            except Exception as e:
                logging.warning(f"Reed: Reset-Fehler GPIO{gpio}: {e}")


def _poll_loop():
    last_save = time.time()
    while _running:
        now = time.time()
        changed = False

        # Reset-Flags prüfen
        _check_reset_flags()

        # GPIO-Flanken erkennen
        for gpio in REED_GPIOS:
            try:
                level = lgpio.gpio_read(_chip, gpio)
                prev = _prev_state.get(gpio, 1)
                if prev == 1 and level == 0:  # fallende Flanke = Kontakt geschlossen
                    with _lock:
                        if now - _last_pulse.get(gpio, 0.0) >= DEBOUNCE_S:
                            _last_pulse[gpio] = now
                            _counts[gpio] = _counts.get(gpio, 0) + 1
                            changed = True
                            logging.debug(f"Reed GPIO{gpio}: Impuls #{_counts[gpio]}")
                _prev_state[gpio] = level
            except Exception as e:
                logging.warning(f"Reed: Lesefehler GPIO{gpio}: {e}")

        # Periodisch oder bei Änderung speichern
        if (changed or now - last_save >= SAVE_INTERVAL_S) and _count_file:
            with _lock:
                try:
                    _save_counts(_count_file)
                except Exception as e:
                    logging.warning(f"Reed: Speicherfehler: {e}")
            last_save = now

        time.sleep(POLL_INTERVAL_S)


def init(count_file: str):
    """Initialisiert das Reed-Modul. Muss einmalig beim Start aufgerufen werden."""
    global _chip, _counts, _prev_state, _running, _thread, _count_file
    _count_file = count_file

    # Persistierte Zählerstände laden
    loaded = _load_counts(count_file)
    with _lock:
        for g in REED_GPIOS:
            _counts[g] = loaded.get(g, 0)

    # GPIO-Chip öffnen und Eingänge konfigurieren
    try:
        _chip = lgpio.gpiochip_open(0)
        for gpio in REED_GPIOS:
            lgpio.gpio_claim_input(_chip, gpio, lgpio.SET_PULL_UP)
            _prev_state[gpio] = lgpio.gpio_read(_chip, gpio)
    except Exception as e:
        logging.error(f"Reed: GPIO-Initialisierung fehlgeschlagen: {e}")
        return

    _running = True
    _thread = threading.Thread(target=_poll_loop, daemon=True, name="reed-poll")
    _thread.start()
    logging.info(f"Reed-Kontakt-Modul gestartet (GPIO {REED_GPIOS}), "
                 f"Zählerstände: {dict(_counts)}")


def get_counts() -> dict:
    """Gibt aktuellen Impulsstand je GPIO zurück: {gpio: count}"""
    with _lock:
        return dict(_counts)


def reset_count(gpio: int):
    """Setzt Impulszähler für den angegebenen GPIO auf 0 zurück."""
    with _lock:
        _counts[gpio] = 0
        if _count_file:
            try:
                _save_counts(_count_file)
            except Exception as e:
                logging.warning(f"Reed: Reset-Speicherfehler: {e}")


def shutdown():
    """Stoppt den Poll-Thread und schließt den GPIO-Chip."""
    global _running
    _running = False
    if _chip is not None:
        try:
            lgpio.gpiochip_close(_chip)
        except Exception:
            pass
