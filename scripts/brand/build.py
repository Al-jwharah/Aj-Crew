#!/usr/bin/env python3
"""Build every Aj Crew brand asset from one definition of the gem mark.

    python scripts/brand/build.py <repo-root>

Writes the SVG sources and their rasters (PNG, ICO, ICNS, BMP, TIFF) into the
checkout. Needs: fonttools, uharfbuzz, pillow, Node with Playwright's Chromium
(only to rasterise SVG), and the Sora variable font: put ``Sora.ttf`` next to
this file or point ``AJ_BRAND_FONT`` at it. Text is converted to outlines, so no
asset depends on a font being installed. See README.md in this directory.
"""

from __future__ import annotations

import io
import json
import os
import plistlib
import re
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

import mark
import mascot
import petclips
from PIL import Image
from textpath import text_path

HERE = Path(__file__).resolve().parent
FONT = os.environ.get("AJ_BRAND_FONT") or str(HERE / "Sora.ttf")
NODE = os.environ.get("NODE", "node")

INK = "#0B0C0F"
INK_TOP, INK_BOTTOM = "#1C1D22", "#08090B"
PAPER = "#F4F5F7"
TEAL = "#2DD4BF"
AMBER = "#FBBF24"
FACETS = {
    "crown_left": "#BFC5CE",
    "table": "#FFFFFF",
    "crown_right": "#E3E6EB",
    "pav_left": "#8E96A3",
    "pav_center": TEAL,
    "pav_right": "#AEB5C0",
}
FACETS_NIGHTLY = dict(FACETS, pav_center=AMBER)
# On a light ground the gem is drawn in ink, the accent facet stays.
FACETS_ON_PAPER = {
    "crown_left": "#3A3D45",
    "table": "#0B0C0F",
    "crown_right": "#23252B",
    "pav_left": "#5A5E68",
    "pav_center": "#0FB5A0",
    "pav_right": "#474A53",
}

# The gem's own box on the 1024 canvas, and its centre.
GEM_X0, GEM_Y0, GEM_X1, GEM_Y1 = 232.0, 306.0, 792.0, 792.0
GEM_W, GEM_H = GEM_X1 - GEM_X0, GEM_Y1 - GEM_Y0
GEM_CX, GEM_CY = (GEM_X0 + GEM_X1) / 2, (GEM_Y0 + GEM_Y1) / 2


def gem(shades, cx, cy, width, gap=10.0, digits=2):
    """The gem as SVG, ``width`` wide and centred on (cx, cy)."""
    k = width / GEM_W
    paths = mark.facet_paths(
        gap=gap, scale=k, dx=cx - GEM_CX * k, dy=cy - GEM_CY * k, digits=digits
    )
    return "".join(f'<path d="{paths[n]}" fill="{shades[n]}"/>' for n in mark.ORDER)


def gem_mono(cx, cy, width, gap=10.0, fill="#000", digits=2):
    """The gem as one path in a single colour (for masks and template images)."""
    k = width / GEM_W
    paths = mark.facet_paths(
        gap=gap, scale=k, dx=cx - GEM_CX * k, dy=cy - GEM_CY * k, digits=digits
    )
    return f'<path fill="{fill}" d="{"".join(paths[n] for n in mark.ORDER)}"/>'


def star(cx, cy, r, fill="#fff", opacity=1.0):
    """A four-point glint."""
    q = r * 0.22
    d = f"M{cx} {cy - r}L{cx + q} {cy - q}L{cx + r} {cy}L{cx + q} {cy + q}L{cx} {cy + r}L{cx - q} {cy + q}L{cx - r} {cy}L{cx - q} {cy - q}Z"
    return f'<path d="{d}" fill="{fill}" opacity="{opacity}"/>'


def wordmark(size, fill, x=0.0, baseline=0.0, weight=600, tracking=None, text="Aj Crew"):
    tracking = -size * 0.008 if tracking is None else tracking
    d, width, cap = text_path(text, FONT, size, {"wght": weight}, tracking=tracking)
    return f'<path transform="translate({x:g} {baseline:g})" fill="{fill}" d="{d}"/>', width, cap


