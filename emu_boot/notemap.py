"""Which MIDI notes (ch 0) start a voice: note-on, measure the next blocks' instruction count, note-off."""
from profile import *
m = setup('snap_ui3.pkl'); install_events(m)
p = Prof(m); p.armed = True
k = [0]
def block():
    dma_irq(m, k[0] & 1); run_for(m, 1_200_000); k[0] += 1
    return p.blocks[-1]
base = [block() for _ in range(2)]
print('idle', base, flush=True)
for n in range(30, 60):
    note_on(m, 0, n); block(); a = block(); b = block()
    note_off(m, 0, n); block(); c = block()
    for _ in range(3): c = block()
    print(n, a, b, 'after off', c, flush=True)
