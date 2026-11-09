import sys, struct
from profile import *
m = setup(sys.argv[1] if len(sys.argv) > 1 else 'snap_ui3.pkl')
install_events(m)
p = Prof(m); p.armed = True
OUT = 0x2407e800
def rms(half):
    b = bytes(m.uc.mem_read(OUT + half * 0x800, 0x800))
    v = struct.unpack('<512i', b)
    return (sum(x * x for x in v) / 512) ** 0.5, max(abs(x) for x in v)
k = 0
def block():
    global k
    dma_irq(m, k & 1); run_for(m, 1_500_000); k += 1
    return p.blocks[-1], rms((k - 1) & 1)
for i in range(3): print('idle', block())
ch = int(sys.argv[2]) if len(sys.argv) > 2 else 0
for n in range(36, 52):
    note_on(m, ch, n)
for i in range(12): print('notes', i, block(), len(m.ev_queue))
