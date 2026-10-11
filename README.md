# blackbox-mod

An unofficial feature mod for the **original 1010music Blackbox** (not the Blackbox 2), built on stock firmware 3.1.9.

> **Not affiliated with, endorsed by, or supported by 1010music.** This repository does not contain 1010music's
> firmware. You supply your own copy, downloaded from 1010music, and patch it yourself. Use at your own risk: this is
> tested on one unit, it may misbehave on yours, and running modified firmware may affect your warranty. Don't ask
> 1010music for support on a modded unit; flash stock first.

**Get new builds by email:** sign up at <https://justinjoe.com/blackbox-mod> and I'll send a note when a new build is
out (new FX, fixes). That's all the list is for.

## What it adds (build 3.1.H, `filter-env` branch)

- **Solo** in the mixer: MIX cycles Mixer → Mute → Solo. Tap pads to solo them (yellow).
- **Slicer knobs**: on the waveform screen, bottom-left = slice Start, bottom-right = slice End, top-right = Zoom.
- **Fidelity** (was Interp): sample-rate crunch plus machine modes SP1200, SP-12, S950, MPC60 and SP Raw, with
  drop-sample pitching. Machine modes work on Sample and Multisample pads.
- **Filter**: 24 dB/oct state-variable filter; drive comes in as Res goes past noon. **Type** picks LP, HP or BP, and
  the Filter knob is cutoff across its whole travel (far left 20 Hz, far right 20.5 kHz; new pads start fully open).
  Presets saved before this build keep their Filter value, so a pad saved with the knob at centre (stock: filter off)
  now loads as a low-pass at 640 Hz.
- **Filter envelope**: per pad, per voice: Attack, Decay, Sustain, Release (0 ms to 60 s on a 0-100 curve like the amp
  envelope; Sustain is a level) and Depth (-100..+100 = up to the cutoff's whole travel). It follows each voice's amp
  envelope: it starts with the note and releases when the amp envelope does (note off, one-shot end, choke).
- **Filt tab**: the pad screen gains a Filt tab after Main with Filter, Res, Type, Depth / Attack, Decay, Sustain,
  Release. Filter and Res leave the Main tab, which now reads Level, Pitch, Pan, Saturation / Attack, Decay, Sustain, Release.
- **Glide** (sample and multisample pads), on the Conf tab after Poly Mode: Glide Off / Always / Legato and Glide
  Time (0-100 on a curve, up to 10 s; a slide takes the same time whatever the interval). Always slides every note from
  the pad's last pitch; Legato only while another note of the pad is held, including the stock Legato switch's in-place
  retune.
- **Startup screen** reads Synb0x instead of blackbox.
- **Modulation sources KEY and FENV**: KEY is key follow ((note - C3) / 60, the engine's own per-voice source that
  stock never listed); FENV is the voice's filter envelope, so it can also drive Pitch, Level, Pan and the rest.
- **Saturation** (was Overdrive): soft saturation in place of the hard clip.
- **Master compressor models**: Stock, Glue, Punch, Opto, Squash, Limit, plus a Comp Thresh setting.
- **Reverb Type**: Plate (stock) or Room.
- **Delay Type**: Delay (stock) or Munchi (a port of the CHOMPI TEMPO granular delay).

### Known issues

- Solo can stick: after un-soloing, pads may stay muted. Unmute them in Mute mode.
- Presets saved with a Fidelity value on an older mod build may read a different value.

## Install

1. Download **blackbox 3.1.9** from <https://1010music.com/downloads> and unzip it. You need the `BLACKBOX.bin` inside.
2. Patch it, either way:
   - **In your browser:** <https://j3threejay.github.io/blackbox-mod/>. Your file never leaves your computer.
   - **With Python 3:** `python3 apply.py path/to/BLACKBOX.bin` → `out/blackbox-mod-3.1.n/BLACKBOX.bin`
3. Keep the stock `BLACKBOX.bin` somewhere safe. That file is your way back.
4. Copy the patched `BLACKBOX.bin` to the root of the Blackbox's microSD card and install it the way you install
   any 1010music firmware update (hold BACK + INFO while powering on).
5. TOOLS should show version `3.1.n`.

**To go back to stock:** put the stock `BLACKBOX.bin` on the card and install it the same way.

The patcher checks your file's SHA-256 before it writes anything
(`281ae303d32e5eb52adca7817a648a34e4bd3848017f26673dd9df3905f1341d`) and checks the result afterwards. It only
works on 3.1.9.

## Build from source

Needs `arm-none-eabi-gcc` and Python 3. Put your stock image at `firmware/BLACKBOX-3.1.9.bin` (see
`firmware/README.md`).

```
./build.sh
python3 patch.py solo slice filter fenv filttab glide splash cpu od comp fx2 munchi cave
```

That writes `out/<patchsets>/BLACKBOX.bin`. (On `main` the list is `solo slice duck chord cond filter cpu od comp seqfix
fx2 munchi cave`, byte-identical to the 3.1.n release.) `python3 make_patch.py <image> <version>`
turns an image into the release patch in `docs/`.

How it works: the stock image is left as it is. New code (`src/`) is compiled and appended after it, and a handful of
call sites and table entries (`patches/`) are redirected to the new code.

Tests (`test_*.py`) run the patched functions under Unicorn (`pip install unicorn`). They test the new functions, not
a full boot. The first power-on of any build is the real test.

`ghidra/`, `disasm.py`, `findbl.py`, `findref.py` are the helpers used to find things in your own copy of the image.

## What is and isn't in this repository

In it: original source code, patch definitions (addresses and replacement bytes), tools, and MIT-licensed third-party
DSP with its notices ([THIRD_PARTY.md](THIRD_PARTY.md)).

Not in it, and please don't add it in issues, pull requests or forks: 1010music's firmware, patched firmware images,
decompiled or disassembled listings of the firmware, and 1010music's manuals or artwork.

## License

MIT for the original work here ([LICENSE](LICENSE)). "1010music" and "Blackbox" are trademarks of 1010music LLC, used
only to say what this mod is for.

If you are from 1010music and have a concern about anything here, open an issue or email justin.joe.dev@gmail.com and
it will be dealt with promptly.
