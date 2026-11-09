"""Pad overdrive: warm asymmetric soft clip + DC blocker + tape tone in place of the stock curve (see src/od.c)."""
import os

from thumb import ROOT, bl, symbols, word

sym = symbols(os.path.join(ROOT, "out", "cave.elf"))


def hook(at, stock, name):
    return (at, bl(at, stock), bl(at, sym[name]))


PATCHES = [
    # pad Overdrive label -> "Saturation:" (literal in the parameter registration; xml name stays "overdrive"; was in
    # comp.py until the compressor models were dropped in 3.1.uo)
    (0x0808D878, word(0x080CC614), word(sym["od_label"])),
    hook(0x08059AB6, 0x0807081C, "od_process_a"), # sample pads (stands aside in a Fidelity machine mode)
    hook(0x08068B12, 0x0807081C, "od_process"),   # clip / slicer pads
]
