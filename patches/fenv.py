"""Filter Type (LP / HP / BP) and per-pad filter envelope: the parameters (see src/fenv.c; the sound is in filter.c).
Apply together with `filter` and `cave`."""
import os

from thumb import ROOT, bl, symbols

sym = symbols(os.path.join(ROOT, "out", "cave.elf"))


def hook(at, stock, name):
    return (at, bl(at, stock), bl(at, sym[name]))


PATCHES = [
    # parameter registration: after "Filter:" (200), register Type and the envelope's Attack/Decay/Sustain/Release/Depth
    hook(0x0808D59C, 0x0808C12C, "fenv_register"),
    # pad record defaults, sample pad (type 3) and empty pad (type 0x4c): Filter fully open + the six new entries
    hook(0x080940DE, 0x08093EF6, "fenv_defaults"),
    hook(0x08094312, 0x08093EF6, "fenv_defaults"),
    # settings store capacity 64 -> 72 entries: a sample pad record already holds 59. movs r1,#64 -> movs r1,#72
    (0x080949F0, bytes.fromhex("4021"), bytes.fromhex("4821")),     # FUN_080949e4, allocates first
    (0x08093F26, bytes.fromhex("4021"), bytes.fromhex("4821")),     # FUN_08093f20 (pad / cell defaults)
]
