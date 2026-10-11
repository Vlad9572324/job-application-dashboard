"""Local CAPTCHA model registry. Model files stay outside Git and Docker images."""

import re
import sys
from pathlib import Path


_ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
MODEL_ROOT = _ROOT / "models" / "captcha"
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}\Z")


def model_paths(name: str) -> tuple[Path, Path]:
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError("Недопустимое имя модели")
    folder = MODEL_ROOT if name == "default" else MODEL_ROOT / name
    return folder / "model.pt", folder / "charset.txt"


def model_exists(name: str) -> bool:
    try:
        weights, charset = model_paths(name)
    except ValueError:
        return False
    folder = weights.parent
    return (not folder.is_symlink() and not weights.is_symlink() and not charset.is_symlink()
            and weights.is_file() and charset.is_file())


def list_models() -> list[dict]:
    names = ["default"] if model_exists("default") else []
    if MODEL_ROOT.is_dir():
        names.extend(sorted(
            path.name for path in MODEL_ROOT.iterdir()
            if path.is_dir() and path.name != "default" and _NAME.fullmatch(path.name)
            and model_exists(path.name)
        ))
    return [{"name": name, "size_bytes": model_paths(name)[0].stat().st_size}
            for name in names]
