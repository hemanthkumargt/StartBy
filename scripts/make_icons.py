#!/usr/bin/env python3
"""Regenerates the app icons in app/static/icons with the standard library only
(no Pillow): an emerald rounded square with a white task-stack glyph.

    python scripts/make_icons.py

Outputs icon-192.png, icon-512.png, icon-maskable-512.png (glyph kept inside the
80% safe zone Android masks to) and apple-touch-icon.png (180px, full-bleed
square: iOS applies its own rounding)."""

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "icons"
TOP, BOTTOM = (139, 92, 246), (91, 33, 182)  # violet


def _png(width: int, height: int, rows: list[bytes]) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    raw = b"".join(b"\x00" + row for row in rows)
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _inside_round_rect(x: float, y: float, size: float, radius: float) -> bool:
    cx = min(max(x, radius), size - radius)
    cy = min(max(y, radius), size - radius)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius**2


def _glyph(x: float, y: float, s: float, scale: float) -> bool:
    """Three white rounded bars (a stacked checklist), centred, scaled."""
    u = s / 100.0
    bars = [(26, 28, 74, 40), (26, 46, 74, 58), (26, 64, 58, 76)]  # x0,y0,x1,y1 in a 100 grid
    for x0, y0, x1, y1 in bars:
        cx0 = 50 + (x0 - 50) * scale
        cx1 = 50 + (x1 - 50) * scale
        cy0 = 50 + (y0 - 52) * scale
        cy1 = 50 + (y1 - 52) * scale
        r = (cy1 - cy0) / 2 * u
        left, right, top, bottom = cx0 * u, cx1 * u, cy0 * u, cy1 * u
        px = min(max(x, left + r), right - r)
        py = (top + bottom) / 2
        if (
            left <= x <= right
            and top <= y <= bottom
            and (x - px) ** 2 + (y - py) ** 2 <= r**2 + 1e-9
        ):
            return True
    return False


def render(size: int, *, rounded: bool, glyph_scale: float, samples: int = 3) -> bytes:
    rows = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            r = g = b = a = 0.0
            for sy in range(samples):
                for sx in range(samples):
                    x = px + (sx + 0.5) / samples
                    y = py + (sy + 0.5) / samples
                    if rounded and not _inside_round_rect(x, y, size, size * 0.225):
                        continue
                    t = y / size
                    base = [TOP[i] + (BOTTOM[i] - TOP[i]) * t for i in range(3)]
                    colour = (255, 255, 255) if _glyph(x, y, size, glyph_scale) else base
                    r += colour[0]
                    g += colour[1]
                    b += colour[2]
                    a += 255
            n = samples * samples
            alpha = a / n
            if alpha == 0:
                row += bytes((0, 0, 0, 0))
            else:
                covered = a / 255
                row += bytes(
                    (round(r / covered), round(g / covered), round(b / covered), round(alpha))
                )
        rows.append(bytes(row))
    return _png(size, size, rows)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "icon-192.png").write_bytes(render(192, rounded=True, glyph_scale=1.0))
    (OUT / "icon-512.png").write_bytes(render(512, rounded=True, glyph_scale=1.0))
    (OUT / "icon-maskable-512.png").write_bytes(render(512, rounded=False, glyph_scale=0.78))
    (OUT / "apple-touch-icon.png").write_bytes(render(180, rounded=False, glyph_scale=0.9))
    print("wrote", sorted(p.name for p in OUT.iterdir()))
