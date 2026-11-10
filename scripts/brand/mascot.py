"""The Aj Crew gem character: the brand mark with a face.

One parametric figure drawn in a unit space (girdle on y = 0, half-width 1):
a crown of facets above the girdle, a single pavilion below it that carries the
face. A *cut* picks the crown and pavilion outlines; a *pose* places, tilts and
scales the figure and says where it looks. Every asset that used to be drawn by
hand as a separate file is one row of a table here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# geometry helpers
# --------------------------------------------------------------------------- #

Pt = tuple[float, float]


def _area(poly: list[Pt]) -> float:
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1])) / 2


def inset(poly: list[Pt], d: float) -> list[Pt]:
    """Shrink a convex polygon by ``d`` on every side."""
    if _area(poly) < 0:
        poly = poly[::-1]
    n = len(poly)
    lines = []
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        nx, ny = -dy / length, dx / length
        lines.append(((x1 + nx * d, y1 + ny * d), (dx, dy)))
    out = []
    for i in range(n):
        (p, r), (q, s) = lines[i - 1], lines[i]
        cross = r[0] * s[1] - r[1] * s[0]
        t = ((q[0] - p[0]) * s[1] - (q[1] - p[1]) * s[0]) / cross
        out.append((p[0] + t * r[0], p[1] + t * r[1]))
    return out


def rounded(poly: list[Pt], radius: float, digits: int = 2) -> str:
    """Closed path through ``poly`` with every corner eased by a quadratic."""
    n = len(poly)
    f = lambda v: f"{round(v, digits):g}"  # noqa: E731
    segs = []
    for i in range(n):
        p0, p1, p2 = poly[i - 1], poly[i], poly[(i + 1) % n]
        a = (p0[0] - p1[0], p0[1] - p1[1])
        b = (p2[0] - p1[0], p2[1] - p1[1])
        la, lb = math.hypot(*a), math.hypot(*b)
        cut = min(radius, la * 0.45, lb * 0.45)
        start = (p1[0] + a[0] / la * cut, p1[1] + a[1] / la * cut)
        end = (p1[0] + b[0] / lb * cut, p1[1] + b[1] / lb * cut)
        segs.append((start, p1, end))
    d = f"M{f(segs[0][0][0])} {f(segs[0][0][1])}"
    for i, (start, corner, end) in enumerate(segs):
        if i:
            d += f"L{f(start[0])} {f(start[1])}"
        d += f"Q{f(corner[0])} {f(corner[1])} {f(end[0])} {f(end[1])}"
    return d + "Z"


# --------------------------------------------------------------------------- #
# cuts
# --------------------------------------------------------------------------- #

# Crowns: outline from the left girdle end over the top to the right one, plus
# the x positions on the girdle where the table's edges come down.
CROWNS = {
    # the brand mark's own crown
    "table": {"top": [(-0.5, -0.52), (0.5, -0.52)], "feet": (-0.4, 0.4)},
    # an emerald's low step
    "step": {"top": [(-0.78, -0.36), (0.78, -0.36)], "feet": (-0.6, 0.6)},
    # a tall, narrow table
    "tall": {"top": [(-0.36, -0.66), (0.36, -0.66)], "feet": (-0.3, 0.3)},
}

# Pavilions: outline from the right girdle end down and round to the left one.
PAVILIONS = {
    "point": [(0.0, 1.215)],
    "shield": [(0.92, 0.52), (0.0, 1.2), (-0.92, 0.52)],
    "emerald": [(0.86, 0.6), (0.5, 1.02), (-0.5, 1.02), (-0.86, 0.6)],
    "drop": [(0.94, 0.5), (0.58, 0.98), (0.0, 1.16), (-0.58, 0.98), (-0.94, 0.5)],
    "kite": [(0.0, 1.5)],
}


@dataclass
class Pose:
    crown: str = "table"
    pavilion: str = "point"
    cx: float = 150.0  # girdle centre on the canvas
    cy: float = 118.0
    half: float = 100.0  # half the girdle width, in canvas units
    tilt: float = 0.0  # degrees, clockwise
    look: float = 0.0  # -1 (left) .. 1 (right): where the eyes sit
    eye_y: float = 0.36  # eye centre below the girdle, in unit space
    eye_gap: float = 0.22  # half the distance between the eyes
    eye_rx: float = 0.1
    eye_ry: float = 0.165
    squash: float = 1.0  # vertical scale of the whole figure
    sparkles: list[tuple[float, float, float]] = field(default_factory=list)  # canvas x, y, r


@dataclass
class Figure:
    body: str  # one path: every white piece of the figure
    eyes: list[str]  # one path per eye
    eye_center: Pt  # midpoint between the eyes, canvas units
    bbox: tuple[float, float, float, float]


def _star_path(cx: float, cy: float, r: float, digits: int = 2) -> str:
    """Four-point twinkle, wound the same way as the facets."""
    k = r * 0.24
    pts = [
        (cx, cy - r),
        (cx + k, cy - k),
        (cx + r, cy),
        (cx + k, cy + k),
        (cx, cy + r),
        (cx - k, cy + k),
        (cx - r, cy),
        (cx - k, cy - k),
    ]
    f = lambda v: f"{round(v, digits):g}"  # noqa: E731
    return "M" + "L".join(f"{f(x)} {f(y)}" for x, y in pts) + "Z"


def figure(p: Pose, gap: float = 0.075, radius: float = 0.11, digits: int = 2) -> Figure:
    crown, pav = CROWNS[p.crown], PAVILIONS[p.pavilion]
    (t1, t2), (f1, f2) = crown["top"], crown["feet"]
    gl, gr = (-1.0, 0.0), (1.0, 0.0)
    g1, g2 = (f1, 0.0), (f2, 0.0)
    pieces = [
        [gl, t1, g1],  # left crown facet
        [t1, t2, g2, g1],  # table
        [t2, gr, g2],  # right crown facet
        [gr, *pav, gl],  # pavilion: the face
    ]
    rad = math.radians(p.tilt)
    cos, sin = math.cos(rad), math.sin(rad)

    def place(pt: Pt) -> Pt:
        x, y = pt[0] * p.half, pt[1] * p.half * p.squash
        return (p.cx + x * cos - y * sin, p.cy + x * sin + y * cos)

    xs, ys, body = [], [], ""
    for i, poly in enumerate(pieces):
        shrunk = inset(poly, gap / 2)
        placed = [place(q) for q in shrunk]
        xs += [q[0] for q in placed]
        ys += [q[1] for q in placed]
        # crown facets are small: ease them less so they keep their points
        body += rounded(placed, (radius if i == 3 else radius * 0.55) * p.half, digits)
    for sx, sy, sr in p.sparkles:
        body += _star_path(sx, sy, sr, digits)
        xs += [sx - sr, sx + sr]
        ys += [sy - sr, sy + sr]

    f = lambda v: f"{round(v, digits):g}"  # noqa: E731
    ex = p.look * 0.2
    eyes, centers = [], []
    for side in (-1, 1):
        c = place((ex + side * p.eye_gap, p.eye_y))
        centers.append(c)
        rx, ry = p.eye_rx * p.half, p.eye_ry * p.half * p.squash
        # an ellipse as two arcs, tilted with the figure
        a = (c[0] - rx * cos, c[1] - rx * sin)
        b = (c[0] + rx * cos, c[1] + rx * sin)
        eyes.append(
            f"M{f(a[0])} {f(a[1])}A{f(rx)} {f(ry)} {f(p.tilt)} 1 1 {f(b[0])} {f(b[1])}"
            f"A{f(rx)} {f(ry)} {f(p.tilt)} 1 1 {f(a[0])} {f(a[1])}Z"
        )
    mid = ((centers[0][0] + centers[1][0]) / 2, (centers[0][1] + centers[1][1]) / 2)
    return Figure(body, eyes, mid, (min(xs), min(ys), max(xs), max(ys)))


def centered(p: Pose, box: float = 300.0, dy: float = 0.0) -> Pose:
    """Place a pose so its figure (sparkles aside) sits in the middle of ``box``."""
    probe = Pose(**{**p.__dict__, "cx": 0.0, "cy": 0.0, "sparkles": []})
    x0, y0, x1, y1 = figure(probe).bbox
    return Pose(**{**p.__dict__, "cx": box / 2 - (x0 + x1) / 2, "cy": box / 2 - (y0 + y1) / 2 + dy})


# --------------------------------------------------------------------------- #
# the shipped sets
# --------------------------------------------------------------------------- #


def _p(**kw) -> Pose:
    return Pose(**kw)


# Eleven avatar tiles (300 x 300). The first is the default a new crew opens on,
# so it is the brand mark's own cut, upright.
AVATAR_POSES: list[Pose] = [
    _p(crown="table", pavilion="point", half=112, look=0.35),
    _p(crown="table", pavilion="shield", half=106, tilt=-9, look=-0.45),
    _p(crown="step", pavilion="emerald", half=110, tilt=6, look=0.6, sparkles=[(252, 52, 16)]),
    _p(crown="tall", pavilion="drop", half=100, tilt=-5, look=-0.2),
    _p(crown="table", pavilion="kite", half=94, tilt=10, look=0.5),
    _p(crown="step", pavilion="drop", half=108, tilt=-12, look=-0.7),
    _p(crown="tall", pavilion="point", half=106, tilt=14, look=0.75, sparkles=[(50, 62, 15)]),
    _p(crown="table", pavilion="drop", half=108, look=0.0),
    _p(crown="step", pavilion="shield", half=110, tilt=7, look=0.3),
    _p(crown="tall", pavilion="shield", half=102, tilt=-15, look=-0.6, sparkles=[(248, 240, 14)]),
    _p(
        crown="table",
        pavilion="emerald",
        half=110,
        tilt=-4,
        look=0.55,
        sparkles=[(46, 244, 13), (256, 58, 10)],
    ),
]

# Eight outlined figures (the chat footer's and the roster's crew): no tile, so
# each is cropped to its own box and carries its own outline.
CREW_POSES: list[Pose] = [
    _p(crown="table", pavilion="point", look=0.4),
    _p(crown="table", pavilion="shield", tilt=-8, look=-0.5),
    _p(crown="step", pavilion="emerald", tilt=5, look=0.6),
    _p(crown="tall", pavilion="drop", tilt=-6, look=-0.3),
    _p(crown="table", pavilion="kite", tilt=9, look=0.5),
    _p(crown="step", pavilion="drop", tilt=-11, look=-0.65),
    _p(crown="tall", pavilion="point", tilt=12, look=0.7),
    _p(crown="table", pavilion="drop", look=0.0),
]


def avatar_pose_svg(p: Pose, bg: str) -> tuple[str, Pt]:
    """A tile: ground rect, the white figure, two eyes left unfilled (black)."""
    fig = figure(centered(p, 300.0))
    eyes = "\n".join(f'  <path d="{d}"/>' for d in fig.eyes)
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 300">\n'
        f'  <rect width="300" height="300" fill="{bg}"/>\n'
        f'  <path d="{fig.body}" fill="#fff"/>\n'
        f"{eyes}\n"
        "</svg>\n"
    )
    return svg, fig.eye_center


def crew_pose_svg(p: Pose, stroke: float = 22.0) -> str:
    """An outlined figure in its own box: white facets, black outline behind them."""
    q = Pose(**{**p.__dict__, "cx": 0.0, "cy": 0.0, "half": 100.0, "sparkles": []})
    fig = figure(q)
    x0, y0, x1, y1 = fig.bbox
    pad = stroke / 2 + 2
    vb = f"{x0 - pad:.2f} {y0 - pad:.2f} {x1 - x0 + 2 * pad:.2f} {y1 - y0 + 2 * pad:.2f}"
    eyes = "\n".join(f'  <path d="{d}" fill="#000000"/>' for d in fig.eyes)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" fill="none">\n'
        f'  <path d="{fig.body}" fill="#ffffff" stroke="#000000" stroke-width="{stroke:g}" '
        'stroke-linejoin="round" paint-order="stroke"/>\n'
        f"{eyes}\n"
        "</svg>\n"
    )


# --------------------------------------------------------------------------- #
# single figures
# --------------------------------------------------------------------------- #

# The trait builder draws brows, mouths, hats and props at coordinates measured
# off its body, so the body it is handed keeps the eyes where they have always
# been in the 1200 tile: centres (637.5, 486.7) and (772.6, 486.7), 39 x 62.6.
BUILDER_EYES = ((637.5, 486.7), (772.6, 486.7))
BUILDER_HALF = 332.0
BUILDER_BODY = Pose(
    crown="table",
    pavilion="builder",
    half=BUILDER_HALF,
    look=0.0,
    eye_y=0.36,
    eye_gap=(772.6 - 637.5) / 2 / BUILDER_HALF,
    eye_rx=39.1 / BUILDER_HALF,
    eye_ry=62.6 / BUILDER_HALF,
)
PAVILIONS["builder"] = [(0.97, 0.62), (0.7, 1.3), (0.0, 1.7), (-0.7, 1.3), (-0.97, 0.62)]


def builder_figure_svg() -> str:
    """Body, eye, eye: the three paths the avatar builder reads its geometry from."""
    (lx, ly), (rx, _) = BUILDER_EYES
    p = BUILDER_BODY
    # eyes sit right of centre, as the figure glances that way
    ex = 0.3
    cx = (lx + rx) / 2 - ex * p.half
    cy = ly - p.eye_y * p.half
    q = Pose(**{**p.__dict__, "cx": cx, "cy": cy, "look": ex / 0.2})
    fig = figure(q, digits=1)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 1200" fill="none">'
        f'<path fill="#fff" d="{fig.body}"/>'
        f'<path fill="#000" d="{fig.eyes[0]}"/><path fill="#000" d="{fig.eyes[1]}"/>'
        "</svg>\n"
    )


def plain_figure(
    p: Pose | None = None, ink: str = "#0B0C0F", pad: float = 6.0, outline: float = 0.0
) -> tuple[str, float, float]:
    """The figure alone, white with dark eyes, cropped to its box. Returns svg, w, h.

    ``outline`` rings the silhouette in the ink colour by that much, so the white
    body still reads where the page behind it is white too. It is drawn under the
    fill, which keeps the facets their full size.
    """
    p = p or Pose(look=0.35)
    q = Pose(**{**p.__dict__, "cx": 0.0, "cy": 0.0, "half": 100.0, "sparkles": []})
    fig = figure(q)
    x0, y0, x1, y1 = fig.bbox
    pad += outline
    w, h = x1 - x0 + 2 * pad, y1 - y0 + 2 * pad
    eyes = "".join(f'<path d="{d}" fill="{ink}"/>' for d in fig.eyes)
    ring = (
        f' stroke="{ink}" stroke-width="{outline * 2:g}" stroke-linejoin="round" paint-order="stroke"'
        if outline
        else ""
    )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0 - pad:.2f} {y0 - pad:.2f} {w:.2f} {h:.2f}" fill="none">'
        f'<path d="{fig.body}" fill="#ffffff"{ring}/><g class="g-eyes">{eyes}</g></svg>'
    )
    return svg, w, h


def boxed_figure(
    p: Pose, vw: float, vh: float, pad: float, ink: str = "#0B0C0F", outline: float | None = None
) -> str:
    """A figure fitted into a fixed viewBox with ``pad`` clear on every side.

    With ``outline`` the same silhouette is drawn solid and grown by that much:
    a mask the page tints, sitting behind the white figure as its border.
    """
    probe = Pose(**{**p.__dict__, "cx": 0.0, "cy": 0.0, "half": 100.0, "sparkles": []})
    x0, y0, x1, y1 = figure(probe).bbox
    fit = pad + 0.4  # the outline's round joins need a hair more than its width
    scale = min((vw - 2 * fit) / (x1 - x0), (vh - 2 * fit) / (y1 - y0))
    half = 100.0 * scale
    cx = vw / 2 - (x0 + x1) / 2 * scale
    cy = vh / 2 - (y0 + y1) / 2 * scale
    fig = figure(Pose(**{**p.__dict__, "cx": cx, "cy": cy, "half": half, "sparkles": []}), digits=3)
    head = f'<svg width="{vw:g}" height="{vh:g}" viewBox="0 0 {vw:g} {vh:g}" fill="none" xmlns="http://www.w3.org/2000/svg">\n'
    if outline is not None:
        return (
            head
            + f'<path d="{fig.body}" fill="black" stroke="black" stroke-width="{outline * 2:g}" stroke-linejoin="round"/>\n</svg>\n'
        )
    eyes = "\n".join(f'<path d="{d}" fill="{ink}"/>' for d in fig.eyes)
    return head + f'<path d="{fig.body}" fill="white"/>\n{eyes}\n</svg>\n'


# --------------------------------------------------------------------------- #
# nav glyphs: drawn on Lucide's own grid (24 x 24, 2 px round stroke) so they
# weigh the same as the icons they sit beside
# --------------------------------------------------------------------------- #

_LUCIDE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#000" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">\n'
)


def nav_mark() -> str:
    """The gem as an outline: table, girdle, and the two pavilion edges."""
    return (
        _LUCIDE
        + '  <path d="M2 8.75L7 3.5H17L22 8.75L12 20.75Z"/>\n'
        + '  <path d="M2 8.75H22"/>\n'
        + '  <path d="M7 3.5L8.25 8.75L12 20.75L15.75 8.75L17 3.5"/>\n'
        + "</svg>\n"
    )


def members_mark() -> str:
    """Two gems, a large one and a small one beside it: the crew, plural."""
    return (
        _LUCIDE
        + '  <path d="M1.5 11L5 7.25H11.5L15 11L8.25 19.75Z"/>\n'
        + '  <path d="M1.5 11H15"/>\n'
        + '  <path d="M15.25 6.5L17.25 4.25H20.5L22.5 6.5L18.9 11.25Z"/>\n'
        + "</svg>\n"
    )


# --------------------------------------------------------------------------- #
# the drop overlay's picture: the gem about to swallow a document
# --------------------------------------------------------------------------- #


def file_chomper_svg(accent: str = "#2DD4BF", ink: str = "#0B0C0F") -> str:
    p = Pose(
        crown="table",
        pavilion="shield",
        cx=196.0,
        cy=112.0,
        half=158.0,
        tilt=-6.0,
        look=1.0,
        eye_y=0.25,
        eye_gap=0.2,
        eye_rx=0.09,
        eye_ry=0.14,
    )
    fig = figure(p)
    rad = math.radians(p.tilt)
    cos, sin = math.cos(rad), math.sin(rad)

    def place(x: float, y: float) -> Pt:
        x, y = x * p.half, y * p.half
        return (p.cx + x * cos - y * sin, p.cy + x * sin + y * cos)

    # an open mouth on the pavilion, facing the document
    mouth = [
        place(0.04, 0.55),
        place(0.76, 0.47),
        place(0.6, 0.72),
        place(0.25, 0.95),
        place(0.05, 0.92),
    ]
    mouth_d = rounded(mouth, 14)
    teeth = ""
    for a, b in ((0.14, 0.32), (0.44, 0.62)):
        top = lambda x: 0.55 - (x - 0.04) * (0.08 / 0.72)  # noqa: E731  the mouth's upper lip
        t = [
            place(a, top(a) - 0.01),
            place(b, top(b) - 0.01),
            place((a + b) / 2, top((a + b) / 2) + 0.15),
        ]
        teeth += f'<path d="{rounded(t, 2.5)}" fill="#fff"/>'
    t = [place(0.07, 0.93), place(0.2, 0.955), place(0.15, 0.8)]
    teeth += f'<path d="{rounded(t, 2.5)}" fill="#fff"/>'
    eyes = "".join(f'<path d="{d}" fill="{ink}"/>' for d in fig.eyes)
    # the document, tilted, with its corner folded
    doc = (
        '<g transform="translate(418 150) rotate(12)">'
        '<path d="M-44 -62H16L46 -32V62H-44Z" fill="#fff" stroke-linejoin="round"/>'
        f'<path d="M16 -62V-32H46Z" fill="{accent}"/>'
        f'<path d="M-24 -8H26M-24 14H26M-24 36H8" stroke="{ink}" stroke-width="9" stroke-linecap="round"/>'
        "</g>"
    )
    speed = f'<path d="M338 168H372M346 190H372" stroke="{accent}" stroke-width="6" stroke-linecap="round"/>'
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="512" height="356" viewBox="0 0 512 356" fill="none">'
        f'<path d="{fig.body}" fill="#fff"/>{eyes}<path d="{mouth_d}" fill="{ink}"/>{teeth}{speed}{doc}'
        "</svg>\n"
    )
