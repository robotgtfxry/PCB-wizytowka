"""Project footprint library: hardware/lib/wizytowka.pretty  (run as its own process)."""
import os
import sys

import pcbnew

sys.path.insert(0, os.path.dirname(__file__))
import fork as FK  # noqa: E402
from kc import FPLIB, V, mm  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LIBDIR = os.path.join(ROOT, "hardware", "lib", "wizytowka.pretty")
LIBNAME = "wizytowka"


def _save(fp, name):
    fp.SetFPID(pcbnew.LIB_ID(LIBNAME, name))
    path = os.path.join(LIBDIR, name + ".kicad_mod")
    if os.path.exists(path):
        os.remove(path)
    pcbnew.PCB_IO_KICAD_SEXPR().FootprintSave(LIBDIR, fp)


def led_nosilk(src, name):
    fp = pcbnew.FootprintLoad(f"{FPLIB}/LED_SMD.pretty", src)
    for g in list(fp.GraphicalItems()):
        if g.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS):
            fp.Remove(g)
    fp.SetLibDescription(f"LED {src} without silkscreen (dense matrix); polarity on F.Fab. "
                         f"Based on KiCad LED_SMD:{src}")
    _save(fp, name)


def _gr(fp, shape, layer, w=0.12):
    s = pcbnew.PCB_SHAPE(fp)
    s.SetShape(shape)
    s.SetLayer(layer)
    s.SetWidth(mm(w))
    return s


def cr2032_fork():
    """Battery contacts for the one-tongue fork cut out of the card. Origin = cell centre.
    Pad 1 (+): strip on F.Cu along the tongue (the tongue is bent behind the cell).
    Pad 2 (-): two pads on B.Cu on the fork arms, close to the cell centre."""
    b = pcbnew.BOARD()
    fp = pcbnew.FOOTPRINT(b)
    fp.SetReference("BT")
    fp.SetValue("CR2032_PCB_FORK")
    fp.SetLibDescription("CR2032 held by a one-tongue fork cut out of the card (no holder). "
                         "Board outline is drawn on the board, see gen/fork.py.")
    fp.SetAttributes(pcbnew.FP_SMD)

    def pad(num, x, y, sx, sy, layers):
        p = pcbnew.PAD(fp)
        p.SetNumber(num)
        p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        ls = pcbnew.LSET()
        for L in layers:
            ls.AddLayer(L)
        p.SetLayerSet(ls)
        p.SetShape(pcbnew.F_Cu, pcbnew.PAD_SHAPE_RECT)
        p.SetSize(pcbnew.F_Cu, V(sx, sy))
        p.SetPosition(V(x, y))
        fp.Add(p)

    x1, x2, w = FK.PLUS_STRIP
    pad("1", (x1 + x2) / 2, 0.0, x2 - x1, w, (pcbnew.F_Cu, pcbnew.F_Mask))
    sx, sy = FK.NEG_PAD_SIZE
    for x, y in FK.NEG_PADS:
        pad("2", x, y, sx, sy, (pcbnew.B_Cu, pcbnew.B_Mask))
    for layer in (pcbnew.F_Fab, pcbnew.B_Fab):
        c = _gr(fp, pcbnew.SHAPE_T_CIRCLE, layer, 0.1)
        c.SetCenter(V(0, 0))
        c.SetEnd(V(FK.BAT_R, 0))
        fp.Add(c)
    _save(fp, "CR2032_PCB_FORK")


def write_lib_table(project_dir, rel="../lib/wizytowka.pretty"):
    with open(os.path.join(project_dir, "fp-lib-table"), "w") as fh:
        fh.write('(fp_lib_table\n  (version 7)\n'
                 f'  (lib (name "{LIBNAME}")(type "KiCad")(uri "${{KIPRJMOD}}/{rel}")'
                 '(options "")(descr "PCB business card project footprints"))\n)\n')


def build_all():
    os.makedirs(LIBDIR, exist_ok=True)
    for f in os.listdir(LIBDIR):
        os.remove(os.path.join(LIBDIR, f))
    led_nosilk("LED_0603_1608Metric", "LED_0603_1608Metric_NoSilk")
    cr2032_fork()


if __name__ == "__main__":
    build_all()
    print("library at", LIBDIR)
