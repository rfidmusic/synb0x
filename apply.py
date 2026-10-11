"""Patch your own stock Blackbox firmware. Needs only Python 3, nothing to install.

  python3 apply.py path/to/BLACKBOX.bin [patch.json] [-o BLACKBOX.bin]

The input must be the unmodified 3.1.9 BLACKBOX.bin from 1010music's download. It is checked by SHA-256 before
anything is written, and the result is checked again afterwards.
"""
import argparse
import glob
import hashlib
import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("stock")
ap.add_argument("patch", nargs="?", default=sorted(glob.glob(os.path.join(ROOT, "docs", "blackbox-mod-*.json")))[-1])
ap.add_argument("-o", "--out", default=None)
a = ap.parse_args()

p = json.load(open(a.patch))
data = bytearray(open(a.stock, "rb").read())
if hashlib.sha256(data).hexdigest() != p["stock_sha256"]:
    raise SystemExit(f"This is not the stock {p['stock_version']} firmware (SHA-256 differs). Nothing written.\n"
                     "Download it from https://1010music.com/downloads and use the BLACKBOX.bin inside the zip.")
for w in p["writes"]:
    b = bytes.fromhex(w["bytes"])
    data[w["offset"]:w["offset"] + len(b)] = b
data += bytes.fromhex(p["append"])
if hashlib.sha256(data).hexdigest() != p["output_sha256"]:
    raise SystemExit("Patched image failed its check. Nothing written.")

out = a.out or os.path.join("out", f"blackbox-mod-{p['version']}", "BLACKBOX.bin")
if os.path.abspath(out) == os.path.abspath(a.stock):
    raise SystemExit("Refusing to overwrite the stock file. Pick another output path and keep the stock one as backup.")
os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
open(out, "wb").write(data)
print(f"wrote {out} ({len(data)} bytes) = {p['version']}")
print(f"SHA-256 {hashlib.sha256(data).hexdigest()} (matches the release; see README / SHA256SUMS)")
