"""Upload and select local CAPTCHA models from dashboard settings."""

import os
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.captcha_models import MODEL_ROOT, list_models, model_exists, model_paths
from app.config import CONFIG, save_config


router = APIRouter()
_MAX_WEIGHTS = 100 * 1024 * 1024
_MAX_CHARSET = 4096


class ModelChoice(BaseModel):
    name: str


@router.get("/api/captcha/models")
def api_captcha_models():
    return {"ok": True, "active": CONFIG.captcha_model_name, "models": list_models()}


async def _copy_upload(file: UploadFile, destination: Path, limit: int):
    total = 0
    with destination.open("xb") as output:
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > limit:
                raise HTTPException(status_code=413, detail="Файл модели слишком большой")
            output.write(chunk)
    if total == 0:
        raise HTTPException(status_code=400, detail="Пустой файл модели")


@router.post("/api/captcha/models")
async def api_captcha_model_upload(
    name: str = Form(...),
    weights: UploadFile = File(...),
    charset: UploadFile | None = File(None),
):
    try:
        model_paths(name)  # validates the name before touching disk
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if name == "default":
        raise HTTPException(status_code=400, detail="Встроенную модель нельзя перезаписать")
    if model_exists(name) or (MODEL_ROOT / name).exists():
        raise HTTPException(status_code=409, detail="Модель с таким именем уже есть")

    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".upload-", dir=MODEL_ROOT) as tmp:
        stage = Path(tmp)
        await _copy_upload(weights, stage / "model.pt", _MAX_WEIGHTS)
        if charset is None:
            default_charset = model_paths("default")[1]
            if not default_charset.is_file():
                raise HTTPException(status_code=400, detail="Загрузите алфавит charset.txt")
            shutil.copyfile(default_charset, stage / "charset.txt")
        else:
            await _copy_upload(charset, stage / "charset.txt", _MAX_CHARSET)

        from app.captcha_predict import load_model
        try:
            await run_in_threadpool(load_model, stage / "model.pt", stage / "charset.txt")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Модель не загружается: {type(exc).__name__}") from exc

        target = MODEL_ROOT / name
        try:
            target.mkdir()
            os.replace(stage / "model.pt", target / "model.pt")
            os.replace(stage / "charset.txt", target / "charset.txt")
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail="Модель с таким именем уже есть") from exc
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise
    return {"ok": True, "name": name, "active": CONFIG.captcha_model_name}


def _select_model(name: str):
    if not model_exists(name):
        raise HTTPException(status_code=404, detail="Модель не найдена")
    from app.captcha_llm import _inference_lock, _local_model
    from app.captcha_predict import load_model
    weights, charset = model_paths(name)
    with _inference_lock:
        try:
            load_model(weights, charset)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Модель не загружается: {type(exc).__name__}") from exc
        CONFIG.captcha_model_name = name
        _local_model.cache_clear()
        save_config()


@router.post("/api/captcha/models/select")
async def api_captcha_model_select(choice: ModelChoice):
    await run_in_threadpool(_select_model, choice.name)
    return {"ok": True, "active": choice.name}
