"""Pad crunch (Interp list) + 24 dB state-variable filter with resonance drive in place of the stock biquad (see src/filter.c). Apply with `cave`."""
import os
import struct

from thumb import ROOT, bl, symbols

sym = symbols(os.path.join(ROOT, "out", "cave.elf"))


def bw(at, target):
    """32-bit Thumb B.W (T4) from `at` to `target` (bit 0 ignored)."""
    off = (target & ~1) - (at + 4)
    assert -(1 << 24) <= off < (1 << 24) and off % 2 == 0
    s = (off >> 24) & 1
    i1, i2 = (off >> 23) & 1, (off >> 22) & 1
    j1, j2 = (1 - i1) ^ s, (1 - i2) ^ s
    return struct.pack("<HH", 0xF000 | (s << 10) | ((off >> 12) & 0x3FF), 0x9000 | (j1 << 13) | (j2 << 11) | ((off >> 1) & 0x7FF))


def hook(at, stock, name):
    return (at, bl(at, stock), bl(at, sym[name]))


PATCHES = [
    # the stock buffer loops, four at a time (src/filter.c fast_*): their wrappers' tail jumps
    (0x0805FD18, bw(0x0805FD18, 0x080C7550), bw(0x0805FD18, sym["fast_scale"])),
    (0x0805F5C6, bw(0x0805F5C6, 0x080C7566), bw(0x0805F5C6, sym["fast_copy"])),
    (0x0805F618, bw(0x0805F618, 0x080C7578), bw(0x0805F618, sym["fast_fill"])),
    (0x080617C0, bytes.fromhex("10b58c10"), bw(0x080617C0, sym["fast_mixadd"])),   # the bus mix itself
    (0x0806A822, bytes.fromhex("c4ed098a"), bw(0x0806A822, sym["env_glide"])),    # the amp envelope's glide loop
    # parameter registration: Interp list 2 -> 9 entries
    hook(0x0808D92A, 0x0808C0D8, "interp_register"),
    # per-voice filter process: sample pads, clip / slicer voices
    # sample / multisample voices: the filter first, then the stock Level, Pan and amp envelope (filter_thunk.S)
    hook(0x08055BD6, 0x0804D8D0, "filter_voice_a"),
    (0x08055C60, bl(0x08055C60, 0x080762D8), bytes.fromhex("00bf00bf")),   # the stock filter call, after them: nops
    # clip / slicer voices: the filter first, then the stock amp envelope (filter_thunk.S)
    hook(0x080669C0, 0x0804D944, "filter_voice_b"),
    (0x080669D6, bl(0x080669D6, 0x080762D8), bytes.fromhex("00bf00bf")),   # the stock filter call, after it: nops
    # machine modes: park pad / position / rate on the way into the sample-voice reader, then swap its two kernels
    hook(0x08057214, 0x08055F0C, "voice_read"),
    hook(0x080574CE, 0x08055F0C, "voice_read"),
    hook(0x080575D2, 0x08055F0C, "voice_read"),
    hook(0x08057694, 0x08055F0C, "voice_read"),
    hook(0x0805619A, 0x080619D0, "read_normal_l"),       # stereo: both channels in the left call (3.1.v1)
    hook(0x080561BE, 0x080619D0, "read_normal_r"),       # ... the right call then only for a machine mode
    hook(0x080561D4, 0x080619D0, "read_normal"),
    hook(0x08056010, 0x08061A64, "read_hq"),
    hook(0x08056098, 0x08061A64, "read_hq_l"),           # stereo HighQ: both channels in the left call (3.1.v1)
    hook(0x080560BC, 0x08061A64, "read_hq_r"),
    # the grain / clip resampler FUN_080603ec, stereo in the left call (3.1.v1): grain renderer, clip / slicer voice
    hook(0x08057F78, 0x080603EC, "resamp_grain_l"),
    hook(0x08057F92, 0x080603EC, "resamp_r"),
    hook(0x080663EC, 0x080603EC, "resamp_clip_l"),
    hook(0x08066404, 0x080603EC, "resamp_r"),
    # pad-mode parameter pages (FUN_08098d40, 5 pages x 36 ids per mode), page 4 = the pad page: Interp right under
    # Saturation (0xdb) on Sample, Multisample, Slicer and Clip (stock had it only on Sample / Multisample, further down)
    (0x080EFD38, struct.pack("<10H", 0xDB, 0x93, 0x95, 0x62, 0xA0, 0xC4, 0xF1, 0x6A, 0xD0, 0xF5),
     struct.pack("<10H", 0xDB, 0xF1, 0x93, 0x95, 0x62, 0xA0, 0xC4, 0x6A, 0xD0, 0xF5)),      # Sample
    (0x080EFBD0, struct.pack("<9H", 0xDB, 0x93, 0x95, 0x62, 0xA0, 0xF5, 0xC4, 0xF1, 0x6A),
     struct.pack("<9H", 0xDB, 0xF1, 0x93, 0x95, 0x62, 0xA0, 0xF5, 0xC4, 0x6A)),            # Multisample
    (0x080EF900, struct.pack("<9H", 0xDB, 0x93, 0x95, 0x62, 0xC4, 0xA1, 0x6A, 0xF5, 0),
     struct.pack("<9H", 0xDB, 0xF1, 0x93, 0x95, 0x62, 0xC4, 0xA1, 0x6A, 0xF5)),            # Slicer
    (0x080EFA68, struct.pack("<9H", 0xDB, 0x93, 0x95, 0x62, 0xC4, 0xA1, 0x6A, 0xF5, 0),
     struct.pack("<9H", 0xDB, 0xF1, 0x93, 0x95, 0x62, 0xC4, 0xA1, 0x6A, 0xF5)),            # Clip
]
