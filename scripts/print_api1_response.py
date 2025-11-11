"""POST to api1 and print the raw JSON response (pretty).

This script reads config.json for api1 URL and optional api1_payload. If not present,
uses sensible defaults. It prints the response JSON to stdout.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
cfg_path = ROOT / 'config.json'

try:
    cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
except Exception as e:
    print('failed to read config.json:', e, file=sys.stderr)
    sys.exit(2)

url = cfg.get('api1')
if not url:
    print('api1 not configured in config.json', file=sys.stderr)
    sys.exit(2)

payload = {}
api1_payload_cfg = cfg.get('api1_payload') if isinstance(cfg, dict) else None
if isinstance(api1_payload_cfg, dict):
    payload['termNo'] = int(api1_payload_cfg.get('termNo') or 606)
    payload['week'] = int(api1_payload_cfg.get('week') or 10)
else:
    payload['termNo'] = 606
    payload['week'] = 10

headers = cfg.get('headers') or {}

# perform POST
try:
    import requests
except Exception:
    print('requests library not available; install requests', file=sys.stderr)
    sys.exit(3)

try:
    resp = requests.post(url, json=payload, headers=headers, timeout=15)
    resp.raise_for_status()
    try:
        data = resp.json()
    except Exception:
        print('api1 returned non-json response', file=sys.stderr)
        print(resp.text)
        sys.exit(0)
    print(json.dumps(data, ensure_ascii=False, indent=2))
except Exception as e:
    print('request failed:', e, file=sys.stderr)
    sys.exit(4)
