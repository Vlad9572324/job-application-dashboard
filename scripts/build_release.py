"""Build a portable one-folder release on the current OS.

Linux and Windows binaries must be built on their respective GitHub runners.
Only source files and public static assets are packaged; data and model weights
are created or supplied by the user beside the executable.
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=("linux-x64", "windows-x64"), required=True)
    args = parser.parse_args()
    expected = "windows-x64" if os.name == "nt" else "linux-x64"
    if args.platform != expected:
        parser.error(f"{args.platform} must be built on its own OS ({expected} here)")

    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
        "--name", "hh-clicker", "--collect-submodules", "app",
        "--collect-submodules", "uvicorn", "--collect-data", "tzdata",
        "--distpath", str(OUT),
        "--workpath", str(ROOT / "build" / "pyinstaller"),
        "--specpath", str(ROOT / "build"), str(ROOT / "web_app.py"),
    ], cwd=ROOT, check=True)

    bundle = OUT / "hh-clicker"
    shutil.copytree(ROOT / "static", bundle / "static", dirs_exist_ok=True)
    (bundle / "models" / "captcha").mkdir(parents=True, exist_ok=True)
    (bundle / "models" / "captcha" / "README.txt").write_text(
        "Optional local CAPTCHA model: place model.pt and charset.txt here.\n",
        encoding="utf-8")
    (bundle / "README.txt").write_text(
        "Run hh-clicker.exe on Windows or ./hh-clicker on Linux.\n"
        "Open http://127.0.0.1:8000 in your browser.\n"
        "Your settings and accounts are stored in data/ beside the executable.\n"
        "Set HH_BOT_API_KEY in the environment before allowing network access.\n"
        "Local CAPTCHA weights, if used, go in models/captcha/.\n",
        encoding="utf-8")

    if args.platform == "linux-x64":
        archive = OUT / "hh-clicker-linux-x64.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            tf.add(bundle, arcname="hh-clicker")
    else:
        archive = OUT / "hh-clicker-windows-x64.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for path in sorted(bundle.rglob("*")):
                if path.is_file():
                    zf.write(path, Path("hh-clicker") / path.relative_to(bundle))
    print(archive)


if __name__ == "__main__":
    main()
