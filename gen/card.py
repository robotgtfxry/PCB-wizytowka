#!/usr/bin/env python3
"""PCB business card (85.6 x 54 mm), KiCad 9.  rev 2

Front: 16x8 charlieplexed 0603 LED matrix (each LED rotated 45 deg, 2.54 mm
pitch, ~40 x 20 mm), two SMD buttons.
Back:  CH32V003F4P6, 12 series resistors, decoupling, reverse-polarity
P-MOSFET, SWIO pogo pads.
CR2032 held by a one-tongue fork cut out of the card itself (see gen/fork.py).

Charlieplex topology (12 lines L0..L11, 128 LEDs, no empty cells):
  * rows 0..7: row bus = L0..L7 (F.Cu), the up-left pad of every LED sits on it
  * column 0:      8 LEDs between the Q lines L8..L11 (Q-Q pairs)
  * columns 1..8:  Q columns (L8..L11, each twice, both polarities)
  * columns 9..15: classic split columns (L-L pairs); the column bus changes
                   line at the diagonal and joins the matching row bus.
"""
import json
import os
import re
import subprocess
import sys
import uuid

import pcbnew

sys.path.insert(0, os.path.dirname(__file__))
import kc  # noqa: E402
from kc import Board, mm, circle_pts  # noqa: E402
from router import Router  # noqa: E402
import fork as FK  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "hardware", "card")
LIBDIR = os.path.join(ROOT, "hardware", "lib", "wizytowka.pretty")
F, B = pcbnew.F_Cu, pcbnew.B_Cu

W, H, R_CORNER = 85.6, 54.0, 3.18

# ------------------------------------------------------------------ matrix
COLS, ROWS = 16, 8
PITCH = 2.54
X0, Y0 = 6.3, 5.6
BUS_DY = -1.08              # row bus (F.Cu) offset from LED centre
VIA_D = (-0.785, 0.785)     # LED via in the lower-left pocket of the cell
JOG_DX = -0.2               # x offset of the split-column jog (B.Cu)
MTW = 0.15                  # matrix track width
LANE_DY0, LANE_STEP = 1.5, 1.0
QX0, QX_STEP = 1.7, 0.85    # Q buses (B.Cu) left of the display
XEXIT = X0 + (COLS - 1) * PITCH + 2.0
NL = 12
Q_COLS = [8, 9, 10, 11, 8, 9, 10, 11]          # line of Q columns x = 1..8
SPECIAL = [(8, 9), (9, 10), (10, 11), (11, 8), (9, 8), (10, 9), (11, 10), (8, 11)]  # column 0
PIN_NAME = {"1": "PD4", "2": "PD5", "3": "PD6", "4": "PD7/NRST", "5": "PA1", "6": "PA2",
            "7": "VSS", "8": "PD0", "9": "VDD", "10": "PC0", "11": "PC1", "12": "PC2",
            "13": "PC3", "14": "PC4", "15": "PC5", "16": "PC6", "17": "PC7",
            "18": "PD1/SWIO", "19": "PD2", "20": "PD3"}

BAT_C = (W - 11.0, 42.5)        # cell centre (cell lies on the back, inside the fork)


def lx(x):
    return X0 + x * PITCH


def ly(y):
    return Y0 + y * PITCH


def lane_y(q):
    return ly(ROWS - 1) + LANE_DY0 + LANE_STEP * (q - 8)


def qbus_x(q):
    return X0 - QX0 - QX_STEP * (q - 8)


def L(i):
    return f"L{i}"


def LM(i):
    return f"L{i}_MCU"


def sym_uuid(ref):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "pcb-wizytowka/card/" + ref))


