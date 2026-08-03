"""Read-only: espera o servidor responder /api/status (ate ~40s)."""
import sys
import time
import urllib.request

for _ in range(40):
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:8000/api/status", timeout=3
        ) as r:
            print("OK", r.status)
            sys.exit(0)
    except Exception:
        time.sleep(1)

print("FALHOU: servidor nao respondeu a tempo")
sys.exit(1)
