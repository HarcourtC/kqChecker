"""CLI helper for cas_token package.

Usage:
    python -m cas_token.cli --username USER --password PASS --url https://...

Environment support: `CAS_USERNAME`, `CAS_PASSWORD`, `CAS_TOKEN_URL`, `CAS_TOKEN_FIELD`
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

from .client import RequestsTokenClient


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch CAS token")
    parser.add_argument("--username", help="username (or set CAS_USERNAME)")
    parser.add_argument("--password", help="password (or set CAS_PASSWORD)")
    parser.add_argument("--url", help="token URL (or set CAS_TOKEN_URL)")
    parser.add_argument(
        "--token-field",
        help="token field in response JSON (default access_token)",
        default="access_token",
    )
    args = parser.parse_args(argv)

    username = args.username or os.environ.get("CAS_USERNAME")
    password = args.password or os.environ.get("CAS_PASSWORD")
    url = args.url or os.environ.get("CAS_TOKEN_URL")
    token_field = args.token_field or os.environ.get("CAS_TOKEN_FIELD", "access_token")

    if not username or not password or not url:
        print(
            "username/password/url required (or set CAS_USERNAME/CAS_PASSWORD/CAS_TOKEN_URL)"
        )
        return 2

    client = RequestsTokenClient(url=url, token_field=token_field)
    token = client.fetch_token(username, password)
    if not token:
        print("failed to fetch token", file=sys.stderr)
        return 1
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
