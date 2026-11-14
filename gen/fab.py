#!/usr/bin/env python3
"""Fabrication outputs: gerbers + drill (zip), BOM, CPL (top/bottom), assembly PDFs,
schematic PDF, LED map, renders (incl. isometric)."""
import collections
import csv
import json
import os
import re
import shutil
import subprocess
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CARD = os.path.join(ROOT, "hardware", "card")
FAB = os.path.join(ROOT, "fab", "card")
IMG = os.path.join(ROOT, "docs", "img")
BOARD = os.path.join(CARD, "card.kicad_pcb")
LAYERS = "F.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts"

NOTES = {
    "LED 0603 yellow-green": "LED 0603 (1608 metric), yellow-green 565-575 nm AlGaInP, Vf ~2.0 V "
                             "(pure green InGaN, Vf ~2.8 V, is too dim on CR2032)",
    "4x33R array 0402 (convex)": "4 x 33 ohm resistor array, 4x0402 convex (e.g. Yageo YC164 / "
                                 "Bourns CAY16)",
    "CH32V003F4P6": "WCH RISC-V MCU, TSSOP-20",
    "AO3401A P-MOSFET": "reverse-battery protection; any SOT-23 P-MOSFET, Vgs(th) < 1.3 V",
    "Tactile 4.2x3.2 SMD": "SMD tact switch 4.2 x 3.2 mm, e.g. C&K PTS810 / XKB TS-1187A",
    "CR2032 (card fork holder)": "CR2032 cell - no holder part, held by the one-tongue fork cut in the card",
}


def run(*args):
    r = subprocess.run(["kicad-cli", *args], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        raise SystemExit("kicad-cli failed: " + " ".join(args))


def gerbers():
    tmp = os.path.join(FAB, "gerber")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    run("pcb", "export", "gerbers", "--layers", LAYERS, "--subtract-soldermask", "-o", tmp + "/", BOARD)
    run("pcb", "export", "drill", "--format", "excellon", "--excellon-separate-th",
        "--generate-map", "--map-format", "gerberx2", "-o", tmp + "/", BOARD)
    zp = os.path.join(FAB, "card-gerbers.zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(tmp)):
            z.write(os.path.join(tmp, f), f)
    return zp


def keyref(r):
    m = re.match(r"([A-Z]+)(\d+)", r)
    return (m.group(1), int(m.group(2)))


def bom():
    parts = json.load(open(os.path.join(CARD, "parts.json")))
    groups = collections.OrderedDict()
    for ref, val, fp, x, y, rot, side in parts:
        groups.setdefault((val, fp, side), []).append(ref)
    path = os.path.join(FAB, "card-bom.csv")
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Qty", "References", "Value / part", "Footprint", "Side", "Notes"])
        for (val, fp, side), refs in groups.items():
            refs = sorted(refs, key=keyref)
            rs = f"{refs[0]}-{refs[-1]}" if len(refs) > 6 else ",".join(refs)
            w.writerow([len(refs), rs, val, fp, side, NOTES.get(val, "")])
    return path


def led_map():
    leds = json.load(open(os.path.join(CARD, "led_map.json")))
    pins = json.load(open(os.path.join(CARD, "pins.json")))
    path = os.path.join(FAB, "led-map.csv")
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ref", "col", "row", "anode_line", "cathode_line", "anode_mcu_pin", "cathode_mcu_pin"])
        for d in leds:
            w.writerow([d["ref"], d["col"], d["row"], d["anode"], d["cathode"],
                        pins[d["anode"]], pins[d["cathode"]]])
    return path


def renders():
    os.makedirs(IMG, exist_ok=True)
    for f in os.listdir(IMG):
        os.remove(os.path.join(IMG, f))
    common = ["--quality", "high"]
    run("pcb", "render", "--side", "top", *common, "-w", "1600", "-h", "1020", "--zoom", "1.25",
        "-o", os.path.join(IMG, "card-front.png"), BOARD)
    run("pcb", "render", "--side", "bottom", *common, "-w", "1600", "-h", "1020", "--zoom", "1.25",
        "-o", os.path.join(IMG, "card-back.png"), BOARD)
    run("pcb", "render", "--side", "top", *common, "-w", "1800", "-h", "1200",
        "--rotate", "'-55,0,-35'", "-o", os.path.join(IMG, "card-iso-front.png"), BOARD)
    run("pcb", "render", "--side", "bottom", *common, "-w", "1800", "-h", "1200",
        "--rotate", "'55,0,-35'", "-o", os.path.join(IMG, "card-iso-back.png"), BOARD)


def main():
    os.makedirs(FAB, exist_ok=True)
    print(gerbers())
    run("pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "both",
        "-o", os.path.join(FAB, "card-cpl.csv"), BOARD)
    run("pcb", "export", "pdf", "--layers", "F.Fab,Edge.Cuts,F.Paste", "--mode-single",
        "--include-border-title", "-o", os.path.join(FAB, "card-assembly-top.pdf"), BOARD)
    run("pcb", "export", "pdf", "--layers", "B.Fab,B.Paste,Edge.Cuts", "--mode-single", "--mirror",
        "--include-border-title", "-o", os.path.join(FAB, "card-assembly-bottom.pdf"), BOARD)
    run("sch", "export", "pdf", "-o", os.path.join(FAB, "card-schematic.pdf"),
        os.path.join(CARD, "card.kicad_sch"))
    print(bom())
    print(led_map())
    renders()
    print("renders ->", IMG)


if __name__ == "__main__":
    main()
