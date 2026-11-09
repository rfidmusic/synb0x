# Blackbox preset.xml format: stock 3.1.9 and Synb0x S.1

The `preset.xml` file a 1010music Blackbox writes in each preset folder, for the stock firmware 3.1.9 and for Synb0x S.1. Every parameter either firmware registers is listed with its XML attribute name, stored range, list items, defaults and meaning, so presets can be written by other tools or converted from other formats. The same table, with every column, is in [`Blackbox_preset_format.csv`](Blackbox_preset_format.csv).

The table was read from each firmware itself: its parameter registration (FUN_0808c158) and record defaults (FUN_08093f20) were run under an emulator and every entry recorded; display formats from FUN_080b0528.

## File rules

- Encoding UTF-8 with a byte-order mark (EF BB BF); first line <?xml version="1.0" encoding="UTF-8"?>.
- Line ends LF (no CR); 4 spaces per indent level; empty elements written as <x/>.
- The Blackbox usually writes a NUL byte (0x00) after </document> (39 of the 40 presets checked). Strict XML parsers reject it: strip trailing NUL bytes before parsing. Writing without it is fine (one preset has none).
- All values are integers written as decimal text. Lists store the item's index (0 = first item); on / off buttons store 0 / 1.
- Sample paths in filename: ".\name.wav" = in the preset's own folder; "\folder\name.wav" = from the SD card's root. Backslashes, as written by the Blackbox.
- On load the firmware builds each cell's record from its defaults, then reads each attribute by name: attribute order doesn't matter, and a missing attribute keeps its default. Unknown attributes are ignored (and are not written back on the next save).
- Pad settings records hold 64 entries in stock and 88 in Synb0x; a sample pad uses 59 (stock) / 82 (Synb0x).

## Structure

