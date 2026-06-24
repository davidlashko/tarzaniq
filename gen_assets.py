"""Generate TarzanIQ's pixel art: the silverback logo, favicon, banana.
Run at install time (and here, to eyeball the result):
    python3 gen_assets.py [outdir]
"""
import sys
from pathlib import Path

from PIL import Image

PALETTE = {
    "K": (16, 20, 23),       # outline
    "D": (52, 58, 64),       # dark fur
    "F": (79, 87, 94),       # fur highlight
    "S": (134, 142, 150),    # silver back/crown
    "T": (125, 101, 83),     # face skin
    "t": (92, 73, 55),       # skin shade
    "W": (242, 239, 230),    # eye white
    "P": (21, 24, 27),       # pupil
    "N": (46, 38, 32),       # nostril
    "G": (63, 163, 77),      # leaf
    "g": (39, 111, 67),      # leaf dark
    "Y": (255, 210, 63),     # banana
    "y": (224, 169, 28),     # banana shade
    "B": (107, 74, 47),      # banana tip / brown
    ".": None,
}

GORILLA = [
    ".....G.G........",
    "......g.........",
    "....KKKKKKKK....",
    "..KKDDDDDDDDKK..",
    ".KDDDDDDDDDDDDK.",
    ".KDDDDDDDDDDDDK.",
    "KDDDTTTTTTTTDDDK",
    "KDDTTPTTTTPTTDDK",
    "KDDTTPTTTTPTTDDK",
    ".KDTTtNTTNtTTDK.",
    ".KDTTTTTTTTTTDK.",
    "..KDTKTTTTKTDK..",
    "..KDTtKKKKtTDK..",
    "...KDDTTTTDDK...",
    "....KKKKKKKK....",
    "................",
]

BANANA = [
    "......BK",
    ".....KYK",
    "....KYYK",
    "...KYYyK",
    "..KYYyK.",
    ".KYYyK..",
    "KYYyK...",
    ".KKK....",
]


def render(grid, scale=16, pad=0):
    h = len(grid)
    w = max(len(r) for r in grid)
    img = Image.new("RGBA", ((w + pad * 2) * scale, (h + pad * 2) * scale),
                    (0, 0, 0, 0))
    px = img.load()
    for y, row in enumerate(grid):
        for x, ch in enumerate(row):
            c = PALETTE.get(ch)
            if c is None:
                continue
            for dy in range(scale):
                for dx in range(scale):
                    px[(x + pad) * scale + dx, (y + pad) * scale + dy] = c + (255,)
    return img


def main(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    logo = render(GORILLA, scale=16)
    logo.save(out / "logo.png")
    render(GORILLA, scale=4).save(out / "logo_small.png")
    render(GORILLA, scale=2).save(out / "favicon.png")
    render(BANANA, scale=8).save(out / "banana.png")
    # iconset sizes for macOS .icns
    for size in (16, 32, 64, 128, 256, 512, 1024):
        im = logo.resize((size, size), Image.NEAREST)
        im.save(out / f"icon_{size}.png")
    print(f"assets -> {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else
         Path(__file__).parent / "tarzaniq" / "static" / "img")
