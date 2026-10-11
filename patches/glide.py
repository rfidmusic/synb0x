"""Portamento for sample and multisample pads: Glide Off / Always / Legato and Glide Time on the Conf tab (see
src/glide.c). Apply after `filter` (it edits the same Conf lists) and with `fenv` (which registers the two parameters
and gives them defaults) and `cave`."""
import os
import struct

from thumb import ROOT, bl, symbols

sym = symbols(os.path.join(ROOT, "out", "cave.elf"))


def hook(at, stock, name):
    return (at, bl(at, stock), bl(at, sym[name]))


P_GLIDE, P_GLIDETIME = 0x1E7, 0x1E8


def conf(addr, before, after):
    """Conf tab list (page 4) as filter.py leaves it -> Glide and Glide Time inserted right after Poly Mode (0xa0)"""
    old = struct.pack(f"<{len(before)}H", *before) + b"\0\0\0\0"
    i = before.index(0xA0) + 1
    new_ids = before[:i] + (P_GLIDE, P_GLIDETIME) + before[i:]
    assert tuple(new_ids) == tuple(after)
    return (addr, old, struct.pack(f"<{len(after)}H", *after))


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
    # Conf tab: Glide, Glide Time after Poly Mode. Sample, Multisample, and Sample in the empty-pad record
    conf(0x080EFD38, (0xDB, 0xF1, 0x93, 0x95, 0x62, 0xA0, 0xC4, 0x6A, 0xD0, 0xF5),
         (0xDB, 0xF1, 0x93, 0x95, 0x62, 0xA0, P_GLIDE, P_GLIDETIME, 0xC4, 0x6A, 0xD0, 0xF5)),
    conf(0x080EFBD0, (0xDB, 0xF1, 0x93, 0x95, 0x62, 0xA0, 0xF5, 0xC4, 0x6A),
         (0xDB, 0xF1, 0x93, 0x95, 0x62, 0xA0, P_GLIDE, P_GLIDETIME, 0xF5, 0xC4, 0x6A)),
    conf(0x080EF4C8, (0xDB, 0x93, 0x95, 0x62, 0xA0, 0xC4, 0xF1, 0x6A, 0xD0, 0xF5),
         (0xDB, 0x93, 0x95, 0x62, 0xA0, P_GLIDE, P_GLIDETIME, 0xC4, 0xF1, 0x6A, 0xD0, 0xF5)),
]
