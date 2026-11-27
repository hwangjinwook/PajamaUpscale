"""파자마업스케일(PajamaUpscale) — 처리 부분(화면 없음, 시험 가능).

AI 확대는 Real-ESRGAN 의 단독 실행 판(realesrgan-ncnn-vulkan.exe, engine 폴더)이 그래픽카드(Vulkan)로 한다.
이 파일은 그 앞뒤를 맡는다:
  1) 원본을 Pillow 로 열어 사진 회전 정보(EXIF)를 바로잡고, 영어 이름의 임시 PNG 로 만든다
     (한글·특수문자 경로, JPG 회전, 팔레트 PNG 등을 엔진이 헷갈리지 않게)
  2) 엔진으로 확대 — 진행률(xx.xx%)을 읽어 알린다, 취소하면 엔진을 끈다
  3) 결과를 원하는 배율로 맞추고(4배 전용 모델로 2·3배를 원하면 4배로 키운 뒤 고품질로 줄임) 원하는 형식으로 저장
화면 스레드와 섞이지 않게 tk 는 전혀 쓰지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = None  # 사장님 본인 이미지라 큰 그림 경고(압축 폭탄 방지)를 끈다 — 대신 아래 MAX_OUT_PIXELS 로 막는다

APP_NAME = "파자마업스케일"
VERSION = "1.0.0"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
# 결과가 이보다 크면(약 4억 화소, 예: 20000×20000) 메모리가 모자랄 수 있어 미리 막는다
MAX_OUT_PIXELS = 400_000_000


@dataclass(frozen=True)
class Model:
    key: str
    label: str
    name: str            # 엔진 모델 이름(engine/models/<name>.param)
    scales: tuple        # 엔진이 바로 낼 수 있는 배율
    hint: str


MODELS = [
    Model("photo", "사진·실사", "realesrgan-x4plus", (4,), "사람·풍경·제품 사진. 가장 선명하고 자연스러워요"),
    Model("art", "그림·애니·일러스트", "realesrgan-x4plus-anime", (4,), "선이 또렷한 그림·만화·캐릭터·게임 그림"),
    Model("fast", "빠르게(가벼운 애니 모델)", "realesr-animevideov3", (2, 3, 4), "많은 장을 빨리 처리할 때. 그림에 알맞아요"),
]
MODEL_BY_KEY = {m.key: m for m in MODELS}
SCALES = (2, 3, 4)
FORMATS = {"png": ".png", "jpg": ".jpg", "webp": ".webp"}


# ── 위치 ─────────────────────────────────────────────

def app_dir() -> Path:
    """exe 로 실행하면 exe 옆, 파이썬으로 실행하면 이 파일 옆."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def engine_dir() -> Path:
    return Path(os.environ.get("PAJAMA_UPSCALE_ENGINE_DIR") or app_dir() / "engine")


def engine_exe() -> Path:
    return engine_dir() / "realesrgan-ncnn-vulkan.exe"


def engine_command() -> list[str]:
    """엔진 실행 명령의 앞부분. 시험에서는 가짜 엔진(tests/fake_engine.py)으로 바꿔 끼운다."""
    return [str(engine_exe())]


def engine_ready() -> tuple[bool, str]:
    exe = engine_exe()
    if not exe.exists():
        return False, f"AI 엔진이 없어요: {exe}"
    missing = [m.name for m in MODELS if not (engine_dir() / "models" / f"{m.name}.param").exists()
               and not any((engine_dir() / "models" / f"{m.name}-x{s}.param").exists() for s in m.scales)]
    if missing:
        return False, "모델 파일이 없어요: " + ", ".join(missing)
    return True, "준비됨"


# ── 설정 ─────────────────────────────────────────────

DEFAULTS = {"model": "photo", "scale": 4, "format": "png", "jpg_quality": 95,
            "out_mode": "beside", "out_dir": "", "use_cpu": False}


def settings_file() -> Path:
    return app_dir() / "settings.json"