| Element | Attribute | Value | Meaning | Example |
|---|---|---|---|---|
| document | (none) |  | The root element. | <document> |
| document/session | version | integer | File layout version; 2 in every preset checked. | 2 |
| session/cell | row | integer | Grid row (see Cell types). | 3 |
| session/cell | column | integer | Grid column. Layer 0 and 1: 0..4 (column 4 holds samtempl / sequence cells beyond the 16 pads). Absent on effect cells. | 0 |
| session/cell | layer | integer | 0 pads, 1 sequences, 2 sections, 3 effects. Absent on the song cell. | 0 |
| session/cell | type | text | The cell's kind: sample, samtempl, asset, noteseq, section, song, delay, reverb, eq, filter, bitcrusher, null (see Cell types). | sample |
| session/cell | filename | path | sample / samtempl / asset cells: the WAV (".\x.wav" preset folder, "\dir\x.wav" card root). Empty for an empty pad. | .\2001 CHOIR.wav |
| session/cell | seqsublayer | integer | noteseq: 0..3, the four sequences of the cell's pad; section: 0. | 2 |
| session/cell | name | text | section cells: the section's name. | Section 1 |
| cell/params | (parameters) | integers | One attribute per setting of the cell's record: see Parameters. Effect cells with no settings write <params/>. | gaindb="0" |
| cell/modsource | dest | text | The destination: the xml name of the parameter it modulates. | dualfilcutoff |
| cell/modsource | src | text | The source (see Mod sources). | velocity |
| cell/modsource | slot | integer | Which of the destination's routes: 0..2. | 0 |
| cell/modsource | amount | integer | -1000..1000 = -100..+100 %. | 400 |
| cell/modsource | mchan | integer | src midicc only: the MIDI channel. | 1 |
| cell/modsource | ccnum | integer | src midicc only: the CC number. | 74 |
| cell/slices | (none) |  | Container for a pad's slice points (written on sample cells, often empty). | <slices/> |
| slices/slice | pos | integer | A slice point (sample frames, as observed). | 120000 |
| cell/sequence | (none) |  | noteseq and section cells: the events. | <sequence> |
| sequence/seqevent | type | text | note (a note step) or sceneitem (a section's per-pad entry). | note |
| sequence/seqevent | step | integer | The step. | 0 |
| sequence/seqevent | chan | integer | sceneitem: pad / sequence reference (values 1..15 and 256..271 seen). | 257 |
| sequence/seqevent | silayer | integer | sceneitem: sequence layer. | 0 |
| sequence/seqevent | cond | integer | Step condition (0 = none). | 0 |
| sequence/seqevent | pitch | integer | note: MIDI note. | 60 |
| sequence/seqevent | velocity | integer | note: velocity. | 100 |
| sequence/seqevent | strtks | integer | note: start offset in ticks. | 0 |
| sequence/seqevent | lencount | integer | note: length in steps. | 1 |
| sequence/seqevent | lentks | integer | note: extra length in ticks. | 0 |
| cell type=asset | filename + params |  | Multisample zone: its WAV in filename; params asssrcrow / asssrccol (the pad it belongs to, 0..3), rootnote, keyrangebottom / keyrangetop, velrangebottom / velrangetop. Its loop is the WAV's own 'smpl' loop (first loop; end exclusive). |  |

## Cell types

| type | layer | Position | Record type | What it is |
|---|---|---|---|---|
| sample | 0 | rows 0..3, columns 0..3 | 0x03 | A pad with a sample. Pad number = row x 4 + column + 1. |
| samtempl | 0 | rows 0..3, columns 0..4 | 0x4C | An empty pad (its settings template); also every column-4 cell. |
| asset | 0 | - | 0x01 | A multisample zone of the pad asssrcrow / asssrccol (not seen in the presets checked). |
| noteseq | 1 | rows 0..3, columns 0..4, seqsublayer 0..3 | 0x47 | A pad's sequence (4 per cell). |
| section | 2 | rows 0..31, column 0 | 0x4E | Song sections / scenes (32). |
| delay | 3 | row 0 | 0x26 | The delay effect. |
| reverb | 3 | row 1 | 0x4B | The reverb effect. |
| eq | 3 | row 2 | 0x36 | The EQ effect (4 bands). |
| filter | 3 | row 2 | 0x37 | The filter effect (in place of eq in some presets). |
| bitcrusher | 3 | row 3 | - | Bitcrusher effect; written with <params/>. |
| null | 3 | rows 3..4 | - | An empty effect slot; <params/>. |
| song | (none) | (none) | 0x1F | The preset's tempo, swing, key and song settings (one cell). |

## Parameters (attributes of `<params>`)

Stored values are integers. Lists store the item's index (0 = first). Buttons store 0 / 1. Synb0x column: Yes = as stock, Changed = label / list / meaning changed, No = not registered.

| ID | XML attribute | Label (S.1) | Kind | Stored as | Min | Max | List items | Stock | S.1 | Default (sample pad, S.1) | Meaning (Synb0x) / notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0x002 | level | Level: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x004 | gaindb | Level: | Number | Decibels: stored x1000, shown with one decimal (9300 = +9.3 dB) | -96000 | 12000 |  | Yes | Yes | 0 | Level in milli-dB (9300 = +9.3 dB). |
| 0x005 | fxtrigmode | Trigger: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Gate; 1 ON | Yes | Yes |  |  |
| 0x006 | waveform | Waveform: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Saw; 1 Triangle; 2 Square; 3 Sine; 4 Noise | Yes | Yes |  |  |
| 0x007 | waveform2 | Waveform: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Saw; 1 Triangle; 2 Square; 3 Sine; 4 Noise | Yes | Yes |  |  |
| 0x008 | lfowave | Waveform: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Saw; 1 Rev Saw; 2 Triangle; 3 Pos Tri; 4 Sine; 5 Pos Sine; 6 Square; 7 Pos Square; 8 Random | Yes | Yes | 0 |  |
| 0x009 | lforate | Rate: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes | 100 |  |
| 0x00a | lforatebeatsync | Rate: | List | List: stored as the item's index, 0 = the first item |  |  | 0 8 bars; 1 4 bars; 2 2 bars; 3 1 bar; 4 1/2; 5 1/2T; 6 1/4; 7 1/4T; 8 1/8; 9 1/8T; 10 1/16; 11 1/16T; 12 1/32; 13 1/32T; 14 1/64 | Yes | Yes | 0 |  |
| 0x00b | lfoamount | Depth: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Changed | 1000 | LFO Depth: still registered and saved, but the knob is removed and the LFO runs at 100 % whatever the stored value (each route's amount sets how far it moves its destination). |
| 0x00c | lfobeatsync | Beat Sync: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes | 0 |  |
| 0x00d | lfokeytrig | Trig | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes | 0 |  |
| 0x00e | cutoff | Cutoff: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x010 | cutoffFx | Cutoff: | Number | Frequency: the stored position through the stock cutoff curve, shown in Hz / kHz | 0 | 1000 |  | Yes | Yes |  |  |
| 0x011 | res | Res: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Changed | 500 | Resonance: below noon a flat, no-peak filter (Q 0.707) up to the stock noon value; from about 93 % the filter self-oscillates (gently, in tune). |
| 0x012 | filtertype | Type: | List | List: stored as the item's index, 0 = the first item |  |  | 0 LP; 1 HP; 2 BP; 3 Notch | Yes | Yes |  |  |
| 0x013 | wet | Wet/Dry: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x014 | amount | Amount: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x016 | bitdepth | Bit Depth: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x017 | ratereduc | Rate Reduc: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x018 | fxalgolivea | FX A: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Repeater; 1 Gater; 2 Filter | Yes | Yes |  |  |
| 0x019 | fxalgoliveb | FX B: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Crusher; 1 Filter; 2 Echo; 3 EchoHP; 4 Flanger; 5 Echo2 | Yes | Yes |  |  |
| 0x01c | repeatlen | Length: | List | List: stored as the item's index, 0 = the first item |  |  | 0 1/4; 1 1/8; 2 1/16; 3 1/32 | Yes | Yes |  |  |
| 0x01d | gaterlen | Length: | List | List: stored as the item's index, 0 = the first item |  |  | 0 1/4; 1 1/8; 2 1/16; 3 1/32 | Yes | Yes |  |  |
| 0x01e | gaterduty | Duty: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x01f | duckattack | Attack: | Number | Milliseconds (shown 'n ms') | 0 | 200 |  | Yes | Yes |  |  |
| 0x020 | duckhold | Hold: | Number | Milliseconds (shown 'n ms') | 0 | 5000 |  | Yes | Yes |  |  |
| 0x021 | duckrelease | Release: | Number | Milliseconds (shown 'n ms') | 0 | 5000 |  | Yes | Yes |  |  |
| 0x022 | duckdepth | Depth: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x023 | ducktrig | Trigger: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Clock; 1 Audio; 2 MIDI; 3 CV | Yes | Yes |  |  |
| 0x024 | duckclkdiv | Division: | List | List: stored as the item's index, 0 = the first item |  |  | 0 1/16; 1 1/8; 2 1/4 | Yes | Yes |  |  |
| 0x025 | duckaudin | Input: | Number | Integer (shown as a number; the knob may add a fixed offset) | 0 | 11 |  | Yes | Yes |  |  |
| 0x026 | duckthresh | Threshold: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x027 | duckmidinote | Note: | Number | Integer (shown as a number; the knob may add a fixed offset) | 0 | 127 |  | Yes | Yes |  |  |
| 0x028 | duckmidich | Channel: | Number | Integer (shown as a number; the knob may add a fixed offset) | 1 | 16 |  | Yes | Yes |  |  |
| 0x029 | duckcvin | CV Input: | List | List: stored as the item's index, 0 = the first item |  |  | 0 CV 1; 1 CV 2; 2 CV 3; 3 CV 4 | Yes | Yes |  |  |
| 0x02a | duckbypass | Bypass: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x02b | flangphase | Phase: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x02c | flangfb | Feedback: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x02d | echodelay | Delay: | List | List: stored as the item's index, 0 = the first item |  |  | 0 1/2; 1 1/2T; 2 1/4; 3 1/4T; 4 1/8; 5 1/8T; 6 1/16; 7 1/16T; 8 1/32; 9 1/32T; 10 1/64 | Yes | Yes |  |  |
| 0x02e | echo2delay | Delay2: | List | List: stored as the item's index, 0 = the first item |  |  | 0 1/2; 1 1/4; 2 1/8; 3 1/16; 4 1/32; 5 1/64 | Yes | Yes |  |  |
| 0x02f | echofb | Feedback: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x030 | echohpf | HPF: | Number | Frequency: the stored position through the stock cutoff curve, shown in Hz / kHz | 0 | 1000 |  | Yes | Yes |  |  |
| 0x031 | slicepos | Slice Pos: | Number | Sample position: stored in sample frames (the registered 0..1000 is the knob's range, not the stored one) | 0 | 2147483647 |  | Yes | Yes |  |  |
| 0x032 | delay | Delay: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x033 | delaymustime | Delay: | List | List: stored as the item's index, 0 = the first item |  |  | 0 1/64; 1 1/32; 2 1/16; 3 1/8T; 4 1/16D; 5 1/8; 6 1/4T; 7 1/8D; 8 1/4; 9 1/2T; 10 1/2; 11 1 bar | Yes | Yes |  |  |
| 0x034 | dealybeatsync | Beat Sync: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x035 | delaypingpong | Ping | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x037 | decay | Decay: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x038 | feedback | Feedback: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x039 | feedback | Feedback: | Number | Percent -100.0..+100.0: stored x10 (-1000..1000) | -1000 | 1000 |  | Yes | Yes |  |  |
| 0x03a | damping | Damping: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x03b | predelay | Predelay: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x03c | envattack | Attack: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes | 0 |  |
| 0x03e | envdecay | Decay: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes | 0 |  |
| 0x03f | envsus | Sustain: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes | 1000 |  |
| 0x040 | envrel | Release: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes | 200 |  |
| 0x041 | distamt | Distortion: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x042 | distamount | Distortion: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x043 | passfreq | Frequency: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x044 | passres | Resolution: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x045 | quantsize | Quant Size: | List | List: stored as the item's index, 0 = the first item |  |  | 0 2 bars; 1 1 bar; 2 1/2; 3 1/2T; 4 1/4; 5 1/4T; 6 1/8; 7 1/8T; 8 1/16; 9 1/16T; 10 1/32; 11 1/32T; 12 1/64 | Yes | Yes |  |  |
| 0x046 | quantsizeseq | Quant Size: | List | List: stored as the item's index, 0 = the first item |  |  | 0 2 bars; 1 1 bar; 2 1/2; 3 1/2T; 4 1/4; 5 1/4T; 6 1/8; 7 1/8T; 8 1/16; 9 1/16T; 10 1/32; 11 1/32T; 12 1/64 | Yes | Yes |  |  |
| 0x047 | quantsize | Quant Size: | List | List: stored as the item's index, 0 = the first item |  |  | 0 8 bars; 1 4 bars; 2 2 bars; 3 1 bar; 4 1/2; 5 1/4; 6 1/8; 7 1/16; 8 None | Yes | Yes | 3 |  |
| 0x048 | steplen | Length: | List | List: stored as the item's index, 0 = the first item |  |  | 0 2 bars; 1 1 bar; 2 1/2; 3 1/2T; 4 1/4; 5 1/4T; 6 1/8; 7 1/8T; 8 1/16; 9 1/16T; 10 1/32; 11 1/32T; 12 1/64 | Yes | Yes |  |  |
| 0x049 | dutycyc | Duty Cycle: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x04a | seqenable | Sequencer: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x04b | seqkeytrig | Key Trig: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x04c | seqquant | Quantize: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x04d | slicemode | Slice Mode: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes | 0 |  |
| 0x04e | actslice | Slice: | Number | Integer (shown as a number; the knob may add a fixed offset) | 1 | 128 |  | Yes | Yes | 1 |  |
| 0x052 | modamt | Amount: | Number | Percent -100.0..+100.0: stored x10 (-1000..1000) | -1000 | 1000 |  | Yes | Yes |  |  |
| 0x053 | modsource | Source: | List | List: stored as the item's index, 0 = the first item |  |  | 0 none; 1 VEL; 2 LFO; 3 PTCH; 4 MODW; 5 MVOL; 6 MPAN; 7 CC; 8 KEY; 9 FENV; 10 AD; 11 OSC | Yes | Changed |  | Source list adds KEY (src 'key'), FENV ('env1', the filter envelope), AD ('env2', the AD envelope), OSC ('env3', the pad's oscillator). |
| 0x054 | modfxsource | Source: | List | List: stored as the item's index, 0 = the first item |  |  | 0 none; 1 PTCH; 2 MODW; 3 MVOL; 4 MPAN; 5 CC | Yes | Yes |  |  |
| 0x055 | mod1vomode | 1V/Octave: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x056 | pitchin | Pitch In: | Number | Integer (shown as a number; the knob may add a fixed offset) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x057 | grainsize | Grain Size: | List | List: stored as the item's index, 0 = the first item |  |  | 0 1024; 1 2048; 2 4096; 3 8192; 4 16384 | Yes | Yes |  |  |
| 0x058 | graincount | Grain Count: | Number | Integer (shown as a number; the knob may add a fixed offset) | 2 | 8 |  | Yes | Yes |  |  |
| 0x059 | gainspreadten | Spread: | List | List: stored as the item's index, 0 = the first item |  |  | 0 0; 1 1; 2 2; 3 3; 4 4; 5 5; 6 6; 7 7; 8 8; 9 9; 10 10; 11 11; 12 13; 13 14; 14 15; 15 17; 16 19; 17 21; 18 23; 19 25; 20 28; 21 30; 22 34; 23 37; 24 41; 25 45; 26 49; 27 54; 28 60; 29 66; 30 72; 31 80; 32 88; 33 97; 34 106; 35 117; 36 129; 37 142; 38 156; 39 171; 40 189; 41 207; 42 228; 43 251; 44 276; 45 304; 46 334; 47 368; 48 405; 49 445; 50 490; 51 539; 52 593; 53 652; 54 717; 55 789; 56 868; 57 955; 58 1051; 59 1156; 60 1271; 61 1399; 62 1538; 63 1692 | Yes | Yes |  |  |
| 0x05b | gainssrcwin | Window: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes | 0 |  |
| 0x05c | pitch | Pitch: | Number | Semitones: stored x1000, shown with two decimals (12080 = +12.08 sem) | -24000 | 24000 |  | Yes | Yes | 0 | Pitch in 1/1000 semitone (-240 = -0.24 semitones). |
| 0x05d | grainreadspeed | Speed: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 2000 |  | Yes | Yes | 1000 |  |
| 0x060 | vinylmode | Mode: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Tape Stop; 1 Scratch; 2 Powerdown; 3 Backspin | Yes | Yes |  |  |
| 0x061 | carfreq | Carrier: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x062 | panpos | Pan: | Number | Percent -100.0..+100.0: stored x10 (-1000..1000) | -1000 | 1000 |  | Yes | Yes | 0 |  |
| 0x063 | seqsteps | Steps: | Number | Integer (shown as a number; the knob may add a fixed offset) | 2 | 32 |  | Yes | Yes |  |  |
| 0x065 | wavepos | WPos: | Number | Integer (shown as a number; the knob may add a fixed offset) | 0 | 255 |  | Yes | Yes |  |  |
| 0x066 | wavesel | WSel: | List | List: stored as the item's index, 0 = the first item |  |  | 0  | Yes | Yes |  |  |
| 0x067 | builddest |  | Number | Integer (shown as a number; the knob may add a fixed offset) | 0 | 1024 |  | Yes | Yes |  |  |
| 0x068 | oscphasereset | Osc Rst: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x069 | velamount | VEL Amount: | Number | Percent -100.0..+100.0: stored x10 (-1000..1000) | -1000 | 1000 |  | Yes | Yes |  |  |
| 0x06a | midimode | MIDI In: | List | List: stored as the item's index, 0 = the first item |  |  | 0 None; 1 Ch 1; 2 Ch 2; 3 Ch 3; 4 Ch 4; 5 Ch 5; 6 Ch 6; 7 Ch 7; 8 Ch 8; 9 Ch 9; 10 Ch 10; 11 Ch 11; 12 Ch 12; 13 Ch 13; 14 Ch 14; 15 Ch 15; 16 Ch 16 | Yes | Yes | 0 |  |
| 0x06b | midioutchan | MIDI Out: | List | List: stored as the item's index, 0 = the first item |  |  | 0 None; 1 Ch 1; 2 Ch 2; 3 Ch 3; 4 Ch 4; 5 Ch 5; 6 Ch 6; 7 Ch 7; 8 Ch 8; 9 Ch 9; 10 Ch 10; 11 Ch 11; 12 Ch 12; 13 Ch 13; 14 Ch 14; 15 Ch 15; 16 Ch 16 | Yes | Yes |  |  |
| 0x06c | reverse | Reverse: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes | 0 |  |
| 0x06d | flangeamount | Flanger: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x071 | midithrumodetype | MIDI Out: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Enabled; 1 MIDI In Thru; 2 USB Dvc Thru | Yes | Yes |  |  |
| 0x073 | midichan | MIDI Ch: | Number | Integer (shown as a number; the knob may add a fixed offset) | 1 | 16 |  | Yes | Yes |  |  |
| 0x074 | midiport | MIDI Port: | Number | Integer (shown as a number; the knob may add a fixed offset) | 1 | 4 |  | Yes | Yes |  |  |
| 0x075 | midibend | Bend Rng: | Number | Integer (shown as a number; the knob may add a fixed offset) | 1 | 12 |  | Yes | Yes |  |  |
| 0x076 | midiglobchan | Global In: | List | List: stored as the item's index, 0 = the first item |  |  | 0 None; 1 Ch 1; 2 Ch 2; 3 Ch 3; 4 Ch 4; 5 Ch 5; 6 Ch 6; 7 Ch 7; 8 Ch 8; 9 Ch 9; 10 Ch 10; 11 Ch 11; 12 Ch 12; 13 Ch 13; 14 Ch 14; 15 Ch 15; 16 Ch 16; 17 Omni | Yes | Yes |  |  |
| 0x078 | midikeysglobchan | MIDI Keys: | List | List: stored as the item's index, 0 = the first item |  |  | 0 None; 1 Ch 1; 2 Ch 2; 3 Ch 3; 4 Ch 4; 5 Ch 5; 6 Ch 6; 7 Ch 7; 8 Ch 8; 9 Ch 9; 10 Ch 10; 11 Ch 11; 12 Ch 12; 13 Ch 13; 14 Ch 14; 15 Ch 15; 16 Ch 16 | Yes | Yes |  |  |
| 0x079 | midiseqglobchan | MIDI Seq: | List | List: stored as the item's index, 0 = the first item |  |  | 0 None; 1 Ch 1; 2 Ch 2; 3 Ch 3; 4 Ch 4; 5 Ch 5; 6 Ch 6; 7 Ch 7; 8 Ch 8; 9 Ch 9; 10 Ch 10; 11 Ch 11; 12 Ch 12; 13 Ch 13; 14 Ch 14; 15 Ch 15; 16 Ch 16 | Yes | Yes |  |  |
| 0x07a | midiseqcellchan | MIDI Out: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Ch 1; 1 Ch 2; 2 Ch 3; 3 Ch 4; 4 Ch 5; 5 Ch 6; 6 Ch 7; 7 Ch 8; 8 Ch 9; 9 Ch 10; 10 Ch 11; 11 Ch 12; 12 Ch 13; 13 Ch 14; 14 Ch 15; 15 Ch 16 | Yes | Yes |  |  |
| 0x07b | midiusbouten | USB Dev Out: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Disabled; 1 Enabled | Yes | Yes |  |  |
| 0x07c | outputmode | Out Mode: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Stereo Mix; 1 Voice x 4 | Yes | Yes |  |  |
| 0x07d | controlmode | Ctrl Mode: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Global; 1 Per Voice | Yes | Yes |  |  |
| 0x07f | scrbrightness | Brightness: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x080 | scrbrightfine | Bright Fine: | Number | Percent -100.0..+100.0: stored x10 (-1000..1000) | -1000 | 1000 |  | Yes | Yes |  |  |
| 0x082 | pitchtrans | 1V/O Trans: | Number | Integer (shown as a number; the knob may add a fixed offset) | -48 | 48 |  | Yes | Yes |  |  |
| 0x083 | trigsrc | Clk Source: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Int; 1 EXT1; 2 EXT2; 3 EXT3; 4 GATE1; 5 GATE2; 6 GATE3; 7 GATE4; 8 None | Yes | Yes |  |  |
| 0x084 | globtempo | BPM: | Number | Integer (shown as a number; the knob may add a fixed offset) | 40 | 250 |  | Yes | Yes |  |  |
| 0x085 | notesteplen | Step Len: | List | List: stored as the item's index, 0 = the first item |  |  | 0 8 bars; 1 4 bars; 2 2 bars; 3 1 bar; 4 1/2; 5 1/2T; 6 1/4; 7 1/4T; 8 1/8; 9 1/8T; 10 1/16; 11 1/16T; 12 1/32; 13 1/32T; 14 1/64 | Yes | Yes |  |  |
| 0x086 | notestepcount | Step Count: | Number | Integer (shown as a number; the knob may add a fixed offset) | 1 | 256 |  | Yes | Yes |  |  |
| 0x087 | notetrans | Transpose: | Number | Integer (shown as a number; the knob may add a fixed offset) | -48 | 48 |  | Yes | Yes |  |  |
| 0x088 | seqstepmode | Step Mode: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x089 | keymode | Scale: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Chromatic; 1 Major; 2 Major Pent; 3 Minor; 4 Minor Pent; 5 Minor Blues; 6 Raga Bhairav; 7 Raga Todi; 8 Gypsy; 9 Arabian; 10 Egyptian; 11 Miyakobushi; 12 Ryukyu; 13 Wholetone; 14 Diminish; 15 Harmonic Minor; 16 Mel Minor; 17 Dorian; 18 Phrygian; 19 Lydian; 20 Mixolydian; 21 Aeolian; 22 Locrian | Yes | Yes |  |  |
| 0x08a | keyroot | Root Note: | List | List: stored as the item's index, 0 = the first item |  |  | 0 A; 1 A#; 2 B; 3 C; 4 C#; 5 D; 6 D#; 7 E; 8 F; 9 F#; 10 G; 11 G# | Yes | Yes |  |  |
| 0x08b | cellmode | Pad Mode: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Sample; 1 Clip; 2 Slicer; 3 Granular; 4 New Rec; 5 New Multi | Yes | Yes | 0 | Pad mode: 0 Sample, 1 Clip, 2 Slicer, 3 Granular (see its list). |
| 0x08c | cellmodeshort | Pad Mode: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Sample; 1 Clip; 2 Slicer; 3 Granular; 4 New Rec | Yes | Yes |  |  |
| 0x08d | loopmode | Loop Mode: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes | 0 |  |
| 0x08e | loopmodes | Loop Mode: | List | List: stored as the item's index, 0 = the first item |  |  | 0 None; 1 Forward; 2 Bidirect | Yes | Yes | 0 |  |
| 0x08f | samstart | Start: | Number | Sample position: stored in sample frames (the registered 0..1000 is the knob's range, not the stored one) | 0 | 1000 |  | Yes | Yes | 0 | Sample frames from the WAV's start (not 0..1000). |
| 0x090 | samlen | Length: | Number | Sample position: stored in sample frames (the registered 0..1000 is the knob's range, not the stored one) | 0 | 1000 |  | Yes | Yes | 0 | Sample frames. |
| 0x091 | loopstart | Loop Start: | Number | Sample position: stored in sample frames (the registered 0..1000 is the knob's range, not the stored one) | 0 | 1000 |  | Yes | Yes | 0 | Sample frames from the WAV's start (absolute, not relative to samstart). |
| 0x092 | loopend | Loop End: | Number | Sample position: stored in sample frames (the registered 0..1000 is the knob's range, not the stored one) | 0 | 1000 |  | Yes | Yes | 0 | Sample frames from the WAV's start (absolute). |
| 0x093 | samtrigtype | Launch Mode: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Trigger; 1 Gate; 2 Toggle | Yes | Yes | 0 |  |
| 0x094 | synctype | Sync: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Slice; 1 1 bar; 2 1/2; 3 1/4; 4 1/8; 5 1/16; 6 None | Yes | Yes | 5 |  |
| 0x095 | outputbus | Output: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Out1; 1 Out2; 2 Out3; 3 Out1L; 4 Out1R; 5 Out2L; 6 Out2R; 7 Out3L; 8 Out3R | Yes | Yes | 0 |  |
| 0x096 | uiflip | Flip UI: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x097 | recpresetlen | Length: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Custom; 1 1/4; 2 1/2; 3 1 bar; 4 2 bars; 5 4 bars; 6 8 bars; 7 16 bars; 8 32 bars; 9 64 bars; 10 128 bars | Yes | Yes | 0 |  |
| 0x098 | recquant | Rec Quant: | List | List: stored as the item's index, 0 = the first item |  |  | 0 8 bars; 1 4 bars; 2 2 bars; 3 1 bar; 4 1/2; 5 1/4; 6 1/8; 7 1/16; 8 None | Yes | Yes | 3 |  |
| 0x099 | recmonmode | Rec Mon: | List | List: stored as the item's index, 0 = the first item |  |  | 0 On; 1 Auto; 2 Off | Yes | Yes |  |  |
| 0x09a | recinput | Rec Input: | List | List: stored as the item's index, 0 = the first item |  |  | 0 L+R; 1 Left; 2 Right; 3 Resam | Yes | Yes | 0 |  |
| 0x09b | recinputmulti | Rec Input: | List | List: stored as the item's index, 0 = the first item |  |  | 0 L+R; 1 Left; 2 Right | Yes | Yes |  |  |
| 0x09c | recactive | Rec Active: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x09d | recautoplay | RecToPlay: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x09f | monomode | Mono Mode: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Poly; 1 Mono | Yes | Yes |  |  |
| 0x0a0 | polymode | Poly Mode: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Mono; 1 Poly 2; 2 Poly 4; 3 Poly 6; 4 Poly 8; 5 Poly X | Yes | Yes | 0 |  |
| 0x0a1 | polymodeslice | Poly Mode: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Mono; 1 Poly 2 | Yes | Yes | 0 |  |
| 0x0a2 | slicestepmode | Slice Seq: | List | List: stored as the item's index, 0 = the first item |  |  | 0 None; 1 Forward; 2 Backwards; 3 Random; 4 Stagger | Yes | Yes | 0 |  |
| 0x0a3 | toolcellmode | Cell Mode: | List | List: stored as the item's index, 0 = the first item |  |  | 0 GATE; 1 NOTE; 2 LFO; 3 SEQ; 4 CPLY; 5 CREC; 6 OUT | Yes | Yes |  |  |
| 0x0a4 | toolcellmodealt | Cell Mode: | List | List: stored as the item's index, 0 = the first item |  |  | 0 (none); 1 GATE; 2 NOTE | Yes | Yes |  |  |
| 0x0a6 | cvplayrate | Play Rate: | Number | Percent -100.0..+100.0: stored x10 (-1000..1000) | -1000 | 1000 |  | Yes | Yes |  |  |
| 0x0a7 | tooltrigmode | LaunchMode: | List | List: stored as the item's index, 0 = the first item |  |  | 0 AlwaysOn; 1 Trigger; 2 Gate | Yes | Yes |  |  |
| 0x0a8 | cvplayamt | Amount: | Number | Percent -100.0..+100.0: stored x10 (-1000..1000) | -1000 | 1000 |  | Yes | Yes |  |  |
| 0x0ab | boxcellmode | Cell Mode: | List | List: stored as the item's index, 0 = the first item |  |  | 0 PATXYZ; 1 PATRAZ; 2 WAVE; 3 LIVE; 4 None; 5 None; 6 None; 7 None; 8 None; 9 None; 10 None; 11 None; 12 None; 13 None; 14 None; 15 None; 16 None | Yes | Yes |  |  |
| 0x0ad | fxchainain | Chain A: | Number | Integer (shown as a number; the knob may add a fixed offset) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x0ae | fxchainbin | Chain B: | Number | Integer (shown as a number; the knob may add a fixed offset) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x0b4 | globcomp | Compressor: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x0b5 | gridcount | Slices: | Number | Integer (shown as a number; the knob may add a fixed offset) | 2 | 128 |  | Yes | Yes |  |  |
| 0x0b6 | scanthres | Threshold: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x0b7 | dispmode | DispMode: | List | List: stored as the item's index, 0 = the first item |  |  | 0 PADS; 1 KEYS; 2 MIDI | Yes | Yes |  |  |
| 0x0b9 | seqpadmapdest | Play Pad: | Number | Integer (shown as a number; the knob may add a fixed offset) | 0 | 15 |  | Yes | Yes |  |  |
| 0x0ba | headphvol | Headphone: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x0bb | out1vol | Out 1 Vol: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x0bc | out2vol | Out 2 Vol: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x0bd | out3vol | Out 3 Vol: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x0be | seqplayenable | PlayMode: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  | Registered with range 0..0, but presets store 0 / 1. |
| 0x0bf | songmode | SongMode: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x0c0 | activeseqlayer | Seq Layer: | Number | Integer (shown as a number; the knob may add a fixed offset) | 0 | 4 |  | Yes | Yes |  |  |
| 0x0c1 | sectcount | SectCount: | Number | Integer (shown as a number; the knob may add a fixed offset) | 1 | 32 |  | Yes | Yes |  |  |
| 0x0c2 | sectloop | SectLoop: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x0c3 | sectionrepeats | Play Count: | Number | Integer (shown as a number; the knob may add a fixed offset) | 1 | 32 |  | Yes | Yes |  |  |
| 0x0c4 | chokegrp | Excl Group: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Excl X; 1 Excl A; 2 Excl B; 3 Excl C; 4 Excl D | Yes | Yes | 0 |  |
| 0x0c8 | dualfilcutoff | Filter: | Number | Percent -100.0..+100.0: stored x10 (-1000..1000) | -1000 | 1000 |  | Yes | Changed | 1000 | Filter cutoff across the knob's whole travel: -1000 = 20 Hz .. +1000 = 20.5 kHz (shown 0..100 %). New pads default to 1000 (fully open); stock defaults to 0. |
| 0x0c9 | filtenable | Filter: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x0ca | filtquality | Width: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x0cb | filtparallel | Mode: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Serial; 1 Parallel | Yes | Yes |  |  |
| 0x0cc | defvel | Velocity | Number | Integer (shown as a number; the knob may add a fixed offset) | 1 | 128 |  | Yes | Yes |  |  |
| 0x0cd | metroopts | Metronome: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Off; 1 Rec; 2 Play | Yes | Yes |  |  |
| 0x0ce | recthresh | Threshold: | Number | Decibels: stored x1000, shown with one decimal (9300 = +9.3 dB) | -96000 | 0 |  | Yes | Yes | -20000 |  |
| 0x0cf | recusethres | RecThresh: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes | 0 |  |
| 0x0d0 | rootnote | Root Note: | List | List: stored as the item's index, 0 = the first item |  |  | 0 None; 1 C#-1 (1); 2 D-1 (2); 3 D#-1 (3); 4 E-1 (4); 5 F-1 (5); 6 F#-1 (6); 7 G-1 (7); 8 G#-1 (8); 9 A-1 (9); 10 A#-1 (10); 11 B-1 (11); 12 C0 (12); 13 C#0 (13); 14 D0 (14); 15 D#0 (15); 16 E0 (16); 17 F0 (17); 18 F#0 (18); 19 G0 (19); 20 G#0 (20); 21 A0 (21); 22 A#0 (22); 23 B0 (23); 24 C1 (24); 25 C#1 (25); 26 D1 (26); 27 D#1 (27); 28 E1 (28); 29 F1 (29); 30 F#1 (30); 31 G1 (31); 32 G#1 (32); 33 A1 (33); 34 A#1 (34); 35 B1 (35); 36 C2 (36); 37 C#2 (37); 38 D2 (38); 39 D#2 (39); 40 E2 (40); 41 F2 (41); 42 F#2 (42); 43 G2 (43); 44 G#2 (44); 45 A2 (45); 46 A#2 (46); 47 B2 (47); 48 C3 (48); 49 C#3 (49); 50 D3 (50); 51 D#3 (51); 52 E3 (52); 53 F3 (53); 54 F#3 (54); 55 G3 (55); 56 G#3 (56); 57 A3 (57); 58 A#3 (58); 59 B3 (59); 60 C4 (60); 61 C#4 (61); 62 D4 (62); 63 D#4 (63) | Yes | Yes | 0 | MIDI note (60 = C3 on the Blackbox). |
| 0x0d2 | beatcount | Beat Count: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Auto; 1 1; 2 2; 3 3; 4 4; 5 5; 6 6; 7 7; 8 8; 9 9; 10 10; 11 11; 12 12; 13 13; 14 14; 15 15; 16 16; 17 17; 18 18; 19 19; 20 20; 21 21; 22 22; 23 23; 24 24; 25 25; 26 26; 27 27; 28 28; 29 29; 30 30; 31 31; 32 32; 33 33; 34 34; 35 35; 36 36; 37 37; 38 38; 39 39; 40 40; 41 41; 42 42; 43 43; 44 44; 45 45; 46 46; 47 47; 48 48; 49 49; 50 50; 51 51; 52 52; 53 53; 54 54; 55 55; 56 56; 57 57; 58 58; 59 59; 60 60; 61 61; 62 62; 63 63 | Yes | Yes | 0 |  |
| 0x0d3 | midircvprogchng | PGM In: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x0d5 | reccountdown | Lead In: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x0d6 | seqblank | SeqBlank: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x0d7 | swing | Swing: | Number | Integer (shown as a number; the knob may add a fixed offset) | 1 | 99 |  | Yes | Yes |  |  |
| 0x0d8 | ingain | Gain: | Number | Decibels: stored x1000, shown with one decimal (9300 = +9.3 dB) | -96000 | 20000 |  | Yes | Yes |  |  |
| 0x0d9 | fx1send | FX1 Send: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes | 0 |  |
| 0x0da | fx2send | FX2 Send: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes | 0 |  |
| 0x0db | overdrive | Saturation: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Changed | 0 | Labelled 'Saturation:'. A soft-clip saturation with warmth and a darkening tone in place of the stock overdrive curve (same stored value). In a Fidelity machine mode it is the converter's input drive. |
| 0x0dc | recmonoutbus | Mon Output: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Out1; 1 Out2; 2 Out3; 3 Out1L; 4 Out1R; 5 Out2L; 6 Out2R; 7 Out3L; 8 Out3R | Yes | Yes | 0 |  |
| 0x0dd | recmonmultioutbus | Mon Output: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Out2; 1 Out3; 2 Out1L; 3 Out1R; 4 Out2L; 5 Out2R; 6 Out3L; 7 Out3R | Yes | Yes |  |  |
| 0x0df | deftemplate | Default Template: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x0e1 | recparmsperpad | RecConfig: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Global; 1 Per Pad | Yes | Yes |  |  |
| 0x0e2 | midikeyrec | Pad Record: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x0e3 | keyrangebottom | Low Note: | List | List: stored as the item's index, 0 = the first item |  |  | 0 None; 1 C#-1 (1); 2 D-1 (2); 3 D#-1 (3); 4 E-1 (4); 5 F-1 (5); 6 F#-1 (6); 7 G-1 (7); 8 G#-1 (8); 9 A-1 (9); 10 A#-1 (10); 11 B-1 (11); 12 C0 (12); 13 C#0 (13); 14 D0 (14); 15 D#0 (15); 16 E0 (16); 17 F0 (17); 18 F#0 (18); 19 G0 (19); 20 G#0 (20); 21 A0 (21); 22 A#0 (22); 23 B0 (23); 24 C1 (24); 25 C#1 (25); 26 D1 (26); 27 D#1 (27); 28 E1 (28); 29 F1 (29); 30 F#1 (30); 31 G1 (31); 32 G#1 (32); 33 A1 (33); 34 A#1 (34); 35 B1 (35); 36 C2 (36); 37 C#2 (37); 38 D2 (38); 39 D#2 (39); 40 E2 (40); 41 F2 (41); 42 F#2 (42); 43 G2 (43); 44 G#2 (44); 45 A2 (45); 46 A#2 (46); 47 B2 (47); 48 C3 (48); 49 C#3 (49); 50 D3 (50); 51 D#3 (51); 52 E3 (52); 53 F3 (53); 54 F#3 (54); 55 G3 (55); 56 G#3 (56); 57 A3 (57); 58 A#3 (58); 59 B3 (59); 60 C4 (60); 61 C#4 (61); 62 D4 (62); 63 D#4 (63) | Yes | Yes |  |  |
| 0x0e4 | keyrangetop | High Note: | List | List: stored as the item's index, 0 = the first item |  |  | 0 None; 1 C#-1 (1); 2 D-1 (2); 3 D#-1 (3); 4 E-1 (4); 5 F-1 (5); 6 F#-1 (6); 7 G-1 (7); 8 G#-1 (8); 9 A-1 (9); 10 A#-1 (10); 11 B-1 (11); 12 C0 (12); 13 C#0 (13); 14 D0 (14); 15 D#0 (15); 16 E0 (16); 17 F0 (17); 18 F#0 (18); 19 G0 (19); 20 G#0 (20); 21 A0 (21); 22 A#0 (22); 23 B0 (23); 24 C1 (24); 25 C#1 (25); 26 D1 (26); 27 D#1 (27); 28 E1 (28); 29 F1 (29); 30 F#1 (30); 31 G1 (31); 32 G#1 (32); 33 A1 (33); 34 A#1 (34); 35 B1 (35); 36 C2 (36); 37 C#2 (37); 38 D2 (38); 39 D#2 (39); 40 E2 (40); 41 F2 (41); 42 F#2 (42); 43 G2 (43); 44 G#2 (44); 45 A2 (45); 46 A#2 (46); 47 B2 (47); 48 C3 (48); 49 C#3 (49); 50 D3 (50); 51 D#3 (51); 52 E3 (52); 53 F3 (53); 54 F#3 (54); 55 G3 (55); 56 G#3 (56); 57 A3 (57); 58 A#3 (58); 59 B3 (59); 60 C4 (60); 61 C#4 (61); 62 D4 (62); 63 D#4 (63) | Yes | Yes |  |  |
| 0x0e5 | velrangebottom | Low Vel: | Number | Integer (shown as a number; the knob may add a fixed offset) | 0 | 127 |  | Yes | Yes |  |  |
| 0x0e6 | velrangetop | High Vel: | Number | Integer (shown as a number; the knob may add a fixed offset) | 0 | 127 |  | Yes | Yes |  |  |
| 0x0e7 | velroot | Vel Root: | Number | Integer (shown as a number; the knob may add a fixed offset) | 0 | 127 |  | Yes | Yes |  |  |
| 0x0e8 | asssrcrow | SourceRow: | Number | Integer (shown as a number; the knob may add a fixed offset) | 0 | 3 |  | Yes | Yes |  |  |
| 0x0e9 | asssrccol | SourceCol: | Number | Integer (shown as a number; the knob may add a fixed offset) | 0 | 3 |  | Yes | Yes |  |  |
| 0x0ea | multisammode | MultiSam: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes | 0 |  |
| 0x0ef | midiclkrcv | Receive: | List | List: stored as the item's index, 0 = the first item |  |  | 0 All; 1 USB Device; 2 MIDI In; 3 Off | Yes | Yes |  |  |
| 0x0f0 | midiclksnd | Send: | List | List: stored as the item's index, 0 = the first item |  |  | 0 All; 1 USB Device; 2 MIDI Out; 3 Off | Yes | Yes |  |  |
| 0x0f1 | interpqual | Fidelity: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Normal; 1 HighQ; 2 SP1200; 3 SP-12; 4 S950; 5 MPC60; 6 SP Raw; 7 16k; 8 12k; 9 10k; 10 8k; 11 6k; 12 4k; 13 2k | Yes | Changed | 0 | Labelled 'Fidelity:'. 0 Normal, 1 HighQ (as stock), then the machine modes 2 SP1200, 3 SP-12, 4 S950, 5 MPC60, 6 SP Raw, then the fixed-rate crunches 7 16k, 8 12k, 9 10k, 10 8k, 11 6k, 12 4k, 13 2k. Granular pads: HighQ = the stock 4-point interpolation, every other value = 2-point (cheaper). |
| 0x0f2 | playthru | PlayThru: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes | 0 |  |
| 0x0f3 | slicerquantsize | Quant Size: | List | List: stored as the item's index, 0 = the first item |  |  | 0 2 bars; 1 1 bar; 2 1/2; 3 1/2T; 4 1/4; 5 1/4T; 6 1/8; 7 1/8T; 8 1/16; 9 1/16T; 10 1/32; 11 1/32T; 12 1/64; 13 None | Yes | Yes | 13 |  |
| 0x0f4 | slicersync | Sync: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes | 0 |  |
| 0x0f5 | padnote | Pad Note: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Default; 1 C#-1; 2 D-1; 3 D#-1; 4 E-1; 5 F-1; 6 F#-1; 7 G-1; 8 G#-1; 9 A-1; 10 A#-1; 11 B-1; 12 C0; 13 C#0; 14 D0; 15 D#0; 16 E0; 17 F0; 18 F#0; 19 G0; 20 G#0; 21 A0; 22 A#0; 23 B0; 24 C1; 25 C#1; 26 D1; 27 D#1; 28 E1; 29 F1; 30 F#1; 31 G1; 32 G#1; 33 A1; 34 A#1; 35 B1; 36 C2; 37 C#2; 38 D2; 39 D#2; 40 E2; 41 F2; 42 F#2; 43 G2; 44 G#2; 45 A2; 46 A#2; 47 B2; 48 C3; 49 C#3; 50 D3; 51 D#3; 52 E3; 53 F3; 54 F#3; 55 G3; 56 G#3; 57 A3; 58 A#3; 59 B3; 60 C4; 61 C#4; 62 D4; 63 D#4 | Yes | Yes | 0 |  |
| 0x0f6 | metoutbus | Metro Out: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Out1; 1 Out2; 2 Out3; 3 Out1L; 4 Out1R; 5 Out2L; 6 Out2R; 7 Out3L; 8 Out3R; 9 HP | Yes | Yes |  |  |
| 0x0f7 | metgain | Metro Gain: | Number | Decibels: stored x1000, shown with one decimal (9300 = +9.3 dB) | -96000 | 20000 |  | Yes | Yes |  |  |
| 0x0f8 | inputiocon | Input: | List | List: stored as the item's index, 0 = the first item |  |  | 0 GATE; 1 CV; 2 CLK; 3 AUDIO | Yes | Yes |  |  |
| 0x0f9 | outputiocon | Output: | List | List: stored as the item's index, 0 = the first item |  |  | 0 OUT 1; 1 OUT 2; 2 OUT 3; 3 OUT 4; 4 OUT 5; 5 OUT 6; 6 OUT 7; 7 OUT 8; 8 OUT 1+FX; 9 OUT 2+FX | Yes | Yes |  |  |
| 0x0fa | loopfadeamt | Loop Fade: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes | 0 | Loop Fade 0..1000: the last (loop length x value / 1000) frames of the loop crossfade into the audio before the loop start (capped at the loop start); linear; forward loops. |
| 0x0fb | mrstartnote | Start Note: | List | List: stored as the item's index, 0 = the first item |  |  | 0 C-1 (0); 1 C#-1 (1); 2 D-1 (2); 3 D#-1 (3); 4 E-1 (4); 5 F-1 (5); 6 F#-1 (6); 7 G-1 (7); 8 G#-1 (8); 9 A-1 (9); 10 A#-1 (10); 11 B-1 (11); 12 C0 (12); 13 C#0 (13); 14 D0 (14); 15 D#0 (15); 16 E0 (16); 17 F0 (17); 18 F#0 (18); 19 G0 (19); 20 G#0 (20); 21 A0 (21); 22 A#0 (22); 23 B0 (23); 24 C1 (24); 25 C#1 (25); 26 D1 (26); 27 D#1 (27); 28 E1 (28); 29 F1 (29); 30 F#1 (30); 31 G1 (31); 32 G#1 (32); 33 A1 (33); 34 A#1 (34); 35 B1 (35); 36 C2 (36); 37 C#2 (37); 38 D2 (38); 39 D#2 (39); 40 E2 (40); 41 F2 (41); 42 F#2 (42); 43 G2 (43); 44 G#2 (44); 45 A2 (45); 46 A#2 (46); 47 B2 (47); 48 C3 (48); 49 C#3 (49); 50 D3 (50); 51 D#3 (51); 52 E3 (52); 53 F3 (53); 54 F#3 (54); 55 G3 (55); 56 G#3 (56); 57 A3 (57); 58 A#3 (58); 59 B3 (59); 60 C4 (60); 61 C#4 (61); 62 D4 (62); 63 D#4 (63) | Yes | Yes |  |  |
| 0x0fc | mrendnote | End Note: | List | List: stored as the item's index, 0 = the first item |  |  | 0 C-1 (0); 1 C#-1 (1); 2 D-1 (2); 3 D#-1 (3); 4 E-1 (4); 5 F-1 (5); 6 F#-1 (6); 7 G-1 (7); 8 G#-1 (8); 9 A-1 (9); 10 A#-1 (10); 11 B-1 (11); 12 C0 (12); 13 C#0 (13); 14 D0 (14); 15 D#0 (15); 16 E0 (16); 17 F0 (17); 18 F#0 (18); 19 G0 (19); 20 G#0 (20); 21 A0 (21); 22 A#0 (22); 23 B0 (23); 24 C1 (24); 25 C#1 (25); 26 D1 (26); 27 D#1 (27); 28 E1 (28); 29 F1 (29); 30 F#1 (30); 31 G1 (31); 32 G#1 (32); 33 A1 (33); 34 A#1 (34); 35 B1 (35); 36 C2 (36); 37 C#2 (37); 38 D2 (38); 39 D#2 (39); 40 E2 (40); 41 F2 (41); 42 F#2 (42); 43 G2 (43); 44 G#2 (44); 45 A2 (45); 46 A#2 (46); 47 B2 (47); 48 C3 (48); 49 C#3 (49); 50 D3 (50); 51 D#3 (51); 52 E3 (52); 53 F3 (53); 54 F#3 (54); 55 G3 (55); 56 G#3 (56); 57 A3 (57); 58 A#3 (58); 59 B3 (59); 60 C4 (60); 61 C#4 (61); 62 D4 (62); 63 D#4 (63) | Yes | Yes |  |  |
| 0x0fd | mrstride | Sample Every: | Number | Integer (shown as a number; the knob may add a fixed offset) | 1 | 16 |  | Yes | Yes |  |  |
| 0x0fe | mrvellayers | Vel Layers: | Number | Integer (shown as a number; the knob may add a fixed offset) | 1 | 16 |  | Yes | Yes |  |  |
| 0x0ff | mrmaxvel | Max Vel: | Number | Integer (shown as a number; the knob may add a fixed offset) | 1 | 127 |  | Yes | Yes |  |  |
| 0x100 | mrnotelen | Note Length: | Number | Integer (shown as a number; the knob may add a fixed offset) | 1 | 60 |  | Yes | Yes |  |  |
| 0x101 | mrrellen | Release Len: | Number | Integer (shown as a number; the knob may add a fixed offset) | 1 | 15 |  | Yes | Yes |  |  |
| 0x106 | mrecmidich | MIDI Chan: | Number | Integer (shown as a number; the knob may add a fixed offset) | 1 | 16 |  | Yes | Yes |  |  |
| 0x108 | recfilename | Filename: | Number | Not shown as a knob value | 0 | 0 |  | Yes | Yes |  |  |
| 0x109 | mrecmode | Rec Type: | List | List: stored as the item's index, 0 = the first item |  |  | 0 1x; 1 Multi | Yes | Yes |  |  |
| 0x10a | miscctrltype | Gate Funct: | List | List: stored as the item's index, 0 = the first item |  |  | 0 None; 1 Record | Yes | Yes |  |  |
| 0x10d | evtvel | VEL: | Number | Integer (shown as a number; the knob may add a fixed offset) | 1 | 128 |  | Yes | Yes |  |  |
| 0x10e | evtcond | PLAY: | List | List: stored as the item's index, 0 = the first item |  |  | 0 ALWAYS; 1 1%; 2 2%; 3 3%; 4 4%; 5 5%; 6 6%; 7 7%; 8 8%; 9 9%; 10 10%; 11 11%; 12 12%; 13 13%; 14 14%; 15 15%; 16 16%; 17 17%; 18 18%; 19 19%; 20 20%; 21 21%; 22 22%; 23 23%; 24 24%; 25 25%; 26 26%; 27 27%; 28 28%; 29 29%; 30 30%; 31 31%; 32 32%; 33 33%; 34 34%; 35 35%; 36 36%; 37 37%; 38 38%; 39 39%; 40 40%; 41 41%; 42 42%; 43 43%; 44 44%; 45 45%; 46 46%; 47 47%; 48 48%; 49 49%; 50 50%; 51 51%; 52 52%; 53 53%; 54 54%; 55 55%; 56 56%; 57 57%; 58 58%; 59 59%; 60 60%; 61 61%; 62 62%; 63 63% | Yes | Yes |  |  |
| 0x10f | clockinppq | Analog In: | List | List: stored as the item's index, 0 = the first item |  |  | 0 1 PPQ; 1 2 PPQ; 2 4 PPQ; 3 8 PPQ; 4 12 PPQ; 5 24 PPQ | Yes | Yes |  |  |
| 0x110 | clockoutppq | Analog Out: | List | List: stored as the item's index, 0 = the first item |  |  | 0 1 PPQ; 1 2 PPQ; 2 4 PPQ; 3 8 PPQ; 4 12 PPQ; 5 24 PPQ | Yes | Yes |  |  |
| 0x118 | eqgain | Gain: | Number | Decibels: stored x1000, shown with one decimal (9300 = +9.3 dB) | -24000 | 24000 |  | Yes | Yes |  |  |
| 0x119 | eqcutoff | Freq: | Number | Frequency: the stored position through the stock cutoff curve, shown in Hz / kHz | 0 | 1000 |  | Yes | Yes |  |  |
| 0x11a | eqres | Q: | Number | Resonance: the stored position through the stock Q curve, shown with one decimal | 0 | 1000 |  | Yes | Yes |  |  |
| 0x11b | eqenable | Enable: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x11c | eqtype | Type: | List | List (EQ band type): stored as the item's index |  |  | 0 None; 1 L Cut; 2 L Shelf; 3 Param; 4 H Shelf; 5 H Cut | Yes | Yes |  |  |
| 0x11d | eqgain2 | Gain: | Number | Decibels: stored x1000, shown with one decimal (9300 = +9.3 dB) | -24000 | 24000 |  | Yes | Yes |  |  |
| 0x11e | eqcutoff2 | Freq: | Number | Frequency: the stored position through the stock cutoff curve, shown in Hz / kHz | 0 | 1000 |  | Yes | Yes |  |  |
| 0x11f | eqres2 | Q: | Number | Resonance: the stored position through the stock Q curve, shown with one decimal | 0 | 1000 |  | Yes | Yes |  |  |
| 0x120 | eqenable2 | Enable: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x121 | eqtype2 | Type: | List | List (EQ band type): stored as the item's index |  |  | 0 None; 1 L Cut; 2 L Shelf; 3 Param; 4 H Shelf; 5 H Cut | Yes | Yes |  |  |
| 0x122 | eqgain3 | Gain: | Number | Decibels: stored x1000, shown with one decimal (9300 = +9.3 dB) | -24000 | 24000 |  | Yes | Yes |  |  |
| 0x123 | eqcutoff3 | Freq: | Number | Frequency: the stored position through the stock cutoff curve, shown in Hz / kHz | 0 | 1000 |  | Yes | Yes |  |  |
| 0x124 | eqres3 | Q: | Number | Resonance: the stored position through the stock Q curve, shown with one decimal | 0 | 1000 |  | Yes | Yes |  |  |
| 0x125 | eqenable3 | Enable: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x126 | eqtype3 | Type: | List | List (EQ band type): stored as the item's index |  |  | 0 None; 1 L Cut; 2 L Shelf; 3 Param; 4 H Shelf; 5 H Cut | Yes | Yes |  |  |
| 0x127 | eqgain4 | Gain: | Number | Decibels: stored x1000, shown with one decimal (9300 = +9.3 dB) | -24000 | 24000 |  | Yes | Yes |  |  |
| 0x128 | eqcutoff4 | Freq: | Number | Frequency: the stored position through the stock cutoff curve, shown in Hz / kHz | 0 | 1000 |  | Yes | Yes |  |  |
| 0x129 | eqres4 | Q: | Number | Resonance: the stored position through the stock Q curve, shown with one decimal | 0 | 1000 |  | Yes | Yes |  |  |
| 0x12a | eqenable4 | Enable: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x12b | eqtype4 | Type: | List | List (EQ band type): stored as the item's index |  |  | 0 None; 1 L Cut; 2 L Shelf; 3 Param; 4 H Shelf; 5 H Cut | Yes | Yes |  |  |
| 0x12d | eqbypass | Bypass: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x12e | eqactband | Band: | Number | Integer (shown as a number; the knob may add a fixed offset) | 0 | 3 |  | Yes | Yes |  |  |
| 0x12f | cattack | C Attack: | Number | Milliseconds (shown 'n ms') | 0 | 10000 |  | Yes | Yes |  |  |
| 0x130 | crelease | C Release: | Number | Milliseconds (shown 'n ms') | 0 | 10000 |  | Yes | Yes |  |  |
| 0x131 | cthreshdb | C Thresh: | Number | Decibels: stored x1000, shown with one decimal (9300 = +9.3 dB) | -48000 | 0 |  | Yes | Yes |  |  |
| 0x132 | cratio | C Ratio: | Number | Integer (shown as a number; the knob may add a fixed offset) | 1 | 100 |  | Yes | Yes |  |  |
| 0x133 | eratio | C Exp Ratio: | Number | Integer (shown as a number; the knob may add a fixed offset) | 1 | 100 |  | Yes | Yes |  |  |
| 0x134 | cautomakeup | C AutoMkup: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x135 | ckneedb | C Knee: | Number | Decibels: stored x1000, shown with one decimal (9300 = +9.3 dB) | 0 | 18000 |  | Yes | Yes |  |  |
| 0x136 | clookahead | C Loopahead: | Number | Milliseconds (shown 'n ms') | 0 | 100 |  | Yes | Yes |  |  |
| 0x137 | cautorel | C AutoRel: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x138 | commode | C Mode: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Peak; 1 RMS; 2 Expander | Yes | Yes |  |  |
| 0x139 | cwetdry | C Wet/Dry: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x13a | cgaindb | C Gain: | Number | Decibels: stored x1000, shown with one decimal (9300 = +9.3 dB) | -36000 | 36000 |  | Yes | Yes |  |  |
| 0x13b | cbypass | C Bypass: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x17c | grainsizeperc | Grain Size: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes | 300 |  |
| 0x17e | grainscat | Scatter: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes | 0 |  |
| 0x17f | grainpanrnd | Pan Rnd: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes | 0 |  |
| 0x180 | graindensity | Density: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes | 600 |  |
| 0x189 | legatomode | Legato: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes | 0 |  |
| 0x18c | unisonmode | Unison: | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | Yes | Yes |  |  |
| 0x18d | unisondetune | Detune: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x18e | unisonspread | Pan Spread: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x18f | unisonvcount | Voices: | Number | Integer (shown as a number; the knob may add a fixed offset) | 1 | 8 |  | Yes | Yes |  |  |
| 0x190 | macrox | Macro X: | Number | Percent -100.0..+100.0: stored x10 (-1000..1000) | -1000 | 1000 |  | Yes | Yes |  |  |
| 0x191 | macroy | Macro Y: | Number | Percent -100.0..+100.0: stored x10 (-1000..1000) | -1000 | 1000 |  | Yes | Yes |  |  |
| 0x197 | fx1algo | FX1: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Flanger/Dist; 1 Chorus; 2 Phaser | Yes | Yes |  |  |
| 0x198 | fx2algo | FX2 | List | List: stored as the item's index, 0 = the first item |  |  | 0 Delay; 1 Reverb | Yes | Yes |  |  |
| 0x199 | chorrate | Rate: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | Yes | Yes |  |  |
| 0x19b | sdsafemode | SD Mode: | List | List: stored as the item's index, 0 = the first item |  |  | 0 High Speed; 1 Compatible | Yes | Yes |  |  |
| 0x1c0 | adatkslope | Atk Slope: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | No | Yes | 500 | AD Atk Slope (3.1.v7): the attack's curve. 500 = linear; 0 = slow start, late climb; 1000 = fast rise easing into full. Stage time unchanged. |
| 0x1c1 | addecslope | Dec Slope: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | No | Yes | 270 | AD Dec Slope (3.1.v7): the decay's curve. 500 = linear; 0 = fast drop with a long tail; 1000 = holds near full, falls late. Default 270 matches the earlier builds' exponential decay. |
| 0x1dc | oscoctave | Octave: | List | List: stored as the item's index, 0 = the first item |  |  | 0 -3; 1 -2; 2 -1; 3 0; 4 +1; 5 +2; 6 +3 | No | Yes | 3 | Oscillator Octave: list index 0..6 = -3 .. +3 octaves (3 = the played note). |
| 0x1dd | osctune | Tune: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | No | Yes | 500 | Oscillator Tune 0..1000 = -6 .. +6 semitones (500 = in tune); a modulation destination. |
| 0x1de | oscfine | Fine: | Number | Percent -100.0..+100.0: stored x10 (-1000..1000) | -1000 | 1000 |  | No | Yes | 0 | Oscillator Fine -1000..1000 = -50 .. +50 cents. |
| 0x1df | oscpw | Pulse W: | Number | Percent -100.0..+100.0: stored x10 (-1000..1000) | -1000 | 1000 |  | No | Yes | 0 | Oscillator Pulse W -1000..1000: every wave's width 50 % +- 45 % (0 = the plain wave); a modulation destination. |
| 0x1e0 | osctrack | Osc Track | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | No | Yes | 1 | Osc Track (Osc tab, an on / off button since S.1; a list on the Conf tab before): 0 Off = fixed C4 (+ Octave / Tune / Fine), 1 On = follows the note, Pitch and Glide. |
| 0x1e1 | fenvtype | Type: | List | List: stored as the item's index, 0 = the first item |  |  | 0 LP; 1 HP; 2 BP | No | Yes | 0 | Hidden. An early build's filter type (LP / HP / BP); read only to convert those presets (HP -> Morph 100, BP -> Morph 50), then set back to LP. |
| 0x1e2 | fenvattack | Attack: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | No | Yes | 0 | Filter envelope Attack: 0..1000 = 0..60 s (60 x^3 s, x = value / 1000). |
| 0x1e3 | fenvdecay | Decay: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | No | Yes | 300 | Filter envelope Decay: 0..1000 = 0..60 s (60 x^3 s). |
| 0x1e4 | fenvsus | Sustain: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | No | Yes | 0 | Filter envelope Sustain level 0..1000. |
| 0x1e6 | fenvdepth | Depth: | Number | Percent -100.0..+100.0: stored x10 (-1000..1000) | -1000 | 1000 |  | No | Yes | 0 | Filter envelope Depth -1000..1000: how far the envelope moves the cutoff (1000 = the knob's whole range). |
| 0x1e7 | glidemode | Glide: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Off; 1 Always; 2 Legato | No | Yes | 0 | Glide (Conf tab): 0 Off, 1 Always, 2 Legato. Sample / multisample pads. |
| 0x1e8 | glidetime | Glide Time: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | No | Yes | 200 | Glide Time 0..1000 = 0..10 s (10 x^3 s). |
| 0x1e9 | fenvmorph | Morph: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | No | Yes | 0 | Filter Morph 0..1000: LP (0) .. notch (500) .. HP (1000); a modulation destination. |
| 0x1eb | fenvrel | Release: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | No | Yes | 300 | Filter envelope Release: 0..1000 = 0..60 s (60 x^3 s). |
| 0x1ec | adattack | AD Atk: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | No | Yes | 0 | AD envelope Attack (Mod tab, label 'AD Atk:'): 0..1000 = 0..60 s (60 x^3 s). The AD envelope is modulation source AD (src 'env2'), one-shot per note. |
| 0x1ed | addecay | AD Decay: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | No | Yes | 300 | AD envelope Decay: 0..1000 = 0..60 s (60 x^3 s); reaches 0 exactly at its time. |
| 0x1ef | filtermodel | Filter Type: | List | List: stored as the item's index, 0 = the first item |  |  | 0 SEM; 1 Polivoks | No | Yes | 0 | Filter Type (Conf tab): 0 SEM (12 dB/oct state-variable, with Morph), 1 Polivoks (12 dB/oct, slew-limited, 2x oversampled). |
| 0x1f0 | oscon | Osc | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | No | Yes | 0 | Oscillator on (Osc tab of sample / multisample pads): 0 off, 1 on. The oscillator is a modulation source only (src 'env3'), never heard. |
| 0x1f1 | oscmode | OSC/MOD | Button | On / off button: stored 0 = off, 1 = on | 0 | 1 |  | No | Yes | 0 | Was the OSC / MOD button. Still registered and saved so presets keep their layout; ignored since 3.1.v1. |
| 0x1f2 | oscwave | Wave: | List | List: stored as the item's index, 0 = the first item |  |  | 0 Sine; 1 Square; 2 Triangle; 3 Saw | No | Yes | 0 | Oscillator Wave: 0 Sine, 1 Square, 2 Triangle, 3 Saw. (An older build stored 0..1000: it loads as the nearest.) |
| 0x1f3 | osclevel | Level: | Number | Percent 0.0..100.0: stored x10 (0..1000) | 0 | 1000 |  | No | Yes | 700 | Oscillator Level 0..1000: the modulation depth (linear); a modulation destination. |
|  | lfomode |  | Button |  |  |  |  | No | No |  | Synb0x 3.1.t .. 3.1.v6 only (LFO 1-Shot, 0 Loop / 1 one cycle per note). Not registered in stock or in 3.1.v7: ignored on load and not written on save. |

## Modulation sources (`<modsource src>`)

Synb0x adds KEY (`key`), FENV (`env1`, the filter envelope), AD (`env2`, the AD envelope) and OSC (`env3`, the pad's oscillator). `<modsource dest>` takes a parameter's XML name.

## Converting presets

- From stock / pre-Synb0x presets: `convert_presets.py` (or the Preset Converter app) maps the old Filter (`dualfilcutoff`) to Synb0x's cutoff + Morph and writes `<name> syn` copies.
- Missing attributes keep their defaults, unknown ones are ignored, so a converter only has to write what it knows; match on the XML attribute name, never on position.
