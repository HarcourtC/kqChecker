from kq.config import load_config
from kq.notifier import send_miss_email
cfg = load_config()
print('cfg smtp present:', 'smtp' in cfg)
ok = send_miss_email(cfg, 'kqChecker test', 'This is a test from scripts/send_test_email.py')
print('send_miss_email returned', ok)
