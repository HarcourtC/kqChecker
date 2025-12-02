"""cas_token: lightweight standalone CAS token fetcher.

This package is intentionally independent of `kq` and provides a
small pluggable TokenClient interface plus a Requests-based
implementation and a CLI helper.
"""

__all__ = ["TokenClient", "RequestsTokenClient", "fetch_token"]
