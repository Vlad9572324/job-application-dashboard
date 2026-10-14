"""Build a portable one-folder release on the current OS.

Linux and Windows binaries must be built on their respective GitHub runners.
The default CAPTCHA model is packaged with the binary. User settings and
additional uploaded models remain outside the release.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "release"
APP_NAME = "job-application-dashboard"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=("linux-x64", "windows-x64"), required=True)
    args = parser.parse_args()
    expected = "windows-x64" if os.name == "nt" else "linux-x64"
    if args.platform != expected:
        parser.error(f"{args.platform} must be built on its own OS ({expected} here)")

    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
        "--name", APP_NAME, "--collect-submodules", "app",
        "--collect-submodules", "uvicorn", "--collect-data", "tzdata",
        "--distpath", str(OUT),
        "--workpath", str(ROOT / "build" / "pyinstaller"),
        "--specpath", str(ROOT / "build"), str(ROOT / "web_app.py"),
    ], cwd=ROOT, check=True)

    bundle = OUT / APP_NAME
    shutil.copytree(ROOT / "static", bundle / "static", dirs_exist_ok=True)
    model_dir = bundle / "models" / "captcha"
    model_dir.mkdir(parents=True, exist_ok=True)
    for name in ("model.pt", "charset.txt"):
        shutil.copy2(ROOT / "models" / "captcha" / name, model_dir / name)
    (bundle / "README.txt").write_text(
        f"Run {APP_NAME}.exe on Windows or ./{APP_NAME} on Linux.\n"
        "Open http://127.0.0.1:8000 in your browser.\n"
        "Your settings and accounts are stored in data/ beside the executable.\n"
        "Set HH_BOT_API_KEY in the environment before allowing network access.\n"
        "The default local CAPTCHA model is included in models/captcha/.\n",
        encoding="utf-8")

    if args.platform == "linux-x64":
        archive = OUT / f"{APP_NAME}-linux-x64.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            tf.add(bundle, arcname=APP_NAME)
    else:
        archive = OUT / f"{APP_NAME}-windows-x64.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for path in sorted(bundle.rglob("*")):
                if path.is_file():
                    zf.write(path, Path(APP_NAME) / path.relative_to(bundle))
    print(archive)


if __name__ == "__main__":
    main()
