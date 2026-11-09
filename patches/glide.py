"""Portamento for sample and multisample pads: Glide Off / Always / Legato and Glide Time on the Conf tab (see
src/glide.c), and the Conf tab lists of every pad mode (with Filter Type, fenv.c). Apply after `filter` (it edits the same Conf lists) and with `fenv` (which registers the two parameters
and gives them defaults) and `cave`."""
import os
import struct

from thumb import ROOT, bl, symbols

sym = symbols(os.path.join(ROOT, "out", "cave.elf"))


def hook(at, stock, name):
    return (at, bl(at, stock), bl(at, sym[name]))


P_GLIDE, P_GLIDETIME = 0x1E7, 0x1E8
P_FMODEL = 0x1EF                                       # Filter Type (fenv.c / filter.c)
P_OSCTRACK = 0x1E0                                     # Osc Track (fenv.c / filter.c): on the Osc tab since S.1 (filt_tab.c)
SAT, FID, LAUNCH, OUT, PAN, POLY, POLYS, EXCL, MIDI, ROOT, NOTE = 0xDB, 0xF1, 0x93, 0x95, 0x62, 0xA0, 0xA1, 0xC4, 0x6A, 0xD0, 0xF5
GL = (P_GLIDE, P_GLIDETIME)
# Conf lists (page 4): address, as filter.py leaves it (stock where filter.py doesn't touch it), final
CONF = [
    (0x080EFD38, (SAT, FID, LAUNCH, OUT, PAN, POLY, EXCL, MIDI, ROOT, NOTE),            # Sample
     (SAT, FID, LAUNCH, P_FMODEL, OUT, POLY, *GL, EXCL, MIDI, ROOT, NOTE)),
    (0x080EFBD0, (SAT, FID, LAUNCH, OUT, PAN, POLY, NOTE, EXCL, MIDI),                  # Multisample
     (SAT, FID, LAUNCH, P_FMODEL, OUT, POLY, *GL, NOTE, EXCL, MIDI)),
    (0x080EFA68, (SAT, FID, LAUNCH, OUT, PAN, EXCL, POLYS, MIDI, NOTE),                 # Clip
     (SAT, FID, LAUNCH, P_FMODEL, OUT, EXCL, POLYS, MIDI, NOTE)),
    (0x080EF900, (SAT, FID, LAUNCH, OUT, PAN, EXCL, POLYS, MIDI, NOTE),                 # Slicer
     (SAT, FID, LAUNCH, P_FMODEL, OUT, EXCL, POLYS, MIDI, NOTE)),
    (0x080EF630, (SAT, LAUNCH, OUT, PAN, EXCL, MIDI, ROOT, NOTE),                       # Granular (no Fidelity)
     (SAT, LAUNCH, P_FMODEL, OUT, EXCL, MIDI, ROOT, NOTE)),
    (0x080EF4C8, (SAT, LAUNCH, OUT, PAN, POLY, EXCL, FID, MIDI, ROOT, NOTE),            # Sample, empty-pad record
     (SAT, FID, LAUNCH, P_FMODEL, OUT, POLY, *GL, EXCL, MIDI, ROOT, NOTE)),
    (0x080EF360, (SAT, LAUNCH, OUT, PAN, EXCL, POLYS, MIDI, NOTE),                      # Clip, empty-pad record
     (SAT, FID, LAUNCH, P_FMODEL, OUT, EXCL, POLYS, MIDI, NOTE)),
    (0x080EF1F8, (SAT, LAUNCH, OUT, PAN, EXCL, POLY, MIDI, NOTE),                       # Slicer, empty-pad record
     (SAT, FID, LAUNCH, P_FMODEL, OUT, EXCL, POLY, MIDI, NOTE)),
    (0x080EF090, (SAT, LAUNCH, OUT, PAN, EXCL, MIDI, ROOT, NOTE),                       # Granular, empty-pad record
     (SAT, LAUNCH, P_FMODEL, OUT, EXCL, MIDI, ROOT, NOTE)),
]


def conf_final(addr, before, after):
    """a Conf list (36 slots, zero-terminated) -> the final order; both padded with zeros to the same length"""
    n = max(len(before), len(after)) + 1
    assert n <= 36
    return (addr, struct.pack(f"<{n}H", *before, *[0] * (n - len(before))),
            struct.pack(f"<{n}H", *after, *[0] * (n - len(after))))


PATCHES = [
    # note-on of sample / multisample pads (the eight calls in FUN_080596b0): note whether a note is held first
    *[hook(a, 0x08058548, "glide_note_on") for a in
      (0x0805999C, 0x08059B3E, 0x0805A6F6, 0x0805A75C, 0x0805A800, 0x0805A910, 0x0805B6E4, 0x0805B9BA)],
    # a new voice's base rate (note-on) and a legato retune: start the slide from where the pad's pitch is
    hook(0x0805892A, 0x0805F6B8, "glide_start_thunk"),
    hook(0x0805864C, 0x0805F6B8, "glide_retune_thunk"),
    # the reader's rate every block (looping and one-shot paths): + the slide's offset
    hook(0x080570B2, 0x0805F728, "glide_rate_thunk"),
    hook(0x0805743A, 0x0805F728, "glide_rate_thunk"),
    # Conf tab (3.1.uf, the user's layout): Saturation, Fidelity, Launch Mode, Filter Type, Output, Poly Mode, Glide,
    # Glide Time, then the rest; Pan only on Main. New (empty) pads get their mode's list.
    *[conf_final(a, before, after) for a, before, after in CONF],
]
