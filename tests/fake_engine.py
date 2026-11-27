"""시험용 가짜 AI 엔진 — realesrgan-ncnn-vulkan.exe 와 같은 인자를 받아 단순 확대(BICUBIC)만 한다.
진행률은 진짜처럼 표준오류에 「xx.xx%」 줄로 찍는다. 받은 인자는 FAKE_ENGINE_LOG 파일에 남긴다.
FAKE_ENGINE_FAIL=1 이면 실패(종료 코드 255), FAKE_ENGINE_SLOW=초 면 그만큼 천천히(취소 시험)."""
import json
import os
import sys
import time

from PIL import Image

args = sys.argv[1:]
opt = {args[i]: args[i + 1] for i in range(0, len(args) - 1, 2) if args[i].startswith("-")}
if os.environ.get("FAKE_ENGINE_LOG"):
    with open(os.environ["FAKE_ENGINE_LOG"], "a", encoding="utf-8") as f:
        f.write(json.dumps(args, ensure_ascii=False) + "\n")
if os.environ.get("FAKE_ENGINE_FAIL"):
    sys.stderr.write("vkCreateInstance failed -9\n")
    sys.exit(255)
slow = float(os.environ.get("FAKE_ENGINE_SLOW") or 0)
for p in (0, 25, 50, 75):
    sys.stderr.write(f"{p:.2f}%\n")
    sys.stderr.flush()
    time.sleep(slow / 4)
s = int(opt.get("-s", 4))
im = Image.open(opt["-i"])
im.resize((im.width * s, im.height * s), Image.Resampling.BICUBIC).save(opt["-o"])
sys.stderr.write("100.00%\n")