def svg(w, h, body, defs="", title=None, vb=None, extra=""):
    vb = vb or f"0 0 {w} {h}"
    head = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="{vb}"{extra}>'
    )
    t = f"<title>{title}</title>" if title else ""
    d = f"<defs>{defs}</defs>" if defs else ""
    return f"{head}{t}{d}{body}</svg>\n"


# --------------------------------------------------------------------------- #
# Icons
# --------------------------------------------------------------------------- #


def _tile_defs(nightly):
    top, bottom = ("#1B1E33", "#090A14") if nightly else (INK_TOP, INK_BOTTOM)
    return (
        f'<linearGradient id="tile" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{top}"/><stop offset="1" stop-color="{bottom}"/></linearGradient>'
    )


def _night_sky(scale=1.0, ox=0.0, oy=0.0):
    pts = [
        (270, 250, 20, 0.9),
        (770, 236, 26, 1.0),
        (812, 600, 15, 0.7),
        (214, 640, 17, 0.75),
        (690, 800, 12, 0.6),
        (350, 820, 10, 0.5),
    ]
    return "".join(
        star(round(x * scale + ox, 1), round(y * scale + oy, 1), round(r * scale, 1), opacity=o)
        for x, y, r, o in pts
    )


def app_icon(nightly=False):
    """Desktop icon: a rounded tile inset in a 1024 canvas, the way macOS frames one."""
    shades = FACETS_NIGHTLY if nightly else FACETS
    body = '<rect x="100" y="100" width="824" height="824" rx="186" fill="url(#tile)"/>'
    body += '<rect x="101.5" y="101.5" width="821" height="821" rx="184.5" fill="none" stroke="#fff" stroke-opacity=".07" stroke-width="3"/>'
    if nightly:
        body += _night_sky()
    body += gem(shades, 512, 512, 560, gap=11)
    return svg(1024, 1024, body, _tile_defs(nightly))


def full_bleed_icon(nightly=False):
    """Web and in-app logo: the tile fills the canvas, corners rounded."""
    shades = FACETS_NIGHTLY if nightly else FACETS
    body = '<rect width="1024" height="1024" rx="230" fill="url(#tile)"/>'
    if nightly:
        body += _night_sky(1.22, -112, -112)
    body += gem(shades, 512, 512, 680, gap=13)
    return svg(1024, 1024, body, _tile_defs(nightly))


BRAND_TILE = "#30343c"  # graphite: the tile a crew avatar wears before anyone picks a colour


def write_mascot(root: Path, r: "Renderer") -> Path:
    """Every drawing of the gem character the dashboard ships.

    Returns where the one raster among them (the drop overlay's picture) will be
    once the renderer has run.
    """
    assets = root / "website" / "src" / "assets"
    (assets / "aj-mark.svg").write_text(mascot.nav_mark(), encoding="utf-8")
    (assets / "crew-member-mark.svg").write_text(mascot.members_mark(), encoding="utf-8")
    (assets / "aj-gem-figure.svg").write_text(mascot.builder_figure_svg(), encoding="utf-8")
    # ringed in ink: the welcome screen shows it straight on the page, light themes included
    (assets / "aj-gem.svg").write_text(
        mascot.plain_figure(outline=5.0, pad=2.0)[0] + "\n", encoding="utf-8"
    )

    centers = {}
    for i, pose in enumerate(mascot.AVATAR_POSES, 1):
        text, (ex, ey) = mascot.avatar_pose_svg(pose, BRAND_TILE)
        (assets / "avatarPoses" / f"pose-{i}.svg").write_text(text, encoding="utf-8")
        centers[f"pose-{i}"] = [round(ex, 1), round(ey, 1)]
    (HERE / "eye-centers.json").write_text(json.dumps(centers, indent=2) + "\n", encoding="utf-8")
    for i, pose in enumerate(mascot.CREW_POSES, 1):
        (assets / "ghost-poses" / f"pose-{i}.svg").write_text(
            mascot.crew_pose_svg(pose), encoding="utf-8"
        )

    # the desktop companion's eyeless body; its eyes and props are live layers
    companion = root / "website" / "src" / "apps" / "crew-companion" / "assets"
    (companion / "kiro_idle.svg").write_text(mascot.companion_body_svg(), encoding="utf-8")

    onboarding = assets / "onboarding"
    guide = mascot.Pose(crown="table", pavilion="shield", tilt=-8, look=0.6)
    (onboarding / "aj-gem-var1.svg").write_text(
        mascot.boxed_figure(mascot.Pose(look=0.4), 51, 48, 1), encoding="utf-8"
    )
    (onboarding / "aj-gem-guide.svg").write_text(
        mascot.boxed_figure(guide, 67, 54, 3), encoding="utf-8"
    )
    (onboarding / "aj-gem-guide-outline.svg").write_text(
        mascot.boxed_figure(guide, 67, 54, 3, outline=3), encoding="utf-8"
    )

    write_splash_gem(root)
    write_pixel_gem(root)
    write_pet_clips(root)
    write_companion_listing(root)
    return r.add(mascot.file_chomper_svg(), 512, 356)


