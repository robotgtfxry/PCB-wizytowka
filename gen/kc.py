"""Small helpers around the KiCad 9 pcbnew Python API."""
import math
import pcbnew

FPLIB = "/usr/share/kicad/footprints"
LOCAL_LIBS = {}  # name -> path, filled by fplib


def mm(v):
    return pcbnew.FromMM(v)


def V(x, y):
    return pcbnew.VECTOR2I(mm(x), mm(y))


class Board:
    def __init__(self, origin=(50.0, 40.0)):
        self.b = pcbnew.BOARD()
        self.ox, self.oy = origin
        self.nets = {}

    # --- coordinates -------------------------------------------------------
    def P(self, x, y):
        return V(x + self.ox, y + self.oy)

    def local(self, vec):
        return (pcbnew.ToMM(vec.x) - self.ox, pcbnew.ToMM(vec.y) - self.oy)

    # --- nets -------------------------------------------------------------
    def net(self, name):
        if name is None:
            return None
        if name not in self.nets:
            n = pcbnew.NETINFO_ITEM(self.b, name)
            self.b.Add(n)
            self.nets[name] = n
        return self.nets[name]

    # --- footprints -------------------------------------------------------
    def fp(self, lib, name, ref, value, x, y, rot=0.0, back=False,
           show_ref=True, strip_silk=False):
        libpath = LOCAL_LIBS.get(lib, f"{FPLIB}/{lib}.pretty")
        f = pcbnew.FootprintLoad(libpath, name)
        if f is None:
            raise RuntimeError(f"footprint {lib}:{name} not found")
        f.SetFPID(pcbnew.LIB_ID(lib, name))
        f.SetReference(ref)
        f.SetValue(value)
        self.b.Add(f)
        f.SetPosition(self.P(x, y))
        f.SetOrientationDegrees(rot)
        if back:
            f.Flip(self.P(x, y), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        if strip_silk:
            for g in list(f.GraphicalItems()):
                if g.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS):
                    f.Remove(g)
        f.Reference().SetVisible(show_ref)
        f.Value().SetVisible(False)
        return f

    def set_pad_nets(self, f, mapping):
        """mapping: pad number -> net name"""
        for p in f.Pads():
            num = p.GetNumber()
            if num in mapping:
                p.SetNet(self.net(mapping[num]))

    # --- copper -----------------------------------------------------------
    def track(self, pts, width, layer, net):
        n = self.net(net)
        out = []
        for (x1, y1), (x2, y2) in zip(pts[:-1], pts[1:]):
            if abs(x1 - x2) < 1e-6 and abs(y1 - y2) < 1e-6:
                continue
            t = pcbnew.PCB_TRACK(self.b)
            t.SetStart(self.P(x1, y1))
            t.SetEnd(self.P(x2, y2))
            t.SetWidth(mm(width))
            t.SetLayer(layer)
            t.SetNet(n)
            self.b.Add(t)
            out.append(t)
        return out

    def via(self, x, y, net, dia=0.5, drill=0.3):
        v = pcbnew.PCB_VIA(self.b)
        v.SetPosition(self.P(x, y))
        v.SetWidth(pcbnew.F_Cu, mm(dia))
        v.SetDrill(mm(drill))
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(self.net(net))
        self.b.Add(v)
        return v

    # --- graphics ---------------------------------------------------------
    def seg(self, x1, y1, x2, y2, layer, w=0.1):
        s = pcbnew.PCB_SHAPE(self.b)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(self.P(x1, y1))
        s.SetEnd(self.P(x2, y2))
        s.SetLayer(layer)
        s.SetWidth(mm(w))
        self.b.Add(s)
        return s

    def arc(self, start, mid, end, layer, w=0.1):
        s = pcbnew.PCB_SHAPE(self.b)
        s.SetShape(pcbnew.SHAPE_T_ARC)
        s.SetArcGeometry(self.P(*start), self.P(*mid), self.P(*end))
        s.SetLayer(layer)
        s.SetWidth(mm(w))
        self.b.Add(s)
        return s

    def circle(self, cx, cy, r, layer, w=0.1, fill=False):
        s = pcbnew.PCB_SHAPE(self.b)
        s.SetShape(pcbnew.SHAPE_T_CIRCLE)
        s.SetCenter(self.P(cx, cy))
        s.SetEnd(self.P(cx + r, cy))
        s.SetLayer(layer)
        s.SetWidth(mm(w))
        s.SetFilled(fill)
        self.b.Add(s)
        return s

    def rect(self, x1, y1, x2, y2, layer, w=0.1, fill=False):
        s = pcbnew.PCB_SHAPE(self.b)
        s.SetShape(pcbnew.SHAPE_T_RECTANGLE)
        s.SetStart(self.P(x1, y1))
        s.SetEnd(self.P(x2, y2))
        s.SetLayer(layer)
        s.SetWidth(mm(w))
        s.SetFilled(fill)
        self.b.Add(s)
        return s

    def text(self, s, x, y, size, layer, thick=None, bold=False,
             justify="left", mirror=None, angle=0.0, italic=False):
        t = pcbnew.PCB_TEXT(self.b)
        t.SetText(s)
        t.SetPosition(self.P(x, y))
        t.SetLayer(layer)
        t.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size)))
        t.SetTextThickness(mm(thick if thick else size * (0.2 if bold else 0.15)))
        t.SetBold(bold)
        t.SetItalic(italic)
        t.SetTextAngleDegrees(angle)
        hj = {"left": pcbnew.GR_TEXT_H_ALIGN_LEFT,
              "center": pcbnew.GR_TEXT_H_ALIGN_CENTER,
              "right": pcbnew.GR_TEXT_H_ALIGN_RIGHT}[justify]
        t.SetHorizJustify(hj)
        if mirror is None:
            mirror = layer in (pcbnew.B_SilkS, pcbnew.B_Cu, pcbnew.B_Mask)
        t.SetMirrored(mirror)
        self.b.Add(t)
        return t

    def rounded_rect_outline(self, x1, y1, x2, y2, r, layer=pcbnew.Edge_Cuts, w=0.1):
        k = r * (1 - 1 / math.sqrt(2))
        self.seg(x1 + r, y1, x2 - r, y1, layer, w)
        self.seg(x2, y1 + r, x2, y2 - r, layer, w)
        self.seg(x2 - r, y2, x1 + r, y2, layer, w)
        self.seg(x1, y2 - r, x1, y1 + r, layer, w)
        self.arc((x2 - r, y1), (x2 - k, y1 + k), (x2, y1 + r), layer, w)
        self.arc((x2, y2 - r), (x2 - k, y2 - k), (x2 - r, y2), layer, w)
        self.arc((x1 + r, y2), (x1 + k, y2 - k), (x1, y2 - r), layer, w)
        self.arc((x1, y1 + r), (x1 + k, y1 + k), (x1 + r, y1), layer, w)

    # --- zones ------------------------------------------------------------
    def zone(self, pts, layer, net, clearance=0.25, min_width=0.2,
             priority=0, thermal_gap=0.3, spoke=0.3, hatch=None):
        z = pcbnew.ZONE(self.b)
        z.SetLayer(layer)
        z.SetNet(self.net(net))
        ol = z.Outline()
        ol.NewOutline()
        for x, y in pts:
            ol.Append(mm(x + self.ox), mm(y + self.oy))
        z.SetLocalClearance(mm(clearance))
        z.SetMinThickness(mm(min_width))
        z.SetAssignedPriority(priority)
        z.SetThermalReliefGap(mm(thermal_gap))
        z.SetThermalReliefSpokeWidth(mm(spoke))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        if hatch:                                  # (thickness, gap, angle) decorative grid
            th, gap, ang = hatch
            z.SetFillMode(pcbnew.ZONE_FILL_MODE_HATCH_PATTERN)
            z.SetHatchThickness(mm(th))
            z.SetHatchGap(mm(gap))
            z.SetHatchOrientation(pcbnew.EDA_ANGLE(ang, pcbnew.DEGREES_T))
            z.SetHatchSmoothingLevel(0)
            z.SetHatchHoleMinArea(0.3)
        self.b.Add(z)
        return z

    def keepout(self, pts, layers, tracks=True, vias=False, pour=True, pads=False):
        z = pcbnew.ZONE(self.b)
        z.SetIsRuleArea(True)
        ls = pcbnew.LSET()
        for l in layers:
            ls.AddLayer(l)
        z.SetLayerSet(ls)
        z.SetDoNotAllowTracks(tracks)
        z.SetDoNotAllowVias(vias)
        z.SetDoNotAllowCopperPour(pour)
        z.SetDoNotAllowPads(pads)
        z.SetDoNotAllowFootprints(False)
        ol = z.Outline()
        ol.NewOutline()
        for x, y in pts:
            ol.Append(mm(x + self.ox), mm(y + self.oy))
        self.b.Add(z)
        return z


def circle_pts(cx, cy, r, n=48):
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n))
            for i in range(n)]
