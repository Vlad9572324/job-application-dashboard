"""Uploading and selecting local CAPTCHA models preserves the active model."""

import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import captcha_models
from app.config import CONFIG
from app.routes import captcha_models as routes


def _client(monkeypatch, tmp_path, loader):
    root = tmp_path / "captcha"
    root.mkdir()
    (root / "model.pt").write_bytes(b"default")
    (root / "charset.txt").write_text("аб в", encoding="utf-8")
    monkeypatch.setattr(captcha_models, "MODEL_ROOT", root)
    monkeypatch.setattr(routes, "MODEL_ROOT", root)
    monkeypatch.setattr(CONFIG, "captcha_model_name", "default")
    monkeypatch.setattr(routes, "save_config", lambda: None)
    monkeypatch.setitem(sys.modules, "app.captcha_predict", SimpleNamespace(load_model=loader))
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app), root


def test_upload_then_select_model(monkeypatch, tmp_path):
    validated = []

    def load_model(weights, charset):
        validated.append((Path(weights).read_bytes(), Path(charset).read_text()))
        return object()

    client, root = _client(monkeypatch, tmp_path, load_model)
    response = client.post("/api/captcha/models", data={"name": "v2"},
                           files={"weights": ("new.pt", b"new-weights", "application/octet-stream")})
    assert response.status_code == 200
    assert response.json()["active"] == "default"
    assert validated == [(b"new-weights", "аб в")]
    assert (root / "v2" / "model.pt").read_bytes() == b"new-weights"
    assert [item["name"] for item in client.get("/api/captcha/models").json()["models"]] == ["default", "v2"]

    custom = client.post("/api/captcha/models", data={"name": "v3"}, files={
        "weights": ("new.pt", b"other-weights", "application/octet-stream"),
        "charset": ("charset.txt", "абв ".encode(), "text/plain"),
    })
    assert custom.status_code == 200
    assert validated[-1] == (b"other-weights", "абв ")
    assert (root / "v3" / "charset.txt").read_text() == "абв "
    duplicate = client.post("/api/captcha/models", data={"name": "v3"},
                            files={"weights": ("new.pt", b"new", "application/octet-stream")})
    assert duplicate.status_code == 409

    selected = client.post("/api/captcha/models/select", json={"name": "v2"})
    assert selected.status_code == 200
    assert selected.json()["active"] == CONFIG.captcha_model_name == "v2"
    assert validated[-1] == (b"new-weights", "аб в")


def test_invalid_upload_cannot_replace_active_model(monkeypatch, tmp_path):
    def reject(*_args):
        raise ValueError("bad checkpoint")

    client, root = _client(monkeypatch, tmp_path, reject)
    invalid = client.post("/api/captcha/models", data={"name": "bad"},
                          files={"weights": ("bad.pt", b"bad", "application/octet-stream")})
    assert invalid.status_code == 400
    assert not (root / "bad").exists()
    assert CONFIG.captcha_model_name == "default"

    traversal = client.post("/api/captcha/models", data={"name": "../outside"},
                            files={"weights": ("bad.pt", b"bad", "application/octet-stream")})
    assert traversal.status_code == 400
    assert client.post("/api/captcha/models/select", json={"name": "missing"}).status_code == 404
