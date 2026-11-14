#!/usr/bin/env python3
"""Generate card.kicad_sch from hardware/card/netlist.json (written by card.py).

Connections are made with global labels at every pin, so the schematic is a
faithful, readable mirror of the PCB netlist. Symbol UUIDs match the footprint
paths on the PCB.
"""
import json
import os
import re
import uuid

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CARD = os.path.join(ROOT, "hardware", "card")
SYMDIR = "/usr/share/kicad/symbols"
SHEET_UUID = str(uuid.uuid5(uuid.NAMESPACE_URL, "pcb-wizytowka/card/sheet"))
PROJECT = "card"

LIBSYM = {"D": "Device:LED", "R": "Device:R", "RN": "Device:R_Pack04", "C": "Device:C", "U": "MCU_WCH_CH32V0:CH32V003FxPx",
          "Q": "Transistor_FET:AO3401A", "SW": "Switch:SW_Push", "TP": "Connector:TestPoint",
          "BT": "Device:Battery_Cell"}
DESC = {"D": "LED 0603 yellow-green (~570 nm)", "R": "", "RN": "4x33R array 0402", "C": "", "U": "", "Q": "", "SW": "",
        "TP": "pogo pad", "BT": "CR2032 in PCB-stack holder"}

_uid_n = [0]


def uid(tag=None):
    if tag:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, "pcb-wizytowka/card/sch/" + tag))
    _uid_n[0] += 1
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"pcb-wizytowka/card/sch/auto{_uid_n[0]}"))


# ----------------------------------------------------------- library access
_libcache = {}


def _block(text, start):
    d = 0
    for j in range(start, len(text)):
        c = text[j]
        if c == "(":
            d += 1
        elif c == ")":
            d -= 1
            if d == 0:
                return text[start:j + 1]
    raise ValueError("unbalanced")


def lib_symbol(lib_id):
    """Flattened symbol definition named 'Lib:Name' for lib_symbols."""
    lib, name = lib_id.split(":")
    path = os.path.join(SYMDIR, lib + ".kicad_sym")
    if path not in _libcache:
        _libcache[path] = open(path).read()
    t = _libcache[path]
    blk = _block(t, t.index(f'\t(symbol "{name}"\n'))
    m = re.search(r'\(extends "([^"]+)"\)', blk)
    if m:
        base = m.group(1)
        bblk = _block(t, t.index(f'\t(symbol "{base}"\n'))
        # properties from the derived symbol, body (sub-symbols, flags) from the base
        props = re.findall(r'\n\t\t\(property .*?\n\t\t\)', blk, re.S)
        body = bblk
        body = re.sub(r'\n\t\t\(property .*?\n\t\t\)', '', body, flags=re.S)
        body = body.replace(f'(symbol "{base}_', f'(symbol "{name}_')
        head = f'\t(symbol "{name}"'
        body = head + "".join(props) + body[len(f'\t(symbol "{base}"'):]
        blk = body
    blk = blk.replace(f'(symbol "{name}"', f'(symbol "{lib_id}"', 1)
    return blk


def pins_of(lib_id):
    blk = lib_symbol(lib_id)
    out = {}
    for m in re.finditer(r'\(pin \w+ \w+\s+\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\).*?\(number "([^"]*)"',
                         blk, re.S):
        x, y, a, num = float(m.group(1)), float(m.group(2)), int(float(m.group(3))), m.group(4)
        out.setdefault(num, (x, y, a))
    return out


