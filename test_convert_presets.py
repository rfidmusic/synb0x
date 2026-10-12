"""convert_presets.py on made-up presets (no firmware, no Unicorn): copy mode, in place, skipping, the numbers."""
import os
import re
import shutil
import sys
import tempfile

import convert_presets as cp

fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


def cell(row, k, routes=()):
    r = "".join(f'            <modsource dest="{d}" src="lfo1" slot="0" amount="{a}"/>\n' for d, a in routes)
    return (f'        <cell row="{row}" column="0" layer="0" filename=".\\x.wav" type="sample">\n'
            f'            <params gaindb="0" chokegrp="0" dualfilcutoff="{k}" res="500" rootnote="0"/>\n{r}'
            '            <slices/>\n        </cell>\n')


def preset(folder, cells):
    os.makedirs(folder)
    with open(os.path.join(folder, "preset.xml"), "w", encoding="utf-8", newline="\n") as f:
        f.write('﻿<?xml version="1.0" encoding="UTF-8"?>\n<document>\n    <session version="2">\n' + "".join(cells)
                + '    </session>\n</document>\n')
    open(os.path.join(folder, "x.wav"), "wb").write(b"RIFF")


def params(folder):
    s = open(os.path.join(folder, "preset.xml"), encoding="utf-8-sig").read()
    return re.findall(r'dualfilcutoff="(-?\d+)" fenvtype="(\d)" fenvmorph="(\d+)"', s), \
        re.findall(r'dest="dualfilcutoff" src="lfo1" slot="0" amount="(-?\d+)"', s)


root = tempfile.mkdtemp()
try:
    card = os.path.join(root, "card", "Presets")
    old = os.path.join(card, "Old")
    preset(old, [cell(0, -1000), cell(1, -500, [("dualfilcutoff", 300)]), cell(2, 0), cell(3, 600, [("dualfilcutoff", 800)]),
                 cell(4, -20)])
    os.makedirs(os.path.join(root, "card", ".Trashes"))
    shutil.copytree(old, os.path.join(root, "card", ".Trashes", "Old"))
    new = os.path.join(card, "deep", "New")
    preset(new, [cell(0, -337).replace('dualfilcutoff="-337"', 'dualfilcutoff="-337" fenvtype="0" fenvmorph="52"')])
    original = open(os.path.join(old, "preset.xml"), "rb").read()

    found = cp.presets_in(os.path.join(root, "card"))
    check("a card is searched all the way down, hidden folders skipped", found == [old, new], found)
    check("a preset.xml names its folder", cp.presets_in(os.path.join(old, "preset.xml")) == [old])

    info = cp.inspect(old)
    check("an older preset: all its pads to convert", info["status"] == "convert" and info["pads"] == 5, info["status"])
    check("a Synb0x preset is skipped", cp.inspect(new)["status"] == "synb0x")

    cp.write(info)
    copy = old + cp.SUFFIX
    got, routes = params(copy)
    check("copy: LP -100 -> 0 %, LP -50 -> 50 %, off -> open, HP +60 -> 60 % with Type HP and Morph 100 %, LP -2 -> 98 %",
          got == [("-1000", "0", "0"), ("0", "0", "0"), ("1000", "0", "0"), ("200", "1", "1000"), ("960", "0", "0")], got)
    check("routes to Filter doubled, capped at 1000", routes == ["600", "1000"], routes)
    check("copy: samples copied, original untouched", os.path.exists(os.path.join(copy, "x.wav"))
          and open(os.path.join(old, "preset.xml"), "rb").read() == original)
    check("the copy itself is not converted again", cp.inspect(copy)["status"] == "copy")
    check("a second copy is refused while the first exists", cp.inspect(old)["status"] == "exists")

    info = cp.inspect(old, in_place=True)
    bak = cp.write(info)
    check("in place: original kept as preset.xml.bak", os.path.basename(bak) == "preset.xml.bak"
          and open(bak, "rb").read() == original)
    check("in place: same result as the copy", open(os.path.join(old, "preset.xml"), "rb").read()
          == open(os.path.join(copy, "preset.xml"), "rb").read())
    check("in place: BOM and line endings kept", open(os.path.join(old, "preset.xml"), "rb").read().startswith(b"\xef\xbb\xbf")
          and b"\r\n" not in open(os.path.join(old, "preset.xml"), "rb").read())
    check("in place, run again: skipped", cp.inspect(old, in_place=True)["status"] == "synb0x")
    shutil.copy(bak, os.path.join(old, "preset.xml"))
    bak2 = cp.write(cp.inspect(old, in_place=True))
    check("an existing backup is never overwritten (.bak2)", os.path.basename(bak2) == "preset.xml.bak2"
          and open(bak, "rb").read() == original)
    check("hidden folders on the card untouched", open(os.path.join(root, "card", ".Trashes", "Old", "preset.xml"), "rb").read()
          == original)
finally:
    shutil.rmtree(root)

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
