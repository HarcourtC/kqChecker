#!/usr/bin/env python3
import socket


def check(host: str, port: int, timeout: int = 5) -> None:
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        print("connect OK")
    except Exception as e:
        print("connect failed:", repr(e))
    finally:
        try:
            s.close()
        except Exception:
            pass


if __name__ == "__main__":
    check("smtp.163.com", 587)
