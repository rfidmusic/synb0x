import sys, collections
from audio import *
m = setup()
m.TICK_INSNS = 20000
ff = [a for a, n in FUNCS if 0x08086000 <= a < 0x08087a00]
def mk(a):
    def h(m):
        s = []
        for r in (0, 1):
            v = m.reg(r)
            if 0x20000000 <= v < 0x24080000 or 0x08040000 <= v < 0x08100000 or 0xC0000000 <= v < 0xC4000000:
                t = m.cstr(v, 80)
                if len(t) >= 2 and all(32 <= ord(c) < 127 for c in t):
                    s.append(repr(t))
        if s:
            print(f"  FS {a:08x} {' '.join(s)}  lr={fname(m.uc.reg_read(UC_ARM_REG_LR))}")
    return h
for a in ff:
    m.hook(a, mk(a))
for i in range(int(sys.argv[1])):
    ui_frame(m)
    run_for(m, 200000)
