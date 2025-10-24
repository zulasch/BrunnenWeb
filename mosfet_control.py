#!/usr/bin/env python3
import RPi.GPIO as GPIO

CHANNELS = [17, 18, 27, 22, 23, 24, 25, 4]
_initialized = False

def init_gpio():
    global _initialized
    if not _initialized:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        for ch in CHANNELS:
            GPIO.setup(ch, GPIO.OUT)
            GPIO.output(ch, GPIO.LOW)
        _initialized = True

def set_output(channel_index, state):
    init_gpio()
    if 0 <= channel_index < len(CHANNELS):
        GPIO.output(CHANNELS[channel_index], GPIO.HIGH if state else GPIO.LOW)

def all_off():
    init_gpio()
    for ch in CHANNELS:
        GPIO.output(ch, GPIO.LOW)

def cleanup():
    GPIO.cleanup()