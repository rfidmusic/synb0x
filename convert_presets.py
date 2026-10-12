#!/usr/bin/env python3
"""Convert Blackbox presets saved before Synb0x (stock 3.1.9, blackbox-mod 3.1.n) so they sound the same on Synb0x.

    python3 convert_presets.py PRESET_FOLDER [PRESET_FOLDER ...]
    python3 convert_presets.py SDCARD/Presets            (every preset folder inside it)

Each preset is copied to a new folder next to it, "<name> syn", with the converted preset.xml; the original folder is
never changed. Presets already saved on Synb0x (3.1.s, 3.1.t or 3.1.9-syn) are skipped: Synb0x saves its settings
("fenvtype", "fenvmorph", ...) on every pad, so a pad without them was saved before Synb0x.

Stock's Filter knob (dualfilcutoff, -1000..1000) is off at centre, low-pass left of it (cutoff = curve(knob + 1)) and
high-pass right of it (cutoff = curve(knob)); Synb0x's is cutoff across its whole travel (curve((knob + 1) / 2)) on the
same curve, with low-pass / high-pass chosen by Morph (3.1.t) or Type (3.1.s). Per pad:
  low-pass  knob k < 0  ->  Filter 2k + 1000, Type LP, Morph 0       (same cutoff)
  high-pass knob k > 0  ->  Filter 2k - 1000, Type HP, Morph 100 %   (same cutoff)
  off       knob 0      ->  Filter 1000 (fully open: the filter switches off), Type LP
  modulation routes to Filter: amount doubled (same sweep), capped at +-1000.
The new envelope and glide settings get Synb0x's defaults (envelope Depth 0, Glide Off). Not converted: the filter's
slope (stock 12 dB/oct, Synb0x 24 dB/oct) and a route that swept the stock knob across centre (LP <-> HP); see the
notes printed per pad.
"""
import os
import re
import shutil
import sys

SUFFIX = " syn"
DEFAULTS = 'fenvattack="0" fenvdecay="300" fenvsus="0" fenvrel="300" fenvdepth="0" glidemode="0" glidetime="200"'
CELL = re.compile(rb"(<cell\b[^>]*>)(.*?)(</cell>)", re.S)
PARAMS = re.compile(rb"<params\b[^>]*/>", re.S)
CUTOFF = re.compile(rb'\bdualfilcutoff="(-?\d+)"')
ROUTE = re.compile(rb'<modsource\b[^>]*\bdest="dualfilcutoff"[^>]*/>')
AMOUNT = re.compile(rb'\bamount="(-?\d+)"')
WHERE = re.compile(rb'row="(\d+)" column="(\d+)"(?: layer="(\d+)")?')


def convert_cell(head, body, notes):
    """One cell: returns the new body (or the same one) and whether it changed."""
    m = PARAMS.search(body)
    if not m or b"fenvtype=" in m.group() or not CUTOFF.search(m.group()):
        return body, False
    params = m.group()
    k = int(CUTOFF.search(params).group(1))
    k = max(-1000, min(1000, k))
    if k < 0:
        new, ftype, morph = 2 * k + 1000, 0, 0
    elif k > 0:
        new, ftype, morph = 2 * k - 1000, 1, 1000
    else:
        new, ftype, morph = 1000, 0, 0
    params = CUTOFF.sub(f'dualfilcutoff="{new}" fenvtype="{ftype}" fenvmorph="{morph}" {DEFAULTS}'.encode(), params,
                        count=1)
    w = WHERE.search(head)
    pad = f"row {int(w.group(1)) + 1}, column {int(w.group(2)) + 1}" if w else "a pad"
    kind = "low-pass" if k < 0 else "high-pass" if k > 0 else "off"
    routes = 0

    def route(r):
        nonlocal routes
        a = AMOUNT.search(r.group())
        if not a:
            return r.group()
        routes += 1
        old = int(a.group(1))
        amt = max(-1000, min(1000, 2 * old))
        if amt != 2 * old:
            notes.append(f"  {pad}: a modulation route to Filter ({old / 10:g} %) is capped at {amt / 10:g} % "
                         f"(it would need {2 * old / 10:g} %)")
        return AMOUNT.sub(f'amount="{amt}"'.encode(), r.group(), count=1)

    body = body[:m.start()] + params + body[m.end():]
    body = ROUTE.sub(route, body)
    if k == 0 and routes:
        notes.append(f"  {pad}: Filter was off (centre) with modulation on it; in stock that opened a low-pass one way "
                     "and a high-pass the other. Converted: fully open, so only the closing (low-pass) half remains")
    if k != 0:
        notes.append(f"  {pad}: {kind}, Filter {k / 10:g} (stock, -100..100) -> {(new + 1000) / 20:g} % (Synb0x)"
                     + (", Morph 100 % / Type HP" if k > 0 else "")
                     + (f", {routes} route(s) to Filter doubled" if routes else ""))
    return body, True


def convert(folder):
    folder = os.path.normpath(folder)
    xml = os.path.join(folder, "preset.xml")
    name = os.path.basename(folder)
    if not os.path.isfile(xml):
        return None
    if name.endswith(SUFFIX):
        print(f"{name}: skipped (already a converted copy)")
        return False
    data = open(xml, "rb").read()
    notes, changed = [], 0

    def cell(m):
        nonlocal changed
        body, did = convert_cell(m.group(1), m.group(2), notes)
        changed += did
        return m.group(1) + body + m.group(3)

    out = CELL.sub(cell, data)
    if not changed:
        print(f"{name}: skipped (saved on Synb0x already, or no pads)")
        return False
    dest = folder + SUFFIX
    if os.path.exists(dest):
        print(f"{name}: skipped ({os.path.basename(dest)} already exists; delete or rename it to convert again)")
        return False
    shutil.copytree(folder, dest)
    with open(os.path.join(dest, "preset.xml"), "wb") as f:
        f.write(out)
    print(f"{name} -> {os.path.basename(dest)}: {changed} pad(s) converted")
    for n in notes:
        print(n)
    return True


def main(args):
    if not args:
        print(__doc__.split("\n\n")[1])
        return 2
    done = 0
    for a in args:
        if not os.path.isdir(a):
            print(f"{a}: not a folder")
            continue
        r = convert(a)
        if r is None:                                   # a Presets folder: every preset in it
            for sub in sorted(os.listdir(a)):
                p = os.path.join(a, sub)
                if os.path.isdir(p) and not sub.endswith(SUFFIX) and convert(p):
                    done += 1
        elif r:
            done += 1
    print(f"\n{done} preset(s) converted. Copy the \"...{SUFFIX}\" folders to the card's Presets folder; the originals "
          "are unchanged.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