def write_pixel_gem(root: Path):
    """Rewrite the bitmap the canvas scenes draw (``KIRO_GHOST_PIXELS`` in sceneText.ts)."""
    rows = mascot.PIXEL_GEM
    if len(rows) != 28 or any(len(row) != 24 for row in rows):
        raise SystemExit("the pixel gem must stay 24 x 28: the scenes place its face by cell")
    page = root / "website" / "src" / "hooks" / "sceneText.ts"
    text = page.read_text(encoding="utf-8")
    start = text.index("[", text.index("export const KIRO_GHOST_PIXELS ="))
    end = text.index("]", start)
    block = "[\n" + "".join(f"  '{row}',\n" for row in rows)
    page.write_text(text[:start] + block + text[end:], encoding="utf-8")


def write_companion_listing(root: Path):
    """The companion in the app catalogue: its icon, and the figure in both banners.

    The banners are hand-drawn scenes; only the block between the two
    ``companion`` comments is the kit's.
    """
    folder = root / "website" / "public" / "app-assets" / "crew-companion"
    (folder / "icon.svg").write_text(mascot.companion_icon(), encoding="utf-8")
    opening, closing = "  <!-- companion: scripts/brand -->\n", "  <!-- /companion -->\n"
    for name in ("hero-dark.svg", "hero-light.svg"):
        text = (folder / name).read_text(encoding="utf-8")
        start = text.index(opening) + len(opening)
        end = text.index(closing, start)
        (folder / name).write_text(
            text[:start] + mascot.companion_banner_group() + text[end:], encoding="utf-8"
        )


def write_pet_clips(root: Path):
    """The desktop pet's gem pack: four Lottie clips (the file names predate the gem)."""
    folder = root / "website" / "src" / "apps" / "mochi" / "assets" / "animations"
    for stem, text in petclips.clips().items():
        (folder / f"{stem}.json").write_text(text, encoding="utf-8")


def write_splash_gem(root: Path):
    """Rewrite the gem the desktop splash draws (the ``GEM_SVG`` block in loading.html).

    The splash is one self-contained file that loads before the app does, so it
    carries the character inline instead of importing an asset.
    """
    svg, width, height = mascot.plain_figure()
    view_box = re.search(r'viewBox="([^"]+)"', svg).group(1)
    body = re.search(r'<path d="([^"]+)" fill="#ffffff"/>', svg).group(1)
    eyes = re.findall(rf'<path d="([^"]+)" fill="{INK}"/>', svg)
    if len(eyes) != 2:
        raise SystemExit(f"the gem has {len(eyes)} eyes; the splash blinks a pair")
    wrap = '<div class="float"><div class="tilt"><div class="pop">'
    block = "\n".join(
        [
            "    var GEM_SVG =",
            f'      \'{wrap}<svg class="g-svg" viewBox="{view_box}"'
            ' fill="none" aria-hidden="true">\' +',
            f'        \'<path d="{body}" fill="#ffffff"/>\' +',
            "        '<g class=\"g-eyes\">' +",
            *(f'          \'<path d="{eye}" fill="{INK}"/>\' +' for eye in eyes),
            "        '</g>' +",
            "      '</svg></div></div></div>';",
            f"    var GEM_ASPECT = {height / width:.3f};   // the figure's height over its width",
        ]
    )
    page = root / "website" / "electron" / "loading.html"
    text = page.read_text(encoding="utf-8")
    start = text.index("    var GEM_SVG =")
    end = text.index("\n", text.index("    var GEM_ASPECT =", start))
    page.write_text(text[:start] + block + text[end:], encoding="utf-8")


