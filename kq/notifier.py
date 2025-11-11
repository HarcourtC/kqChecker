"""Simple SMTP notifier used to send alerts when attendance matching fails."""
from typing import Dict, Any, List, Optional
import logging
import smtplib
from email.message import EmailMessage


def _load_smtp_config(cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    smtp = cfg.get("smtp") or cfg.get("email")
    if not smtp or not isinstance(smtp, dict):
        return None
    # required: host, port, from, to
    return smtp


def send_miss_email(cfg: Dict[str, Any], subject: str, body: str) -> bool:
    """Send a simple notification using SMTP config from cfg.

    Returns True on success, False otherwise. If no smtp config found, returns False silently.
    """
    smtp_cfg = _load_smtp_config(cfg)
    if not smtp_cfg:
        logging.debug("no smtp config found in config.json; skipping email notification")
        return False

    host = smtp_cfg.get("host")
    port = int(smtp_cfg.get("port", 587))
    username = smtp_cfg.get("username")
    password = smtp_cfg.get("password")
    from_addr = smtp_cfg.get("from") or smtp_cfg.get("sender")
    to_addrs = smtp_cfg.get("to") or smtp_cfg.get("recipients") or smtp_cfg.get("recipient")

    if not host or not from_addr or not to_addrs:
        logging.warning("incomplete smtp config (host/from/to) - skipping email")
        return False

    if isinstance(to_addrs, str):
        to_addrs = [to_addrs]

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        # choose SSL vs STARTTLS based on port
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=10) as smtp:
                if username and password:
                    smtp.login(username, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=10) as smtp:
                smtp.ehlo()
                try:
                    smtp.starttls()
                    smtp.ehlo()
                except Exception:
                    # starttls may fail; continue without it
                    logging.debug("starttls failed or not supported, continuing without TLS")
                if username and password:
                    smtp.login(username, password)
                smtp.send_message(msg)
        logging.info("sent notification email to %s", to_addrs)
        return True
    except Exception as e:
        logging.exception("failed to send notification email: %s", e)
        return False


def send_miss_email_async(cfg: Dict[str, Any], subject: str, body: str) -> bool:
    """Schedule sending of the miss email in a background thread and return immediately."""
    try:
        import threading

        # use a non-daemon thread to ensure send completes even if caller exits
        t = threading.Thread(target=send_miss_email, args=(cfg, subject, body), daemon=False)
        t.start()
        logging.debug("scheduled background email send")
        return True
    except Exception:
        logging.exception("failed to schedule background email send")
        return False
