"""The gem character as four looping Lottie clips for the desktop pet.

The pet's second built-in pack plays Lottie. Its player is the light build of
lottie-web, which runs no expressions and no SVG effects, so every clip here is
plain keyframes: shapes, fills, strokes, one ellipse per eye, and a null that
carries the bob. The art faces LEFT because the pack declares ``flipX`` and
every surface mirrors it.
"""

from __future__ import annotations

import json
import math

import mascot

W, H, FPS = 800, 700, 30
HALF = 224.0  # half the girdle width, in composition units
CENTER = (380.0, 286.0)  # where the girdle's centre rests
OUTLINE = 22.0 * HALF / 100.0  # the crew figures' outline, at this size
WHITE, BLACK, TEAL = (1, 1, 1), (0, 0, 0), (0.176, 0.831, 0.749)
POSE = mascot.Pose(cx=0.0, cy=0.0, half=HALF, look=-0.55)

Pt = tuple[float, float]


def _n(v: float) -> float | int:
    v = round(v, 2)
    return int(v) if v == int(v) else v


def _still(value):
    return {"a": 0, "k": value}


def _keys(frames: list[tuple[float, list[float]]], hold: bool = False):
    """Keyframes easing in and out of every stop; the last one only marks the end."""
    out = []
    for i, (t, value) in enumerate(frames):
        key = {"t": t, "s": [_n(v) for v in value]}
        if i < len(frames) - 1:
            if hold:
                key["h"] = 1
            else:
                n = len(value)
                key["i"] = {"x": [0.5] * n, "y": [1] * n}
                key["o"] = {"x": [0.5] * n, "y": [0] * n}
        out.append(key)
    return {"a": 1, "k": out}


def _transform(p=(0, 0), s=(100, 100), r=0):
    return {
        "ty": "tr",
        "p": _still(list(p)),
        "a": _still([0, 0]),
        "s": _still(list(s)),
        "r": _still(r),
        "o": _still(100),
        "sk": _still(0),
        "sa": _still(0),
    }


def _fill(rgb):
    return {"ty": "fl", "c": _still([*rgb, 1]), "o": _still(100), "r": 1, "bm": 0}


def _stroke(rgb, width):
    return {
        "ty": "st",
        "c": _still([*rgb, 1]),
        "o": _still(100),
        "w": _still(_n(width)),
        "lc": 2,
        "lj": 2,
        "bm": 0,
    }


def _path(poly: list[Pt], radius: float, name: str):
    """A closed polygon with every corner eased, as ``mascot.rounded`` draws it."""
    v, i, o = [], [], []
    n = len(poly)
    for k in range(n):
        p0, p1, p2 = poly[k - 1], poly[k], poly[(k + 1) % n]
        a = (p0[0] - p1[0], p0[1] - p1[1])
        b = (p2[0] - p1[0], p2[1] - p1[1])
        la, lb = math.hypot(*a), math.hypot(*b)
        cut = min(radius, la * 0.45, lb * 0.45)
        start = (p1[0] + a[0] / la * cut, p1[1] + a[1] / la * cut)
        end = (p1[0] + b[0] / lb * cut, p1[1] + b[1] / lb * cut)
        # the quadratic through the corner, as the cubic a Lottie path holds
        v += [start, end]
        i += [(0, 0), ((p1[0] - end[0]) * 2 / 3, (p1[1] - end[1]) * 2 / 3)]
        o += [((p1[0] - start[0]) * 2 / 3, (p1[1] - start[1]) * 2 / 3), (0, 0)]
    shape = {
        "i": [[_n(x), _n(y)] for x, y in i],
        "o": [[_n(x), _n(y)] for x, y in o],
        "v": [[_n(x), _n(y)] for x, y in v],
        "c": True,
    }
    return {"ty": "sh", "nm": name, "ks": _still(shape)}


def _facets() -> list[dict]:
    """The four pieces of the brand mark's own cut, around the girdle's centre."""
    crown, pav = mascot.CROWNS[POSE.crown], mascot.PAVILIONS[POSE.pavilion]
    (t1, t2), (f1, f2) = crown["top"], crown["feet"]
    gl, gr, g1, g2 = (-1.0, 0.0), (1.0, 0.0), (f1, 0.0), (f2, 0.0)
    pieces = [
        ("left facet", [gl, t1, g1], 0.06),
        ("table", [t1, t2, g2, g1], 0.06),
        ("right facet", [t2, gr, g2], 0.06),
        ("face", [gr, *pav, gl], 0.11),
    ]
    out = []
    for name, poly, radius in pieces:
        placed = [(x * HALF, y * HALF) for x, y in mascot.inset(poly, 0.075 / 2)]
        out.append(_path(placed, radius * HALF, name))
    return out


def _layer(ind: int, name: str, kind: int, op: int, parent: int | None = None, **ks):
    layer = {
        "ddd": 0,
        "ind": ind,
        "ty": kind,
        "nm": name,
        "sr": 1,
        "ks": {
            "o": ks.get("o", _still(100)),
            "r": ks.get("r", _still(0)),
            "p": ks.get("p", _still([0, 0, 0])),
            "a": ks.get("a", _still([0, 0, 0])),
            "s": ks.get("s", _still([100, 100, 100])),
        },
        "ao": 0,
        "ip": 0,
        "op": op,
        "st": 0,
        "bm": 0,
    }
    if parent is not None:
        layer["parent"] = parent
    return layer