def tray_glyph():
    """Menu-bar template: black on clear, gaps wide enough to survive 18 px."""
    return svg(1024, 1024, gem_mono(512, 512, 920, gap=36, fill="#000"))


# --------------------------------------------------------------------------- #
# Banner, site logo, installer art
# --------------------------------------------------------------------------- #


def _facet_lines(w, h, color, opacity, step=120.0):
    """Long diagonals crossing the ground, like the cut lines of a stone."""
    out = []
    x = -h
    while x < w + h:
        out.append(f"M{x:g} {h}L{x + h * 0.9:g} 0")
        out.append(f"M{x + step * 0.5:g} 0L{x + step * 0.5 + h * 0.9:g} {h}")
        x += step
    return f'<path d="{"".join(out)}" stroke="{color}" stroke-opacity="{opacity}" stroke-width="1" fill="none"/>'


def banner():
    w, h = 1280, 240
    defs = (
        '<linearGradient id="ground" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#111216"/><stop offset="1" stop-color="#08090B"/></linearGradient>'
        '<linearGradient id="hair" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0" stop-color="{TEAL}" stop-opacity="0"/><stop offset=".5" stop-color="{TEAL}"/>'
        f'<stop offset="1" stop-color="{TEAL}" stop-opacity="0"/></linearGradient>'
        '<radialGradient id="glow" cx=".5" cy=".5" r=".5">'
        f'<stop offset="0" stop-color="{TEAL}" stop-opacity=".16"/><stop offset="1" stop-color="{TEAL}" stop-opacity="0"/></radialGradient>'
        + _tile_defs(False)
    )
    word, word_w, cap = wordmark(104, "#F4F5F7")
    tile = 128
    gap = 34
    total = tile + gap + word_w
    x0 = (w - total) / 2
    cy = h / 2 + 2
    body = f'<rect width="{w}" height="{h}" fill="url(#ground)"/>'
    body += _facet_lines(w, h, "#fff", 0.035)
    body += f'<ellipse cx="{x0 + tile / 2:g}" cy="{cy:g}" rx="260" ry="150" fill="url(#glow)"/>'
    body += f'<rect width="{w}" height="2" fill="url(#hair)"/>'
    body += f'<rect x="{x0:g}" y="{cy - tile / 2:g}" width="{tile}" height="{tile}" rx="{tile * 0.226:g}" fill="url(#tile)" stroke="#fff" stroke-opacity=".08"/>'
    body += gem(FACETS, x0 + tile / 2, cy, tile * 0.68, gap=1.6)
    word, _, _ = wordmark(104, "#F4F5F7", x=x0 + tile + gap, baseline=cy + cap / 2)
    body += word
    return svg(w, h, body, defs, title="Aj Crew", extra=' role="img" aria-label="Aj Crew"')


def dmg_background():
    """macOS disk image window, 660 x 420. Finder draws its captions in dark
    text whatever the system appearance, so the ground is light."""
    w, h = 660, 420
    body = f'<rect width="{w}" height="{h}" fill="{PAPER}"/>'
    body += _facet_lines(w, h, "#0B0C0F", 0.045, step=110)
    title, tw, cap = wordmark(34, INK, weight=700, tracking=4.5, text="AJ CREW")
    title, _, _ = wordmark(
        34, INK, x=(w - tw) / 2, baseline=78, weight=700, tracking=4.5, text="AJ CREW"
    )
    body += title
    sub, sw, _ = wordmark(
        14.5, "#3A3D45", weight=500, tracking=0, text="Drag Aj Crew onto the Applications folder"
    )
    sub, _, _ = wordmark(
        14.5,
        "#3A3D45",
        x=(w - sw) / 2,
        baseline=112,
        weight=500,
        tracking=0,
        text="Drag Aj Crew onto the Applications folder",
    )
    body += sub
    # Chevron between the app (x=170) and Applications (x=490), both at y=246.
    body += '<path d="M316 220L344 246L316 272" fill="none" stroke="#0FB5A0" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>'
    # A large, quiet gem bleeding off the lower corners.
    body += f'<g opacity=".07">{gem_mono(96, 396, 300, gap=6, fill=INK)}</g>'
    body += f'<g opacity=".07">{gem_mono(590, 30, 220, gap=5, fill=INK)}</g>'
    return svg(w, h, body)


