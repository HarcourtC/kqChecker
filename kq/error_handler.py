"""Centralized error handling for api2 400-like responses.

This module provides handle_api400(cfg, api400_error) which will attempt to
send a synchronous alert email, save debug payload/response to disk if present,
log outcomes, and exit the process with a non-zero code.
"""
from pathlib import Path
import json
import logging
import sys
from typing import Any, Dict

from .notifier import send_miss_email


def _save_debug_dump(cfg: Dict[str, Any], context: Dict[str, Any]) -> None:
    try:
        dbg = (cfg.get("debug") or {})
        if not dbg.get("save_missing_response"):
            return
        dump_dir = Path(__file__).parent.parent / (dbg.get("dump_dir") or "debug_responses")
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
    try:
        subj = getattr(api400_error, "subject", None) or "api2 returned error 400"
        body = getattr(api400_error, "body", None) or "api2 returned a 400-like payload"
        context = getattr(api400_error, "context", None) or {}

        # Attempt to persist debug info first (so we have payload/response saved even if mail fails)
        try:
            _save_debug_dump(cfg, context)
        except Exception:
            logging.exception("error while saving debug dump for API400Error")

        # Send synchronously (blocking) so caller can be sure send attempted
        try:
            ok = send_miss_email(cfg, subject=subj, body=body, context=context)
            if ok:
                logging.info("alert_on_400 email sent successfully")
            else:
                logging.warning("alert_on_400 email send returned False")
        except Exception:
            logging.exception("failed to send alert_on_400 email")
    finally:
        logging.info("exiting process due to api2 400 response")
        try:
            sys.exit(1)
        except SystemExit:
            # ensure exit even if caller intercepts
            raise