# ------------------------------------------------------------- s-expr bits
def q(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'


def prop(name, value, x, y, hide=False, justify=None, angle=0):
    j = f" (justify {justify})" if justify else ""
    h = " (hide yes)" if hide else ""
    return (f'\t\t(property {q(name)} {q(value)}\n\t\t\t(at {x:.2f} {y:.2f} {angle})\n'
            f'\t\t\t(effects (font (size 1.27 1.27)){j}{h})\n\t\t)\n')


def symbol_inst(lib_id, ref, value, footprint, x, y, sym_uuid, pin_nums, ref_off=(0, -3.0),
                val_off=(0, 3.0), desc="", hide_value=False):
    in_bom = "no" if ref.startswith("TP") else "yes"
    s = (f'\t(symbol\n\t\t(lib_id {q(lib_id)})\n\t\t(at {x:.2f} {y:.2f} 0)\n\t\t(unit 1)\n'
         f'\t\t(exclude_from_sim no)\n\t\t(in_bom {in_bom})\n\t\t(on_board yes)\n\t\t(dnp no)\n'
         f'\t\t(uuid {q(sym_uuid)})\n')
    s += prop("Reference", ref, x + ref_off[0], y + ref_off[1])
    s += prop("Value", value, x + val_off[0], y + val_off[1], hide=hide_value)
    s += prop("Footprint", footprint, x, y, hide=True)
    s += prop("Datasheet", "~", x, y, hide=True)
    s += prop("Description", desc, x, y, hide=True)
    for n in pin_nums:
        s += f'\t\t(pin {q(n)}\n\t\t\t(uuid {q(uid(ref + "/pin/" + n))})\n\t\t)\n'
    s += (f'\t\t(instances\n\t\t\t(project {q(PROJECT)}\n\t\t\t\t(path {q("/" + SHEET_UUID)}\n'
          f'\t\t\t\t\t(reference {q(ref)})\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n')
    return s


LABEL_ANGLE = {0: 180, 180: 0, 90: 270, 270: 90}   # pin angle -> label angle
LABEL_JUST = {0: "left", 180: "right", 90: "left", 270: "right"}


def global_label(net, x, y, angle):
    return (f'\t(global_label {q(net)}\n\t\t(shape bidirectional)\n\t\t(at {x:.2f} {y:.2f} {angle})\n'
            f'\t\t(fields_autoplaced yes)\n\t\t(effects (font (size 1.27 1.27)) (justify {LABEL_JUST[angle]}))\n'
            f'\t\t(uuid {q(uid())})\n'
            f'\t\t(property "Intersheetrefs" "${{INTERSHEET_REFS}}"\n\t\t\t(at {x:.2f} {y:.2f} 0)\n'
            f'\t\t\t(effects (font (size 1.27 1.27)) (hide yes))\n\t\t)\n\t)\n')


def no_connect(x, y):
    return f'\t(no_connect\n\t\t(at {x:.2f} {y:.2f})\n\t\t(uuid {q(uid())})\n\t)\n'


def text(s, x, y, size=1.8, bold=False):
    b = " (bold yes)" if bold else ""
    return (f'\t(text {q(s)}\n\t\t(exclude_from_sim no)\n\t\t(at {x:.2f} {y:.2f} 0)\n'
            f'\t\t(effects (font (size {size} {size}){b}) (justify left top))\n\t\t(uuid {q(uid())})\n\t)\n')


def snap(v):
    return round(v / 1.27) * 1.27


# ------------------------------------------------------------------ layout
def build():
    nl = json.load(open(os.path.join(CARD, "netlist.json")))
    used_libs = []
    items = []

    def prefix(ref):
        return re.match(r"[A-Z]+", ref).group(0)

    def place(ref, x, y, **kw):
        x, y = snap(x), snap(y)
        comp = nl[ref]
        lib_id = LIBSYM[prefix(ref)]
        if lib_id not in used_libs:
            used_libs.append(lib_id)
        pins = pins_of(lib_id)
        items.append(symbol_inst(lib_id, ref, comp["value"], comp["footprint"], x, y, comp["uuid"],
                                 sorted(pins), desc=DESC[prefix(ref)], **kw))
        for num, (px, py, pa) in pins.items():
            net = comp["pins"].get(num, "")
            cx, cy = x + px, y - py
            if net and not net.startswith("unconnected-"):
                items.append(global_label(net, cx, cy, LABEL_ANGLE[pa]))
            else:
                items.append(no_connect(cx, cy))

    # LED matrix (16 x 8, same arrangement as on the PCB)
    leds = json.load(open(os.path.join(CARD, "led_map.json")))
    x0, y0, dx, dy = 22.86, 38.1, 24.13, 10.16
    for d in leds:
        place(d["ref"], x0 + d["col"] * dx, y0 + d["row"] * dy, ref_off=(0, -2.6), val_off=(0, 2.6),
              hide_value=True)
    items.append(text("Matryca LED 16×8 (charlieplexing, 12 linii L0..L11). Układ jak na PCB: "
                      "kolumna x / wiersz y. Każda dioda obrócona o 45° na płytce.",
                      x0 - 6, y0 - 12, 2.0, bold=True))

    # series resistors
    rx0, ry = 40.64, 152.4
    for j in range(3):
        place(f"RN{j + 1}", rx0 + j * 38.1, ry, ref_off=(9.0, -1.0), val_off=(9.0, 1.5))
    items.append(text("Rezystory szeregowe linii 33 Ω (3 drabinki 4×0402):\n"
                      "L* = matryca, L*_MCU = pin MCU", rx0 - 10, ry - 22, 1.8))

    # MCU
    place("U1", 215.9, 160.0, ref_off=(3.0, -20.0), val_off=(3.0, 20.0))
    items.append(text("CH32V003F4P6: PC1..PC7, PD2..PD6 = linie charlieplex;\n"
                      "PA1/PA2 = przyciski (wewn. pull-up); PD1 = SWIO", 185, 128, 1.8))
    # decoupling
    place("C1", 254.0, 160.0, ref_off=(2.5, -1.0), val_off=(2.5, 1.5))
    place("C2", 266.7, 160.0, ref_off=(2.5, -1.0), val_off=(2.5, 1.5))
    # power: battery + reverse protection
    place("BT1", 292.1, 160.0, ref_off=(3.0, -4.0), val_off=(3.0, 5.0))
    place("Q1", 317.5, 160.0, ref_off=(5.0, -2.5), val_off=(5.0, 2.5))
    items.append(text("Zasilanie: CR2032 → Q1 (P-MOSFET, ochrona przed odwrotną baterią:\n"
                      "D=+BATT, S=VDD, G=GND)", 285, 136, 1.8))
    # buttons
    place("SW1", 350.0, 155.0, ref_off=(0, -4.0), val_off=(0, 4.0))
    place("SW2", 350.0, 170.0, ref_off=(0, -4.0), val_off=(0, 4.0))
    # pogo pads
    for i, refd in enumerate(("TP1", "TP2", "TP3")):
        place(refd, 375.0 + i * 12.7, 160.0, ref_off=(0, -6.0), val_off=(0, -8.0), hide_value=True)
    items.append(text("Pady pogo (spód):\n3V3 / SWIO / GND — WCH-LinkE", 368, 140, 1.8))

    # PWR_FLAGs so ERC knows the power nets are driven
    pf = lib_symbol("power:PWR_FLAG")
    used_libs.append("power:PWR_FLAG")
    for i, net in enumerate(("+BATT", "GND", "VDD")):
        x, y = snap(300.0 + i * 15.24), snap(200.0)
        fid = uid("pwrflag/" + net)
        items.append(
            f'\t(symbol\n\t\t(lib_id "power:PWR_FLAG")\n\t\t(at {x:.2f} {y:.2f} 0)\n\t\t(unit 1)\n'
            f'\t\t(exclude_from_sim no)\n\t\t(in_bom yes)\n\t\t(on_board yes)\n\t\t(dnp no)\n'
            f'\t\t(uuid {q(fid)})\n' + prop("Reference", f"#FLG0{i + 1}", x, y - 3.0, hide=True)
            + prop("Value", "PWR_FLAG", x, y - 4.5) + prop("Footprint", "", x, y, hide=True)
            + prop("Datasheet", "~", x, y, hide=True) + prop("Description", "", x, y, hide=True)
            + f'\t\t(pin "1"\n\t\t\t(uuid {q(uid("pwrflag/pin/" + net))})\n\t\t)\n'
            + f'\t\t(instances\n\t\t\t(project {q(PROJECT)}\n\t\t\t\t(path {q("/" + SHEET_UUID)}\n'
              f'\t\t\t\t\t(reference "#FLG0{i + 1}")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n')
        items.append(global_label(net, x, y, 270))

    libs = "".join(lib_symbol(l).replace("\n\t", "\n\t\t").replace("\t(symbol", "\t\t(symbol", 1) + "\n"
                   for l in used_libs)
    out = ("(kicad_sch\n\t(version 20250114)\n\t(generator \"eeschema\")\n\t(generator_version \"9.0\")\n"
           f"\t(uuid {q(SHEET_UUID)})\n\t(paper \"A2\")\n"
           "\t(title_block\n\t\t(title \"PCB wizytówka — CH32V003 + 128× LED 0201\")\n"
           "\t\t(date \"2026-11-13\")\n\t\t(rev \"1.0\")\n"
           "\t\t(comment 1 \"Wygenerowano skryptem gen/schematic.py z netlisty PCB (gen/card.py)\")\n\t)\n"
           f"\t(lib_symbols\n{libs}\t)\n" + "".join(items) +
           "\t(sheet_instances\n\t\t(path \"/\"\n\t\t\t(page \"1\")\n\t\t)\n\t)\n"
           "\t(embedded_fonts no)\n)\n")
    path = os.path.join(CARD, "card.kicad_sch")
    with open(path, "w") as fh:
        fh.write(out)
    print("saved", path)


if __name__ == "__main__":
    build()