def windows_sidebar():
    """NSIS welcome/finish sidebar, 164 x 314."""
    w, h = 164, 314
    defs = (
        '<linearGradient id="ground" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#16171C"/><stop offset="1" stop-color="#08090B"/></linearGradient>'
    )
    body = f'<rect width="{w}" height="{h}" fill="url(#ground)"/>'
    body += _facet_lines(w, h, "#fff", 0.05, step=64)
    body += gem(FACETS, w / 2, 112, 92, gap=2.0)
    word, ww, cap = wordmark(17, "#F4F5F7", weight=700, tracking=2.4, text="AJ CREW")
    word, _, _ = wordmark(
        17, "#F4F5F7", x=(w - ww) / 2, baseline=196, weight=700, tracking=2.4, text="AJ CREW"
    )
    body += word
    body += f'<rect x="{w / 2 - 27:g}" y="246" width="54" height="1.5" fill="{TEAL}"/>'
    sub, sw, _ = wordmark(12, "#AEB5C0", weight=500, tracking=0.2, text="Quick setup")
    sub, _, _ = wordmark(
        12, "#AEB5C0", x=(w - sw) / 2, baseline=274, weight=500, tracking=0.2, text="Quick setup"
    )
    body += sub
    return svg(w, h, body, defs)


# Where the icon tile sits in the 150 x 57 header; the packaging test reads it.
HEADER_TILE = (96, 8, 41)  # x, y, edge


def windows_header():
    """NSIS page header, 150 x 57, drawn on the installer's white header strip."""
    w, h = 150, 57
    x, y, edge = HEADER_TILE
    body = f'<rect width="{w}" height="{h}" fill="#FFFFFF"/>'
    body += (
        f'<rect x="{x}" y="{y}" width="{edge}" height="{edge}" rx="{edge * 0.226:g}" fill="{INK}"/>'
    )
    body += gem(FACETS, x + edge / 2, y + edge / 2, edge * 0.68, gap=0.9)
    word, ww, cap = wordmark(13, INK, weight=700, tracking=0.1)
    word, _, _ = wordmark(13, INK, x=x - 9 - ww, baseline=h / 2 + cap / 2, weight=700, tracking=0.1)
    body += word
    return svg(w, h, body)


# --------------------------------------------------------------------------- #
# Rasterising and container formats
# --------------------------------------------------------------------------- #

_RENDER_JS = r"""
import { createRequire } from 'module'
import { readFileSync } from 'fs'
const require = createRequire(process.argv[2] + '/')
const { chromium } = require('playwright')
const jobs = JSON.parse(readFileSync(process.argv[3], 'utf8'))
const exe = process.env.CHROMIUM
const browser = await chromium.launch(exe ? { executablePath: exe, args: ['--no-sandbox'] } : {})
for (const j of jobs) {
  const page = await browser.newPage({ viewport: { width: j.w, height: j.h }, deviceScaleFactor: 1 })
  const svg = readFileSync(j.svg, 'utf8')
    .replace(/<svg ([^>]*?)width="[^"]*" height="[^"]*"/, '<svg $1')
    .replace('<svg ', `<svg width="${j.w}" height="${j.h}" `)
  await page.setContent(`<html><body style="margin:0;background:${j.bg || 'transparent'}">${svg}</body></html>`)
  await page.screenshot({ path: j.out, omitBackground: !j.bg, clip: { x: 0, y: 0, width: j.w, height: j.h } })
  await page.close()
}
await browser.close()
"""