def matrix_map():
    """(x, y) -> (anode_line, cathode_line, ul_role)"""
    cells = {}
    for y in range(ROWS):
        a, k = SPECIAL[y]
        cells[(0, y)] = (a, k, "anode")
    seen = set()
    for x in range(1, 9):
        q = Q_COLS[x - 1]
        typ = "A" if q not in seen else "B"
        seen.add(q)
        for y in range(ROWS):
            cells[(x, y)] = (y, q, "anode") if typ == "A" else (q, y, "cathode")
    for x in range(9, 16):
        k = x - 9
        for r in range(ROWS):
            cells[(x, r)] = (r, k if k < r else k + 1, "anode")
    pairs = [(a, c) for a, c, _ in cells.values()]
    assert len(pairs) == 128 and len(set(pairs)) == 128 and all(a != c for a, c in pairs)
    return cells


def build():
    here = os.path.dirname(__file__)
    subprocess.run([sys.executable, os.path.join(here, "fplib.py")], check=True,
                   stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    subprocess.run([sys.executable, os.path.join(here, "models3d.py")], check=True,
                   stdout=subprocess.DEVNULL)
    kc.LOCAL_LIBS["wizytowka"] = LIBDIR
    kb = Board(origin=(50.0, 40.0))
    b = kb.b
    parts = []

    ds = b.GetDesignSettings()
    ds.m_TrackMinWidth = mm(0.127)
    ds.m_MinClearance = mm(0.15)
    ds.m_ViasMinSize = mm(0.45)
    ds.m_MinThroughDrill = mm(0.3)
    ds.m_CopperEdgeClearance = mm(0.3)
    ds.m_HoleToHoleMin = mm(0.25)
    ds.m_HoleClearance = mm(0.2)
    nc = ds.m_NetSettings.GetDefaultNetclass()
    nc.SetClearance(mm(0.15))
    nc.SetTrackWidth(mm(0.2))
    nc.SetViaDiameter(mm(0.5))
    nc.SetViaDrill(mm(0.3))
    ds.SetBoardThickness(mm(1.6))

    # ---- outline (card minus the fork pocket / slots) ------------------------
    bx, by = BAT_C
    for ol in FK.board_outline(W, H, R_CORNER, bx, by):
        for (x1, y1), (x2, y2) in zip(ol, ol[1:] + ol[:1]):
            kb.seg(x1, y1, x2, y2, pcbnew.Edge_Cuts)
    st = FK.strain_estimate()
    print("fork: tongue %.1f mm to the cell, deflection %.1f mm, strain %.2f%%, force ~%.1f N"
          % (st["length"], st["deflection"], 100 * st["strain"], st["force"]))

    # ---- LED matrix ---------------------------------------------------------
    cells = matrix_map()
    row_taps = {y: [] for y in range(ROWS)}
    led_table = []
    n = 1
    qvias = {q: [] for q in range(8, 12)}
    for y in range(ROWS):
        for x in range(COLS):
            a, k, ul_role = cells[(x, y)]
            X, Y = lx(x), ly(y)
            rot = 135 if ul_role == "anode" else -45
            ref = f"D{n}"
            n += 1
            f = kb.fp("wizytowka", "LED_0603_1608Metric_NoSilk", ref, "LED_0603_YG", X, Y, rot,
                      show_ref=False)
            kb.set_pad_nets(f, {"2": L(a), "1": L(k)})
            pads = {p.GetNumber(): kb.local(p.GetPosition()) for p in f.Pads() if p.GetNumber()}
            ulp = pads["2" if ul_role == "anode" else "1"]
            lrp = pads["1" if ul_role == "anode" else "2"]
            assert ulp[0] < X and ulp[1] < Y and lrp[0] > X and lrp[1] > Y
            ul_net = L(a if ul_role == "anode" else k)
            lr_net = L(k if ul_role == "anode" else a)
            led_table.append(dict(ref=ref, col=x, row=y, anode=L(a), cathode=L(k)))
            parts.append((ref, "LED 0603 yellow-green", "wizytowka:LED_0603_1608Metric_NoSilk",
                          X, Y, rot, "top"))
            if x == 0:
                # Q-Q LED: both pads go left to the Q buses
                for (px, py), net in ((ulp, ul_net), (lrp, lr_net)):
                    q = int(net[1:])
                    vx = qbus_x(q)
                    kb.track([(px, py), (vx, py)], MTW, F, net)
                    kb.via(vx, py, net)
                    qvias[q].append(py)
                continue
            kb.track([ulp, (ulp[0], Y + BUS_DY)], MTW, F, ul_net)       # -> row bus
            row_taps[y].append(ulp[0])
            vx, vy = X + VIA_D[0], Y + VIA_D[1]                          # -> pocket via
            kb.track([lrp, (vx, vy)], MTW, F, lr_net)
            kb.via(vx, vy, lr_net)

    # Q columns (B.Cu), down to their lane
    for x in range(1, 9):
        q = Q_COLS[x - 1]
        cx = lx(x) + VIA_D[0]
        kb.via(cx, lane_y(q), L(q))
        kb.track([(cx, ly(r) + VIA_D[1]) for r in range(ROWS)] + [(cx, lane_y(q))], MTW, B, L(q))
    # split columns (B.Cu)
    for x in range(9, 16):
        k = x - 9
        cx = lx(x) + VIA_D[0]
        jy = ly(k + 1) + BUS_DY       # upper segment (line k+1) joins row bus k+1 here
        kb.track([(cx, ly(r) + VIA_D[1]) for r in range(0, k + 1)] + [(cx, jy)], MTW, B, L(k + 1))
        kb.via(cx, jy, L(k + 1))
        row_taps[k + 1].append(cx)
        jx = lx(x) + JOG_DX           # lower segment (line k) jogs right, up to row bus k
        lower = [(cx, ly(r) + VIA_D[1]) for r in range(ROWS - 1, k, -1)]
        tx, ty = lower[-1]
        lower += [(jx, ty - abs(jx - tx)), (jx, ly(k) + BUS_DY)]
        kb.track(lower, MTW, B, L(k))
        kb.via(jx, ly(k) + BUS_DY, L(k))
        row_taps[k].append(jx)
    # Q buses left of the display (B.Cu) + lanes under the display (F.Cu)
    lane_taps = {q: [qbus_x(q)] for q in range(8, 12)}
    for x in range(1, 9):
        lane_taps[Q_COLS[x - 1]].append(lx(x) + VIA_D[0])
    for q in range(8, 12):
        qx = qbus_x(q)
        ys = sorted(set(round(v, 4) for v in qvias[q] + [lane_y(q)]))
        kb.via(qx, lane_y(q), L(q))
        kb.track([(qx, yv) for yv in ys], MTW, B, L(q))
        xs = sorted(set(round(v, 4) for v in lane_taps[q] + [XEXIT]))
        kb.track([(xv, lane_y(q)) for xv in xs], MTW, F, L(q))
    # row buses (F.Cu), split at every tap
    for y in range(ROWS):
        xs = sorted(set(round(v, 4) for v in row_taps[y] + [XEXIT]))
        kb.track([(xv, ly(y) + BUS_DY) for xv in xs], MTW, F, L(y))

    S = pcbnew.F_SilkS
    fx1, fy1 = lx(0) - 1.9, ly(0) - 2.0
    fx2, fy2 = lx(COLS - 1) + 1.9, ly(ROWS - 1) + 1.9
    for (a1, b1, a2, b2) in [(fx1, fy1, fx1 + 2.5, fy1), (fx1, fy1, fx1, fy1 + 2.5),
                             (fx2, fy1, fx2 - 2.5, fy1), (fx2, fy1, fx2, fy1 + 2.5),
                             (fx1, fy2, fx1 + 2.5, fy2), (fx1, fy2, fx1, fy2 - 2.5),
                             (fx2, fy2, fx2 - 2.5, fy2), (fx2, fy2, fx2, fy2 - 2.5)]:
        kb.seg(a1, b1, a2, b2, S, 0.15)

    # ---- back: MCU (rot 0 + flip: left column = pins 20..11 top->bottom) -------
    UX, UY = 58.0, 14.0
    u1 = kb.fp("Package_SO", "TSSOP-20_4.4x6.5mm_P0.65mm", "U1", "CH32V003F4P6", UX, UY, 0,
               back=True)
    upads = {p.GetNumber(): kb.local(p.GetPosition()) for p in u1.Pads()}
    assert upads["20"][0] < UX and upads["20"][1] < upads["11"][1] and upads["1"][0] > UX
    # L0..L2 wrap over the top of the MCU onto PD6/PD5/PD4, the rest go to the left column
    line_pin = {0: "3", 1: "2", 2: "1", 3: "20", 4: "19", 5: "17", 6: "16", 7: "15",
                8: "14", 9: "13", 10: "12", 11: "11"}
    mp = {line_pin[i]: LM(i) for i in range(NL)}
    mp.update({"9": "VDD", "7": "GND", "18": "SWIO", "5": "BTN_A", "6": "BTN_B",
               "4": "unconnected-(U1-PD7-Pad4)", "10": "unconnected-(U1-PC0-Pad10)",
               "8": "unconnected-(U1-PD0-Pad8)"})
    kb.set_pad_nets(u1, mp)
    parts.append(("U1", "CH32V003F4P6", "Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm", UX, UY, 0, "bottom"))

    # ---- back: series resistors = 3 x 4-resistor arrays left of the MCU ----------
    res = {}
    for j, cy in enumerate((UY - 3.6, UY - 0.6, UY + 1.95)):
        refd = f"RN{j + 1}"
        f = kb.fp("Resistor_SMD", "R_Array_Convex_4x0402", refd, "4x33R", UX - 5.6, cy, 0, back=True,
                  show_ref=False)
        pp = {p.GetNumber(): p for p in f.Pads()}
        pairs = sorted([(pp[str(k)], pp[str(9 - k)]) for k in range(1, 5)],
                       key=lambda t: kb.local(t[0].GetPosition())[1])
        for i, (pa, pb) in zip(range(4 * j, 4 * j + 4), pairs):
            p_l, p_r = sorted((pa, pb), key=lambda p: kb.local(p.GetPosition())[0])
            p_l.SetNet(kb.net(L(i)))
            p_r.SetNet(kb.net(LM(i)))
            res[i] = (f, p_l, p_r)
        parts.append((refd, "4x33R array 0402 (convex)", "Resistor_SMD:R_Array_Convex_4x0402",
                      UX - 5.6, cy, 0, "bottom"))
    # staircase escape stubs on the display side of the arrays: the line whose
    # pad is highest is outermost (longest stub); L0..L2 come from above.
    order_below = list(range(3, 12))            # outermost first
    stub = {}
    for rank, i in enumerate(reversed(order_below)):
        stub[i] = 0.45 + 0.3 * rank
    for rank, i in enumerate([0, 1, 2]):
        stub[i] = 0.45 + 0.3 * rank
    stub_end = {}
    for i in range(NL):
        x_, y_ = kb.local(res[i][1].GetPosition())
        stub_end[i] = (x_ - stub[i], y_)
        kb.track([(x_, y_), stub_end[i]], MTW, B, L(i))

    def ploc(fp, num):
        return [kb.local(p.GetPosition()) for p in fp.Pads() if p.GetNumber() == num][0]

    vdd, vss = ploc(u1, "9"), ploc(u1, "7")
    c1 = kb.fp("Capacitor_SMD", "C_0402_1005Metric", "C1", "100n", vdd[0] + 2.0, (vdd[1] + vss[1]) / 2,
               90, back=True, show_ref=False)
    c2 = kb.fp("Capacitor_SMD", "C_0805_2012Metric", "C2", "22u", UX, UY + 5.6, 0, back=True,
               show_ref=False)
    for f in (c1, c2):
        pa, pb = sorted(f.Pads(), key=lambda p: (kb.local(p.GetPosition())[0] - vdd[0]) ** 2 +
                        (kb.local(p.GetPosition())[1] - vdd[1]) ** 2)
        pa.SetNet(kb.net("VDD"))
        pb.SetNet(kb.net("GND"))
        x_, y_ = kb.local(f.GetPosition())
        parts.append((f.GetReference(), "100nF 0402 X7R" if f is c1 else "22uF 0805 X5R 6.3V",
                      f"Capacitor_SMD:{f.GetFPID().GetLibItemName()}", x_, y_, 0, "bottom"))

    q1 = kb.fp("Package_TO_SOT_SMD", "SOT-23", "Q1", "AO3401A", 30.0, 36.0, 0, back=True,
               show_ref=False)
    kb.set_pad_nets(q1, {"1": "GND", "2": "VDD", "3": "+BATT"})
    parts.append(("Q1", "AO3401A P-MOSFET", "Package_TO_SOT_SMD:SOT-23", 30.0, 36.0, 0, "bottom"))

    # ---- back: pogo pads ----------------------------------------------------
    TP = [("TP1", "VDD", "3V3", 40.0), ("TP2", "SWIO", "SWIO", 42.54), ("TP3", "GND", "GND", 45.08)]
    TPY = 34.0
    tps = {}
    for refd, net, lab, tx in TP:
        f = kb.fp("TestPoint", "TestPoint_Pad_D1.5mm", refd, lab, tx, TPY, 0, back=True,
                  show_ref=False)
        kb.set_pad_nets(f, {"1": net})
        tps[refd] = f
        kb.text(lab, tx, TPY + 3.0, 0.8, pcbnew.B_SilkS, justify="center", angle=90)

    # ---- front: buttons -------------------------------------------------------
    SW = [("SW1", "BTN_A", "A", 66.0), ("SW2", "BTN_B", "B", 78.0)]
    SWY = 19.0
    sws = {}
    for refd, net, lab, sx in SW:
        f = kb.fp("Button_Switch_SMD", "SW_SPST_PTS810", refd, "PTS810", sx, SWY, 0, show_ref=False)
        kb.set_pad_nets(f, {"1": net, "2": "GND"})
        sws[refd] = f
        kb.text(lab, sx, SWY - 3.7, 1.4, S, bold=True, justify="center")
        parts.append((refd, "Tactile 4.2x3.2 SMD", "Button_Switch_SMD:SW_SPST_PTS810", sx, SWY, 0,
                      "top"))

    # ---- battery contacts + fork copper -------------------------------------------
    bt = kb.fp("wizytowka", "CR2032_PCB_FORK", "BT1", "CR2032", bx, by, 0, show_ref=False)
    kb.set_pad_nets(bt, {"1": "+BATT", "2": "GND"})
    parts.append(("BT1", "CR2032 (card fork holder)", "wizytowka:CR2032_PCB_FORK", bx, by, 0, "bottom"))
    x1, x2, _ = FK.PLUS_STRIP                # (+) strip on the tongue -> along the tongue (F.Cu)
    kb.track([(bx + x1 + 0.6, by), (bx + FK.PLUS_VIA_X, by)], 0.4, F, "+BATT")
    kb.via(bx + FK.PLUS_VIA_X, by, "+BATT")
    plus_join = (bx + FK.PLUS_VIA_X, by)
    neg_vias = []
    for x, y in FK.NEG_PADS:                 # (-) pads on the arms: via in pad
        kb.via(bx + x, by + y, "GND", 0.6, 0.3)
        neg_vias.append((bx + x, by + y))

    # ---- silkscreen ------------------------------------------------------------
    kb.text("IMIĘ NAZWISKO", 5.0, 32.8, 2.6, S, bold=True)
    kb.text("Embedded / Hardware Engineer", 5.0, 36.4, 1.25, S)
    kb.seg(5.0, 38.3, 60.0, 38.3, S, 0.15)
    kb.text("imie.nazwisko@example.com", 5.0, 47.8, 1.15, S)
    kb.text("+48 000 000 000", 40.0, 47.8, 1.15, S)
    kb.text("github.com/twoj-nick", 5.0, 50.8, 1.15, S)
    kb.text("www.example.com", 40.0, 50.8, 1.15, S)
    kb.text("16×8 · LED 0603 · CH32V003", 69.0, 5.6, 0.9, S, justify="center")
    kb.text("odegnij język do tyłu, wsuń CR2032 (−) do karty", 69.0, 8.2, 0.8, S, justify="center")
    BS = pcbnew.B_SilkS
    kb.text("PCB WIZYTÓWKA rev 4.0", 24.0, 47.6, 1.6, BS, bold=True, justify="center")
    kb.text("2026-11", 24.0, 50.3, 1.0, BS, justify="center")
    kb.text("CH32V003 · 128× LED 0603 · charlieplex 12 linii", 24.0, 52.4, 0.9, BS, justify="center")
    kb.text("SWD (WCH-LinkE)", 42.54, TPY - 2.0, 0.9, BS, justify="center")
    kb.text("CR2032: (−) do karty, (+) do języka", bx - 6.0, by - 11.6, 0.9, BS, justify="center")

    # ---- routing --------------------------------------------------------------
    rt = Router(kb, 0, 0, W, H, corner_r=R_CORNER)
    rt.import_board()
    rt.block_mask(FK.in_region(rt.X - bx, rt.Y - by), (0, 1))
    rt.block_mask((rt.X - bx) ** 2 + (rt.Y - by) ** 2 < 10.9 ** 2, (1,))

    def pxy(fp, num, idx=0):
        p = [p for p in fp.Pads() if p.GetNumber() == num][idx]
        x, y = kb.local(p.GetPosition())
        return (x, y, tuple(i for i, Ly in enumerate((F, B)) if p.IsOnLayer(Ly)))

    log = []

    def R(net, a, dst, w=0.2, **kw):
        kw.setdefault("layer_bias", (2.5, 1.0))
        kw.setdefault("via_cost", 5.0)
        try:
            made, vias = rt.route(net, a, dst, width=w, **kw)
        except RuntimeError:
            dbg = os.path.join(os.environ.get("TMPDIR", "/tmp"), "debug_failed.kicad_pcb")
            pcbnew.SaveBoard(dbg, b)
            print("partial board saved to", dbg)
            raise
        log.append((net, len(made), len(vias)))

    for i in [3, 4, 5, 6, 7, 8, 9, 10, 11, 2, 1, 0]:
        x_, y_ = kb.local(res[i][2].GetPosition())
        R(LM(i), (x_, y_, (1,)), pxy(u1, line_pin[i]), w=MTW)
    pad_y = {i: kb.local(res[i][1].GetPosition())[1] for i in range(NL)}
    exit_y = {i: (ly(i) + BUS_DY if i < 8 else lane_y(i)) for i in range(NL)}
    for i in [11, 10, 9, 8, 7, 6, 5, 4, 3, 0, 1, 2]:
        sx_, sy_ = stub_end[i]
        R(L(i), (XEXIT, exit_y[i], (0,)), (sx_, sy_, (1,)), w=MTW, exact=True)
    R("+BATT", pxy(q1, "3"), (plus_join[0], plus_join[1], (1,)), w=0.3)
    R("GND", (neg_vias[0][0], neg_vias[0][1], (0,)), pxy(q1, "1"), w=0.3)
    R("GND", (neg_vias[1][0], neg_vias[1][1], (0,)), pxy(q1, "1"), w=0.3)
    R("SWIO", pxy(u1, "18"), pxy(tps["TP2"], "1"))
    for f in (c1, c2):
        x_, y_ = kb.local([p for p in f.Pads() if p.GetNetname() == "VDD"][0].GetPosition())
        R("VDD", (x_, y_, (1,)), pxy(u1, "9"), w=0.3)
    R("VDD", pxy(q1, "2"), "net", w=0.3)
    R("VDD", pxy(tps["TP1"], "1"), "net", w=0.3)
    for refd, net, lab, sx in SW:
        R(net, pxy(sws[refd], "1", 0), pxy(sws[refd], "1", 1))
    R("BTN_A", pxy(u1, "5"), "net")
    R("BTN_B", pxy(u1, "6"), "net")
    for f in (c1, c2):
        x_, y_ = kb.local([p for p in f.Pads() if p.GetNetname() == "GND"][0].GetPosition())
        R("GND", (x_, y_, (1,)), pxy(u1, "7"), w=0.3)
    R("GND", pxy(u1, "7"), pxy(q1, "1"), w=0.3)          # MCU ground -> main tree
    R("GND", pxy(tps["TP3"], "1"), pxy(q1, "1"), w=0.3)
    for refd, net, lab, sx in SW:
        R("GND", pxy(sws[refd], "2", 0), pxy(sws[refd], "2", 1), w=0.3)
    R("GND", pxy(sws["SW2"], "2", 0), pxy(sws["SW1"], "2", 1), w=0.3)
    R("GND", pxy(sws["SW1"], "2", 0), pxy(u1, "7"), w=0.3)

    # ---- pours ---------------------------------------------------------------------
    outline = [(0, 0), (W, 0), (W, H), (0, H)]
    HATCH = (0.3, 0.9, 45.0)          # decorative 45 deg copper lattice (matches the LEDs)
    kb.zone(outline, F, "GND", clearance=0.25, min_width=0.25, hatch=HATCH)
    kb.zone(outline, B, "GND", clearance=0.25, min_width=0.25, hatch=HATCH)
    kz = [(bx + FK.X_ROOT - 1.0, by - FK.BAND - 0.3), (W, by - FK.BAND - 0.3),
          (W, by + FK.BAND + 0.3), (bx + FK.X_ROOT - 1.0, by + FK.BAND + 0.3)]
    kb.keepout(kz, [F, B], tracks=False, vias=False, pour=True)
    kb.keepout(circle_pts(bx, by, 10.6, 72), [B], tracks=False, vias=False, pour=True)

    # ---- footprint <-> schematic link + netlist ---------------------------------
    netlist = {}
    for f in b.GetFootprints():
        refd = f.GetReference()
        uid = sym_uuid(refd)
        f.SetPath(pcbnew.KIID_PATH("/" + uid))
        fpid = f.GetFPID()
        netlist[refd] = dict(value=f.GetValue(), uuid=uid,
                             footprint=f"{fpid.GetLibNickname()}:{fpid.GetLibItemName()}",
                             pins={p.GetNumber(): p.GetNetname() for p in f.Pads() if p.GetNumber()})
    os.makedirs(OUT, exist_ok=True)
    json.dump(netlist, open(os.path.join(OUT, "netlist.json"), "w"), indent=1, sort_keys=True)
    json.dump(led_table, open(os.path.join(OUT, "led_map.json"), "w"), indent=1)
    json.dump(parts, open(os.path.join(OUT, "parts.json"), "w"), indent=1)
    pins = {L(i): PIN_NAME[line_pin[i]] for i in range(NL)}
    pins.update({"BTN_A": PIN_NAME["5"], "BTN_B": PIN_NAME["6"], "SWIO": PIN_NAME["18"]})
    json.dump(pins, open(os.path.join(OUT, "pins.json"), "w"), indent=1)
    with open(os.path.join(OUT, "fp-lib-table"), "w") as fh:
        fh.write('(fp_lib_table\n  (version 7)\n  (lib (name "wizytowka")(type "KiCad")'
                 '(uri "${KIPRJMOD}/../lib/wizytowka.pretty")(options "")'
                 '(descr "PCB business card project footprints"))\n)\n')
    path = os.path.join(OUT, "card.kicad_pcb")
    pcbnew.SaveBoard(path, b)
    set_stackup_file(path)
    b2 = pcbnew.LoadBoard(path)
    b2.BuildConnectivity()
    pcbnew.ZONE_FILLER(b2).Fill(b2.Zones())
    pcbnew.SaveBoard(path, b2)
    set_models_file(path)
    for l_ in log:
        print("routed", *l_)
    print("saved", path)


STACKUP = """  (stackup
   (layer "F.SilkS" (type "Top Silk Screen") (color "White"))
   (layer "F.Paste" (type "Top Solder Paste"))
   (layer "F.Mask" (type "Top Solder Mask") (color "Black") (thickness 0.01))
   (layer "F.Cu" (type "copper") (thickness 0.035))
   (layer "dielectric 1" (type "core") (thickness 1.51) (material "FR4") (epsilon_r 4.5) (loss_tangent 0.02))
   (layer "B.Cu" (type "copper") (thickness 0.035))
   (layer "B.Mask" (type "Bottom Solder Mask") (color "Black") (thickness 0.01))
   (layer "B.Paste" (type "Bottom Solder Paste"))
   (layer "B.SilkS" (type "Bottom Silk Screen") (color "White"))
   (copper_finish "ENIG")
   (dielectric_constraints no)
  )
"""


def set_stackup_file(path):
    txt = open(path).read()
    if "(stackup" not in txt:
        i = txt.index("(setup") + len("(setup")
        txt = txt[:i] + "\n" + STACKUP + txt[i:]
        open(path, "w").write(txt)


MODELS = {"LED_0603_1608Metric_NoSilk": "LED_0603", "R_0402_1005Metric": "R_0402",
          "C_0402_1005Metric": "C_0402", "C_0805_2012Metric": "C_0805",
          "TSSOP-20_4.4x6.5mm_P0.65mm": "TSSOP20", "SOT-23": "SOT23",
          "SW_SPST_PTS810": "PTS810", "CR2032_PCB_FORK": "CR2032_FORK"}


def _block_end(t, i):
    d = 0
    for j in range(i, len(t)):
        if t[j] == "(":
            d += 1
        elif t[j] == ")":
            d -= 1
            if d == 0:
                return j
    raise ValueError("unbalanced")


def _strip_models(blk):
    while True:
        i = blk.find("(model ")
        if i < 0:
            return blk
        j = _block_end(blk, i)
        k = blk.rfind("\n", 0, i)
        blk = blk[:k] + blk[j + 1:]


def set_models_file(path):
    """Point every footprint at the simple project VRML models (hardware/lib/3d)."""
    t = open(path).read()
    out, pos = [], 0
    for m in re.finditer(r'\n\t\(footprint "([^"]*):([^"]*)"', t):
        start = m.start() + 1
        end = _block_end(t, start)
        blk = _strip_models(t[start:end + 1])
        name = m.group(2)
        if name in MODELS:
            mdl = (f'\t\t(model "${{KIPRJMOD}}/../lib/3d/{MODELS[name]}.wrl"\n'
                   '\t\t\t(offset (xyz 0 0 0))\n\t\t\t(scale (xyz 1 1 1))\n\t\t\t(rotate (xyz 0 0 0))\n\t\t)\n')
            blk = blk[:-1].rstrip("\t") + mdl + "\t)"
        out.append(t[pos:start])
        out.append(blk)
        pos = end + 1
    out.append(t[pos:])
    open(path, "w").write("".join(out))


if __name__ == "__main__":
    build()
