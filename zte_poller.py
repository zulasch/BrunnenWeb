#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Poller, der den ZTE MF79U periodisch abfragt, die Counter in SQLite speichert
und Nutzungs-Aggregate (Tag/Woche/Zyklus) berechnet.
"""

from __future__ import annotations

import calendar
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

from zte_client import DEFAULT_BASE_URL, fetch_stats, safe_int

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config", "config.json")
DB_PATH = os.path.join(BASE_DIR, "data", "offline_cache.db")
LOGFILE = os.path.join(BASE_DIR, "logs", "zte_poller.log")
SUMMARY_FILE = os.path.join(BASE_DIR, "data", "zte_traffic_summary.json")
LATEST_FILE = os.path.join(BASE_DIR, "data", "zte_latest.json")

DEFAULT_CONFIG = {
    "MODEM_URL": DEFAULT_BASE_URL,
    "MODEM_POLL_INTERVAL": 300,  # Sekunden
    "DATA_CYCLE_START": 1,       # Tag im Monat (1-28)
}


def ensure_dirs():
    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)


def load_config() -> Dict[str, Any]:
    cfg: Dict[str, Any] = {}
    changed = False

    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                cfg = json.load(f)
        except Exception as exc:
            logging.warning("Konnte config.json nicht lesen: %s", exc)

    for key, val in DEFAULT_CONFIG.items():
        if key not in cfg:
            cfg[key] = val
            changed = True

    if changed:
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            with open(CONFIG_PATH, "w") as f:
                json.dump(cfg, f, indent=2)
            logging.info("config.json mit neuen Defaults ergänzt.")
        except Exception as exc:
            logging.warning("Konnte config.json nicht schreiben: %s", exc)

    return cfg


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS modem_traffic (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            rx_bytes INTEGER NOT NULL,
            tx_bytes INTEGER NOT NULL,
            rx_rate_bps INTEGER,
            tx_rate_bps INTEGER,
            monthly_rx_bytes INTEGER,
            monthly_tx_bytes INTEGER,
            session_time_s INTEGER,
            reset_flag INTEGER DEFAULT 0,
            network_type TEXT,
            network_provider TEXT,
            wan_ipaddr TEXT,
            ppp_status TEXT,
            signalbar TEXT,
            lte_rsrp TEXT,
            lte_rsrq TEXT,
            lte_snr TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_modem_traffic_ts ON modem_traffic(ts)")
    conn.commit()


def store_sample(conn: sqlite3.Connection, ts: int, stats: Dict[str, Any], reset_flag: int) -> None:
    conn.execute(
        """
        INSERT INTO modem_traffic (
            ts, rx_bytes, tx_bytes, rx_rate_bps, tx_rate_bps,
            monthly_rx_bytes, monthly_tx_bytes, session_time_s, reset_flag,
            network_type, network_provider, wan_ipaddr, ppp_status,
            signalbar, lte_rsrp, lte_rsrq, lte_snr
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ts,
            safe_int(stats.get("rx_bytes"), 0),
            safe_int(stats.get("tx_bytes"), 0),
            safe_int(stats.get("rx_rate_bps"), 0),
            safe_int(stats.get("tx_rate_bps"), 0),
            safe_int(stats.get("monthly_rx_bytes"), 0),
            safe_int(stats.get("monthly_tx_bytes"), 0),
            safe_int(stats.get("session_time_s"), 0),
            reset_flag,
            stats.get("network_type"),
            stats.get("network_provider"),
            stats.get("wan_ipaddr"),
            stats.get("ppp_status"),
            stats.get("signalbar"),
            stats.get("lte_rsrp"),
            stats.get("lte_rsrq"),
            stats.get("lte_snr"),
        ),
    )
    conn.commit()


