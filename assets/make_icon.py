from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).parent / "buildforge.ico"
GREEN = (61, 255, 143)
BG = (10, 14, 12)
EDGE = (30, 66, 46)
GRID = (16, 36, 27)

BASE = 1024
img = Image.new("RGBA", (BASE, BASE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

d.rounded_rectangle([16, 16, BASE - 16, BASE - 16], radius=190, fill=BG,
                    outline=EDGE, width=16)
for x in range(160, BASE - 100, 128):
    d.line([(x, 90), (x, BASE - 90)], fill=GRID, width=6)
for y in range(160, BASE - 100, 128):
    d.line([(90, y), (BASE - 90, y)], fill=GRID, width=6)

d.line([(300, 300), (560, 512), (300, 724)], fill=GREEN, width=78,
       joint="curve")
d.rounded_rectangle([610, 690, 800, 742], radius=18, fill=GREEN)
d.rounded_rectangle([300, 806, 800, 846], radius=12, fill=(24, 92, 60))

big = img.resize((256, 256), Image.LANCZOS)
big.save(OUT, format="ICO",
         sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32),
                (24, 24), (16, 16)])
print(OUT, OUT.stat().st_size, "bytes")
