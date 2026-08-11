"""Regenerate the brand favicon from the design tokens.

Committed next to the PNG it produces so the asset has provenance: the mark is
derived from the tokens, not drawn by hand in a tool nobody else has. Run with
``uv run python app/streamlit_app/assets/make_favicon.py`` after a token change.

The mark is a north-east arrow — relocation, and a market moving up — in sand
on petrol. Deliberately one shape and two colours: at 16px, anything more
(initials, a compass rose) turns to mush.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

PETROL_900 = "#274C56"
SAND_100 = "#F6E2B3"
RUST_500 = "#D96C2C"

SIZE = 512  # rendered big, downsampled for clean antialiasing
OUT = Path(__file__).with_name("favicon.png")


def build() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=int(SIZE * 0.22), fill=PETROL_900)

    # Shaft of the arrow, bottom-left to top-right.
    w = int(SIZE * 0.10)
    d.line([(SIZE * 0.28, SIZE * 0.72), (SIZE * 0.70, SIZE * 0.30)], fill=SAND_100, width=w)
    # Arrow head as a filled triangle at the top-right.
    d.polygon(
        [
            (SIZE * 0.74, SIZE * 0.26),
            (SIZE * 0.74, SIZE * 0.53),
            (SIZE * 0.47, SIZE * 0.26),
        ],
        fill=SAND_100,
    )
    # Rust anchor dot at the origin — the deterministic signal the arrow starts from.
    r = SIZE * 0.075
    d.ellipse(
        [SIZE * 0.28 - r, SIZE * 0.72 - r, SIZE * 0.28 + r, SIZE * 0.72 + r],
        fill=RUST_500,
    )
    return img.resize((256, 256), Image.Resampling.LANCZOS)


if __name__ == "__main__":
    build().save(OUT)
    print(f"wrote {OUT}")
