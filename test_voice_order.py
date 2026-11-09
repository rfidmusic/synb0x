"""The voice order under Unicorn: the filter runs before the stock Level, Pan and amp envelope, on every pad type.

Real firmware runs for: the sample / multisample voice's closing routine FUN_08055bb8 (Level and Pan ramps, the amp
envelope FUN_0806a6c0, the bus mix) and the hooked call sites. Recorded: which of filter_process, the Level / Pan ramp
FUN_08075e40 and the amp envelope run, in order. Clip / slicer: their call site (0x080669c0) runs the filter, and the
stock filter call after the envelope (0x080669d6) is gone.
NOT checked: how it sounds (hardware).
"""
import struct
import sys

from unicorn import UC_HOOK_CODE

src = open("test_filter.py").read()
ns = {"__name__": "test_voice_order"}
exec(compile(src[:src.index("# --- the Filter knob is cutoff")], "test_filter.py", "exec"), ns)
e, values, PARAMS, PAD, BUF, LBUF, RBUF = (ns[k] for k in ("e", "values", "PARAMS", "PAD", "BUF", "LBUF", "RBUF"))
N = 256
VOICE = 0x24074000
OBJ, ENV, ENVP = VOICE + 0xA8, VOICE + 0x28, 0x2407E000
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


order = []
for name, addr in (("filter", e.sym["filter_process"]), ("level/pan ramp", 0x08075E40), ("amp envelope", 0x0806A6C0),
                   ("stock filter", 0x080762D8)):
    e.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, n: order.append(n), name, begin=addr, end=addr)
e.stub(0x08063790, value=1)                          # the sample's channel count: stereo
e.stub(0x080636F0, value=1 << 24)                    # its length
e.stub(0x0804DA6C)                                   # the bus mix

ns["setup"](-0.3, 0.5)
e.uc.mem_write(OBJ + 0x40, bytes(0x20))
e.w32(OBJ + 0x84, PARAMS)
values[VOICE + 0x150] = 1.0
e.uc.mem_write(PAD + 0x100, bytes(0x500))
e.uc.mem_write(PAD + 0x5A8, struct.pack("<f", 1.0))
e.uc.mem_write(ENVP, bytes(0x40))
e.uc.mem_write(ENVP + 0x18, struct.pack("<f", 0.5))
e.uc.mem_write(ENV, bytes(0x40))
e.uc.mem_write(ENV + 4, bytes([3]))
e.w32(ENV + 8, ENVP)
e.uc.mem_write(LBUF, struct.pack(f"<{N}f", *[0.3] * N))
e.uc.mem_write(RBUF, struct.pack(f"<{N}f", *[0.3] * N))
e.uc.mem_write(BUF, struct.pack("<IIIIBB", N, N, LBUF, RBUF, 0, 1))
order.clear()
e.call(0x08055BB8, PAD, VOICE, BUF, BUF)
seq = [o for i, o in enumerate(order) if i == 0 or order[i - 1] != o]
check(f"sample / multisample voice: filter, then Level / Pan, then the amp envelope (ran: {' -> '.join(seq)})",
      seq[:1] == ["filter"] and "amp envelope" in seq and seq.index("amp envelope") > 0 and "stock filter" not in seq
      and all(o != "filter" for o in seq[1:]), seq)
check("clip / slicer voice: the stock filter call after the envelope is gone (0x080669d6: nops), the filter is called "
      "from 0x080669c0", e.r16(0x080669D6) == 0xBF00 and e.r16(0x080669D8) == 0xBF00 and e.r16(0x080669C0) != 0xF7E6)
print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
