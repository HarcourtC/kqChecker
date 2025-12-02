"""Notifier abstraction and SMTP implementation.

Provides a Notifier interface and an SMTP-based implementation that can be
reused by `kq.notifier` and injected for testing.
"""

from __future__ import annotations

import logging
import smtplib
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from typing import Any, Dict, List, Optional


class Notifier:
    def send(
        self,
        subject: str,
        body: str,
        from_addr: Optional[str],
        to_addrs: Optional[List[str]],
    ) -> bool:
        raise NotImplementedError()

    def send_async(
        self,
        subject: str,
        body: str,
        from_addr: Optional[str],
        to_addrs: Optional[List[str]],
    ) -> bool:
        raise NotImplementedError()


class SMTPNotifier(Notifier):
    def __init__(
        self, smtp_cfg: Dict[str, Any], max_workers: int = 2, timeout: int = 10
    ) -> None:
        self._cfg = smtp_cfg or {}
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._timeout = int(timeout or 10)

    def _build_message(
        self,
        subject: str,
        body: str,
        from_addr: Optional[str],
        to_addrs: Optional[List[str]],
    ) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = from_addr or ""
        msg["To"] = ", ".join(to_addrs or [])
        msg["Subject"] = subject
        msg.set_content(body)
        return msg

    def send(
        self,
        subject: str,
        body: str,
        from_addr: Optional[str],
        to_addrs: Optional[List[str]],
    ) -> bool:
        host = self._cfg.get("host")
        port = int(self._cfg.get("port", 587))
        username = self._cfg.get("username")
        password = self._cfg.get("password")

        if not host or not from_addr or not to_addrs:
            logging.warning("incomplete smtp config (host/from/to) - skipping email")
            return False

        msg = self._build_message(subject, body, from_addr, to_addrs)

        try:
            if port == 465:
                with smtplib.SMTP_SSL(host, port, timeout=self._timeout) as smtp:
                    if username and password:
                        smtp.login(username, password)
                    smtp.send_message(msg)
            else:
                with smtplib.SMTP(host, port, timeout=self._timeout) as smtp:
                    smtp.ehlo()
                    try:
                        smtp.starttls()
                        smtp.ehlo()
                    except Exception:
                        logging.debug(
                            "starttls failed or not supported, continuing without TLS"
                        )
                    if username and password:
                        smtp.login(username, password)
                    smtp.send_message(msg)
            logging.info("sent notification email to %s", to_addrs)
            return True
        except Exception:
            logging.exception("failed to send notification email")
            return False

    def send_async(
        self,
        subject: str,
        body: str,
        from_addr: Optional[str],
        to_addrs: Optional[List[str]],
    ) -> bool:
        try:
            self._executor.submit(self.send, subject, body, from_addr, to_addrs)
            logging.debug("scheduled background email send via ThreadPoolExecutor")
            return True
        except Exception:
            logging.exception("failed to schedule background email send")
            return False
