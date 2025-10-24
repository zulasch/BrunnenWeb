#!/usr/bin/env python3
import logging
import RPi.GPIO as GPIO
import lgpio

chip = lgpio.gpiochip_open(0)
CHANNELS = [17, 18, 27, 22, 23, 24, 25, 4]
_initialized = False
_state = {i: False for i in range(len(CHANNELS))}

def init_gpio():
    global _initialized
    if not _initialized:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        for ch in CHANNELS:
            GPIO.setup(ch, GPIO.OUT)
            GPIO.output(ch, GPIO.LOW)
        _initialized = True

def set_output(index, state):
    handle = lgpio.gpiochip_open(0)
    lgpio.gpio_claim_output(handle, CHANNELS[index])
    lgpio.gpio_write(handle, CHANNELS[index], 1 if state else 0)
    lgpio.gpiochip_close(handle)

def get_state():
    """Gibt den aktuellen Zustand aller Kanäle zurück (auch im Simulationsmodus)."""
    init_gpio()
    if HARDWARE_AVAILABLE:
        try:
            for i, ch in enumerate(CHANNELS):
                _state[i] = bool(GPIO.input(ch))
        except Exception as e:
            logging.error(f"GPIO-Abfrage fehlgeschlagen: {e}")
            globals()["HARDWARE_AVAILABLE"] = False
    return _state

    
def all_off():
    init_gpio()
    for ch in CHANNELS:
        GPIO.output(ch, GPIO.LOW)

def cleanup():
    GPIO.cleanup()