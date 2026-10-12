#!/usr/bin/env python3
"""Convert Blackbox presets saved before Synb0x (stock 3.1.9, blackbox-mod 3.1.n) so they sound the same on Synb0x.

    python3 convert_presets.py PATH [PATH ...]               copies: "<name> syn" next to each preset
    python3 convert_presets.py --in-place PATH [PATH ...]    rewrite each preset.xml where it is

PATH is a preset folder, a preset.xml, or any folder above them (a Presets folder, the whole SD card): every
preset.xml below it is found. By default each older preset is copied to a new folder next to it, "<name> syn", with
the converted preset.xml, and the original is never changed. With --in-place each older preset.xml is rewritten where
it is and the original kept beside it as preset.xml.bak (to undo: delete preset.xml, rename preset.xml.bak back).
Presets already saved on Synb0x (3.1.s, 3.1.t or 3.1.9-syn), or converted before, are skipped: Synb0x saves its
settings ("fenvtype", "fenvmorph", ...) on every pad, so a pad without them was saved before Synb0x.

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


def inspect(folder, dest_root=None, in_place=False):
    """Read one preset folder without writing anything. Returns None if it holds no preset.xml, else a dict:
    status "convert" (out = the new preset.xml, dest = where it goes, pads, notes), "synb0x" (saved on Synb0x
    already), "copy" (a converted copy itself) or "exists" (its copy is already there). in_place: dest is the folder
    itself."""
    folder = os.path.normpath(folder)
    xml = os.path.join(folder, "preset.xml")
    if not os.path.isfile(xml):
        return None
    name = os.path.basename(folder)
    dest = folder if in_place else os.path.join(dest_root or os.path.dirname(folder), name + SUFFIX)
    info = {"folder": folder, "name": name, "dest": dest, "pads": 0, "notes": [], "out": None, "in_place": in_place}
    if name.endswith(SUFFIX) and not in_place:
        return dict(info, status="copy")
    data = open(xml, "rb").read()

    def cell(m):
        body, did = convert_cell(m.group(1), m.group(2), info["notes"])
        info["pads"] += did
        return m.group(1) + body + m.group(3)

    out = CELL.sub(cell, data)
    if not info["pads"]:
        return dict(info, status="synb0x", notes=[])
    if not in_place and os.path.exists(dest):
        return dict(info, status="exists")
    return dict(info, status="convert", out=out)


def backup_name(folder):
    """preset.xml.bak, or .bak2, .bak3 ... if an earlier backup is there (never overwrite one)."""
    b, n = os.path.join(folder, "preset.xml.bak"), 1
    while os.path.exists(b):
        n += 1
        b = os.path.join(folder, f"preset.xml.bak{n}")
    return b


def write(info):
    """Write an inspect() result with status "convert": the copy, or (in place) the new preset.xml with the original
    kept as preset.xml.bak. Returns the backup's path in place, else None."""
    if not info["in_place"]:
        shutil.copytree(info["folder"], info["dest"])
        with open(os.path.join(info["dest"], "preset.xml"), "wb") as f:
            f.write(info["out"])
        return None
    xml = os.path.join(info["folder"], "preset.xml")
    if b"fenvtype=" in open(xml, "rb").read():       # changed since it was inspected: leave it
        raise RuntimeError("preset.xml was already converted")
    bak, tmp = backup_name(info["folder"]), xml + ".new"
    shutil.copy2(xml, bak)
    with open(tmp, "wb") as f:
        f.write(info["out"])
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, xml)                              # the original is in the backup before it is replaced
    return bak


def presets_in(path):
    """The preset folders a path names: a preset.xml's folder, the folder itself, or every folder below it that holds
    a preset.xml (a Presets folder, a whole SD card). Hidden and system folders are skipped."""
    path = os.path.normpath(path)
    if os.path.isfile(path):
        return [os.path.dirname(os.path.abspath(path))] if os.path.basename(path).lower() == "preset.xml" else []
    found = []
    for root, dirs, files in os.walk(path):
        dirs[:] = sorted(d for d in dirs if not d.startswith((".", "$")) and d != "System Volume Information")
        if "preset.xml" in files:
            found.append(root)
    return found


def describe(info):
    """One line for an inspect() result."""
    return {"convert": f"{info['pads']} pad(s) to convert",
            "synb0x": "skipped (saved on Synb0x already)",
            "copy": "skipped (already a converted copy)",
            "exists": f"skipped ({os.path.basename(info['dest'])} already exists; delete or rename it to convert "
                      "again)"}[info["status"]]


def convert(folder, in_place=False):
    info = inspect(folder, in_place=in_place)
    if info is None:
        return None
    if info["status"] != "convert":
        print(f"{info['name']}: {describe(info)}")
        return False
    bak = write(info)
    if bak:
        print(f"{info['name']}: {info['pads']} pad(s) converted in place (original kept as {os.path.basename(bak)})")
    else:
        print(f"{info['name']} -> {os.path.basename(info['dest'])}: {info['pads']} pad(s) converted")
    for n in info["notes"]:
        print(n)
    return True


def main(args):
    in_place = "--in-place" in args
    args = [a for a in args if a != "--in-place"]
    if not args:
        print(__doc__.split("\n\n")[1])
        return 2
    done, seen = 0, set()
    for a in args:
        if not os.path.exists(a):
            print(f"{a}: not found")
            continue
        found = presets_in(a)
        if not found:
            print(f"{a}: no preset.xml found")
        for f in found:
            if f in seen:
                continue
            seen.add(f)
            if convert(f, in_place):
                done += 1
    if in_place:
        print(f"\n{done} preset(s) converted in place; each original is kept as preset.xml.bak beside it.")
    else:
        print(f"\n{done} preset(s) converted. Copy the \"...{SUFFIX}\" folders to the card's Presets folder; the "
              "originals are unchanged.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
