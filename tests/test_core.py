"""upscale_core 시험 — 진짜 AI 엔진 대신 tests/fake_engine.py 를 끼워 앞뒤 처리를 확인한다.
실행: python -m unittest discover -s tests -v   (PajamaUpscale 폴더에서)"""
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import upscale_core as core  # noqa: E402


def info(path):
    with Image.open(path) as im:
        return im.size, im.mode


class CoreTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.dir = Path(self.td.name) / "한글 폴더 (시험)"
        self.dir.mkdir()
        # 가짜 엔진 폴더(모델 파일 이름만 있으면 준비된 것으로 본다)
        eng = Path(self.td.name) / "engine"
        (eng / "models").mkdir(parents=True)
        (eng / "realesrgan-ncnn-vulkan.exe").write_bytes(b"")
        for n in ("realesrgan-x4plus", "realesrgan-x4plus-anime", "realesr-animevideov3-x2"):
            (eng / "models" / f"{n}.param").write_text("")
        self.log = Path(self.td.name) / "engine.log"
        self.env = {"PAJAMA_UPSCALE_ENGINE_DIR": str(eng), "FAKE_ENGINE_LOG": str(self.log)}
        self.old_env = {k: os.environ.get(k) for k in list(self.env) + ["FAKE_ENGINE_FAIL", "FAKE_ENGINE_SLOW"]}
        os.environ.update(self.env)
        self.old_cmd = core.engine_command
        core.engine_command = lambda: [sys.executable, str(HERE / "fake_engine.py")]

    def tearDown(self):
        core.engine_command = self.old_cmd
        for k, v in self.old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.td.cleanup()

    def img(self, name, size=(40, 30), mode="RGB", **save):
        p = self.dir / name
        color = (200, 80, 120, 128) if mode == "RGBA" else (200, 80, 120)
        Image.new(mode, size, color).save(p, **save)
        return p

    def calls(self):
        return [json.loads(x) for x in self.log.read_text(encoding="utf-8").splitlines()] if self.log.exists() else []

    # ── 경로·설정 ──
    def test_output_path_beside_and_numbering(self):
        src = self.img("고양이 사진.jpg")
        d1 = core.output_path(src, 4, "png")
        self.assertEqual(d1, self.dir / "업스케일" / "고양이 사진_x4.png")
        d1.parent.mkdir()
        d1.write_bytes(b"x")
        self.assertEqual(core.output_path(src, 4, "png").name, "고양이 사진_x4 (2).png")
        self.assertEqual(core.output_path(src, 2, "jpg", "same").parent, self.dir)
        self.assertEqual(core.output_path(src, 3, "webp", "custom", self.td.name), Path(self.td.name) / "고양이 사진_x3.webp")

    def test_collect_images_skips_non_images_and_result_folder(self):
        a = self.img("a.png")
        (self.dir / "메모.txt").write_text("x")
        sub = self.dir / "업스케일"
        sub.mkdir()
        Image.new("RGB", (4, 4)).save(sub / "a_x4.png")
        got = core.collect_images([self.dir, a])
        self.assertEqual(got, [a])

    def test_plan(self):
        self.assertEqual(core.plan("photo", 2), ("realesrgan-x4plus", 4))
        self.assertEqual(core.plan("art", 4), ("realesrgan-x4plus-anime", 4))
        self.assertEqual(core.plan("fast", 3), ("realesr-animevideov3", 3))

    def test_settings_defaults_on_bad_values(self):
        old = core.settings_file
        core.settings_file = lambda: Path(self.td.name) / "settings.json"
        try:
            core.settings_file().write_text('{"model": "없음", "scale": 9, "format": "gif"}', encoding="utf-8")
            s = core.load_settings()
            self.assertEqual((s["model"], s["scale"], s["format"]), ("photo", 4, "png"))
            s["scale"] = 2
            core.save_settings(s)
            self.assertEqual(core.load_settings()["scale"], 2)
        finally:
            core.settings_file = old

    # ── 확대 ──
    def test_upscale_x4_png_korean_path_progress(self):
        src = self.img("한글 이름.png")
        seen = []
        dest = core.upscale(core.Job(src=src, model="photo", scale=4), seen.append)
        self.assertTrue(dest.exists())
        self.assertEqual(info(dest)[0], (160, 120))
        self.assertIn(50.0, seen)
        self.assertEqual(seen[-1], 100.0)
        args = self.calls()[0]
        # 엔진에는 영어 임시 경로만 넘어간다(한글 경로 문제 방지)
        self.assertNotIn("한글", " ".join(args))
        self.assertEqual(args[args.index("-n") + 1], "realesrgan-x4plus")

    def test_scale2_with_x4_model_downscales(self):
        src = self.img("b.jpg", size=(50, 20))
        dest = core.upscale(core.Job(src=src, model="photo", scale=2, fmt="jpg"))
        self.assertEqual(info(dest)[0], (100, 40))
        self.assertEqual(dest.suffix, ".jpg")
        args = self.calls()[0]
        self.assertEqual(args[args.index("-s") + 1], "4")

    def test_fast_model_native_scale(self):
        src = self.img("c.png")
        core.upscale(core.Job(src=src, model="fast", scale=2))
        args = self.calls()[0]
        self.assertEqual(args[args.index("-s") + 1], "2")
        self.assertEqual(args[args.index("-n") + 1], "realesr-animevideov3")

    def test_alpha_kept_png_and_flattened_jpg(self):
        src = self.img("투명.png", mode="RGBA")
        png = core.upscale(core.Job(src=src, scale=2))
        self.assertEqual(info(png)[1], "RGBA")
        jpg = core.upscale(core.Job(src=src, scale=2, fmt="jpg"))
        self.assertEqual(info(jpg)[1], "RGB")

    def test_exif_rotation_applied(self):
        im = Image.new("RGB", (40, 20), (10, 20, 30))
        ex = im.getexif()
        ex[0x0112] = 6  # 90도 돌려 보기
        src = self.dir / "회전.jpg"
        im.save(src, exif=ex)
        self.assertEqual(core.image_size(src), (20, 40))
        dest = core.upscale(core.Job(src=src, scale=2))
        self.assertEqual(info(dest)[0], (40, 80))

    def test_engine_failure_message(self):
        os.environ["FAKE_ENGINE_FAIL"] = "1"
        src = self.img("d.png")
        with self.assertRaises(core.UpscaleError) as cm:
            core.upscale(core.Job(src=src))
        self.assertIn("vkCreateInstance", str(cm.exception))
        self.assertIn("CPU", str(cm.exception))
        self.assertFalse((self.dir / "업스케일").exists() and any((self.dir / "업스케일").iterdir()))

    def test_cpu_option_passes_gpu_minus1(self):
        src = self.img("e.png")
        core.upscale(core.Job(src=src, use_cpu=True))
        args = self.calls()[0]
        self.assertEqual(args[args.index("-g") + 1], "-1")

    def test_cancel(self):
        os.environ["FAKE_ENGINE_SLOW"] = "4"
        src = self.img("f.png")
        job = core.Job(src=src)
        threading.Timer(0.8, job.cancel.set).start()
        with self.assertRaises(core.Cancelled):
            core.upscale(job)
        self.assertFalse((self.dir / "업스케일" / "f_x4.png").exists())

    def test_too_big_refused(self):
        src = self.img("g.png", size=(12000, 10000))
        with self.assertRaises(core.UpscaleError):
            core.upscale(core.Job(src=src, scale=4))
        self.assertEqual(self.calls(), [])

    def test_broken_image(self):
        bad = self.dir / "깨짐.png"
        bad.write_bytes(b"not an image")
        with self.assertRaises(core.UpscaleError):
            core.upscale(core.Job(src=bad))

    def test_engine_missing(self):
        os.environ["PAJAMA_UPSCALE_ENGINE_DIR"] = str(Path(self.td.name) / "없는폴더")
        ok, why = core.engine_ready()
        self.assertFalse(ok)
        self.assertIn("엔진", why)


if __name__ == "__main__":
    unittest.main()
