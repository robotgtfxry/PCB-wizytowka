"""CR2032 'fork' holder with ONE tongue, cut out of the card itself.

Two parallel slots run from the right card edge to the left. The strip between
them is the tongue (free at the card edge, attached at X_ROOT); the card on both
sides of the slots are the two rigid arms of the fork.

The cell lies flat on the BACK of the card, (-) face towards the card: the arms
touch the (-) cap through two pads close to the cell centre (r < 7 mm; the rim
of that face is the (+) crimp and only touches solder mask). The tongue is bent
~5 mm towards the back, behind the cell, and its front F.Cu strip presses the
(+) face. Insert: pull the tongue tip (at the card edge) back, slide the cell in
between the arms and the tongue, release.

Coordinates are relative to the cell centre (card front view, y down).
"""
import math

import pcbnew

BAT_R = 10.0
TONGUE_HW = 1.75             # tongue 3.5 mm wide
SLOT = 1.0
BAND = TONGUE_HW + SLOT      # |y| of the outer slot edge
X_ROOT = -48.0               # tongue root (slots end here)
NEG_PADS = [(0.0, -5.0), (0.0, 5.0)]      # (-) pads on the arms, B.Cu
NEG_PAD_SIZE = (6.0, 2.6)                  # -> farthest pad point r ~ 6.95 mm
PLUS_STRIP = (-9.6, 9.0, 2.3)              # (+) strip on the tongue, F.Cu: x from, x to, width
PLUS_VIA_X = X_ROOT - 2.0                  # tongue trace -> via behind the root


def _mm(v):
    return pcbnew.FromMM(v)


def _poly(pts):
    s = pcbnew.SHAPE_POLY_SET()
    s.NewOutline()
    for x, y in pts:
        s.Append(_mm(x), _mm(y))
    return s


def _slot(y0, y1, x_end, n=16):
    """Slot from X_ROOT (round end) to beyond the card edge, between y0 and y1."""
    hw = (y1 - y0) / 2
    yc = (y0 + y1) / 2
    pts = [(x_end, y0), (x_end, y1)]
    for i in range(n + 1):
        a = math.pi / 2 + math.pi * i / n
        pts.append((X_ROOT + hw * math.cos(a), yc + hw * math.sin(a)))
    return _poly(pts)


def board_outline(W, H, R, cx, cy, n_arc=16):
    """Card outline minus the two slots (board-local closed polylines)."""
    pts = []
    for (ccx, ccy, a0) in ((W - R, R, 270), (W - R, H - R, 0), (R, H - R, 90), (R, R, 180)):
        for i in range(n_arc + 1):
            a = math.radians(a0 + 90 * i / n_arc)
            pts.append((ccx + R * math.cos(a), ccy + R * math.sin(a)))
    board = _poly(pts)
    xe = W - cx + 2.0
    for s in (-1, 1):
        sl = _slot(min(s * TONGUE_HW, s * BAND), max(s * TONGUE_HW, s * BAND), xe)
        sl.Move(pcbnew.VECTOR2I(_mm(cx), _mm(cy)))
        board.BooleanSubtract(sl)
    out = []
    for oi in range(board.OutlineCount()):
        ol = board.COutline(oi)
        out.append([(pcbnew.ToMM(ol.CPoint(i).x), pcbnew.ToMM(ol.CPoint(i).y))
                    for i in range(ol.PointCount())])
        assert board.HoleCount(oi) == 0
    return out


def in_region(X, Y, margin=0.6):
    """numpy mask (relative coords) of the tongue + slots: router keep-out (both layers)."""
    import numpy as np
    return (X > X_ROOT - SLOT / 2 - margin) & (np.abs(Y) < BAND + margin)


def strain_estimate(E=20000.0, t=1.6):
    gap = 1.6 + 3.2 + 0.3          # card + cell + a little preload
    L = -math.sqrt(BAT_R ** 2 - TONGUE_HW ** 2) - X_ROOT    # root -> first contact
    k = 3 * E * (2 * TONGUE_HW) * t ** 3 / 12 / L ** 3
    return dict(length=L, deflection=gap, strain=3 * gap * t / (2 * L ** 2), force=k * gap)
