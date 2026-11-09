"""3.1.ug: the Room reverb (fx2) is not in this build: the four places fx2 patched are the stock firmware's bytes again,
so the reverb is the stock Plate, its param 0x198 is the stock registration and the reverb cell gets stock defaults."""
import sys

IMG = "out/solo+slice+filter+fenv+filttab+glide+splash+cpu+od+cave/BLACKBOX.bin"
B = 0x08040000
img, stock = open(IMG, "rb").read(), open("firmware/BLACKBOX-3.1.9.bin", "rb").read()
fails = 0
for at, what in ((0x0808DEA4, "reverb Type registration (param 0x198)"), (0x080944A2, "reverb cell defaults (first)"),
                 (0x080944B8, "reverb cell defaults (last)"), (0x0806318E, "reverb process: the Plate core call")):
    ok = img[at - B:at - B + 4] == stock[at - B:at - B + 4]
    print(("PASS " if ok else "FAIL ") + f"stock {what} at {at:#x}")
    fails += not ok
syms = open("out/cave.elf", "rb").read()
ok = b"fx2_core" not in syms and b"fx2_register" not in syms
print(("PASS " if ok else "FAIL ") + "no fx2 code in the cave")
fails += not ok
print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