class Renderer:
    def __init__(self, website_dir: Path):
        self.website = website_dir
        self.tmp = Path(tempfile.mkdtemp(prefix="aj-brand-"))
        self.jobs = []

    def add(self, svg_text, w, h, bg=None):
        i = len(self.jobs)
        src = self.tmp / f"{i}.svg"
        src.write_text(svg_text, encoding="utf-8")
        out = self.tmp / f"{i}.png"
        self.jobs.append({"svg": str(src), "out": str(out), "w": w, "h": h, "bg": bg})
        return out

    def run(self):
        script = self.tmp / "render.mjs"
        script.write_text(_RENDER_JS, encoding="utf-8")
        jobs = self.tmp / "jobs.json"
        jobs.write_text(json.dumps(self.jobs), encoding="utf-8")
        subprocess.run([NODE, str(script), str(self.website), str(jobs)], check=True)


def save_png(src: Path, dst: Path):
    im = Image.open(src).convert("RGBA")
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, format="PNG", optimize=True)


def png_bytes(src: Path) -> bytes:
    buf = io.BytesIO()
    Image.open(src).convert("RGBA").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _icns_rle(channel: bytes) -> bytes:
    """Apple's icon run-length coding for one 8-bit channel."""
    out = bytearray()
    i, n = 0, len(channel)
    while i < n:
        run = 1
        while i + run < n and run < 130 and channel[i + run] == channel[i]:
            run += 1
        if run >= 3:
            out += bytes([run + 125, channel[i]])
            i += run
            continue
        start = i
        while i < n and i - start < 128:
            if i + 2 < n and channel[i] == channel[i + 1] == channel[i + 2]:
                break
            i += 1
        out += bytes([i - start - 1]) + channel[start:i]
    return bytes(out)


def _icns_argb(src: Path) -> bytes:
    im = Image.open(src).convert("RGBA")
    r, g, b, a = (c.tobytes() for c in im.split())
    return b"ARGB" + b"".join(_icns_rle(c) for c in (a, r, g, b))


def _icns_info() -> bytes:
    # The trailing property list iconutil writes: {"name": "icon"}.
    return plistlib.dumps(
        {
            "$version": 100000,
            "$archiver": "NSKeyedArchiver",
            "$top": {"root": plistlib.UID(1)},
            "$objects": [
                "$null",
                {
                    "NS.keys": [plistlib.UID(2), plistlib.UID(3)],
                    "NS.objects": [plistlib.UID(4), plistlib.UID(5)],
                    "$class": plistlib.UID(6),
                },
                "name",
                "assetcatalog-reference",
                "icon",
                {"NS.keys": [], "NS.objects": [], "$class": plistlib.UID(6)},
                {"$classname": "NSDictionary", "$classes": ["NSDictionary", "NSObject"]},
            ],
        },
        fmt=plistlib.FMT_BINARY,
    )


def write_icns(by_size: dict[int, Path], dst: Path):
    """Same slots, in the same order, as Apple's iconutil emits."""
    slots = [
        (b"ic12", png_bytes(by_size[64])),
        (b"ic07", png_bytes(by_size[128])),
        (b"ic13", png_bytes(by_size[256])),
        (b"ic08", png_bytes(by_size[256])),
        (b"ic04", _icns_argb(by_size[16])),
        (b"ic14", png_bytes(by_size[512])),
        (b"ic09", png_bytes(by_size[512])),
        (b"ic05", _icns_argb(by_size[32])),
        (b"ic10", png_bytes(by_size[1024])),
        (b"ic11", png_bytes(by_size[32])),
        (b"info", _icns_info()),
    ]
    body = b"".join(name + struct.pack(">I", len(data) + 8) + data for name, data in slots)
    dst.write_bytes(b"icns" + struct.pack(">I", len(body) + 8) + body)


def write_ico(by_size: dict[int, Path], dst: Path):
    sizes = [16, 32, 48, 64, 256]
    images = [Image.open(by_size[s]).convert("RGBA") for s in sizes]
    images[-1].save(dst, format="ICO", sizes=[(s, s) for s in sizes], append_images=images[:-1])


def write_bmp24(src: Path, dst: Path):
    Image.open(src).convert("RGB").save(dst, format="BMP")


def write_template_png(src: Path, dst: Path):
    """RGBA, 8-bit, one IDAT, filter 0 on every row, colour bytes zero."""
    im = Image.open(src).convert("RGBA")
    w, h = im.size
    alpha = im.getchannel("A").tobytes()
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            raw += bytes([0, 0, 0, alpha[y * w + x]])

    def chunk(tag, data):
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")
    dst.write_bytes(png)