def fetch_samples(conn: sqlite3.Connection, days: int = 90) -> List[Dict[str, Any]]:
    cutoff = int(time.time()) - days * 86400
    rows = conn.execute(
        """
        SELECT ts, rx_bytes, tx_bytes, rx_rate_bps, tx_rate_bps,
               monthly_rx_bytes, monthly_tx_bytes, session_time_s, reset_flag,
               network_type, network_provider, wan_ipaddr, ppp_status,
               signalbar, lte_rsrp, lte_rsrq, lte_snr
        FROM modem_traffic
        WHERE ts >= ?
        ORDER BY ts ASC
        """,
        (cutoff,),
    ).fetchall()

    keys = [
        "ts",
        "rx_bytes",
        "tx_bytes",
        "rx_rate_bps",
        "tx_rate_bps",
        "monthly_rx_bytes",
        "monthly_tx_bytes",
        "session_time_s",
        "reset_flag",
        "network_type",
        "network_provider",
        "wan_ipaddr",
        "ppp_status",
        "signalbar",
        "lte_rsrp",
        "lte_rsrq",
        "lte_snr",
    ]
    return [dict(zip(keys, row)) for row in rows]


def adjusted_samples(samples: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Hebt Counter-Resets auf, indem wir den Laufenden Offset addieren."""
    out: List[Dict[str, Any]] = []
    offset = 0
    prev_total: Optional[int] = None

    for entry in samples:
        total = safe_int(entry.get("rx_bytes"), 0) + safe_int(entry.get("tx_bytes"), 0)
        if prev_total is not None and total < prev_total:
            offset += prev_total
        adjusted_total = offset + total
        merged = dict(entry)
        merged["total_bytes"] = total
        merged["adjusted_total"] = adjusted_total
        out.append(merged)
        prev_total = total
    return out


def daily_history(adjusted: Sequence[Dict[str, Any]], days: int = 14) -> List[Dict[str, Any]]:
    by_day: Dict[str, Dict[str, int]] = {}
    for entry in adjusted:
        day = datetime.fromtimestamp(entry["ts"]).date().isoformat()
        stats = by_day.setdefault(day, {"min": entry["adjusted_total"], "max": entry["adjusted_total"]})
        stats["min"] = min(stats["min"], entry["adjusted_total"])
        stats["max"] = max(stats["max"], entry["adjusted_total"])

    history = []
    for day, stats in by_day.items():
        history.append({"day": day, "bytes": max(0, stats["max"] - stats["min"])})

    history.sort(key=lambda x: x["day"], reverse=True)
    return history[:days]


def window_usage(adjusted: Sequence[Dict[str, Any]], start_ts: int, end_ts: int) -> int:
    window = [e for e in adjusted if start_ts <= e["ts"] < end_ts]
    if len(window) < 2:
        return 0
    min_total = min(e["adjusted_total"] for e in window)
    max_total = max(e["adjusted_total"] for e in window)
    return max(0, max_total - min_total)


def cycle_window(cycle_day: int, now: Optional[datetime] = None) -> (int, int):
    now = now or datetime.now()
    cycle_day = min(max(int(cycle_day or 1), 1), 28)

    if now.day >= cycle_day:
        start = now.replace(day=cycle_day, hour=0, minute=0, second=0, microsecond=0)
    else:
        # Vormonat
        year = now.year if now.month > 1 else now.year - 1
        month = now.month - 1 if now.month > 1 else 12
        last_day_prev = calendar.monthrange(year, month)[1]
        start = datetime(year=year, month=month, day=min(cycle_day, last_day_prev))
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)

    # Ende = Start + 1 Monat
    end_year = start.year if start.month < 12 else start.year + 1
    end_month = start.month + 1 if start.month < 12 else 1
    last_day_end = calendar.monthrange(end_year, end_month)[1]
    end = datetime(year=end_year, month=end_month, day=min(cycle_day, last_day_end))
    end = end.replace(hour=0, minute=0, second=0, microsecond=0)

    return int(start.timestamp()), int(end.timestamp())


def build_summary(conn: sqlite3.Connection, cycle_start_day: int, poll_interval: int) -> Dict[str, Any]:
    samples = fetch_samples(conn, days=90)
    if not samples:
        return {
            "online": False,
            "last_poll": None,
            "today_bytes": 0,
            "week_bytes": 0,
            "cycle_bytes": 0,
            "history": [],
            "latest": {},
        }

    adjusted = adjusted_samples(samples)
    now = datetime.now()
    start_today = int(datetime(now.year, now.month, now.day).timestamp())
    start_week = int((datetime(now.year, now.month, now.day) - timedelta(days=6)).timestamp())
    today_bytes = window_usage(adjusted, start_today, int(time.time()) + 1)
    week_bytes = window_usage(adjusted, start_week, int(time.time()) + 1)

    cycle_start_ts, cycle_end_ts = cycle_window(cycle_start_day, now)
    cycle_bytes = window_usage(adjusted, cycle_start_ts, cycle_end_ts)

    hist = daily_history(adjusted, days=14)
    latest = samples[-1]

    online = (int(time.time()) - latest["ts"]) < max(poll_interval * 2, 30)

    return {
        "online": online,
        "last_poll": latest["ts"],
        "today_bytes": today_bytes,
        "week_bytes": week_bytes,
        "cycle_bytes": cycle_bytes,
        "history": hist,
        "latest": latest,
    }


def write_json(path: str, data: Any) -> None:
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as exc:
        logging.warning("Konnte %s nicht schreiben: %s", path, exc)


def poll_loop() -> None:
    ensure_dirs()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(LOGFILE), logging.StreamHandler()],
    )

    cfg = load_config()
    poll_interval = max(30, int(cfg.get("MODEM_POLL_INTERVAL", 300)))
    modem_url = cfg.get("MODEM_URL", DEFAULT_BASE_URL)
    cycle_start_day = int(cfg.get("DATA_CYCLE_START", 1))

    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    init_db(conn)

    last_total: Optional[int] = None

    logging.info("Starte ZTE-Poller: URL=%s, Intervall=%ss, Zyklus-Starttag=%s", modem_url, poll_interval, cycle_start_day)

    try:
        while True:
            cfg = load_config()
            poll_interval = max(30, int(cfg.get("MODEM_POLL_INTERVAL", poll_interval)))
            modem_url = cfg.get("MODEM_URL", modem_url)
            cycle_start_day = int(cfg.get("DATA_CYCLE_START", cycle_start_day))

            stats = fetch_stats(base_url=modem_url)
            ts = int(time.time())

            if not stats:
                logging.warning("Keine Daten vom Modem.")
                summary = build_summary(conn, cycle_start_day, poll_interval)
                summary["online"] = False
                summary["last_poll"] = ts
                write_json(SUMMARY_FILE, summary)
                time.sleep(poll_interval)
                continue

            total = safe_int(stats.get("rx_bytes"), 0) + safe_int(stats.get("tx_bytes"), 0)
            reset_flag = 1 if (last_total is not None and total < last_total) else 0
            last_total = total

            store_sample(conn, ts, stats, reset_flag)

            # Für UI/API: letzte Rohdaten separat ablegen
            write_json(LATEST_FILE, {"ts": ts, "stats": stats})

            summary = build_summary(conn, cycle_start_day, poll_interval)
            write_json(SUMMARY_FILE, summary)

            logging.info(
                "Poll OK | RX %.2f MB, TX %.2f MB, heute %.2f MB",
                total / (1024 * 1024),
                safe_int(stats.get("tx_bytes"), 0) / (1024 * 1024),
                summary.get("today_bytes", 0) / (1024 * 1024),
            )

            time.sleep(poll_interval)
    except KeyboardInterrupt:
        logging.info("Poller beendet (KeyboardInterrupt).")
    finally:
        conn.close()


if __name__ == "__main__":
    poll_loop()
