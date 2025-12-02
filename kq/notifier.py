"""Notifier facade kept for backward compatibility.

This module now delegates to `kq.notifier_client` implementations while
preserving the original function signatures so existing callers continue to
work. The concrete notifier is created based on `cfg['smtp']`.
"""

import logging
from typing import Any, Dict, Optional, Tuple

from .notifier_client import SMTPNotifier


def _render_context(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    class _SafeDict(dict):
        def __missing__(self, key: object) -> str:
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
    return ctx


def _get_notifier_from_cfg(cfg: Dict[str, Any]) -> Optional[SMTPNotifier]:
    smtp_cfg = (cfg or {}).get("smtp") or (cfg or {}).get("email")
    if not smtp_cfg or not isinstance(smtp_cfg, dict):
        logging.debug(
            "no smtp config found in config.json; skipping email notification"
        )
        return None
    # allow optional notifier tuning via config keys: max_workers, timeout
    try:
        max_workers = int(smtp_cfg.get("max_workers", smtp_cfg.get("workers", 2)))
    except Exception:
        max_workers = 2
    try:
        timeout = int(smtp_cfg.get("timeout", smtp_cfg.get("smtp_timeout", 10)))
    except Exception:
        timeout = 10
    return SMTPNotifier(smtp_cfg, max_workers=max_workers, timeout=timeout)


def render_notification(
    cfg: Dict[str, Any], context: Optional[Dict[str, Any]]
) -> Tuple[str, str]:
    notifs = (cfg or {}).get("notifications") or {}
    tpl_subject = (
        notifs.get("miss_subject") or "Attendance missing for {courses} on {date}"
    )
    tpl_body = notifs.get("miss_body") or (
        "Attendance check for courses {courses} on {date} returned no matches.\n\nCandidates:\n{candidates}\n\nThis is an automated message from kqChecker."
    )

    ctx = _render_context(context)

    try:
        subject = tpl_subject.format_map(ctx)
    except Exception:
        subject = tpl_subject
    try:
        body = tpl_body.format_map(ctx)
    except Exception:
        body = tpl_body
    return subject, body


def send_miss_email(
    cfg: Dict[str, Any],
    subject: Optional[str] = None,
    body: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> bool:
    """Synchronous send. Returns True on success.

    Preserves original function signature for compatibility.
    """
    notifier = _get_notifier_from_cfg(cfg)
    if notifier is None:
        return False

    if not subject or not body:
        subject, body = render_notification(cfg, context)

    smtp_cfg = cfg.get("smtp") or {}
    from_addr = smtp_cfg.get("from") or smtp_cfg.get("sender")
    to_addrs = (
        smtp_cfg.get("to") or smtp_cfg.get("recipients") or smtp_cfg.get("recipient")
    )
    if isinstance(to_addrs, str):
        to_addrs = [to_addrs]

    return notifier.send(subject, body, from_addr, to_addrs)


def send_miss_email_async(
    cfg: Dict[str, Any],
    subject: Optional[str] = None,
    body: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> bool:
    """Schedule sending of the miss email asynchronously."""
    notifier = _get_notifier_from_cfg(cfg)
    if notifier is None:
        return False

    if not subject or not body:
        subject, body = render_notification(cfg, context)

    smtp_cfg = cfg.get("smtp") or {}
    from_addr = smtp_cfg.get("from") or smtp_cfg.get("sender")
    to_addrs = (
        smtp_cfg.get("to") or smtp_cfg.get("recipients") or smtp_cfg.get("recipient")
    )
    if isinstance(to_addrs, str):
        to_addrs = [to_addrs]

    return notifier.send_async(subject, body, from_addr, to_addrs)
