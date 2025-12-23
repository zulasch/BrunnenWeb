#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Leichter HTTP-Client für den ZTE MF79U, der den bekannten
`goform_get_cmd_process`-Endpunkt ohne Authentifizierung abfragt.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, Optional

import requests

DEFAULT_BASE_URL = "http://192.168.0.1"

# Typische Felder, die der Stick liefert. `traffic_stat` bringt die Counter.
DEFAULT_COMMANDS = [
    "traffic_stat",
    "network_type",
    "network_provider",
    "lte_rsrp",
    "lte_rsrq",
    "lte_snr",
    "wan_ipaddr",
    "ppp_status",
    "signalbar",
]

DEFAULT_HEADERS = {
    "Referer": "http://192.168.0.1/index.html",
    "User-Agent": "Mozilla/5.0",
}


def safe_int(value: Any, default: int = 0) -> int:
    """Konvertiert beliebige Eingaben robust nach int."""
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def pick_first(data: Dict[str, Any], keys: Iterable[str], default: int = 0) -> int:
    """Nimmt den ersten vorhandenen Key und konvertiert zu int."""
    for key in keys:
        if key in data:
            return safe_int(data.get(key), default)
    return default


def normalize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Bringt die verschiedenen Feldnamen des ZTE in ein einheitliches Dict.
    Unbekannte Felder bleiben im `raw` erhalten.
    """
    rx_bytes = pick_first(
        payload,
        ["realtime_rx_bytes", "rx_bytes", "CurrentDownload", "TotalDownload"],
        default=0,
    )
    tx_bytes = pick_first(
        payload,
        ["realtime_tx_bytes", "tx_bytes", "CurrentUpload", "TotalUpload"],
        default=0,
    )
    rx_rate = pick_first(
        payload,
        ["realtime_rx_rate", "rx_rate", "rx_flow", "RealtimeDownloadRate"],
        default=0,
    )
    tx_rate = pick_first(
        payload,
        ["realtime_tx_rate", "tx_rate", "tx_flow", "RealtimeUploadRate"],
        default=0,
    )
    monthly_rx = pick_first(payload, ["monthly_rx_bytes", "month_to_date_rx_bytes"], default=0)
    monthly_tx = pick_first(payload, ["monthly_tx_bytes", "month_to_date_tx_bytes"], default=0)

    session_time_s = pick_first(payload, ["realtime_time", "CurrentConnectTime"], default=0)

    return {
        "rx_bytes": rx_bytes,
        "tx_bytes": tx_bytes,
        "rx_rate_bps": rx_rate,
        "tx_rate_bps": tx_rate,
        "monthly_rx_bytes": monthly_rx,
        "monthly_tx_bytes": monthly_tx,
        "session_time_s": session_time_s,
        "network_type": payload.get("network_type"),
        "network_provider": payload.get("network_provider"),
        "wan_ipaddr": payload.get("wan_ipaddr"),
        "ppp_status": payload.get("ppp_status"),
        "signalbar": payload.get("signalbar"),
        "lte_rsrp": payload.get("lte_rsrp"),
        "lte_rsrq": payload.get("lte_rsrq"),
        "lte_snr": payload.get("lte_snr"),
        "raw": payload,
    }


def fetch_stats(
    base_url: str = DEFAULT_BASE_URL,
    commands: Iterable[str] = DEFAULT_COMMANDS,
    timeout: int = 5,
    session: Optional[requests.Session] = None,
) -> Optional[Dict[str, Any]]:
    """
    Ruft den ZTE-Stick ab und liefert ein normalisiertes Dict mit Countern.
    Gibt None zurück, falls kein JSON oder HTTP-Fehler.
    """
    url = f"{base_url.rstrip('/')}/goform/goform_get_cmd_process"
    params = {
        "isOnline": "true",
        "isTest": "false",
        "cmd": ",".join(commands),
        "multi_data": "1",
    }

    sess = session or requests.Session()

    try:
        resp = sess.get(url, params=params, headers=DEFAULT_HEADERS, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, dict):
            logging.warning("ZTE Antwort ist kein JSON-Objekt: %s", payload)
            return None
        return normalize_payload(payload)
    except (requests.RequestException, json.JSONDecodeError) as exc:
        logging.warning("ZTE-Abfrage fehlgeschlagen: %s", exc)
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    stats = fetch_stats()
    if not stats:
        print("Keine Daten erhalten.")
    else:
        mb = lambda b: round(b / (1024 * 1024), 2)
        print(f"RX: {mb(stats['rx_bytes'])} MB, TX: {mb(stats['tx_bytes'])} MB")
        print(f"RX-Rate: {stats['rx_rate_bps']} bps, TX-Rate: {stats['tx_rate_bps']} bps")
        print(f"Monthly RX: {mb(stats['monthly_rx_bytes'])} MB")
        print(f"Session Time: {stats['session_time_s']} s")
