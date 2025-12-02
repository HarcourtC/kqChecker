"""Token client abstraction and Requests-based implementation.

Design goals:
- Independent of `kq`, usable as a small standalone helper.
- Provide a `TokenClient` interface and a `RequestsTokenClient`.
- `RequestsTokenClient.fetch_token` will POST either form or JSON to a
  configurable URL (from env or provided at construction) and extract a
  token field from the JSON response.

Usage example:
    from cas_token.client import RequestsTokenClient
    c = RequestsTokenClient(url=os.environ['CAS_TOKEN_URL'])
    token = c.fetch_token(username, password)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

requests: Optional[Any] = None
try:
    import requests  # type: ignore
except Exception:  # pragma: no cover - requests may be missing in some envs
    requests = None


class TokenClient:
    """Abstract token fetcher interface."""

    def fetch_token(
        self, username: str, password: str, timeout: int = 10
    ) -> Optional[str]:
        """Fetch and return a token string, or None on failure."""
        raise NotImplementedError()


class RequestsTokenClient(TokenClient):
    """Simple requests-based token client.

    Configuration via constructor args or environment variables:
      - url: token endpoint (or env `CAS_TOKEN_URL`)
      - token_field: JSON field name for token (default: 'access_token')
      - use_json: whether to send credentials as JSON (default True),
                  otherwise send as form data.
    """

    def __init__(
        self,
        url: Optional[str] = None,
        token_field: str = "access_token",
        use_json: bool = True,
    ) -> None:
        self.url = url or os.environ.get("CAS_TOKEN_URL")
        self.token_field = token_field or "access_token"
        self.use_json = bool(use_json)
        if requests is None:
            raise RuntimeError("requests is required for RequestsTokenClient")

    def fetch_token(
        self, username: str, password: str, timeout: int = 10
    ) -> Optional[str]:
        if not self.url:
            logging.error("RequestsTokenClient: no URL configured (CAS_TOKEN_URL?)")
            return None

        payload: Dict[str, Any] = {"username": username, "password": password}
        try:
            if self.use_json:
                # mypy: narrow union type (requests may be Optional at module level)
                assert requests is not None
                resp = requests.post(self.url, json=payload, timeout=timeout)
            else:
                assert requests is not None
                resp = requests.post(self.url, data=payload, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            # tolerant extraction: nested `data` wrapper or direct field
            if isinstance(data, dict):
                if self.token_field in data:
                    return str(data.get(self.token_field))
                if "data" in data and isinstance(data["data"], dict):
                    if self.token_field in data["data"]:
                        return str(data["data"].get(self.token_field))
            # fallback: try common keys
            for k in ("token", "access_token", "id_token"):
                if isinstance(data, dict) and k in data:
                    return str(data.get(k))
            logging.debug("token field not found in response JSON: %s", data)
            return None
        except Exception as e:
            logging.exception("failed to fetch token: %s", e)
            return None


def fetch_token_from_env(timeout: int = 10) -> Optional[str]:
    """Convenience helper: read username/password from env and fetch token.

    Environment variables:
      - CAS_TOKEN_URL
      - CAS_USERNAME
      - CAS_PASSWORD
      - CAS_TOKEN_FIELD (optional)
    """
    url = os.environ.get("CAS_TOKEN_URL")
    username = os.environ.get("CAS_USERNAME")
    password = os.environ.get("CAS_PASSWORD")
    token_field = os.environ.get("CAS_TOKEN_FIELD", "access_token")

    if not url or not username or not password:
        logging.debug("fetch_token_from_env: missing CAS_TOKEN_URL/USERNAME/PASSWORD")
        return None

    client = RequestsTokenClient(url=url, token_field=token_field)
    return client.fetch_token(username, password, timeout=timeout)
