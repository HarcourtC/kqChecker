#!/usr/bin/env python3
"""
Wrapper to run `main.py` with a filesystem lock to prevent overlapping runs.
Use this script as the action for Task Scheduler or other schedulers.
"""
import os
import sys
import subprocess
import time

LOCKNAME = "run_once_locked.lock"
HERE = os.path.dirname(os.path.abspath(__file__))
LOCKPATH = os.path.join(HERE, LOCKNAME)

def acquire_lock():
    if os.name == 'nt':
        import msvcrt
        lock_file = open(LOCKPATH, 'w')
        try:
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            lock_file.close()
            return None
        return lock_file
    else:
        import fcntl
        lock_file = open(LOCKPATH, 'w')
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except IOError:
            lock_file.close()
            return None
        return lock_file


def release_lock(lock_file):
    try:
        if lock_file is None:
            return
        if os.name == 'nt':
            import msvcrt
            try:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            except Exception:
                pass
        else:
            import fcntl
            try:
                fcntl.flock(lock_file, fcntl.LOCK_UN)
            except Exception:
                pass
    finally:
        try:
            lock_file.close()
        except Exception:
            pass
        try:
            os.remove(LOCKPATH)
        except Exception:
            pass


def main():
    lock_file = acquire_lock()
    if lock_file is None:
        print("Another instance is running; exiting.")
        return 0

    try:
        python = sys.executable
        script = os.path.join(HERE, 'main.py')
        if not os.path.exists(script):
            print(f"Script not found: {script}")
            return 2

        # Run the main script. We don't fail hard on non-zero return; scheduler can log it.
        try:
            completed = subprocess.run([python, script], check=False)
            return completed.returncode if completed.returncode is not None else 0
        except Exception as ex:
            print("Error running main.py:", ex)
            return 3
    finally:
        release_lock(lock_file)


if __name__ == '__main__':
    sys.exit(main())
