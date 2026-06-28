"""Deterministic GitHub-style identicon (0028).

A 5×5 left-right-mirrored grid of squares, colored from a hash of a seed (the
user's email/id), on a light background. Pure + deterministic — same seed always
yields the same SVG, so a user's default avatar is stable without storing
anything. Returned as an SVG string (served with image/svg+xml)."""

from __future__ import annotations

import hashlib

_GRID = 5          # cells per side (GitHub uses 5)
_PAD = 0.5         # padding in cell units around the grid


def _digest(seed: str) -> bytes:
    return hashlib.sha256(seed.encode("utf-8")).digest()


def _color(d: bytes) -> str:
    """A pleasant, saturated foreground from the hash — HSL with fixed S/L."""
    hue = int.from_bytes(d[:2], "big") % 360
    return f"hsl({hue}, 62%, 52%)"


def identicon_svg(seed: str, size: int = 240) -> str:
    """Render a stable identicon for `seed` as an SVG string sized `size`×`size`."""
    d = _digest(seed or "?")
    fg = _color(d)
    bg = "hsl(220, 14%, 94%)"

    cells = _GRID + _PAD * 2
    cell = size / cells
    half = (_GRID + 1) // 2  # columns we actually decide (mirror the rest)

    rects: list[str] = []
    for col in range(half):
        for row in range(_GRID):
            # One bit per (col, row) from the digest; deterministic + well-spread.
            bit = d[(col * _GRID + row) % len(d)]
            if bit & 1:
                for c in (col, _GRID - 1 - col):  # mirror across the vertical axis
                    x = (_PAD + c) * cell
                    y = (_PAD + row) * cell
                    rects.append(
                        f'<rect x="{x:.2f}" y="{y:.2f}" width="{cell:.2f}" '
                        f'height="{cell:.2f}" fill="{fg}"/>'
                    )

    body = "".join(rects)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}" role="img">'
        f'<rect width="{size}" height="{size}" rx="{size * 0.12:.0f}" fill="{bg}"/>'
        f"{body}</svg>"
    )
