"""Supporters' names, engraved on the underside of the body lid (just under my neck).

Each name is debossed NAME_DEPTH into the lid's flat underside, laid along arcs around the
pan-bearing boss. The lid prints upside down, so the names face up on the bed and print cleanly.

Free area on the underside (29 Oct, the rounded-box abdomen): outside the bearing boss (r 25),
inside the shell's walls, behind the screen face (which meets the lid just in front of the neck),
clear of the shell's top screws and the pan-servo hanger on the -X side. Names run on RINGS; each
ring is split into the arcs that stay CLEAR of all of that (ring_arcs), filled left side first.

    python names.py names.txt   # one name per line -> out/body_lid_names.stl, and checks the fit
    python names.py --worst     # 20 names of 16 wide letters: proves the advertised capacity fits
"""
import math
import sys
from pathlib import Path

import tempfile

import manifold3d
import numpy as np
import trimesh
from build123d import Align, BuildSketch, Text, export_stl, extrude

import params as P
import model as M

MAX_NAMES = 20                 # what /claude/name sells: keep these two in step (23 of the widest fit)
MAX_CHARS = 16
FONT = 3.2                     # mm (was 3.5 on the round lid; 3.2 is what lets 20 x 16-wide names fit the new lid, 29 Oct)
NAME_DEPTH = 0.6
RINGS = (30.5, 36.0, 41.5, 47.0, 52.5, 58.0, 63.5, 69.0, 74.5, 80.0, 85.5, 91.0)
CLEAR = 2.5                    # mm kept between any letter and the walls, screws, bearing boss and hanger
SEP = 4.0                      # mm of arc between names


_GLYPHS = {}


def glyph(ch):
    """(sketch, width) for one letter, centred. Cached: names repeat letters."""
    if ch not in _GLYPHS:
        with BuildSketch() as s:
            Text(ch, font_size=FONT, align=(Align.CENTER, Align.CENTER))
        _GLYPHS[ch] = (s.sketch, max(s.sketch.bounding_box().size.X, FONT * 0.3))
    return _GLYPHS[ch]


def letters(name):
    """[(ch, offset_mm)] along the arc, and the name's total length. The ONE spacing rule, used by
    both layout and engrave, so a name takes exactly the room it was given."""
    out, x = [], 0.0
    for ch in name:
        if ch == " ":
            x += FONT * 0.35
            continue
        w = glyph(ch)[1]
        out.append((ch, x + w / 2))
        x += w + FONT * 0.12
    return out, x


def hanger_box():
    """The pan-servo hanger's footprint on the underside (x0, x1, y0, y1), from model.body_lid."""
    sv = M.pan_servo().bounding_box()
    gear_r = P.GEAR_TEETH * P.GEAR_MODULE / 2 + P.GEAR_MODULE + 1.5
    y_lo = min(sv.min.Y - P.FIT, -gear_r) - 3
    y_hi = max(sv.max.Y + P.FIT, gear_r) + 3
    return sv.min.X - 3, sv.max.X + 3, y_lo, y_hi


def free(x, y, box):
    """True where a letter may sit on the lid's underside (see the module docstring)."""
    z = P.BODY_Z1
    d, w, rr = M.body_section(z)
    hx, hy = d / 2 - P.BODY_WALL - CLEAR, w / 2 - P.BODY_WALL - CLEAR       # inside the walls
    cr = max(rr - P.BODY_WALL - CLEAR, 1.0)
    qx, qy = abs(x) - (hx - cr), abs(y) - (hy - cr)
    if abs(x) > hx or abs(y) > hy or (qx > 0 and qy > 0 and math.hypot(qx, qy) > cr):
        return False
    n = M.facet_n()                                                         # behind the screen face's inner side
    if (x - M.facet_pt(0, 0, -P.BODY_WALL).X) * n.X + (z - M.facet_pt(0, 0, -P.BODY_WALL).Z) * n.Z > -CLEAR:
        return False
    if math.hypot(x, y) < P.PAN_BRG_OD / 2 + 4 + CLEAR:                      # the bearing boss under the neck
        return False
    if any(math.hypot(x - bx, y - by) < 4.5 + CLEAR for bx, by, _ in M.body_bosses(z)):
        return False
    x0, x1, y0, y1 = box
    return not (x0 - CLEAR <= x <= x1 + CLEAR and y0 - CLEAR <= y <= y1 + CLEAR)


