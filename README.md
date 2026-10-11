# Synb0x

An unofficial feature mod for the **original 1010music Blackbox** (not the Blackbox 2), built on stock firmware 3.1.9.
Synb0x is a fork of [j3threejay/blackbox-mod](https://github.com/j3threejay/blackbox-mod) by Justin Joe (build 3.1.n):
it keeps most of that mod, drops four of its features and adds a synth-style filter section, glide and two modulation
sources. Firmware version: **3.1.9-syn**.

> **Not affiliated with, endorsed by, or supported by 1010music.** This repository does not contain 1010music's
> firmware. You supply your own copy, downloaded from 1010music, and patch it yourself. Use at your own risk: this is
> tested on one unit, it may misbehave on yours, and running modified firmware may affect your warranty. Don't ask
> 1010music for support on a modded unit; flash stock first.

## Checksums

| File | SHA-256 |
|---|---|
| Stock `BLACKBOX.bin` from 1010music's **3.1.9** zip (what you patch) | `281ae303d32e5eb52adca7817a648a34e4bd3848017f26673dd9df3905f1341d` |
| Patched `BLACKBOX.bin`, **Synb0x 3.1.9-syn** (what `apply.py` writes) | `de613438eafd9c866e06331c770c139ca208c66d621c1b0f57ad6c0350051c79` |

The patcher checks both itself and prints the result's SHA-256. To check a file by hand:

```
shasum -a 256 BLACKBOX.bin          # macOS / Linux
certutil -hashfile BLACKBOX.bin SHA256   # Windows
```

The same value is in [`SHA256SUMS`](SHA256SUMS) (`shasum -a 256 -c SHA256SUMS` next to your patched file) and in the
patch file itself (`docs/blackbox-mod-3.1.9-syn.json`, `output_sha256`).

## Install

1. Download **blackbox 3.1.9** from <https://1010music.com/downloads> and unzip it. You need the `BLACKBOX.bin` inside.
2. With Python 3 (nothing to install):

   ```
   python3 apply.py path/to/BLACKBOX.bin
   ```

   It writes `out/blackbox-mod-3.1.9-syn/BLACKBOX.bin` and prints its SHA-256, which must match the table above. It
   refuses to run on anything but the stock 3.1.9 file, and refuses to overwrite it.
3. Keep the stock `BLACKBOX.bin` somewhere safe. That file is your way back.
4. Copy the patched `BLACKBOX.bin` to the root of the Blackbox's microSD card and install it the way you install any
   1010music firmware update (hold BACK + INFO while powering on).
5. TOOLS and the startup screen show **3.1.9-syn**.

**To go back to stock:** put the stock `BLACKBOX.bin` on the card and install it the same way.

## What Synb0x adds

- **Filter Type**: a new Type control picks **LP, HP or BP** (24 dB/oct state-variable filter, Res drive past noon as
  before). The Filter knob is now cutoff across its whole travel: far left 20 Hz, far right 20.5 kHz, shown as
  **0-100 %**; new pads start fully open.
- **Filter envelope**, per pad and per voice: **Attack, Decay, Sustain, Release** (0 ms to 60 s on a 0-100 curve like
  the amp envelope; Sustain is a level) and **Depth** (-100..+100, up to the cutoff's whole travel). It follows each
  voice's amp envelope: it starts with the note and releases when the amp envelope does (note off, one-shot end, choke).
- **Filt tab** on the pad screen, right after Main: Filter, Res, Type, Depth / Attack, Decay, Sustain, Release, with
  modulation indicators. Main now reads Level, Pitch, Pan, Saturation / Attack, Decay, Sustain, Release.
- **Modulation sources KEY and FENV** in every pad's Source list: KEY is key follow ((note - C3) / 60, the engine's own
  per-voice source that stock never listed); FENV is the voice's filter envelope, so it can also drive Pitch, Level,
  Pan and the rest.
- **Glide** (sample and multisample pads), on the Conf tab after Poly Mode: **Glide** Off / Always / Legato and
  **Glide Time** (0-100 on a curve, up to 10 s; a slide takes the same time whatever the interval). Always slides every
  note from the pad's last pitch; Legato only while another note of the pad is held, including the stock Legato
  switch's in-place retune.
- **Startup screen** reads Synb0x.
- **Less CPU** per voice than the 3.1.n filter (settings lookups cached, one-pass filter, idle envelopes skipped).

## Kept from blackbox-mod 3.1.n

- **Solo** in the mixer: MIX cycles Mixer → Mute → Solo. Tap pads to solo them (yellow).
- **Slicer knobs**: on the waveform screen, bottom-left = slice Start, bottom-right = slice End, top-right = Zoom.
- **Fidelity** (was Interp): sample-rate crunch plus machine modes SP1200, SP-12, S950, MPC60 and SP Raw, with
  drop-sample pitching. Machine modes work on Sample and Multisample pads.
- **Saturation** (was Overdrive): soft saturation in place of the hard clip.
- **Master compressor models**: Stock, Glue, Punch, Opto, Squash, Limit, plus a Comp Thresh setting.
- **Reverb Type**: Plate (stock) or Room.
- **Delay Type**: Delay (stock) or Munchi (a port of the CHOMPI TEMPO granular delay), with its own Duck control.
- **CPU meter** next to the version: average / worst block of the last second.

## Differences from blackbox-mod 3.1.n

| | blackbox-mod 3.1.n | Synb0x 3.1.9-syn |
|---|---|---|
| Pad-1 ducker (EXP1 / EXP2 / PUMP / LINR sources) | yes | **removed** |
| Chords on the Keys screen | yes | **removed** |
| Note conditions (1:2 … 8:8) | yes | **removed** |
| Sequencer fix (notes just ahead of the playhead) | yes | **removed** |
| Filter knob | centre = off, left LP, right HP | **cutoff**, 0-100 %; **Type** LP / HP / BP |
| Filter envelope, Filt tab, KEY / FENV sources, Glide | – | **new** |
| Main tab | Level, Filter, Pitch, Res / A D S R | Level, Pitch, Pan, Saturation / A D S R |
| Clip / slicer pads, second voice | Fidelity read another pad's setting | **fixed** |
| Pad settings capacity | 64 entries | 72 (the new settings need room) |
| Version shown | 3.1.n | 3.1.9-syn |
| Browser patcher | yes | no: Python `apply.py` only |

**Presets:** they load. Synb0x's new settings save with the pad; presets made before it get the defaults (Type LP,
envelope Depth 0, Glide Off). One change to know about: a pad saved with the Filter knob at centre (stock: filter off)
now loads as a low-pass at 640 Hz; turn Filter fully right to open it. Stock firmware ignores the extra settings.

