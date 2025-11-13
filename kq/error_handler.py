"""Centralized error handling for api2 400-like responses.

This module provides handle_api400(cfg, api400_error) which will attempt to
send a synchronous alert email, save debug payload/response to disk if present,
log outcomes, and exit the process with a non-zero code.
"""

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict

from .notifier import send_miss_email


def _save_debug_dump(cfg: Dict[str, Any], context: Dict[str, Any]) -> None:
    try:
        dbg = cfg.get("debug") or {}
        if not dbg.get("save_missing_response"):
            return
        dump_dir = Path(__file__).parent.parent / (
            dbg.get("dump_dir") or "debug_responses"
        )
        dump_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime

        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        safe_name = f"api2_400_{ts}.json"
        outp = dump_dir / safe_name
        with outp.open("w", encoding="utf-8") as fh:
            json.dump(context, fh, ensure_ascii=False, indent=2)
        logging.info("saved api2 400 debug dump to %s", outp)
    except Exception:
        logging.exception("failed to save api2 400 debug dump")


def handle_api400(cfg: Dict[str, Any], api400_error: Exception) -> None:
    """Handle API400Error: send sync email, save debug info if available, then exit.

    Exits the process with code 1 when finished.
    """
    subj = getattr(api400_error, "subject", None) or "api2 returned error 400"
    body = getattr(api400_error, "body", None) or "api2 returned a 400-like payload"
    context = getattr(api400_error, "context", None) or {}

    # Determine dump dir for saving debug info and for rate-limit state
    try:
        dbg = cfg.get("debug") or {}
        dump_dir = Path(__file__).parent.parent / (
            dbg.get("dump_dir") or "debug_responses"
        )
        dump_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        dump_dir = Path(__file__).parent.parent / "debug_responses"
        dump_dir.mkdir(parents=True, exist_ok=True)

    # Rate-limit repeated alert emails: check last alert timestamp file
    try:
        notifs = cfg.get("notifications") or {}
        rate_seconds = int(notifs.get("alert_400_rate_seconds", 3600))
    except Exception:
        rate_seconds = 3600

    last_file = dump_dir / "last_api2_400_alert.txt"
    send_allowed = True
    try:
        if last_file.exists():
            try:
                last_ts = float(last_file.read_text(encoding="utf-8").strip())
            except Exception:
                last_ts = 0.0
            import time

            if time.time() - last_ts < rate_seconds:
                send_allowed = False
    except Exception:
        logging.debug("failed to read last alert timestamp; proceeding to send")

    # Attempt to persist debug info first (so we have payload/response saved even if mail fails)
    try:
        _save_debug_dump(cfg, context)
    except Exception:
        logging.exception("error while saving debug dump for API400Error")

    # Send synchronously (blocking) if allowed
    if send_allowed:
        try:
            ok = send_miss_email(cfg, subject=subj, body=body, context=context)
            if ok:
                logging.info("alert_on_400 email sent successfully")
                try:
                    import time

                    last_file.write_text(str(time.time()), encoding="utf-8")
                except Exception:
                    logging.debug("failed to write last alert timestamp")
            else:
                logging.warning("alert_on_400 email send returned False")
        except Exception:
            logging.exception("failed to send alert_on_400 email")
    else:
        logging.info("skipping alert_on_400 email because last alert was sent recently")

    # Do not exit the process here; let caller or external supervisor decide restart policy.
    logging.info("handle_api400 completed (no process exit).")
    # Create a sentinel file to indicate a manual intervention is recommended.
    try:
        sentinel = dump_dir / "stop_requested.json"
        import json as _json
        import time

        payload = {
            "when": __import__("time").ctime(),
            "timestamp": __import__("time").time(),
            "reason": "api2 returned code 400 repeatedly; manual intervention recommended",
            "subject": subj,
        }
        try:
            sentinel.write_text(
                _json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logging.info(
                "wrote sentinel file to %s; external supervisor should avoid auto-restart",
                sentinel,
            )
        except Exception:
            logging.exception("failed to write sentinel file %s", sentinel)
    except Exception:
        logging.debug("failed creating stop sentinel (non-fatal)")
