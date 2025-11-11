"""Apply real_api_response.json -> weekly.json using existing parser."""
import json
from pathlib import Path
import shutil
import os
from get_weekly_json import parse_sample_to_schedule

ROOT = Path(__file__).parent
IN = ROOT / 'real_api_response.json'
OUT = ROOT / 'weekly.json'

if not IN.exists():
    print('real_api_response.json not found')
    raise SystemExit(2)

with IN.open('r', encoding='utf-8') as f:
    data = json.load(f)

sched = parse_sample_to_schedule(data)
text = json.dumps(sched, ensure_ascii=False, indent=2)

# atomic write
tmp = OUT.with_name(OUT.name + '.tmp')
with tmp.open('w', encoding='utf-8') as f:
    f.write(text)

if OUT.exists():
    try:
        bak = OUT.with_suffix(OUT.suffix + '.bak')
        shutil.copy2(OUT, bak)
    except Exception:
        pass

os.replace(str(tmp), str(OUT))
print('Wrote', OUT)
print(text)
