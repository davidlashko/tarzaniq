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


# ---------------------------------------------------------------- app icon
# macOS app icon: the ape on a chunky rounded jungle tile, in the app's own
# palette. Big Sur proportions (1024 canvas, ~100px margins) so it sits right
# next to other Dock icons; the rounding is done on a coarse 64-cell grid and
# scaled with NEAREST, so even the corners are 8-bit.

ICON_INK = (14, 19, 17)      # --ink
ICON_VINE = (31, 111, 67)    # --vine
ICON_MOSS = (20, 43, 26)     # --moss
ICON_MOSS2 = (15, 35, 21)    # --moss2

GRID = 64          # coarse cells across the 1024 canvas (1 cell = 16px)
MARGIN = 6         # transparent cells around the tile (~96px, Big Sur-ish)
RADIUS = 11        # tile corner radius in cells (~176px at 1024)


def _tile_grid():
    """64x64 cell colours for the rounded tile: None (transparent), ink
    border, vine inner line, moss fill (moss2 on the lower half)."""
    lo, hi = MARGIN, GRID - 1 - MARGIN
    r = RADIUS
    corners = [(lo + r, lo + r), (hi - r, lo + r), (lo + r, hi - r), (hi - r, hi - r)]

    def inside(x, y, inset):
        a, b = lo + inset, hi - inset
        if not (a <= x <= b and a <= y <= b):
            return False
        rr = r - inset
        for cx, cy in corners:
            # only the quarter beyond each corner centre is subject to rounding
            if ((x < cx and cx == lo + r) or (x > cx and cx == hi - r)) and \
               ((y < cy and cy == lo + r) or (y > cy and cy == hi - r)):
                if (x - cx) ** 2 + (y - cy) ** 2 > rr * rr + rr:  # +rr: chunkier
                    return False
        return True

    cells = [[None] * GRID for _ in range(GRID)]
    for y in range(GRID):
        for x in range(GRID):
            if not inside(x, y, 0):
                continue
            if not inside(x, y, 2):
                cells[y][x] = ICON_INK          # 2-cell ink border
            elif not inside(x, y, 3):
                cells[y][x] = ICON_VINE         # 1-cell vine inner line
            else:
                cells[y][x] = ICON_MOSS if y < GRID // 2 else ICON_MOSS2
    return cells


def render_app_icon(size=1024):
    cell = size // GRID
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = img.load()
    for y, row in enumerate(_tile_grid()):
        for x, c in enumerate(row):
            if c is None:
                continue
            for dy in range(cell):
                for dx in range(cell):
                    px[x * cell + dx, y * cell + dy] = c + (255,)
    # the ape, centred on the tile (sprite is 16 cells -> scale 40 = 640px)
    ape = render(GORILLA, scale=size * 40 // 1024)
    img.alpha_composite(ape, ((size - ape.width) // 2, (size - ape.height) // 2))
    return img


def main(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    logo = render(GORILLA, scale=16)
    logo.save(out / "logo.png")
    render(GORILLA, scale=4).save(out / "logo_small.png")
    render(GORILLA, scale=2).save(out / "favicon.png")
    render(BANANA, scale=8).save(out / "banana.png")
    # iconset sizes for macOS .icns — from the rounded-tile app icon.
    # NEAREST keeps big sizes chunky-crisp; LANCZOS keeps 16/32 legible
    # (a pure subsample would alias the 2-cell border away).
    master = render_app_icon(1024)
    for size in (16, 32, 64, 128, 256, 512, 1024):
        interp = Image.NEAREST if size >= 64 else Image.LANCZOS
        master.resize((size, size), interp).save(out / f"icon_{size}.png")
    print(f"assets -> {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else
         Path(__file__).parent / "tarzaniq" / "static" / "img")
