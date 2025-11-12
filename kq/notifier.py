"""Simple SMTP notifier used to send alerts when attendance matching fails."""

import logging
import smtplib
from email.message import EmailMessage
from typing import Any, Dict, List, Optional, Tuple


def _load_smtp_config(cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    smtp = cfg.get("smtp") or cfg.get("email")
    if not smtp or not isinstance(smtp, dict):
        return None
    # required: host, port, from, to
    return smtp


def send_miss_email(
    cfg: Dict[str, Any],
    subject: Optional[str] = None,
    body: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> bool:
    """Send a notification using SMTP config from cfg.

    If `subject` or `body` are omitted, attempt to render templates from cfg['notifications']
    using the provided `context` mapping. Returns True on success, False otherwise.
    If no smtp config found, returns False silently.
    """
    smtp_cfg = _load_smtp_config(cfg)
    if not smtp_cfg:
        logging.debug(
            "no smtp config found in config.json; skipping email notification"
        )
        return False

    host = smtp_cfg.get("host")
    port = int(smtp_cfg.get("port", 587))
    username = smtp_cfg.get("username")
    password = smtp_cfg.get("password")
    from_addr = smtp_cfg.get("from") or smtp_cfg.get("sender")
    to_addrs = (
        smtp_cfg.get("to") or smtp_cfg.get("recipients") or smtp_cfg.get("recipient")
    )

    if not host or not from_addr or not to_addrs:
        logging.warning("incomplete smtp config (host/from/to) - skipping email")
        return False

    if isinstance(to_addrs, str):
        to_addrs = [to_addrs]

    # prepare subject/body from templates if needed
    if (not subject) or (not body):
        # try to load templates from config
        notifs = cfg.get("notifications") or {}
        tpl_subject = (
            notifs.get("miss_subject") or "Attendance missing for {courses} on {date}"
        )
        tpl_body = notifs.get("miss_body") or (
            "Attendance check for courses {courses} on {date} returned no matches.\n"
            "Candidates:\n{candidates}\n\nThis is an automated message from kqChecker."
        )

        # safe format: missing keys -> empty string
        class _SafeDict(dict):
            def __missing__(self, key):
                return ""

        ctx = _SafeDict()
        if context and isinstance(context, dict):
            ctx.update(context)
        # format candidates list as text if present
        if "candidates" in ctx and isinstance(ctx["candidates"], list):
            cand_lines = []
            for c in ctx["candidates"]:
                try:
                    # expect dict-like snippet
                    when = (
                        c.get("operdate") or c.get("watertime") or c.get("intime") or ""
                    )
                    subj = c.get("subject") or ""
                    teacher = c.get("teacher") or ""
                    cand_lines.append(f"- {when} | {subj} | {teacher}")
                except Exception:
                    cand_lines.append(str(c))
            ctx["candidates"] = "\n".join(cand_lines)

        # default simple mappings
        # normalize courses to a readable string
        courses_val = ctx.get("courses")
        if isinstance(courses_val, list):
            ctx["courses"] = ", ".join(str(x) for x in courses_val)
        if "courses" not in ctx:
            ctx["courses"] = (
                ", ".join(context.get("courses", []))
                if context and context.get("courses")
                else ""
            )
        if "date" not in ctx:
            ctx["date"] = context.get("date", "") if context else ""

        if not subject:
            try:
                subject = tpl_subject.format_map(ctx)
            except Exception:
                subject = tpl_subject
        if not body:
            try:
                body = tpl_body.format_map(ctx)
            except Exception:
                body = tpl_body

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = subject
    msg.set_content(body)
    # log rendered subject/body for traceability (truncate body to avoid huge logs)
    try:
        logging.info("notification subject: %s", subject)
        if body is None:
            body_preview = ""
        else:
            body_preview = (
                body if len(body) < 1000 else body[:1000] + "\n...[truncated]"
            )
        logging.debug("notification body preview:\n%s", body_preview)
    except Exception:
        pass

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
                    logging.debug(
                        "starttls failed or not supported, continuing without TLS"
                    )
                if username and password:
                    smtp.login(username, password)
                smtp.send_message(msg)
        logging.info("sent notification email to %s", to_addrs)
        return True
    except Exception as e:
        logging.exception("failed to send notification email: %s", e)
        return False


def render_notification(
    cfg: Dict[str, Any], context: Optional[Dict[str, Any]]
) -> Tuple[str, str]:
    """Render subject and body from cfg['notifications'] using given context and return them.

    This is useful for previewing the notification without sending.
    """
    # reuse send_miss_email's formatting logic by calling it with no smtp but capturing result would early-return;
    # replicate minimal rendering used above.
    notifs = (cfg or {}).get("notifications") or {}
    tpl_subject = (
        notifs.get("miss_subject") or "Attendance missing for {courses} on {date}"
    )
    tpl_body = notifs.get("miss_body") or (
        "Attendance check for courses {courses} on {date} returned no matches.\n\nCandidates:\n{candidates}\n\nThis is an automated message from kqChecker."
    )

    class _SafeDict(dict):
        def __missing__(self, key):
            return ""

    ctx = _SafeDict()
    if context and isinstance(context, dict):
        ctx.update(context)
    if "candidates" in ctx and isinstance(ctx["candidates"], list):
        cand_lines = []
        for c in ctx["candidates"]:
            try:
                when = c.get("operdate") or c.get("watertime") or c.get("intime") or ""
                subj = c.get("subject") or ""
                teacher = c.get("teacher") or ""
                cand_lines.append(f"- {when} | {subj} | {teacher}")
            except Exception:
                cand_lines.append(str(c))
        ctx["candidates"] = "\n".join(cand_lines)

    # normalize courses to string
    courses_val = ctx.get("courses")
    if isinstance(courses_val, list):
        ctx["courses"] = ", ".join(str(x) for x in courses_val)
    if "courses" not in ctx:
        ctx["courses"] = (
            ", ".join(context.get("courses", []))
            if context and context.get("courses")
            else ""
        )
    if "date" not in ctx:
        ctx["date"] = context.get("date", "") if context else ""

    try:
        subject = tpl_subject.format_map(ctx)
    except Exception:
        subject = tpl_subject
    try:
        body = tpl_body.format_map(ctx)
    except Exception:
        body = tpl_body
    return subject, body


def send_miss_email_async(
    cfg: Dict[str, Any],
    subject: Optional[str] = None,
    body: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> bool:
    """Schedule sending of the miss email in a background thread and return immediately."""
    try:
        import threading

        # use a non-daemon thread to ensure send completes even if caller exits
        t = threading.Thread(
            target=send_miss_email, args=(cfg, subject, body, context), daemon=False
        )
        t.start()
        logging.debug("scheduled background email send")
        return True
    except Exception:
        logging.exception("failed to schedule background email send")
        return False