### Known issues

- Solo can stick: after un-soloing, pads may stay muted. Unmute them in Mute mode.
- Presets saved with a Fidelity value on an older mod build may read a different value.

## Build from source

Needs `arm-none-eabi-gcc` and Python 3. Put your stock image at `firmware/BLACKBOX-3.1.9.bin` (see
`firmware/README.md`).

```
./build.sh
python3 patch.py solo slice filter fenv filttab glide splash cpu od comp fx2 munchi cave
```

That writes `out/<patchsets>/BLACKBOX.bin`, byte-identical to 3.1.9-syn (the SHA-256 above) with Homebrew's
arm-none-eabi-gcc 16.2. `python3 make_patch.py <image> 3.1.9-syn` turns an image into the release patch in `docs/`.

How it works: the stock image is left as it is. New code (`src/`) is compiled and appended after it, and a handful of
call sites and table entries (`patches/`) are redirected to the new code. The Synb0x parts are `src/fenv.c` (filter
parameters, KEY / FENV routing), `src/filter.c` (filter Type and envelope), `src/filt_tab.c` (Filt tab),
`src/glide.c` (glide) and their `patches/`.

Tests (`test_*.py`) run the patched functions under Unicorn (`pip install unicorn`); `for t in test_*.py; do python3
$t; done`. They test the new functions against real stock code where they can, not a full boot. The first power-on of
any build is the real test.

`ghidra/`, `disasm.py`, `findbl.py`, `findref.py` are the helpers used to find things in your own copy of the image.

## What is and isn't in this repository

In it: original source code, patch definitions (addresses and replacement bytes), tools, and MIT-licensed third-party
DSP with its notices ([THIRD_PARTY.md](THIRD_PARTY.md)).

Not in it, and please don't add it in issues or pull requests: 1010music's firmware, patched firmware images,
decompiled or disassembled listings of the firmware, and 1010music's manuals or artwork.

## Credits and license

Synb0x is built on [blackbox-mod](https://github.com/j3threejay/blackbox-mod) by Justin Joe, whose patcher, toolchain,
test harness and features are most of this project. Third-party DSP is listed in [THIRD_PARTY.md](THIRD_PARTY.md).

MIT ([LICENSE](LICENSE)). "1010music" and "Blackbox" are trademarks of 1010music LLC, used only to say what this mod
is for.

Questions, problems, or a concern from 1010music: open an issue on this repository and it will be dealt with promptly.
