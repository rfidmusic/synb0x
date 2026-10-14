"""Filter Type (LP / HP / BP) and per-pad filter envelope: the parameters (see src/fenv.c; the sound is in filter.c).
Apply together with `filter` and `cave`."""
import os

from thumb import ROOT, bl, symbols, word

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

    # modulation: FENV and AD (sources 1, 2) through the sample-pad route and voice copy, and the clip / slicer route
    hook(0x0805A138, 0x08056810, "fenv_mod_msg_a"),
    hook(0x08058C34, 0x0805623C, "fenv_voice_copy"),
    hook(0x0805A8DA, 0x0805623C, "fenv_voice_copy"),
    hook(0x080685C4, 0x08067018, "fenv_mod_msg_b"),
    # LFO Mode 1-Shot: the per-block LFO update of sample, multisample and clip / slicer voices (filter.c)
    hook(0x08056FF8, 0x0806F108, "lfo_update_a"),
    hook(0x0805800A, 0x0806F108, "lfo_update_a"),
    hook(0x08066838, 0x0806F108, "lfo_update_b"),
    # UI: pad modulation Source list grows from 8 to 11 entries (+ KEY, FENV, AD)
    (0x0808CCC0, word(0x080ECD0C), word(sym["fenv_source_names"])),     # parameter registration: names
    (0x080B6964, word(0x080ECD0C), word(sym["fenv_source_names"])),     # knob page: names
    (0x0809A69C, word(0x080ECCFC), word(sym["fenv_source_codes"])),     # app: list index -> source code
    (0x080B696C, word(0x080ECCFC), word(sym["fenv_source_codes"])),     # knob page: source code -> list index
    (0x080B7B00, word(0x080ECCFC), word(sym["fenv_source_codes"])),     # modulation screen: source code -> list index
    (0x0808CB3E, bytes.fromhex("cdf800b0"), bytes.fromhex("0b210091")),  # registration count: str fp(8),[sp] -> movs r1,#11; str r1,[sp]
    (0x080B67CC, bytes.fromhex("082b"), bytes.fromhex("0b2b")),          # knob page loop: cmp r3,#8 -> #11
    (0x080B7994, bytes.fromhex("0820"), bytes.fromhex("0b20")),          # modulation screen loop: movne r0,#8 -> #11
]