def load_settings() -> dict:
    s = dict(DEFAULTS)
    try:
        s.update(json.loads(settings_file().read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    if s.get("model") not in MODEL_BY_KEY:
        s["model"] = DEFAULTS["model"]
    if s.get("scale") not in SCALES:
        s["scale"] = DEFAULTS["scale"]
    if s.get("format") not in FORMATS:
        s["format"] = DEFAULTS["format"]
    return s


def save_settings(s: dict) -> None:
    try:
        tmp = settings_file().with_suffix(".tmp")
        tmp.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(settings_file())
    except OSError:
        pass


# ── 파일 고르기·이름 ───────────────────────────────────

def collect_images(paths) -> list[Path]:
    """파일·폴더(하위 폴더 포함)에서 이미지만 모은다. 순서 유지, 중복 제거."""
    out, seen = [], set()

    def add(p: Path):
        key = str(p.resolve()).lower()
        if key not in seen and p.suffix.lower() in IMAGE_EXTS and p.is_file():
            seen.add(key)
            out.append(p)

    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                # 이 앱이 만든 결과 폴더는 다시 넣지 않는다
                if "업스케일" in f.parent.name and f.parent != p:
                    continue
                add(f)
        else:
            add(p)
    return out


def output_path(src: Path, scale: int, fmt: str, out_mode: str = "beside", out_dir: str = "") -> Path:
    """결과 파일 경로. 기본은 원본 옆 「업스케일」 폴더에 「이름_x4.png」. 같은 이름이 있으면 (2), (3)…"""
    if out_mode == "custom" and out_dir:
        folder = Path(out_dir)
    elif out_mode == "same":
        folder = src.parent
    else:
        folder = src.parent / "업스케일"
    ext = FORMATS.get(fmt, ".png")
    base = f"{src.stem}_x{scale}"
    dest = folder / f"{base}{ext}"
    n = 2
    while dest.exists():
        dest = folder / f"{base} ({n}){ext}"
        n += 1
    return dest


def image_size(path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(path) as im:
            w, h = im.size
            # 사진 회전 정보가 90도면 가로세로가 바뀐다
            o = im.getexif().get(0x0112)
            return (h, w) if o in (5, 6, 7, 8) else (w, h)
    except (OSError, ValueError):
        return None


def plan(model_key: str, scale: int) -> tuple[str, int]:
    """(엔진 모델 이름, 엔진 배율). 모델이 그 배율을 못 내면 4배로 키운 뒤 줄인다."""
    # 배율이 여럿인 모델(realesr-animevideov3)은 엔진이 -s 를 보고 -x2/-x3/-x4 모델 파일을 알아서 고른다.
    m = MODEL_BY_KEY[model_key]
    native = scale if scale in m.scales else max(m.scales)
    return m.name, native


# ── 처리 ─────────────────────────────────────────────

class Cancelled(Exception):
    pass


class UpscaleError(Exception):
    pass


@dataclass
class Job:
    src: Path
    model: str = "photo"
    scale: int = 4
    fmt: str = "png"
    jpg_quality: int = 95
    out_mode: str = "beside"
    out_dir: str = ""
    use_cpu: bool = False
    cancel: threading.Event = field(default_factory=threading.Event)


_PCT = re.compile(r"(\d+(?:\.\d+)?)%")


def _prepare(src: Path, tmp: Path) -> tuple[Path, bool, tuple[int, int], dict]:
    """원본 → 임시 PNG(회전 바로잡음). (임시 경로, 투명 여부, 크기, 저장 때 되살릴 정보)"""
    try:
        with Image.open(src) as raw:  # 원본 파일을 붙잡고 있지 않게 바로 닫는다
            if getattr(raw, "n_frames", 1) > 1:
                raw.seek(0)  # 움직이는 GIF·WebP 는 첫 장만
            raw.load()
            keep = {"icc_profile": raw.info.get("icc_profile"), "dpi": raw.info.get("dpi")}
            im = ImageOps.exif_transpose(raw)
            alpha = im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)
            im = im.convert("RGBA" if alpha else "RGB")
    except (OSError, ValueError) as e:
        raise UpscaleError("이미지를 열 수 없어요 — 손상됐거나 지원하지 않는 형식이에요.") from e
    path = tmp / "in.png"
    im.save(path)
    return path, alpha, im.size, keep


def _run_engine(cmd: list[str], job: Job, on_progress: Callable[[float], None]) -> None:
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                creationflags=flags, cwd=str(engine_dir()))
    except OSError as e:
        raise UpscaleError(f"AI 엔진을 실행하지 못했어요: {e}") from e
    tail: list[str] = []
    killer = threading.Thread(target=_watch_cancel, args=(proc, job.cancel), daemon=True)
    killer.start()
    buf = b""
    while True:
        ch = proc.stderr.read(1)
        if not ch:
            break
        if ch in (b"\n", b"\r"):
            line = buf.decode("utf-8", "replace").strip()
            buf = b""
            if not line:
                continue
            m = _PCT.fullmatch(line)
            if m:
                on_progress(min(100.0, float(m.group(1))))
            else:
                tail = (tail + [line])[-6:]
        else:
            buf += ch
    proc.stderr.close()
    code = proc.wait()
    if job.cancel.is_set():
        raise Cancelled()
    if code != 0:
        msg = " / ".join(tail[-3:]) or f"종료 코드 {code}"
        hint = "" if job.use_cpu else " 그래픽카드 문제라면 설정에서 「그래픽카드 대신 CPU 로」를 켜 보세요(느려요)."
        raise UpscaleError(f"AI 엔진이 실패했어요: {msg}.{hint}")


def _watch_cancel(proc: subprocess.Popen, cancel: threading.Event) -> None:
    while proc.poll() is None:
        if cancel.wait(0.2):
            try:
                proc.kill()
            except OSError:
                pass
            return


def _finish(tmp_out: Path, dest: Path, job: Job, src_size: tuple[int, int], alpha: bool, keep: dict) -> tuple[int, int]:
    try:
        with Image.open(tmp_out) as raw:  # 임시 폴더를 지울 수 있게 바로 닫는다
            im = raw.copy()
    except (OSError, ValueError) as e:
        raise UpscaleError("AI 엔진이 결과 이미지를 만들지 못했어요.") from e
    want = (src_size[0] * job.scale, src_size[1] * job.scale)
    if im.size != want:
        im = im.resize(want, Image.Resampling.LANCZOS)
    if alpha and im.mode != "RGBA":
        im = im.convert("RGBA")
    dest.parent.mkdir(parents=True, exist_ok=True)
    opts = {}
    if keep.get("icc_profile"):
        opts["icc_profile"] = keep["icc_profile"]
    if keep.get("dpi"):
        opts["dpi"] = keep["dpi"]
    part = dest.with_name(dest.name + ".part")
    if job.fmt == "jpg":
        if im.mode == "RGBA":  # JPG 는 투명이 없어 흰 바탕에 얹는다
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.getchannel("A"))
            im = bg
        im.convert("RGB").save(part, "JPEG", quality=int(job.jpg_quality), subsampling=0, optimize=True, **opts)
    elif job.fmt == "webp":
        im.save(part, "WEBP", quality=int(job.jpg_quality), method=4, **opts)
    else:
        im.save(part, "PNG", **opts)
    os.replace(part, dest)
    return im.size


