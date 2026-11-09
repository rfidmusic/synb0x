"""(S.1) Stock grain renderer FUN_08057db8, two bit-identical CPU savings (see src/grainmix_thunk.S):
- @0x08057e40: its source scratch from FUN_0804da0c, not FUN_0804d9c0 (that one cleared all 1024 frames of both
  channels every block, which FUN_08074a00 then overwrites; the stock sample reader takes FUN_0804da0c too).
- @0x08057ee2: the mix loop -> grain_mix (no sdiv per sample)."""
import os

from thumb import ROOT, bl, symbols
from cache import bw

sym = symbols(os.path.join(ROOT, "out", "cave.elf"))

PATCHES = [
    (0x08057E40, bl(0x08057E40, 0x0804D9C0), bl(0x08057E40, 0x0804DA0C)),
    (0x08057EE2, bytes.fromhex("beec017a"), bw(0x08057EE2, sym["grain_mix"])),     # vldmia lr!, {s14}
]
