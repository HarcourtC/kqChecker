cas_token
=========

A tiny standalone helper package to fetch authentication tokens from a
CAS-like token endpoint. Intentionally independent of the `kq` package so it
can be reused in other projects or run as a small CLI.

Files:
- `client.py`: `TokenClient` interface + `RequestsTokenClient` implementation
- `cli.py`: simple command-line wrapper to fetch token using env vars or args

Environment variables supported (for the `fetch_token_from_env` helper and CLI):
- `CAS_TOKEN_URL` - token endpoint URL
- `CAS_USERNAME` - username
- `CAS_PASSWORD` - password
- `CAS_TOKEN_FIELD` - field name in JSON response that holds the token (default `access_token`)

Example:

    CAS_TOKEN_URL=https://auth.example.com/token \
    CAS_USERNAME=alice CAS_PASSWORD=secret python -m cas_token.cli