def ring_arcs(r, box):
    """[(lo_deg, hi_deg)] arcs of this ring where a letter (FONT tall, centred on the ring) fits."""
    ok = [all(free(rr * math.cos(math.radians(a / 2)), rr * math.sin(math.radians(a / 2)), box)
              for rr in (r - FONT / 2, r + FONT / 2)) for a in range(-360, 360)]
    arcs, start = [], None
    for i, good in enumerate(ok + [False]):
        if good and start is None:
            start = i
        if not good and start is not None:
            arcs.append(((start - 360) / 2, (i - 1 - 360) / 2))
            start = None
    return sorted(arcs, key=lambda a: -a[1])          # left side (+Y) first


def layout(names):
    """[(name, ring_r, start_deg)] or raise ValueError if they don't fit."""
    box = hanger_box()
    slots = [(r, lo, hi) for r in RINGS for lo, hi in ring_arcs(r, box)]
    placed, k, arc_pos = [], 0, 0.0
    for name in names:
        w = letters(name)[1]
        while True:
            if k >= len(slots):
                raise ValueError(f"out of room after {len(placed)} names")
            r, lo, hi = slots[k]
            if arc_pos + w <= math.radians(hi - lo) * r:
                break
            k, arc_pos = k + 1, 0.0
        r, lo, hi = slots[k]
        placed.append((name, r, hi - math.degrees(arc_pos / r)))
        arc_pos += w + SEP
    return placed


def placements(placed):
    """(letter, x, y, turn_deg) per letter, along its arc, tops outward, going CLOCKWISE seen from
    above: left to right for someone looking up at the underside (checked in a render, 26 Oct)."""
    for name, r, start in placed:
        for ch, off in letters(name)[0]:
            a = start - math.degrees(off / r)
            yield ch, r * math.cos(math.radians(a)), r * math.sin(math.radians(a)), a - 90


def _manifold(shape):
    with tempfile.NamedTemporaryFile(suffix=".stl") as f:
        export_stl(shape, f.name, tolerance=0.01, angular_tolerance=0.1)
        m = trimesh.load(f.name)
    out = manifold3d.Manifold(manifold3d.Mesh(vert_properties=np.asarray(m.vertices, np.float32),
                                              tri_verts=np.asarray(m.faces, np.uint32)))
    if out.status() != manifold3d.Error.NoError or out.is_empty():
        raise ValueError(f"not a closed mesh: {out.status()}")
    return out


def engrave(placed):
    """The lid with the names cut in, as a mesh. The cut is a MESH boolean (manifold3d), not a
    B-rep one: a B-rep face with hundreds of letter holes meshes with open T-junctions (seen
    26 Oct: 37k open edges on a solid that build123d called valid), and manifold3d's output is
    closed by construction."""
    lid = _manifold(M.body_lid())
    # Each letter is meshed ONCE, flat, then the finished mesh is moved into place: re-meshing a
    # curved letter after rotating it gave open edges ("a", "e", "o" ... on 26 Oct).
    flat = {}
    cuts = []
    for ch, x, y, turn in placements(placed):
        if ch not in flat:
            flat[ch] = _manifold(extrude(glyph(ch)[0], NAME_DEPTH + 0.01))
        cuts.append(flat[ch].rotate((180, 0, 0)).rotate((0, 0, turn))       # face down: reads from below
                    .translate((x, y, P.BODY_Z1 + NAME_DEPTH)))
    letters_ = manifold3d.Manifold.batch_boolean(cuts, manifold3d.OpType.Add)
    out = (lid - letters_).to_mesh()
    return trimesh.Trimesh(np.asarray(out.vert_properties)[:, :3], np.asarray(out.tri_verts))


def main(argv):
    if argv[1:2] == ["--worst"]:
        names = ["W" * MAX_CHARS] * MAX_NAMES
    else:
        names = [n.strip() for n in Path(argv[1]).read_text().splitlines() if n.strip()]
    if len(names) > MAX_NAMES or any(len(n) > MAX_CHARS for n in names):
        sys.exit(f"over the limit: {MAX_NAMES} names of {MAX_CHARS} characters")
    placed = layout(names)
    print(f"{len(placed)} names fit on {len({p[1] for p in placed})} of {len(RINGS)} rings")
    lid = engrave(placed)
    out = Path(__file__).parent / "out" / ("body_lid_names_worst.stl" if argv[1:2] == ["--worst"]
                                           else "body_lid_names.stl")
    out.parent.mkdir(exist_ok=True)
    lid.export(out)
    print(f"wrote {out}: watertight {lid.is_watertight}, bodies {lid.body_count}, "
          f"size {np.round(lid.extents, 1).tolist()} mm")
    if not lid.is_watertight or lid.body_count != 1:
        sys.exit("the engraved lid is not one closed solid")


if __name__ == "__main__":
    main(sys.argv)
