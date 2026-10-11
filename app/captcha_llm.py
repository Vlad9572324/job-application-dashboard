"""Local CRNN captcha recognition.

The module name is retained for existing imports/settings. Captcha images never
leave this process for recognition; cloud LLM profiles are not used here.
"""
import logging
import re
import threading
from functools import lru_cache

logger = logging.getLogger(__name__)
_WORDS = re.compile(r"[а-яё]+(?: [а-яё]+){1,2}")
_inference_lock = threading.Lock()


def _normalize(text):
    value = " ".join(str(text or "").strip().strip("\"'«»").lower().split())
    return value if 3 <= len(value) <= 40 and _WORDS.fullmatch(value) else None


@lru_cache(maxsize=1)
def _local_model():
    from app.captcha_predict import load_model
    return load_model()


def _local_answer(image_bytes):
    if not image_bytes:
        return None
    try:
        from app.captcha_predict import predict_bytes
        with _inference_lock:
            return _normalize(predict_bytes(image_bytes, _local_model()))
    except Exception as exc:
        logger.warning('Local captcha recognition failed (%s)', type(exc).__name__)
        return None


def recognize_captcha(image_bytes: bytes) -> str | None:
    return _local_answer(image_bytes)
