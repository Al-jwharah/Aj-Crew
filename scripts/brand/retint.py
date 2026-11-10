#!/usr/bin/env python3
"""Move violet, indigo and purple artwork into the brand's teal.

    python scripts/brand/retint.py <svg file or folder> [...]

The app catalogue's illustrations were drawn against the old purple theme. This
turns every hex colour whose hue sits in that band to the accent's hue, keeping
how light it is (so text on it reads as before) and as much of its strength as
teal can carry at that lightness. Colours outside the band are left alone, so a
second run changes nothing.
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path

# OKLCH hue, in degrees. Blue ends near 262 and pink starts near 320; what lies
# between is the old theme: indigo (277), violet (293), purple (304).
BAND = (268.0, 314.0)
TEAL_HUE = 181.0  # the accent #2DD4BF
MIN_CHROMA = 0.012  # below this a colour is a grey and its hue is noise
GROUND_CHROMA, GROUND_LIGHT = 0.085, 0.42  # dark, faintly tinted fills: grounds
GROUND_KEEP = 0.55  # how much tint a ground keeps: the brand's ground is ink

_HEX = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-fA-F])")


def _to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _to_srgb(c: float) -> float:
    return c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _oklch(r: float, g: float, b: float) -> tuple[float, float, float]:
    r, g, b = _to_linear(r), _to_linear(g), _to_linear(b)
    l_ = math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m_ = math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s_ = math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    light = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    b2 = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    return light, math.hypot(a, b2), math.degrees(math.atan2(b2, a)) % 360


def _rgb(light: float, chroma: float, hue: float) -> tuple[float, float, float]:
    a, b = chroma * math.cos(math.radians(hue)), chroma * math.sin(math.radians(hue))
    l_ = (light + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (light - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (light - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (
        4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
        -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
        -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_,
    )


def _in_gamut(rgb: tuple[float, float, float]) -> bool:
    return all(-1e-4 <= c <= 1 + 1e-4 for c in rgb)


def retint_hex(text: str) -> str:
    """One ``#rgb`` / ``#rrggbb`` / ``#rrggbbaa`` colour, moved if it is in the band."""
    digits = text[1:]
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    red, green, blue = (int(digits[i : i + 2], 16) / 255 for i in (0, 2, 4))
    light, chroma, hue = _oklch(red, green, blue)
    if chroma < MIN_CHROMA or not BAND[0] <= hue <= BAND[1]:
        return text
    if chroma < GROUND_CHROMA and light < GROUND_LIGHT:
        chroma *= GROUND_KEEP
    out = _rgb(light, chroma, TEAL_HUE)
    while not _in_gamut(out) and chroma > 0:
        chroma = max(0.0, chroma - 0.002)
        out = _rgb(light, chroma, TEAL_HUE)
    body = "".join(f"{round(min(1, max(0, _to_srgb(max(0, c)))) * 255):02x}" for c in out)
    upper = digits[:6].isupper() or (text[1:].isupper() and not text[1:].isdigit())
    return "#" + (body.upper() if upper else body) + digits[6:]


def retint_text(svg: str) -> str:
    return _HEX.sub(lambda m: retint_hex(m.group(0)), svg)


def retint_tree(*paths: Path) -> list[Path]:
    """Rewrite every SVG under ``paths``; returns the files that changed."""
    changed = []
    for path in paths:
        files = sorted(path.rglob("*.svg")) if path.is_dir() else [path]
        for file in files:
            before = file.read_text(encoding="utf-8")
            after = retint_text(before)
            if after != before:
                file.write_text(after, encoding="utf-8")
                changed.append(file)
    return changed


if __name__ == "__main__":
    for done in retint_tree(*(Path(arg) for arg in sys.argv[1:])):
        print("retinted", done)
