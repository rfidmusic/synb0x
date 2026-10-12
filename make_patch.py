"""Turn a built image into a release patch: python3 make_patch.py out/<patchsets>/BLACKBOX.bin 3.1.s

Writes docs/blackbox-mod-<version>.json. The patch holds only the bytes this project adds or changes (new bytes and
their offsets). It contains no bytes of the stock firmware; the stock image is identified by SHA-256 only.
"""
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
stock = open(os.path.join(ROOT, "firmware", "BLACKBOX-3.1.9.bin"), "rb").read()
built = open(sys.argv[1], "rb").read()
version = sys.argv[2]
assert len(built) >= len(stock)

writes = []
i = 0
while i < len(stock):
    if stock[i] == built[i]:
        i += 1
        continue
    j = i
    while j < len(stock) and stock[j] != built[j]:
        j += 1
    writes.append({"offset": i, "bytes": built[i:j].hex()})
    i = j

patch = {
    "name": "blackbox-mod",
    "version": version,
    "stock_version": "3.1.9",
    "stock_size": len(stock),
    "stock_sha256": hashlib.sha256(stock).hexdigest(),
    "output_size": len(built),
    "output_sha256": hashlib.sha256(built).hexdigest(),
    "writes": writes,
    "append": built[len(stock):].hex(),
}
out = os.path.join(ROOT, "docs", f"blackbox-mod-{version}.json")
json.dump(patch, open(out, "w"), indent=1)
print(f"wrote {out}: {len(writes)} writes, {sum(len(w['bytes']) for w in writes) // 2} changed bytes, "
      f"{len(patch['append']) // 2} appended")
