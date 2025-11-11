import json
import sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from kq.notifier import render_notification

cfg = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
context = {
    'courses': ['Unrelated Course'],
    'date': '2025-11-11',
    'candidates': [],
}
subj, body = render_notification(cfg, context)
print('SUBJECT:')
print(subj)
print('\nBODY:')
print(body)