def upscale(job: Job, on_progress: Callable[[float], None] = lambda p: None) -> Path:
    """한 장 확대. 결과 경로를 돌려준다. 실패하면 UpscaleError, 취소하면 Cancelled."""
    ok, why = engine_ready()
    if not ok:
        raise UpscaleError(why)
    model_name, native = plan(job.model, job.scale)
    with tempfile.TemporaryDirectory(prefix="pajama-upscale-") as td:
        tmp = Path(td)
        tmp_in, alpha, size, keep = _prepare(job.src, tmp)
        if size[0] * size[1] * job.scale * job.scale > MAX_OUT_PIXELS:
            raise UpscaleError(f"결과가 너무 커요({size[0] * job.scale}×{size[1] * job.scale}). 배율을 낮춰 주세요.")
        tmp_out = tmp / "out.png"
        cmd = [*engine_command(), "-i", str(tmp_in), "-o", str(tmp_out), "-n", model_name, "-s", str(native),
               "-m", str(engine_dir() / "models"), "-f", "png"]
        if job.use_cpu:
            cmd += ["-g", "-1"]
        on_progress(0.0)
        _run_engine(cmd, job, on_progress)
        if job.cancel.is_set():
            raise Cancelled()
        dest = output_path(job.src, job.scale, job.fmt, job.out_mode, job.out_dir)
        _finish(tmp_out, dest, job, size, alpha, keep)
        on_progress(100.0)
        return dest


def open_in_explorer(path: Path) -> None:
    """탐색기에서 그 파일을 선택해 보여 준다(폴더면 연다)."""
    try:
        if path.is_file():
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            os.startfile(str(path))  # type: ignore[attr-defined]
    except OSError:
        pass
