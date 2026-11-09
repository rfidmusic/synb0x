"""3.1.v1: Munchi removed. The delay slot is the stock delay again: the calls Munchi took over are stock again.

Checked (bytes in the built image against stock 3.1.9): the delay's process call (0x08054f3a), the 0x197 registration
(0x0808de8e), the delay cell defaults (0x0809444a, 0x08094494), the settings-list fill (0x08098e72) and the FX screen's
message handler slot. NOT checked: how the stock delay sounds (stock).
"""
import sys

MOD = "out/solo+slice+filter+fenv+filttab+glide+splash+cpu+od+cave/BLACKBOX.bin"
B = 0x08040000
stock, mine = open("firmware/BLACKBOX-3.1.9.bin", "rb").read(), open(MOD, "rb").read()
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


sites = {"delay process call": 0x08054F3A, "0x197 registration": 0x0808DE8E, "delay defaults (first)": 0x0809444A,
         "delay defaults (last)": 0x08094494, "settings-list fill": 0x08098E72, "FX screen handler slot": 0x080F07F0}
for name, a in sites.items():
    o = a - B
    check(f"{name} ({a:#x}) is stock again", mine[o:o + 4] == stock[o:o + 4], (mine[o:o + 4].hex(), stock[o:o + 4].hex()))
print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
