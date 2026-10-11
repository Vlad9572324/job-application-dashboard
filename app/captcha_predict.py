"""Read RU arc-text captchas (two words) with the trained CRNN+CTC model. CPU is enough.

pip install torch pillow
python predict.py img1.png img2.png ...
python predict.py folder/            # every png in the folder
"""
import glob, os, sys
from pathlib import Path
import numpy as np
import torch, torch.nn as nn
from PIL import Image

MODEL_DIR = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
             else Path(__file__).resolve().parent.parent) / "models" / "captcha"
MODEL_PATH = MODEL_DIR / "model.pt"
H, W = 90, 250


def _selected_paths():
    from app.config import CONFIG
    from app.captcha_models import model_paths
    return model_paths(CONFIG.captcha_model_name)


def block(i, o, pool):
    layers = [nn.Conv2d(i, o, 3, padding=1, bias=False), nn.BatchNorm2d(o), nn.ReLU(inplace=True)]
    if pool:
        layers.append(nn.MaxPool2d(pool))
    return nn.Sequential(*layers)


class CRNN(nn.Module):
    def __init__(self, nc, width=1, hidden=256, layers=2):
        super().__init__()
        c = [32 * width, 64 * width, 128 * width, 128 * width, 192 * width, 192 * width]
        self.cnn = nn.Sequential(block(1, c[0], 2), block(c[0], c[1], 2), block(c[1], c[2], None),
                                 block(c[2], c[3], (2, 1)), block(c[3], c[4], None), block(c[4], c[5], (2, 1)))
        self.drop = nn.Dropout(.25)
        self.rnn = nn.LSTM(c[5] * 5, hidden, num_layers=layers, bidirectional=True, batch_first=True, dropout=.25)
        self.fc = nn.Linear(hidden * 2, nc)

    def forward(self, x):
        f = self.cnn((x - .5) / .25)
        B, C, h, w = f.shape
        f = f.permute(0, 3, 1, 2).reshape(B, w, C * h)
        f, _ = self.rnn(self.drop(f))
        return self.fc(self.drop(f))


def load_model(path=None, charset_path=None):
    if path is None:
        path, selected_charset = _selected_paths()
        charset_path = charset_path or selected_charset
    else:
        path = Path(path)
        charset_path = charset_path or path.parent / "charset.txt"
    charset = Path(charset_path).read_text(encoding="utf-8")
    if not 2 <= len(charset) <= 200 or len(set(charset)) != len(charset) or any(c in charset for c in "\r\n\x00"):
        raise ValueError("Invalid captcha model charset")
    ck = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(ck, dict) or not isinstance(ck.get("cfg"), dict) or not isinstance(ck.get("model"), dict):
        raise ValueError("Invalid captcha model checkpoint")
    cfg = ck["cfg"]
    width, hidden, layers = (cfg.get("width", 1), cfg.get("hidden", 256), cfg.get("layers", 2))
    if (set(cfg) - {"width", "hidden", "layers"}
            or any(type(value) is not int for value in (width, hidden, layers))
            or not (1 <= width <= 4 and 32 <= hidden <= 512 and 1 <= layers <= 4)):
        raise ValueError("Unsupported captcha model architecture")
    m = CRNN(len(charset) + 1, **cfg)
    m.load_state_dict(ck["model"])
    m._captcha_i2c = {i + 1: c for i, c in enumerate(charset)}  # 0 = CTC blank
    return m.eval()


def decode(logits, i2c):  # greedy CTC, no TTA (averaging views breaks CTC)
    out = []
    for seq in logits.argmax(-1).numpy():
        s, prev = [], 0
        for i in seq:
            if i != prev and i != 0:
                s.append(i2c[i])
            prev = i
        out.append("".join(s))
    return out


@torch.no_grad()
def predict(paths, model=None, bs=64):
    model = model or load_model()
    res = []
    for i in range(0, len(paths), bs):
        ch = paths[i:i + bs]
        x = np.stack([np.asarray(Image.open(p).convert("L").resize((W, H))) for p in ch])
        x = torch.from_numpy(x)[:, None].float() / 255
        res += decode(model(x), model._captcha_i2c)
    return res


def predict_bytes(image_bytes, model=None):
    import io
    model = model or load_model()
    with Image.open(io.BytesIO(image_bytes)) as image:
        x = np.asarray(image.convert("L").resize((W, H)))
    tensor = torch.from_numpy(x.copy())[None, None].float() / 255
    with torch.no_grad():
        return decode(model(tensor), model._captcha_i2c)[0]


if __name__ == "__main__":
    args = sys.argv[1:] or ["."]
    paths = []
    for a in args:
        paths += sorted(glob.glob(os.path.join(a, "*.png"))) if os.path.isdir(a) else [a]
    for p, t in zip(paths, predict(paths)):
        print(f"{os.path.basename(p)}\t{t}")
