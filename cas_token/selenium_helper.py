"""Selenium helper to open the CAS login page specified in config.

This module uses `selenium` to open the URL and provides a resilient
auto-fill helper with JS fallbacks for frameworks such as React.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import List, Optional
from urllib.parse import parse_qs, urlparse


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
                    # After attempting auto-login, try to capture token from final redirect
                    try:
                        token = _wait_for_token_after_login(driver, account_info)
                        if token:
                            token_bearer = f"bearer {token}"
                            # save token to file for convenience
                            try:
                                outp = Path(__file__).parent / "last_token.txt"
                                outp.write_text(token_bearer, encoding="utf-8")
                            except Exception:
                                logging.exception("failed to write token to file")
                            # persist into py_config.json headers (synjones-auth)
                            try:
                                _save_token_to_config(token_bearer, None)
                            except Exception:
                                logging.exception("failed to save token to config")
                            print(f"TOKEN:{token_bearer}")
                    except Exception:
                        logging.debug("token capture attempt failed", exc_info=True)
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


def _safe_find(driver: object, selectors: List[tuple]) -> Optional[object]:
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


def _extract_token_from_url(
    url: str, param_names: Optional[List[str]] = None
) -> Optional[str]:
    """Parse URL query and return the first matching parameter value.

    param_names: list of candidate query parameter names to check in order.
    """
    if not url:
        return None
    if param_names is None:
        param_names = ["token", "access_token", "ticket", "t"]
    try:
        p = urlparse(url)
        qs = parse_qs(p.query)
        for name in param_names:
            if name in qs and qs[name]:
                return qs[name][0]
        # also check fragment (hash) like '#/path?token=...'
        frag = p.fragment or ""
        if "?" in frag:
            try:
                frag_qs = parse_qs(frag.split("?", 1)[1])
                for name in param_names:
                    if name in frag_qs and frag_qs[name]:
                        return frag_qs[name][0]
            except Exception:
                pass
    except Exception:
        logging.debug("failed to parse URL for token: %s", url, exc_info=True)
    return None


def _wait_for_token_after_login(
    driver: object, account_info: dict, timeout: int = 30
) -> Optional[str]:
    """Poll the browser for a redirect URL containing a token query param.

    Returns the token if found within timeout seconds, else None.
    """
    param = account_info.get("token_param")
    params: Optional[List[str]]
    if isinstance(param, str) and param:
        params = [param]
    elif isinstance(param, list) and param:
        params = [p for p in param if isinstance(p, str) and p]
    else:
        params = None

    cap_timeout = account_info.get("capture_timeout")
    try:
        cap_timeout = int(cap_timeout) if cap_timeout is not None else timeout
    except Exception:
        cap_timeout = timeout

    import time

    end = time.time() + cap_timeout
    last_urls = set()
    while time.time() < end:
        try:
            # check all window handles
            for h in list(driver.window_handles):
                try:
                    driver.switch_to.window(h)
                    cur = driver.current_url
                except Exception:
                    continue
                if not cur:
                    continue
                if cur in last_urls:
                    continue
                last_urls.add(cur)
                tok = _extract_token_from_url(cur, params)
                if tok:
                    return tok
                # check cookies for token-like names
                try:
                    ck = {c.get("name"): c.get("value") for c in driver.get_cookies()}
                    for name in params or ["token", "access_token", "ticket", "t"]:
                        if name in ck and ck[name]:
                            logging.debug("found token in cookie %s", name)
                            return ck[name]
                except Exception:
                    logging.debug(
                        "could not read cookies for token detection", exc_info=True
                    )
                # check localStorage for token names
                try:
                    if params:
                        keys = params
                    else:
                        keys = ["token", "access_token", "ticket", "t"]
                    for k in keys:
                        try:
                            val = driver.execute_script(
                                "return window.localStorage.getItem(arguments[0]);", k
                            )
                        except Exception:
                            val = None
                        if val:
                            logging.debug("found token in localStorage %s", k)
                            return val
                except Exception:
                    logging.debug("localStorage token check failed", exc_info=True)
        except Exception:
            logging.debug("error while polling for token", exc_info=True)
        time.sleep(0.5)
    return None


def _save_token_to_config(token_value: str, config_path: Optional[str] = None) -> bool:
    """Save the token string into `py_config.json` under `headers.synjones-auth`.

    Returns True on success, False otherwise.
    """
    try:
        if config_path:
            p = Path(config_path)
        else:
            p = Path(__file__).parent.parent / "py_config.json"
        if not p.exists():
            logging.error("config file not found: %s", p)
            return False
        raw = json.loads(p.read_text(encoding="utf-8"))
        hdrs = raw.get("headers")
        if not isinstance(hdrs, dict):
            hdrs = {}
            raw["headers"] = hdrs
        # update synjones-auth header (common in this project)
        hdrs["synjones-auth"] = token_value
        # also store convenience top-level key
        raw["auth_token"] = token_value
        # backup original
        try:
            bak = p.with_suffix(p.suffix + ".bak")
            bak.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:
            pass
        p.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        logging.exception("failed to save token into config")
        return False


def _attempt_auto_login(driver: object, account_info: dict) -> bool:
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

    uname_xpath = account_info.get("username_xpath")
    pwd_xpath = account_info.get("password_xpath")

    uname_candidates = []
    # Prefer explicit XPath from config
    if uname_xpath:
        uname_candidates.append((By.XPATH, uname_xpath))
    elif uname_sel:
        s = uname_sel.strip()
        if s.startswith("//") or s.startswith("/"):
            uname_candidates.append((By.XPATH, uname_sel))
        else:
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
    # Prefer explicit XPath from config
    if pwd_xpath:
        pwd_candidates.append((By.XPATH, pwd_xpath))
    elif pwd_sel:
        s = pwd_sel.strip()
        if s.startswith("//") or s.startswith("/"):
            pwd_candidates.append((By.XPATH, pwd_sel))
        else:
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

        def _set_value(el: object, val: object) -> bool:
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
