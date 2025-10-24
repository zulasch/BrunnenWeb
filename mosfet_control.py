#!/usr/bin/env python3
import logging
import RPi.GPIO as GPIO
import lgpio

chip = lgpio.gpiochip_open(0)
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

def set_output(index, state):
    handle = lgpio.gpiochip_open(0)
    lgpio.gpio_claim_output(handle, CHANNELS[index])
    lgpio.gpio_write(handle, CHANNELS[index], 1 if state else 0)
    lgpio.gpiochip_close(handle)
    
def all_off():
    init_gpio()
    for ch in CHANNELS:
        GPIO.output(ch, GPIO.LOW)

def cleanup():
    GPIO.cleanup()