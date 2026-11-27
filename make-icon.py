"""핑크 아이콘(icon.ico, icon.png) 만들기 — 둥근 분홍 사각형 위에 흰 돋보기, 돋보기 안은 작은 화소 → 큰 화소, 반짝이."""
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
S = 512
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((24, 24, S - 24, S - 24), radius=110, fill="#ff8fa3")
d.rounded_rectangle((24, 24, S - 24, S - 24), radius=110, outline="#ff6f8a", width=14)
# 돋보기 손잡이
d.line((330, 330, 420, 420), fill="white", width=46)
d.ellipse((398, 398, 442, 442), fill="white")
# 돋보기 테·유리
d.ellipse((96, 96, 356, 356), fill="white")
d.ellipse((126, 126, 326, 326), fill="#ffe3e9")
# 유리 안: 2×2 큰 화소(확대된 느낌)
cells = [("#ff6f8a", 0, 0), ("#ffb3c1", 1, 0), ("#ffb3c1", 0, 1), ("#ff6f8a", 1, 1)]
x0, y0, c = 166, 166, 60
for color, i, j in cells:
    d.rounded_rectangle((x0 + i * c, y0 + j * c, x0 + (i + 1) * c - 6, y0 + (j + 1) * c - 6), radius=10, fill=color)
# 반짝이
def sparkle(cx, cy, r, fill="white"):
    d.polygon([(cx, cy - r), (cx + r * 0.28, cy - r * 0.28), (cx + r, cy), (cx + r * 0.28, cy + r * 0.28),
               (cx, cy + r), (cx - r * 0.28, cy + r * 0.28), (cx - r, cy), (cx - r * 0.28, cy - r * 0.28)], fill=fill)
sparkle(410, 112, 50)
sparkle(452, 205, 24)
img.save(HERE / "icon.png")
img.save(HERE / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icon.ico, icon.png 저장")
