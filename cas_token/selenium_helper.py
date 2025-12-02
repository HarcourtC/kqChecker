"""Selenium helper to open the CAS login page specified in config.

This module uses `selenium` to open the URL and provides a resilient
auto-fill helper with JS fallbacks for frameworks such as React.
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


def _read_account_info_from_config(config_path: Optional[str]) -> Optional[dict]:
    if config_path:
        p = Path(config_path)
    else:
        p = Path(__file__).parent.parent / "py_config.json"
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        ai = raw.get("AccoutInfo") or raw.get("AccountInfo") or raw.get("account_info")
        if isinstance(ai, dict):
            return ai
    except Exception:
        logging.debug("failed to read AccoutInfo from %s", p, exc_info=True)
    return None


def open_login_page(
    url: Optional[str] = None,
    headless: bool = False,
    timeout: Optional[int] = None,
    auto_login: bool = True,
    keep_open: bool = False,
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

        # lazy selenium import to avoid hard dependency at import time
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service as ChromeService

        # try local chromedriver next to module if present
        driver_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "chromedriver.exe"
        )
        service = (
            ChromeService(executable_path=driver_path)
            if os.path.exists(driver_path)
            else None
        )

        options = webdriver.ChromeOptions()
        if headless:
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        if service:
            driver = webdriver.Chrome(service=service, options=options)
        else:
            driver = webdriver.Chrome(options=options)

        driver.get(url)

        if auto_login:
            account_info = _read_account_info_from_config(None)
            if account_info:
                try:
                    _attempt_auto_login(driver, account_info)
                except Exception:
                    logging.exception("auto-login attempt failed")

        if timeout is not None and timeout > 0:
            import time

            time.sleep(timeout)
            try:
                driver.quit()
            except Exception:
                pass
        else:
            print(f"Opened login page: {url}. Close the browser to continue.")
            if keep_open:
                try:
                    # If interactive, block until user presses Enter
                    input("Press Enter to close the browser and exit...")
                    try:
                        driver.quit()
                    except Exception:
                        pass
                except Exception:
                    # Non-interactive environment: wait until browser windows are closed manually
                    try:
                        import time

                        while True:
                            try:
                                handles = driver.window_handles
                            except Exception:
                                # driver no longer available / closed
                                break
                            if not handles:
                                break
                            time.sleep(0.5)
                    except Exception:
                        pass
        return True
    except Exception:
        logging.exception("failed to open login page %s", url)
        return False


def _safe_find(driver, selectors):
    """Try a sequence of selector tuples and return first found element.

    selectors: list of tuples (by, value) where by is a selenium By string.
    """
    from selenium.common.exceptions import NoSuchElementException

    for by, val in selectors:
        try:
            return driver.find_element(by, val)
        except NoSuchElementException:
            continue
        except Exception:
            continue
    return None


def _attempt_auto_login(driver, account_info: dict) -> bool:
    """Resilient autofill for username/password with JS fallbacks.

    Returns True if both username and password were set (not strictly whether login succeeded).
    """
    import time

    from selenium.webdriver.common.by import By

    username = account_info.get("username") or account_info.get("user")
    password = account_info.get("password") or account_info.get("pass")
    if not username or not password:
        logging.info("AccoutInfo found but missing username/password")
        return False

    uname_sel = account_info.get("username_selector")
    pwd_sel = account_info.get("password_selector")
    submit_sel = account_info.get("submit_selector")

    uname_candidates = []
    if uname_sel:
        uname_candidates.append((By.CSS_SELECTOR, uname_sel))
    else:
        uname_candidates.extend(
            [
                (
                    By.XPATH,
                    '//*[@id="vue_main"]/div[2]/div[2]/div/div[4]/div/div[2]/div[1]/div/form/div[1]/div/div/input',
                ),
                (By.NAME, "username"),
                (By.NAME, "user"),
                (By.CSS_SELECTOR, "input[type='text']"),
                (By.CSS_SELECTOR, "input[id*='user']"),
                (By.CSS_SELECTOR, "input[name*='account']"),
            ]
        )

    pwd_candidates = []
    if pwd_sel:
        pwd_candidates.append((By.CSS_SELECTOR, pwd_sel))
    else:
        pwd_candidates.extend(
            [
                (By.CSS_SELECTOR, "input[type='password']"),
                (By.NAME, "password"),
                (By.CSS_SELECTOR, "input[id*='pass']"),
            ]
        )

    try:
        uname_el = _safe_find(driver, uname_candidates)
        pwd_el = _safe_find(driver, pwd_candidates)
        if uname_el is None or pwd_el is None:
            logging.info("could not locate username/password fields for auto-login")
            return False

        def _set_value(el, val) -> bool:
            try:
                try:
                    el.click()
                except Exception:
                    pass
                try:
                    el.clear()
                except Exception:
                    pass
                el.send_keys(str(val))
                return True
            except Exception:
                try:
                    driver.execute_script(
                        "const el = arguments[0]; const val = arguments[1]; var nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set; nativeSetter.call(el, val); el.dispatchEvent(new Event('input', {bubbles:true}));",
                        el,
                        val,
                    )
                    return True
                except Exception:
                    logging.exception("failed to set value via JS")
                    return False

        ok_user = _set_value(uname_el, username)
        time.sleep(0.15)
        ok_pwd = _set_value(pwd_el, password)
        time.sleep(0.15)

        # submit
        if submit_sel:
            try:
                from selenium.webdriver.support.ui import WebDriverWait

                wait = WebDriverWait(driver, 5)
                try:
                    if submit_sel.strip().startswith("//"):
                        btn = wait.until(lambda d: d.find_element(By.XPATH, submit_sel))
                    else:
                        btn = wait.until(
                            lambda d: d.find_element(By.CSS_SELECTOR, submit_sel)
                        )
                except Exception:
                    try:
                        if submit_sel.strip().startswith("//"):
                            btn = driver.find_element(By.XPATH, submit_sel)
                        else:
                            btn = driver.find_element(By.CSS_SELECTOR, submit_sel)
                    except Exception:
                        btn = None

                if btn is not None:
                    try:
                        btn.click()
                    except Exception:
                        try:
                            driver.execute_script("arguments[0].click();", btn)
                        except Exception:
                            logging.debug("click submit failed", exc_info=True)
                else:
                    try:
                        pwd_el.send_keys("\n")
                    except Exception:
                        logging.debug("submit fallback ENTER failed", exc_info=True)
            except Exception:
                logging.debug("submit helper failed", exc_info=True)
        else:
            try:
                pwd_el.send_keys("\n")
            except Exception:
                try:
                    form = driver.execute_script(
                        "var e = arguments[0]; while(e && e.nodeName.toLowerCase() !== 'form') e = e.parentElement; return e;",
                        pwd_el,
                    )
                    if form:
                        driver.execute_script("arguments[0].submit();", form)
                except Exception:
                    logging.debug("final form submit fallback failed", exc_info=True)

        logging.info(
            "auto-login attempted for user %s (user_ok=%s pwd_ok=%s)",
            username,
            ok_user,
            ok_pwd,
        )
        return bool(ok_user and ok_pwd)
    except Exception:
        logging.exception("auto-login outer failure")
        return False


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Open CAS login page and optionally auto-fill"
    )
    parser.add_argument("--url", help="direct URL to open (overrides config)")
    parser.add_argument("--headless", action="store_true", help="run headless")
    parser.add_argument(
        "--timeout",
        type=int,
        help="seconds to wait before closing the browser (default: keep open)",
    )
    parser.add_argument(
        "--auto-login",
        action="store_true",
        help="attempt to auto-fill using AccoutInfo from py_config.json",
    )
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="keep browser open and wait for Enter before closing",
    )
    args = parser.parse_args()

    ok = open_login_page(
        url=args.url,
        headless=args.headless,
        timeout=args.timeout,
        auto_login=args.auto_login,
        keep_open=args.keep_open,
    )
    sys.exit(0 if ok else 1)