def write_tiff_pair(src1x: Path, src2x: Path, dst: Path):
    a = Image.open(src1x).convert("RGBA")
    b = Image.open(src2x).convert("RGBA")
    a.save(
        dst, format="TIFF", save_all=True, append_images=[b], compression="tiff_lzw", dpi=(72, 72)
    )
    # Pillow writes one resolution for every page; the retina page needs 144.
    _retag_second_page_dpi(dst, 144)


def _retag_second_page_dpi(path: Path, dpi: int):
    data = bytearray(path.read_bytes())
    le = data[:2] == b"II"

    def u16(o: int) -> int:
        return struct.unpack_from("<H" if le else ">H", data, o)[0]

    def u32(o: int) -> int:
        return struct.unpack_from("<I" if le else ">I", data, o)[0]

    ifd = u32(4)
    ifd = u32(ifd + 2 + u16(ifd) * 12)  # second directory
    for i in range(u16(ifd)):
        entry = ifd + 2 + i * 12
        if u16(entry) in (282, 283):
            off = u32(entry + 8)
            struct.pack_into("<II" if le else ">II", data, off, dpi, 1)
    path.write_bytes(bytes(data))


# --------------------------------------------------------------------------- #


def main(root: Path):
    web = root / "website"
    el = web / "electron"
    inst = root / "packaging" / "installer-assets"
    r = Renderer(Path(os.environ.get("AJ_WEBSITE_DIR", web)))

    icon_sizes = [16, 32, 48, 64, 128, 256, 512, 1024]
    icons = {}
    for variant, nightly in (("", False), ("-nightly", True)):
        src = app_icon(nightly)
        icons[variant] = {s: r.add(src, s, s) for s in icon_sizes}
    bleed = {
        v: {s: r.add(full_bleed_icon(n), s, s) for s in (192, 512)}
        for v, n in (("", False), ("-nightly", True))
    }
    tray = {s: r.add(tray_glyph(), s, s) for s in (18, 36)}
    dmg_svg, side_svg, head_svg = dmg_background(), windows_sidebar(), windows_header()
    dmg1, dmg2 = r.add(dmg_svg, 660, 420), r.add(dmg_svg, 1320, 840)
    side, head = r.add(side_svg, 164, 314, "#000"), r.add(head_svg, 150, 57, "#fff")
    chomper = write_mascot(root, r)
    r.run()

    for variant in ("", "-nightly"):
        by = icons[variant]
        save_png(by[1024], el / f"icon{variant}.png")
        write_icns(by, el / f"icon{variant}.icns")
        write_ico(by, el / f"icon{variant}.ico")
        for s in (16, 32, 48, 64, 128, 256, 512):
            save_png(by[s], el / "build" / f"icons{variant}" / f"{s}x{s}.png")
        save_png(
            bleed[variant][512], root / "src" / "aj_crew" / "static" / f"ajcrew-logo{variant}.png"
        )
    save_png(bleed[""][192], web / "public" / "icon-192.png")
    save_png(bleed[""][512], web / "public" / "icon-512.png")
    save_png(bleed[""][192], root / "site" / "public" / "ajcrew-logo.png")
    (root / "site" / "public" / "ajcrew-logo.svg").write_text(full_bleed_icon(), encoding="utf-8")
    write_template_png(tray[18], el / "trayTemplate.png")
    write_template_png(tray[36], el / "trayTemplate@2x.png")

    (root / "assets" / "banner.svg").write_text(banner(), encoding="utf-8")
    save_png(chomper, web / "src" / "assets" / "aj-file-chomper.png")

    (inst / "dmg-background.svg").write_text(dmg_svg, encoding="utf-8")
    (inst / "windows-installer-sidebar.svg").write_text(side_svg, encoding="utf-8")
    (inst / "windows-installer-header.svg").write_text(head_svg, encoding="utf-8")
    write_tiff_pair(dmg1, dmg2, inst / "dmg-background.tiff")
    write_bmp24(side, inst / "windows-installer-sidebar.bmp")
    write_bmp24(head, inst / "windows-installer-header.bmp")
    print("brand assets written under", root)


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
