"""Check that a frozen release serves its health and bundled UI locally."""

import argparse
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    executable = bundle / ("hh-clicker.exe" if os.name == "nt" else "hh-clicker")
    if not executable.is_file() or not (bundle / "static" / "index.html").is_file():
        parser.error("binary or static assets missing from bundle")

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = os.environ.copy()
    env.update(HH_BOT_HOST="127.0.0.1", HH_BOT_PORT=str(port))
    # Keep CI build smoke independent of any runner credentials.
    for key in ("HH_BOT_API_KEY", "TELEGRAM_BOT_TOKEN", "HH_TELEGRAM_BOT_TOKEN"):
        env.pop(key, None)
    with tempfile.TemporaryFile() as log:
        proc = subprocess.Popen([str(executable)], cwd=bundle, env=env,
                                stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    break
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as r:
                        if r.status == 200:
                            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as page:
                                assert b"questionnaire-history" in page.read()
                            print("Frozen app serves /healthz and /")
                            return
                except (OSError, AssertionError):
                    time.sleep(0.5)
            log.seek(0)
            print(log.read().decode(errors="replace")[-5000:], file=sys.stderr)
            raise SystemExit("Frozen app failed smoke check")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    main()
