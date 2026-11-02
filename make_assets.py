"""Turn the small pictures in raw_art/ into the 3x pictures the game loads.

Run this on your computer:  python make_assets.py
It writes assets/*.png. raw_art/ is never changed.
"""

import os
import shutil

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw_art")
OUT = os.path.join(HERE, "assets")
SCALE = 3

# Straight copies, only made bigger.
FLAT_NAMES = ["hero", "bat", "slime", "ghost", "demon", "floor", "sword"]

# raw_art/gem.png is a dark navy crystal. We keep its shading and swap the
# colours for a bright ramp: blue gem = XP 1, pink gem = XP 2.
GEM_RAMPS = {
    "gem_blue": ((28, 96, 214), (168, 232, 255)),
    "gem_pink": ((196, 36, 132), (255, 172, 232)),
}


def upscale(image):
    """NEAREST keeps the pixels square: bigger, but not blurry."""
    return image.resize((image.width * SCALE, image.height * SCALE), Image.NEAREST)


def recolour(image, low, high):
    """Shade every visible pixel between `low` (dark) and `high` (bright)."""
    src = image.load()
    width, height = image.size

    def luminance(x, y):
        r, g, b, _ = src[x, y]
        return 0.299 * r + 0.587 * g + 0.114 * b

    visible = [luminance(x, y) for y in range(height) for x in range(width)
               if src[x, y][3] > 0]
    brightest = max(visible) if visible else 1.0
    out = Image.new("RGBA", (width, height))
    dst = out.load()
    for y in range(height):
        for x in range(width):
            _, _, _, alpha = src[x, y]
            if alpha == 0:
                dst[x, y] = (0, 0, 0, 0)
                continue
            t = min(1.0, luminance(x, y) / brightest)
            dst[x, y] = tuple(round(low[i] + (high[i] - low[i]) * t) for i in range(3)) + (255,)
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    shutil.copy(os.path.join(RAW, "LICENSE-Kenney-CC0.txt"), OUT)
    print(f"license -> assets/LICENSE-Kenney-CC0.txt")

    for name in FLAT_NAMES:
        source = Image.open(os.path.join(RAW, name + ".png")).convert("RGBA")
        target = upscale(source)
        target.save(os.path.join(OUT, name + ".png"))
        print(f"{name}.png {source.size[0]}x{source.size[1]} -> "
              f"{target.size[0]}x{target.size[1]}")

    gem = Image.open(os.path.join(RAW, "gem.png")).convert("RGBA")
    for name, (low, high) in GEM_RAMPS.items():
        target = upscale(recolour(gem, low, high))
        target.save(os.path.join(OUT, name + ".png"))
        print(f"gem.png -> {name}.png {target.size[0]}x{target.size[1]}")


if __name__ == "__main__":
    main()
