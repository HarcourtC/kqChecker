#!/usr/bin/env python3
from kq.config import load_config
from kq.notifier import send_miss_email

cfg = load_config()
smtp = cfg.get('smtp') or cfg.get('email')
if not smtp:
    print('no smtp config found in config.json')
    raise SystemExit(1)

# Temporarily override port to 465 and use SMTP_SSL
smtp = dict(smtp)
smtp['port'] = 465
cfg2 = dict(cfg)
cfg2['smtp'] = smtp

print('Attempting SSL send to', smtp.get('host'), 'port', smtp.get('port'))
ok = send_miss_email(cfg2, 'kqChecker SSL test', 'This is a SSL(465) test email from kqChecker')
print('send_miss_email returned', ok)