def _eyes(ind: int, op: int, parent: int, blink_at: float | None):
    rx, ry = POSE.eye_rx * HALF, POSE.eye_ry * HALF
    open_, shut = [2 * rx, 2 * ry], [2 * rx * 1.15, 2 * ry * 0.12]
    if blink_at is None:
        size = _still([_n(v) for v in open_])
    else:
        size = _keys(
            [
                (0, open_),
                (blink_at, open_),
                (blink_at + 4, shut),
                (blink_at + 8, open_),
                (op, open_),
            ]
        )
    groups = []
    for side, name in ((-1, "left eye"), (1, "right eye")):
        x = (POSE.look * 0.2 + side * POSE.eye_gap) * HALF
        y = POSE.eye_y * HALF
        ellipse = {"ty": "el", "nm": name, "d": 1, "p": _still([_n(x), _n(y)]), "s": size}
        groups.append({"ty": "gr", "nm": name, "it": [ellipse, _fill(BLACK), _transform()]})
    layer = _layer(ind, "EYES", 4, op, parent)
    layer["shapes"] = groups
    return layer


def _body(ind: int, op: int, parent: int):
    layer = _layer(ind, "GEM", 4, op, parent)
    layer["shapes"] = [
        {"ty": "gr", "nm": "facets", "it": [*_facets(), _fill(WHITE), _transform()]},
        {
            "ty": "gr",
            "nm": "outline",
            "it": [*_facets(), _stroke(BLACK, OUTLINE), _fill(BLACK), _transform()],
        },
    ]
    return layer


def _sparkle(ind: int, op: int, at: Pt, r: float, beats: list[float]):
    """A four-point twinkle that swells and goes out once per beat."""
    k = r * 0.24
    star = [(0, -r), (k, -k), (r, 0), (k, k), (0, r), (-k, k), (-r, 0), (-k, -k)]
    frames: list[tuple[float, list[float]]] = []
    for a, b in zip(beats, beats[1:]):
        frames += [(a, [0, 0, 100]), (a + (b - a) * 0.45, [100, 100, 100])]
    frames.append((beats[-1], [0, 0, 100]))
    if frames[0][0] > 0:
        frames.insert(0, (0, [0, 0, 100]))
    if frames[-1][0] < op:
        frames.append((op, [0, 0, 100]))
    layer = _layer(ind, "SPARKLE", 4, op, p=_still([_n(at[0]), _n(at[1]), 0]), s=_keys(frames))
    layer["shapes"] = [
        {
            "ty": "gr",
            "nm": "twinkle",
            "it": [_path(star, 0.0001, "twinkle"), _fill(TEAL), _transform()],
        }
    ]
    return layer


def _bob(ind: int, op: int, rise: float, period: int | None, tilt: float = 0.0):
    """The null everything rides on: split position, so only ``y`` is keyed."""
    cx, cy = CENTER
    if period is None:
        y = _still(_n(cy))
    else:
        frames = []
        for start in range(0, op, period):
            frames += [(start, [cy]), (start + period / 2, [cy - rise])]
        frames.append((op, [cy]))
        y = _keys(frames)
    return _layer(ind, "BOB", 3, op, p={"s": True, "x": _still(_n(cx)), "y": y}, r=_still(tilt))


def _clip(name: str, op: int, layers: list[dict]) -> str:
    doc = {
        "v": "5.13.0",
        "fr": FPS,
        "ip": 0,
        "op": op,
        "w": W,
        "h": H,
        "nm": name,
        "ddd": 0,
        "assets": [],
        "layers": layers,
        "markers": [],
    }
    return json.dumps(doc, separators=(",", ":")) + "\n"


def clips() -> dict[str, str]:
    """File stem -> the clip's JSON text."""
    out = {}

    # resting: a slow bob, one twinkle off the crown's far corner
    for stem, name, blink in (
        ("kiro_idle_mid", "Aj_Gem_Idle", None),
        ("kiro_idle_mid_blink", "Aj_Gem_Idle_Blink", 28.0),
    ):
        op = 84
        out[stem] = _clip(
            name,
            op,
            [
                _eyes(1, op, 4, blink),
                _body(2, op, 4),
                _sparkle(3, op, (672, 122), 36, [10, 52]),
                _bob(4, op, 16, 42),
            ],
        )

    # still: no bob at all, so an error or a nap reads as stopped; it only blinks
    op = 84
    out["kiro_static_blink"] = _clip(
        "Aj_Gem_Still_Blink",
        op,
        [_eyes(1, op, 3, 28.0), _body(2, op, 3), _bob(3, op, 0, None)],
    )

    # moving: leaning into the travel, a quick bob, twinkles left in its wake
    op = 88
    out["kiro_flying"] = _clip(
        "Aj_Gem_Moving",
        op,
        [
            _eyes(1, op, 6, None),
            _body(2, op, 6),
            _sparkle(3, op, (690, 232), 38, [0, 44, 88]),
            _sparkle(4, op, (748, 356), 28, [14, 58]),
            _sparkle(5, op, (676, 470), 32, [28, 72]),
            _bob(6, op, 22, 22, tilt=-9),
        ],
    )
    return out
