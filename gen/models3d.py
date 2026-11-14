"""Very simple VRML 3D models (boxes / cylinders) so renders show the parts.
KiCad treats VRML units as 0.1 inch -> divide millimetres by 2.54."""
import math
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DIR = os.path.join(ROOT, "hardware", "lib", "3d")
U = 1 / 2.54

C_BLACK = (0.08, 0.08, 0.09)
C_METAL = (0.78, 0.78, 0.80)
C_TAN = (0.72, 0.58, 0.38)
C_LED = (0.45, 0.85, 0.15)
C_WHITE = (0.92, 0.92, 0.90)
C_BAT = (0.70, 0.71, 0.74)


def _shape(points, faces, color, shin=0.3, transp=0.0):
    pts = ", ".join(f"{x * U:.4f} {y * U:.4f} {z * U:.4f}" for x, y, z in points)
    idx = ", ".join(" ".join(str(i) for i in f) + " -1" for f in faces)
    r, g, b = color
    return (f"Shape {{ appearance Appearance {{ material Material {{ diffuseColor {r} {g} {b} "
            f"specularColor 0.3 0.3 0.3 shininess {shin} transparency {transp} }} }}\n"
            f"geometry IndexedFaceSet {{ solid FALSE coord Coordinate {{ point [ {pts} ] }}\n"
            f"coordIndex [ {idx} ] }} }}\n")


def box(x1, y1, z1, x2, y2, z2, color, **kw):
    p = [(x1, y1, z1), (x2, y1, z1), (x2, y2, z1), (x1, y2, z1),
         (x1, y1, z2), (x2, y1, z2), (x2, y2, z2), (x1, y2, z2)]
    f = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return _shape(p, f, color, **kw)


def cylinder(cx, cy, r, z1, z2, color, n=48, **kw):
    p = []
    for i in range(n):
        a = 2 * math.pi * i / n
        p.append((cx + r * math.cos(a), cy + r * math.sin(a), z1))
    for i in range(n):
        a = 2 * math.pi * i / n
        p.append((cx + r * math.cos(a), cy + r * math.sin(a), z2))
    f = [tuple(range(n - 1, -1, -1)), tuple(range(n, 2 * n))]
    for i in range(n):
        j = (i + 1) % n
        f.append((i, j, n + j, n + i))
    return _shape(p, f, color, **kw)


def write(name, *shapes):
    os.makedirs(DIR, exist_ok=True)
    with open(os.path.join(DIR, name + ".wrl"), "w") as fh:
        fh.write("#VRML V2.0 utf8\n" + "".join(shapes))


def chip(name, L, W, H, body, end=C_METAL, end_len=None):
    e = end_len if end_len else L * 0.22
    write(name,
          box(-L / 2, -W / 2, 0, -L / 2 + e, W / 2, H, end),
          box(L / 2 - e, -W / 2, 0, L / 2, W / 2, H, end),
          box(-L / 2 + e, -W / 2, 0, L / 2 - e, W / 2, H, body))


def build_all():
    # LED 0603: white package, lens colour on top
    write("LED_0603",
          box(-0.8, -0.4, 0, -0.55, 0.4, 0.5, C_METAL),
          box(0.55, -0.4, 0, 0.8, 0.4, 0.5, C_METAL),
          box(-0.55, -0.4, 0, 0.55, 0.4, 0.3, (0.85, 0.88, 0.8)),
          box(-0.5, -0.36, 0.3, 0.5, 0.36, 0.55, C_LED, transp=0.15))
    chip("R_0402", 1.0, 0.5, 0.35, C_BLACK)
    chip("C_0402", 1.0, 0.5, 0.5, C_TAN)
    chip("C_0805", 2.0, 1.25, 1.0, C_TAN)
    # TSSOP-20 4.4 x 6.5 body, pins along x edges
    legs = []
    for i in range(10):
        y = -2.925 + 0.65 * i
        legs.append(box(-3.2, y - 0.12, 0, -2.2, y + 0.12, 0.25, C_METAL))
        legs.append(box(2.2, y - 0.12, 0, 3.2, y + 0.12, 0.25, C_METAL))
    write("TSSOP20", box(-2.2, -3.25, 0.05, 2.2, 3.25, 1.0, C_BLACK), *legs,
          cylinder(-1.5, -2.5, 0.3, 1.0, 1.01, (0.3, 0.3, 0.3)))
    sot = [box(-0.15, 1.0, 0, 0.15, 1.3, 0.3, C_METAL),
           box(-1.1, -1.3, 0, -0.8, -1.0, 0.3, C_METAL),
           box(0.8, -1.3, 0, 1.1, -1.0, 0.3, C_METAL)]
    write("SOT23", box(-1.45, -0.65, 0.05, 1.45, 0.65, 1.0, C_BLACK), *sot)
    write("PTS810",
          box(-2.1, -1.6, 0, 2.1, 1.6, 1.0, C_METAL, shin=0.8),
          cylinder(0, 0, 0.9, 1.0, 1.5, C_BLACK),
          box(-2.6, -1.3, 0, -2.1, -0.85, 0.2, C_METAL), box(2.1, -1.3, 0, 2.6, -0.85, 0.2, C_METAL),
          box(-2.6, 0.85, 0, -2.1, 1.3, 0.2, C_METAL), box(2.1, 0.85, 0, 2.6, 1.3, 0.2, C_METAL))
    # CR2032 lying on the back of the card (footprint is on the top side, z<0 = below)
    # cell lying on the card back: z = 0 is the card front surface, the card back is
    # at -1.6; (-) cap against the card, (+) face 3.2 mm further back
    write("CR2032_FORK",
          cylinder(0, 0, 10.0, -4.8, -1.85, C_BAT, n=72, shin=0.9),
          cylinder(0, 0, 8.2, -1.85, -1.6, (0.6, 0.6, 0.62), n=72, shin=0.9))

if __name__ == "__main__":
    build_all()
    print("models in", DIR)
