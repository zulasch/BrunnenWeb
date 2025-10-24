#!/usr/bin/env python3
import RPi.GPIO as GPIO
import time

# BCM-Nummern
CHANNELS = [17, 18, 27, 22, 23, 24, 25, 4]

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

# Alle Ausgänge initialisieren
for ch in CHANNELS:
    GPIO.setup(ch, GPIO.OUT)
    GPIO.output(ch, GPIO.LOW)

def set_output(channel_index, state):
    """channel_index: 0–7, state: True/False"""
    if 0 <= channel_index < len(CHANNELS):
        GPIO.output(CHANNELS[channel_index], GPIO.HIGH if state else GPIO.LOW)

def all_off():
    for ch in CHANNELS:
        GPIO.output(ch, GPIO.LOW)

def test_sequence():
    print("Starte Test...")
    for i, ch in enumerate(CHANNELS):
        print(f" Kanal {i+1} AN")
        GPIO.output(ch, GPIO.HIGH)
        time.sleep(0.5)
        GPIO.output(ch, GPIO.LOW)
    print("Test abgeschlossen.")

if __name__ == "__main__":
    try:
        test_sequence()
    except KeyboardInterrupt:
        all_off()
        GPIO.cleanup()
