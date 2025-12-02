"""HTTP client abstraction for kqChecker.

Provides a lightweight Requests-based client and a `get_http_client()` factory
so higher-level modules can depend on an interface rather than `requests`.

The client currently returns the native `requests.Response` object so existing
callers that rely on `resp.json()` / `resp.text` / `resp.status_code` keep working.
"""

from typing import TYPE_CHECKING, Any, Optional

# typing-friendly placeholder for the requests module when it's not available
requests: Optional[Any] = None

try:
    import requests
except Exception:
    requests = None


if TYPE_CHECKING:
    # import for type checking only; at runtime we avoid hard dependency in annotation
    from requests import Response
else:
    Response = Any


class HTTPClient:
    """Minimal interface for POST used in this project."""

    def post(
        self,
        url: str,
        json: Optional[dict] = None,
        headers: Optional[dict] = None,
        timeout: int = 10,
    ) -> "Response":
        raise NotImplementedError()


class RequestsHTTPClient(HTTPClient):
    def __init__(self) -> None:
        if requests is None:
            raise RuntimeError("requests library is required for RequestsHTTPClient")
        self._session = requests.Session()

    def post(
        self,
        url: str,
        json: Optional[dict] = None,
        headers: Optional[dict] = None,
        timeout: int = 10,
    ) -> "Response":
        return self._session.post(url, json=json, headers=headers, timeout=timeout)


_singleton_client: Optional[HTTPClient] = None


def get_http_client() -> HTTPClient:
    """Return a singleton HTTPClient instance (Requests-based by default).

    This function keeps callers decoupled from direct `requests` usage and
    makes it possible to inject test/mocked clients in the future.
    """
    global _singleton_client
    if _singleton_client is None:
        if requests is None:
            raise RuntimeError("requests is not available in this Python environment")
        _singleton_client = RequestsHTTPClient()
    return _singleton_client
