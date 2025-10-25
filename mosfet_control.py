#!/usr/bin/env python3
import logging
import lgpio
import threading
_gpio_lock = threading.Lock()

# Alle verwendeten GPIO-Kanäle
CHANNELS = [4, 17, 18, 27, 22, 23, 24, 25]

# Globale Variablen
chip = None
_handles = {}
_state = {i: False for i in range(len(CHANNELS))}


def init_gpio():
    """Initialisiert alle GPIOs als Ausgänge."""
    global chip
    if chip is None:
        chip = lgpio.gpiochip_open(0)

    for i, ch in enumerate(CHANNELS):
        try:
            if ch not in _handles:
                handle = lgpio.gpio_claim_output(chip, ch)
                _handles[ch] = handle
                lgpio.gpio_write(chip, ch, 0)
                _state[i] = False
        except Exception as e:
            logging.error(f"Fehler beim Initialisieren von GPIO {ch}: {e}")


def set_output(index: int, state: bool):
    """Setzt den angegebenen Kanal auf HIGH oder LOW (thread-safe)."""
    global chip
    if chip is None:
        chip = lgpio.gpiochip_open(0)

    ch = CHANNELS[index]

    with _gpio_lock:
        if ch not in _handles:
            try:
                handle = lgpio.gpio_claim_output(chip, ch)
                _handles[ch] = handle
            except Exception as e:
                logging.error(f"GPIO {ch} konnte nicht reserviert werden: {e}")
                return

        try:
            lgpio.gpio_write(chip, ch, 1 if state else 0)
            _state[index] = state
        except Exception as e:
            logging.error(f"Fehler beim Setzen von Ausgang {index}: {e}")


def get_state():
    """Gibt aktuellen Status aller Kanäle zurück (aus Cache)."""
    try:
        if not _state:
            return {i: False for i in range(len(CHANNELS))}
        return _state
    except Exception as e:
        logging.error(f"Fehler in get_state(): {e}")
        return {i: False for i in range(len(CHANNELS))}
