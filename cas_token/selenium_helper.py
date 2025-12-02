"""Selenium helper to open the CAS login page specified in config.

This module uses `webdriver-manager` to install a Chrome driver and
`selenium` to open the URL. It is intentionally minimal: it opens the
page and keeps the browser open until the user closes it (or after an
optional timeout).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional


def _read_auth_url_from_config(config_path: Optional[str]) -> Optional[str]:
    if config_path:
        p = Path(config_path)
    else:
        p = Path(__file__).parent.parent / "py_config.json"
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        url = raw.get("auth_login_url")
        if isinstance(url, str) and url:
            return url
    except Exception:
        logging.exception("failed to read auth_login_url from %s", p)
    return None


def open_login_page(
    url: Optional[str] = None, headless: bool = False, timeout: Optional[int] = None
) -> bool:
    """Open the login page using Selenium + ChromeDriver.

    Parameters:
    - url: direct URL to open; if None, reads from `py_config.json` in repo root
    - headless: whether to run Chrome in headless mode (default False)
    - timeout: optional seconds to wait before closing the browser (None = wait until manual close)

    Returns True on success, False on failure.
    """
    try:
        if not url:
            url = _read_auth_url_from_config(None)
        if not url:
            logging.error("no auth_login_url found in config and no url provided")
            return False

        # lazy imports so package doesn't require selenium at import time
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service as ChromeService
        from webdriver_manager.chrome import ChromeDriverManager
    except Exception:
        logging.exception("selenium or webdriver-manager not available")
        return False

    try:
        options = Options()
        if headless:
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)

        driver.get(url)

        if timeout is not None and timeout > 0:
            import time

            time.sleep(timeout)
            try:
                driver.quit()
            except Exception:
                pass
        else:
            # keep browser open until user closes it manually
            print(f"Opened login page: {url}. Close the browser to continue.")
        return True
    except Exception:
        logging.exception("failed to open login page %s", url)
        return False
