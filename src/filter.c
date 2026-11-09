/*
 * Pad crunch + Mutable Instruments-style state-variable filter. Original 1010music Blackbox, firmware 3.1.9.
 *
 * Stock: every voice runs its pad filter once per audio block (FUN_080762d8): one RBJ biquad, 12 dB/oct, low-pass
 * when the Filter knob is left of centre and high-pass when right of it, bypassed at centre. This replaces that
 * call (both pad classes) with:
 *   1. Crunch: the pad's Interp list gains seven entries after Normal / HighQ (16k down to 2k:
 *      on his hardware 26k / 20k were inaudible on bright material and 12k was where it started to bite). Each holds the
 *      voice's output at a lower sample rate (zero-order hold, no anti-aliasing: the old-sampler sound) and rounds
 *      it to 12 bits, before the filter, so the filter can tame the grit.
 *   2. Filter (SEM): 12 dB/oct, as the Oberheim SEM's 2-pole state-variable filter (3.1.v1: it was 24 dB/oct, two
 *      stages): one trapezoidal state-variable filter from Emilie Gillet's stmlib (dsp/filter.h, class Svf; MIT
 *      licence, Copyright 2014 Emilie Gillet) carrying the Res knob, flat (Q 0.707) at Res 0. Cutoff and resonance go
 *      through the stock curves, so the Filter and Res knobs keep their ranges. Above the default Res (noon) the
 *      resonant integrator has a soft ceiling high above its swing (a safety net: no audible drive) and a mild bass
 *      compensation (a low shelf on the low-pass part, up to +0.6 dB at 50 Hz at full Res).
 *      Self-oscillation: gentle, from Res 85 % the damping is pulled through 0 to negative at full, and an amplitude
 *      control (damping + KAP x the stage's energy, per 32-frame step) holds it to a soft sine at the cutoff, 0.3 peak,
 *      in every Morph position; KEY -> Filter at +100 % plays it in tune (1 octave per octave).
 *   3. Morph (new pad param, fenv.c): LP at 0, notch at 50 %, HP at 100 %, a plain LP / HP crossfade in each stage (as
 *      the SEM's pot) (morph_weights), and a modulation destination (any source, applied here). The Filter knob is cutoff across its whole travel, far left
 *      20 Hz to far right 20.5 kHz (the stock curve's 0..1 half), instead of centre = off, left LP, right HP.
 *      LP fully open or HP fully closed, with nothing moving the filter, skips it, as centre did before.
 *   4. Filter envelope (new pad params, fenv.c): per voice ADSR, times 0 .. 60 s (60 x^3 s on the 0..100 knob, like the
 *      amp envelope's cubic), Sustain a level. Gated by the voice's own amp envelope: stages 1..3 (attack, decay,
 *      sustain) are gate on, 4 (release, also choke and one-shot end) is gate off. Depth -100..+100 moves the cutoff by
 *      up to the knob's full travel (10 octaves). The envelope also feeds modulation source FENV.
 *      Updated every 32 frames so fast envelopes are not stepped at the 256-frame block rate.
 * State lives in the stock filter object, in the part only the stock process function used; the envelope sits in
 * +0x44..+0x5f, which the stock voice start (FUN_08076704) zeroes, so each note starts it from 0.
 * Stock firmware treats the new Interp values as HighQ, so presets stay loadable there.
 */
#include <stdint.h>
#include "fenv.h"

#pragma GCC optimize("O2", "no-tree-loop-distribute-patterns")   /* per-sample loops run for every voice; no libc to call */

#define FN(addr) ((addr) | 1u)

typedef float (*curve_fn)(float x);
typedef float (*param_fn)(void *param);
typedef int (*buf_int_fn)(void *buf);
typedef int (*buf_chans_fn)(void *buf, float **left, float **right);
typedef void (*register_fn)(void *table, int param, const char *label, const char *const *names, int count,
                            const char *xml);

#define fw_cutoff_hz  ((curve_fn)FN(0x08060640))     /* knob 0..1 -> Hz */
#define fw_res_q      ((curve_fn)FN(0x080606c0))     /* Res 0..1 -> Q */
#define fw_param      ((param_fn)FN(0x0806fb30))     /* modulated parameter value */
#define fw_buf_silent ((buf_int_fn)FN(0x0804d8f4))
#define fw_buf_frames ((buf_int_fn)FN(0x0804d8e8))
#define fw_buf_chans  ((buf_chans_fn)FN(0x0804d944))
#define fw_register_list ((register_fn)FN(0x0808c0d8))
typedef int (*setting_fn)(const void *store, unsigned param);
#define fw_setting    ((setting_fn)FN(0x08093e9c))     /* a pad record's value by id (scans) */

#define FS         48000.0f
#define PI_F       3.14159265f
#define OBJ_PARAMS 0x84          /* filter object -> its parameter block: Filter knob @+8, Res @+0x44 */

static const float crunch_rate[] = {16000.0f, 12000.0f, 10000.0f, 8000.0f, 6000.0f, 4000.0f, 2000.0f};
#define CRUNCHES ((int)(sizeof crunch_rate / sizeof crunch_rate[0]))
#define STOCK_INTERP 2           /* Normal, HighQ */

/*
 * Machine modes: the old samplers' pitch path, not just their output rate.
 *   grid    the machine's sample rate. The voice reader (machine_read) plays the pad's sample as if it had been
 *           sampled at this rate: it reads the source only on that grid (after a 5-tap anti-alias FIR at 0.45 x grid),
 *           so pitching skips or doubles stored samples like the SP's carry-adder pitch logic, and the aliasing moves
 *           with the note. (A fixed-rate hold alone, the 16k..2k crunch, cannot do that.)
 *   hold    1: the DAC runs at the grid rate whatever the pitch (SP-1200, SP-12, MPC60): zero-order hold at grid
 *           after the voice. 0: a per-voice variable-rate DAC (S950): no fixed hold; the reader interpolates linearly
 *           between grid samples, standing in for its rate-tracking smoothing filter.
 *   out     output stage, an RBJ low-pass {b0, b1, a1, a2} at 48 kHz (b2 = b0): SP-1200 12 kHz Q 1.25, SP-12
 *           12.5 kHz Q 1.2 (resonant: the steep-filter ring), S950 13.5 kHz Q 0.75, MPC60 16 kHz Q 0.9.
 *   SP Raw  (3.1.n) SP1200 without the output filter, like the SP's unfiltered outputs 7-8: the hold's images and the
 *           pitched-down sizzle come straight through.
 * All 12-bit. The SP's SSM2044 outputs are the pad's own Filter knob (24 dB SVF with drive) after this.
 * Drive (3.1.n): in a machine mode the pad's Saturation knob is the converter input level instead of the warm saturation
 * (od.c stands aside for these pads): gain 1 + 7 d^2 (up to +18 dB) into a hard clip at the converter's full scale,
 * ahead of the hold and the 12 bits, then level back by 1 / (1 + 1.1 d^2): hitting the SP's inputs hot.
 * MPC60 is the least documented: 40 kHz 12-bit with the same skip/double pitch is a best guess.
 */
struct machine {
    float grid;
    uint8_t hold, linear, raw;
    float fir[5];
    float out[4];
};
static const struct machine machines[] = {
    {26040.0f, 1, 0, 0, {0.00302f, 0.24563f, 0.5027f, 0.24563f, 0.00302f}, {0.357143f, 0.714286f, 0.0f, 0.428571f}},
    {27500.0f, 1, 0, 0, {-0.00396f, 0.24215f, 0.52363f, 0.24215f, -0.00396f}, {0.376262f, 0.752523f, 0.092392f, 0.412654f}},
    {31250.0f, 0, 1, 0, {-0.02035f, 0.2289f, 0.58291f, 0.2289f, -0.02035f}, {0.361304f, 0.722608f, 0.235922f, 0.209295f}},
    {40000.0f, 1, 0, 0, {-0.03947f, 0.16746f, 0.74402f, 0.16746f, -0.03947f}, {0.506372f, 1.012744f, 0.675162f, 0.350325f}},
    {26040.0f, 1, 0, 1, {0.00302f, 0.24563f, 0.5027f, 0.24563f, 0.00302f}, {0.0f, 0.0f, 0.0f, 0.0f}},     /* SP Raw */
};
#define MACHINES ((int)(sizeof machines / sizeof machines[0]))
#define FIRST_MACHINE STOCK_INTERP                      /* his order (3.1.n): machines before the plain crunches */
#define FIRST_CRUNCH  (STOCK_INTERP + MACHINES)

const char *const interp_names[STOCK_INTERP + CRUNCHES + MACHINES] = {
    (const char *)0x080cd770u, (const char *)0x080cd778u,       /* Normal, HighQ */
    "SP1200", "SP-12", "S950", "MPC60", "SP Raw",
    "16k", "12k", "10k", "8k", "6k", "4k", "2k",
};

/* Replaces the Interp list registration call: 2 -> 9 entries, and the label "Interp:" -> "Fidelity:" (his pick of
   names; the xml name "interpqual" stays, so presets are unaffected). */
void interp_register(void *table, int param, const char *label, const char *const *names, int count, const char *xml)
{
    (void)label;
    (void)names;
    (void)count;
    fw_register_list(table, param, "Fidelity:", interp_names, STOCK_INTERP + CRUNCHES + MACHINES, xml);
}

struct fstate {                  /* at filter object +4..+0x48; the stock coefficient sets and states used to live here */
    uint32_t magic;
    float osc, r, drive;         /* smoothed: self-oscillation 0..1, damping of the resonant stage, drive 0..1 */
    union {                      /* the running filter's state (magic says which) */
        struct {
            float s1[2][2], s2[2][2];    /* SEM: integrator states [0][channel], bass shelf s1[1][channel] */
        };
        float h[2][4];           /* Stock: biquad history [channel]{x1, x2, y1, y2}; Polivoks: [channel]{bp, lp} */
    };
    float phase, held[2];        /* crunch: hold phase and held sample per channel */
    uint32_t on;                 /* filter was running last block */
};
#define MAGIC 0x53454d32u        /* "SEM2": the 2-pole SEM (3.1.v1; the 4-pole "SVF2" state does not carry over) */
#define MAGIC_PV 0x50564b31u     /* "PVK1": Polivoks (as 3.1.up) */
enum { MODEL_SEM, MODEL_PV };              /* the Filter Type list's order (fenv.c); the Stock biquad was removed: under
                                              audio-rate cutoff modulation its direct form went unstable */
static const uint32_t magics[FMODELS] = {MAGIC, MAGIC_PV};
#define BASS_A   0.0156f         /* the bass shelf's one-pole: 1 - exp(-2 pi 120 Hz / 48 kHz) */
#define BASS_MAX 0.09f           /* its boost at full Res: +0.6 dB at 50 Hz on the low-pass part (was 0.26, too much) */
#define LIMIT_SEM 8.0f           /* the resonant integrator's soft ceiling above noon: a safety net only, above the
                                    resonance's normal swing (4 -> 2.5 squeezed the peak: that was audible drive) */
#define SMOOTH 0.33333f          /* per-block coefficient smoothing, as the stock filter */
/* Self-oscillation (3.1.u): from Res OSC_FROM up, the resonant stage's damping is pulled down from the stock curve
   through 0 (around 94 %) to R_TOP at full, where the stage is unstable on its own. An amplitude control holds it: the
   damping grows with the stage's energy, r + KAP * osc * E, E = bp^2 + lp^2 (constant over a cycle of a sine, so the
   control adds no distortion), updated per 32-frame step from the states. It settles where r + KAP E = 0: a sine at the
   cutoff of peak sqrt(-R_TOP / KAP) = 0.3 (gentle: half the old 4-pole's -R_TOP, so it builds slowly too). */
#define OSC_FROM 0.85f
#define R_FULL   0.05524f        /* 1 / the stock curve's Q at full Res (18.1) */
#define R_TOP    (-0.05f)
#define KAP      0.5556f
#define CLAMP    2.0f            /* resonant integrator ceiling while self-oscillating, x (1 + g) (a sine never reaches it) */
/* The control acts once per step, so its loop gain grows with g (damping per sample ~ r g); above G_REF (~4.4 kHz) the
   whole resonant damping is scaled by G_REF / g as self-oscillation takes over, or it would overshoot and cycle. Its
   zero, and so the sine's level, stays where it is. */
#define G_REF    0.3f
#define Q_RES_LOW2 0.70711f      /* a 2-pole filter's Q at Res 0 (Polivoks): Butterworth, flat, no peak */
/* Polivoks (3.1.up) */
#define R_TOP_PV (-0.15f)
#define OSC_TRIM 0.4f
#define RAIL     1.5f            /* op-amp output rails (signals are +-1 full scale: easy to overload, as the original) */
#define SLEW     1.5f            /* integrator input scale: past it the integrator's rate is limited (slew) */
#define FC_MAX   16000.0f        /* top of the Polivoks's cutoff range (its oversampled integrators stay stable to here) */

/* tan(x) for 0 <= x < 1.45, Pade (3,2); 3% low at the top of the range, exact enough below. */
static float tan_approx(float x)
{
    float x2 = x * x;
    return x * (15.0f - x2) / (15.0f - 6.0f * x2);
}

static float quantize12(float x)
{
    float s = x * 2048.0f;
    int i = (int)(s + (s >= 0.0f ? 0.5f : -0.5f));
    return (float)i * (1.0f / 2048.0f);
}

/* Output stage of a machine mode. State in the filter object at +0x60..+0x73, which only the stock process (replaced)
   and its coefficient helper FUN_0807612c (called only from it) used. */
struct ostate {
    uint32_t magic;
    float z[2][2];
};
#define OMAGIC 0x4d4f5554u       /* "MOUT" */

static void out_stage(uint8_t *obj, float **ch, int n, const float *c)
{
    struct ostate *o = (struct ostate *)(obj + 0x60);
    if (o->magic != OMAGIC) {
        o->z[0][0] = o->z[0][1] = o->z[1][0] = o->z[1][1] = 0.0f;
        o->magic = OMAGIC;
    }
    float b0 = c[0], b1 = c[1], a1 = c[2], a2 = c[3];
    for (int k = 0; k < 2; k++) {
        float *x = ch[k];
        if (!x)
            continue;
        float z1 = o->z[k][0], z2 = o->z[k][1];
        for (int i = 0; i < n; i++) {                       /* transposed direct form II */
            float in = x[i], y = b0 * in + z1;
            z1 = b1 * in - a1 * y + z2;
            z2 = b0 * in - a2 * y;
            x[i] = y;
        }
        o->z[k][0] = z1;
        o->z[k][1] = z2;
    }
}

static void crunch(struct fstate *st, float **ch, int n, float rate)
{
    float step = rate / FS, phase = st->phase;
    float held0 = st->held[0], held1 = st->held[1];
    for (int i = 0; i < n; i++) {
        phase += step;
        if (phase >= 1.0f) {
            phase -= 1.0f;
            held0 = quantize12(ch[0][i]);
            if (ch[1])
                held1 = quantize12(ch[1][i]);
        }
        ch[0][i] = held0;
        if (ch[1])
            ch[1][i] = held1;
    }
    st->phase = phase;
    st->held[0] = held0;
    st->held[1] = held1;
}

/* Soft clip, unity gain at zero, flat at |x| = 1.5 t, ceiling t: t * (u - 4/27 u^3), u = x / t. */
static inline __attribute__((always_inline)) float soft(float x, float inv_t, float t)
{
    float u = x * inv_t;
    u = __builtin_fminf(__builtin_fmaxf(u, -1.5f), 1.5f);    /* vmaxnm / vminnm: no branch in the sample loop */
    return t * u * (1.0f - 0.148148f * u * u);
}

/* The same with the cubic's weight c3 (0.148148 = soft): c3 = 0 makes it a plain clamp at 1.5 t, linear below */
static inline __attribute__((always_inline)) float soft_c(float x, float inv_t, float t, float c3)
{
    float u = x * inv_t;
    u = __builtin_fminf(__builtin_fmaxf(u, -1.5f), 1.5f);
    return t * u * (1.0f - c3 * u * u);
}

/*
 * stmlib Svf::Process<FILTER_MODE_LOW_PASS / HIGH_PASS> for one channel with coefficients fixed for the call, and the
 * Morph crossfade of the two. CLIP: soft-limit the band-pass integrator (the resonant loop); only used on the resonant
 * stage while driven.
 */
enum { TYPE_LP, TYPE_HP, TYPE_MIX };
#define OUT_LP(hp, bp, lp, r) (lp)
#define OUT_HP(hp, bp, lp, r) (hp)
/* Morph: a mix of the two in each stage (weights from morph_weights). Halfway it is LP + HP, which in a state-variable
   filter cancel at the cutoff: a notch, two of them in series here (the Oberheim SEM's LP - Notch - HP idea, twice). */
#define OUT_MIX(hp, bp, lp, r) (wl * (lp) + wh * (hp))

/* The SEM's safety clamp: t * clamp(x / t, +-1.5) (the soft clip's form with its cubic gone, bit for bit) */
static inline __attribute__((always_inline)) float clamp_t(float x, float inv_t, float t)
{
    float u = x * inv_t;
    u = __builtin_fminf(__builtin_fmaxf(u, -1.5f), 1.5f);
    return t * u;
}

/*
 * The 2-pole SEM, one channel, coefficients fixed for the call. DRIVEN (Res above noon): the resonant integrator
 * softly limited (the only drive: on the resonance), the bass shelf (z: a one-pole of bass x the low-pass, added with
 * LP's weight; the weight inside the one-pole, so a Res change glides in instead of stepping). DRIVEN, RAMP, FILL are compile-time 0 / 1, so each variant is its own tight loop.
 */
#define SVF1_LOOP(OUT, DRIVEN, RAMP, FILL)                                                                         \
    for (int i = 0; i < n; i++) {                                                                                  \
        if (RAMP) {                                                                                                \
            wl += dl;                                                                                              \
            wh += dh;                                                                                              \
        }                                                                                                          \
        float hp = (x[i] - rg * b1 - b2) * h;                                                                      \
        float bp = g * hp + b1;                                                                                    \
        b1 = DRIVEN ? clamp_t(g * hp + bp, inv, limit) : g * hp + bp;                                              \
        float lp = g * bp + b2;                                                                                    \
        b2 = g * bp + lp;                                                                                          \
        float y = OUT(hp, bp, lp, r);                                                                              \
        if (FILL)                                                                                                  \
            y += fill * wl * wh * bp;                                                                              \
        if (DRIVEN) {                                                                                              \
            z += BASS_A * (bass * lp - z);                                                                         \
            y += wl * z;                                                                                           \
        }                                                                                                          \
        x[i] = y;                                                                                                  \
    }

/* s = {s1, s2, bass shelf} for this channel. drive 0 = clean. w0 -> w1: the {LP, HP} weights at the start and end of
   the call, ramped sample by sample when they differ (a step would click). Pure LP or pure HP throughout takes that
   output's own loop (no blending cost). osc: self-oscillation 0..1. Between LP and HP the stage adds its band-pass
   (4 wl wh osc, all of it at the notch), where LP + HP would cancel the oscillation: the sine keeps its level across
   Morph. */
static void svf1(float *x, int n, float g, float r, float *s[3], const float w0[2], const float w1[2], float drive,
                 float osc)
{
    int ramp = w0[0] != w1[0] || w0[1] != w1[1];
    float wl = w0[0], wh = w0[1];
    float dl = ramp && n > 0 ? (w1[0] - w0[0]) / (float)n : 0.0f, dh = ramp && n > 0 ? (w1[1] - w0[1]) / (float)n : 0.0f;
    int type = ramp ? TYPE_MIX : wh == 0.0f ? TYPE_LP : wl == 0.0f ? TYPE_HP : TYPE_MIX;
    float h = 1.0f / (1.0f + r * g + g * g), rg = r + g;
    float b1 = *s[0], b2 = *s[1], z = *s[2];
    if (drive > 0.001f) {
        float bass = BASS_MAX * drive;
        /* resonant integrator: a soft ceiling high above its normal swing (a safety net, no audible drive); as
           self-oscillation takes over, the cubic fades out by (1 - osc)^4 and the ceiling moves to a plain clamp at
           CLAMP (1 + g), above the sine */
        float limit = LIMIT_SEM;
        limit += osc * (CLAMP / 1.5f * (1.0f + g) - limit);
        float inv = 1.0f / limit, fill = 4.0f * osc;   /* a plain clamp at 1.5 x the ceiling, linear below it (any
                                                       cubic in the loop squeezed the peak) */
        if (type == TYPE_HP)
            SVF1_LOOP(OUT_HP, 1, 0, 0)
        else if (type == TYPE_MIX && ramp)
            SVF1_LOOP(OUT_MIX, 1, 1, 1)
        else if (type == TYPE_MIX)
            SVF1_LOOP(OUT_MIX, 1, 0, 1)
        else
            SVF1_LOOP(OUT_LP, 1, 0, 0)
    } else {
        float limit = 1.0f, inv = 1.0f, fill = 0.0f, bass = 0.0f;
        (void)limit;
        (void)inv;
        (void)fill;
        (void)bass;
        (void)osc;
        z = 0.0f;                                     /* (the shelf starts from 0 when Res comes back above noon) */
        if (type == TYPE_HP)
            SVF1_LOOP(OUT_HP, 0, 0, 0)
        else if (type == TYPE_MIX && ramp)
            SVF1_LOOP(OUT_MIX, 0, 1, 0)
        else if (type == TYPE_MIX)
            SVF1_LOOP(OUT_MIX, 0, 0, 0)
        else
            SVF1_LOOP(OUT_LP, 0, 0, 0)
    }
    *s[0] = b1;
    *s[1] = b2;
    *s[2] = z;
}

/*
 * The same for a stereo voice: both channels in one loop (3.1.v1, CPU), each with its own damping (r0 / r1: the
 * amplitude control is per channel), states and shelf; each channel's arithmetic is svf1's, in its order (bit-
 * identical), so the two independent chains overlap in the FPU's pipeline instead of each waiting on itself.
 */
#define SVF1X2_CH(OUT, DRIVEN, FILL, X, H, RG, B1, B2, Z)                                                         \
    {                                                                                                              \
        float hp = (X[i] - RG * B1 - B2) * H;                                                                      \
        float bp = g * hp + B1;                                                                                    \
        B1 = DRIVEN ? clamp_t(g * hp + bp, inv, limit) : g * hp + bp;                                              \
        float lp = g * bp + B2;                                                                                    \
        B2 = g * bp + lp;                                                                                          \
        float y = OUT(hp, bp, lp, 0.0f);                                                                           \
        if (FILL)                                                                                                  \
            y += fill * wl * wh * bp;                                                                              \
        if (DRIVEN) {                                                                                              \
            Z += BASS_A * (bass * lp - Z);                                                                         \
            y += wl * Z;                                                                                           \
        }                                                                                                          \
        X[i] = y;                                                                                                  \
    }
#define SVF1X2_LOOP(OUT, DRIVEN, RAMP, FILL)                                                                       \
    for (int i = 0; i < n; i++) {                                                                                  \
        if (RAMP) {                                                                                                \
            wl += dl;                                                                                              \
            wh += dh;                                                                                              \
        }                                                                                                          \
        SVF1X2_CH(OUT, DRIVEN, FILL, x0, h0, rg0, a1, a2, za)                                                      \
        SVF1X2_CH(OUT, DRIVEN, FILL, x1, h1, rg1, c1, c2, zc)                                                      \
    }

static void svf1x2(float *x0, float *x1, int n, float g, float r0, float r1, float *s0[3], float *s1[3],
                   const float w0[2], const float w1[2], float drive, float osc)
{
    int ramp = w0[0] != w1[0] || w0[1] != w1[1];
    float wl = w0[0], wh = w0[1];
    float dl = ramp && n > 0 ? (w1[0] - w0[0]) / (float)n : 0.0f, dh = ramp && n > 0 ? (w1[1] - w0[1]) / (float)n : 0.0f;
    int type = ramp ? TYPE_MIX : wh == 0.0f ? TYPE_LP : wl == 0.0f ? TYPE_HP : TYPE_MIX;
    float h0 = 1.0f / (1.0f + r0 * g + g * g), rg0 = r0 + g, h1 = 1.0f / (1.0f + r1 * g + g * g), rg1 = r1 + g;
    float a1 = *s0[0], a2 = *s0[1], za = *s0[2], c1 = *s1[0], c2 = *s1[1], zc = *s1[2];
    if (drive > 0.001f) {
        float bass = BASS_MAX * drive;
        float limit = LIMIT_SEM;
        limit += osc * (CLAMP / 1.5f * (1.0f + g) - limit);
        float inv = 1.0f / limit, fill = 4.0f * osc;
        if (type == TYPE_HP)
            SVF1X2_LOOP(OUT_HP, 1, 0, 0)
        else if (type == TYPE_MIX && ramp)
            SVF1X2_LOOP(OUT_MIX, 1, 1, 1)
        else if (type == TYPE_MIX)
            SVF1X2_LOOP(OUT_MIX, 1, 0, 1)
        else
            SVF1X2_LOOP(OUT_LP, 1, 0, 0)
    } else {
        float limit = 1.0f, inv = 1.0f, fill = 0.0f, bass = 0.0f;
        (void)limit;
        (void)inv;
        (void)fill;
        (void)bass;
        (void)osc;
        za = zc = 0.0f;
        if (type == TYPE_HP)
            SVF1X2_LOOP(OUT_HP, 0, 0, 0)
        else if (type == TYPE_MIX && ramp)
            SVF1X2_LOOP(OUT_MIX, 0, 1, 0)
        else if (type == TYPE_MIX)
            SVF1X2_LOOP(OUT_MIX, 0, 0, 0)
        else
            SVF1X2_LOOP(OUT_LP, 0, 0, 0)
    }
    *s0[0] = a1;
    *s0[1] = a2;
    *s0[2] = za;
    *s1[0] = c1;
    *s1[1] = c2;
    *s1[2] = zc;
}

/*
 * Polivoks (Filter Type Polivoks, as 3.1.up). The Formanta Polivoks's 2-pole state-variable filter has no capacitors: its two integrators are
 * K140UD12 (uA776-type) programmable op-amps whose bias current sets how fast they can ramp, so they are slew
 * generators, linear for small signals and rate-limited for big ones, and their outputs clip at the rails. Modelled
 * as a state-variable filter whose integrators take their input through a cubic clipper (the rate limit) and clamp
 * their output (the rails), run twice per sample (explicit, as Vult's ladder example, MIT) so the clipping aliases
 * less; the output is the mean of the two. f = 2 sin(pi fc / 2 fs) keeps small signals in tune.
 * Morph: (1 - m) LP + m HP, so the notch at 50 % (the original has LP and BP).
 * DRIVEN: the input soft clip while Res drives (into the rails).
 */
static inline __attribute__((always_inline)) float clampf(float x, float a)
{
    return __builtin_fminf(__builtin_fmaxf(x, -a), a);
}

static inline __attribute__((always_inline)) float slew(float u)    /* cubic, slope 1 at 0, flat 2/3 from |u| = 1 */
{
    u = clampf(u, 1.0f);
    return u - u * u * u * (1.0f / 3.0f);
}

#define PV_STEP(v)                                                                                                 \
    hp = (v) - q * bp - lp;                                                                                        \
    bp = clampf(bp + fl * slew(hp * (1.0f / SLEW)), RAIL);                                                         \
    lp = clampf(lp + fl * slew(bp * (1.0f / SLEW)), RAIL);

#define PV_LOOP(DRIVEN, RAMP)                                                                                      \
    for (int i = 0; i < n; i++) {                                                                                  \
        if (RAMP) {                                                                                                \
            wl += dl;                                                                                              \
            wh += dh;                                                                                              \
            wb = fill * wl * wh;                                                                                   \
        }                                                                                                          \
        trim += dt;                                                                                                \
        float v = x[i], hp;                                                                                        \
        if (DRIVEN)                                                                                                \
            v = soft(v * pre, 1.0f, 1.0f);                                                                         \
        PV_STEP(v)                                                                                                 \
        float o = wl * lp + wh * hp + wb * bp;                                                                     \
        PV_STEP(v)                                                                                                 \
        x[i] = trim * (o + wl * lp + wh * hp + wb * bp);                                                           \
    }

/* One channel: f the integrator coefficient, q the damping, h = this channel's {bp, lp}, w0 -> w1: the {LP, HP}
   weights at the start and end of the call, ramped sample by sample when they differ (a step would click). osc: the
   self-oscillation amount: between LP and HP, where LP + HP cancels the oscillation, 4 wl wh osc of the band-pass keeps
   it at the LP level; t0 -> t1 its level trim over the call. */
static void pv(float *x, int n, float f, float q, float *h, const float w0[2], const float w1[2], float drive,
               float osc, float t0, float t1)
{
    float fl = f * SLEW, bp = h[0], lp = h[1], wl = w0[0], wh = w0[1], fill = 4.0f * osc, wb = fill * wl * wh;
    int ramp = w0[0] != w1[0] || w0[1] != w1[1];
    float dl = ramp && n > 0 ? (w1[0] - wl) / (float)n : 0.0f, dh = ramp && n > 0 ? (w1[1] - wh) / (float)n : 0.0f;
    float trim = 0.5f * t0, dt = n > 0 ? 0.5f * (t1 - t0) / (float)n : 0.0f;
    if (drive > 0.001f) {
        float pre = 1.0f + 3.0f * drive;
        if (ramp)
            PV_LOOP(1, 1)
        else
            PV_LOOP(1, 0)
    } else {
        float pre = 1.0f;
        (void)pre;
        if (ramp)
            PV_LOOP(0, 1)
        else
            PV_LOOP(0, 0)
    }
    h[0] = bp;
    h[1] = lp;
}

/*
 * The same for a stereo voice (3.1.v1, CPU): both channels per sample, each with its own {bp, lp}; everything else
 * (f, q, the weights, the trim, the drive) is shared. Each channel's arithmetic is pv's in its order (bit-identical),
 * so the two channels' long dependent chains (two slew-limited steps per sample) overlap in the FPU's pipeline.
 */
#define PV_STEP_C(v, HP, BP, LP)                                                                                   \
    HP = (v) - q * BP - LP;                                                                                        \
    BP = clampf(BP + fl * slew(HP * (1.0f / SLEW)), RAIL);                                                         \
    LP = clampf(LP + fl * slew(BP * (1.0f / SLEW)), RAIL);

#define PV2_LOOP(DRIVEN, RAMP)                                                                                     \
    for (int i = 0; i < n; i++) {                                                                                  \
        if (RAMP) {                                                                                                \
            wl += dl;                                                                                              \
            wh += dh;                                                                                              \
            wb = fill * wl * wh;                                                                                   \
        }                                                                                                          \
        trim += dt;                                                                                                \
        float va = x0[i], vb = x1[i], hpa, hpb;                                                                    \
        if (DRIVEN) {                                                                                              \
            va = soft(va * pre, 1.0f, 1.0f);                                                                       \
            vb = soft(vb * pre, 1.0f, 1.0f);                                                                       \
        }                                                                                                          \
        PV_STEP_C(va, hpa, bpa, lpa)                                                                               \
        PV_STEP_C(vb, hpb, bpb, lpb)                                                                               \
        float oa = wl * lpa + wh * hpa + wb * bpa, ob = wl * lpb + wh * hpb + wb * bpb;                            \
        PV_STEP_C(va, hpa, bpa, lpa)                                                                               \
        PV_STEP_C(vb, hpb, bpb, lpb)                                                                               \
        x0[i] = trim * (oa + wl * lpa + wh * hpa + wb * bpa);                                                      \
        x1[i] = trim * (ob + wl * lpb + wh * hpb + wb * bpb);                                                      \
    }

static void pv2(float *x0, float *x1, int n, float f, float q, float *h0, float *h1, const float w0[2],
                const float w1[2], float drive, float osc, float t0, float t1)
{
    float fl = f * SLEW, bpa = h0[0], lpa = h0[1], bpb = h1[0], lpb = h1[1];
    float wl = w0[0], wh = w0[1], fill = 4.0f * osc, wb = fill * wl * wh;
    int ramp = w0[0] != w1[0] || w0[1] != w1[1];
    float dl = ramp && n > 0 ? (w1[0] - wl) / (float)n : 0.0f, dh = ramp && n > 0 ? (w1[1] - wh) / (float)n : 0.0f;
    float trim = 0.5f * t0, dt = n > 0 ? 0.5f * (t1 - t0) / (float)n : 0.0f;
    if (drive > 0.001f) {
        float pre = 1.0f + 3.0f * drive;
        if (ramp)
            PV2_LOOP(1, 1)
        else
            PV2_LOOP(1, 0)
    } else {
        float pre = 1.0f;
        (void)pre;
        if (ramp)
            PV2_LOOP(0, 1)
        else
            PV2_LOOP(0, 0)
    }
    h0[0] = bpa;
    h0[1] = lpa;
    h1[0] = bpb;
    h1[1] = lpb;
}

/*
 * The pad's Interp setting, read from the app's record of the pad (what the screen shows and presets save), not from
 * the engine's copy: the engine's pad reset (FUN_080596b0, the block that zeroes +0x550..+0x582) sets its copy back to
 * Normal, which in 3.1.d-f made the crunch drop out a moment after each change.
 * Engine pad id (pad +0x18) = bank << 16 | row << 8 | col; app pad record = app + 0x1840 + row * 0xf0 + col * 0x30
 * (FUN_08098d0c), read directly with cached positions (below) rather than the stock lookup FUN_08093e9c, which scans.
 */
#define APP_PADS   (0x24020088u + 0x1840u)


/* Settings stores: 8-byte entries {u16 id, pad, i32 value}, array at store + 4, count at store + 10 */
#define STORE_ENTRIES(store) (*(const uint8_t *const *)((const uint8_t *)(store) + 4))
#define STORE_COUNT(store)   (*(const uint16_t *)((const uint8_t *)(store) + 10))
#define ENTRY_ID(e, i)       (*(const uint16_t *)((e) + 8 * (i)))
#define ENTRY_VALUE(e, i)    (*(const int32_t *)((e) + 8 * (i) + 4))
#define ABSENT 0xff

/*
 * Fidelity (0xf1) is read up to three times per voice per block (filter, overdrive, reader), so each pad keeps where
 * in its record the entry sits: patch RAM 0x2405ff70..0x2405ff9b (the gap above the heap, free since the ducker went).
 * A cached position is used only if the entry there still has the id; otherwise the record is scanned again.
 */
struct interp_cache {
    uint32_t magic;
    uint8_t idx[20];
    uint8_t count[20];
};
#define IC     ((volatile struct interp_cache *)0x2405ff70u)
_Static_assert(sizeof(struct interp_cache) <= 0x30, "must end before slice.c's byte at 0x2405ffa0");
#define IMAGIC 0x49445831u       /* "IDX1" */

static __attribute__((noinline, optimize("Os"))) unsigned pad_interp(const uint8_t *pad)
{
    if (!pad)
        return 0;
    uint32_t id = *(const uint32_t *)(pad + 0x18);
    unsigned row = (id >> 8) & 0xff, col = id & 0xff;
    if (row >= 4 || col >= 5)
        return 0;
    const void *store = (const void *)(APP_PADS + row * 0xf0u + col * 0x30u);
    const uint8_t *e = STORE_ENTRIES(store);
    unsigned count = STORE_COUNT(store), slot = row * 5 + col;
    if (!e)
        return 0;
    if (IC->magic != IMAGIC) {
        for (unsigned i = 0; i < 20; i++)
            IC->idx[i] = ABSENT;
        IC->magic = IMAGIC;
    }
    unsigned k = IC->idx[slot];
    if (k != ABSENT && k < count && IC->count[slot] == (uint8_t)count && ENTRY_ID(e, k) == 0xf1)
        return (unsigned)ENTRY_VALUE(e, k);
    for (k = 0; k < count && ENTRY_ID(e, k) != 0xf1; k++)
        ;
    IC->idx[slot] = k < count ? (uint8_t)k : ABSENT;
    IC->count[slot] = (uint8_t)count;
    return k < count ? (unsigned)ENTRY_VALUE(e, k) : 0;
}

/* For od.c: this pad is in a machine mode, so its Saturation knob is the machine's input drive (applied here). */
int pad_machine_mode(const uint8_t *pad)
{
    unsigned interp = pad_interp(pad);
    return interp >= FIRST_MACHINE && interp < FIRST_MACHINE + MACHINES;
}

/* Saturation into the converter: gain, hard clip at full scale, level back */
static void adc_drive(float **ch, int n, float d)
{
    float gain = 1.0f + 7.0f * d * d;
    /* level back: a hard-clipped loud loop at full drive (+18 dB) lands near its original RMS (0.48 x a full-scale
       square vs a 0.8 sine); quiet material that never reaches the ceiling comes out louder, as with a hot SP input */
    float post = 1.0f / (1.0f + 1.1f * d * d);
    for (int k = 0; k < 2; k++) {
        float *x = ch[k];
        if (!x)
            continue;
        for (int i = 0; i < n; i++) {
            float v = x[i] * gain;
            v = v > 1.0f ? 1.0f : v < -1.0f ? -1.0f : v;
            x[i] = v * post;
        }
    }
}

/*
 * Everything this file needs from the app's pad record in one pass over its store (8-byte entries: u16 id at +0,
 * value at +4; array at store +4, count at store +10), instead of one stock lookup per setting. Settings missing from
 * the store (a pad record from before this build cannot have them: the defaults add them) keep their defaults.
 */
#define MAX_ROUTES 18              /* Morph, Wave, Level, Tune, and OSC to Filter / Level: three slots each */
struct pad_cfg {
    unsigned interp, drive;
    float morph;                                     /* 0 LP .. 0.5 notch .. 1 HP, before modulation */
    float attack, decay, sustain, release, depth;    /* seconds, seconds, level, seconds, cutoff travel -1..1 */
    unsigned routes, morph_routes;                   /* routes this file applies itself (below), of them to Morph */
    uint16_t source[MAX_ROUTES], dest[MAX_ROUTES];
    float amount[MAX_ROUTES];
    const void *store;                               /* the pad's record (0: none) */
};

/* A route this file applies: to Morph or the oscillator's Wave / Level / Tune (any source), or from OSC to Filter /
   Level (the oscillator in MOD mode, per sample) */
static int own_route(unsigned src, unsigned dest)
{
    return dest == P_FMORPH || dest == P_OSC_PW || dest == P_OSC_LEVEL || dest == P_OSC_TUNE ||
           (src == SRC_OSC && (dest == P_FILTER || dest == P_LEVEL));
}

static __attribute__((noinline, optimize("Os"))) float seg_time(int v)                       /* knob 0..1000 -> 60 x^3 seconds, 0 at 0 */
{
    float x = (float)v * 0.001f;
    x = x < 0.0f ? 0.0f : x > 1.0f ? 1.0f : x;
    return 60.0f * x * x * x;
}

/*
 * The filter's settings come from the pad record every block for every voice. Each voice keeps where its pad's entries
 * sit in the filter object at +0x74..+0x83 (only the replaced stock process used it): store, count and one position per
 * setting. Positions are checked against the entry id on every read; a different store, a different count or a
 * mismatch rescans. Settings the record does not have (a record from before this build) keep their defaults.
 */
#define CFG_IDS 9
static const uint16_t cfg_ids[CFG_IDS] = {0xf1, 0xdb, P_FMORPH, P_FATTACK, P_FDECAY, P_FSUSTAIN, P_FRELEASE, P_FDEPTH,
                                          P_FTYPE};
struct cfg_cache {
    const uint8_t *entries;
    uint8_t count;               /* a record holds at most 72 */
    uint8_t idx[CFG_IDS];
    uint8_t magic;
    uint8_t ad_idx;              /* where AD Attack sits (AD Decay follows it), 0 = look it up; checked on every read */
};
#define CFG_CACHE(obj) ((struct cfg_cache *)((obj) + 0x74))
#define CMAGIC 0x48u             /* "H": bumped with the layout */
_Static_assert(sizeof(struct cfg_cache) == 16, "the cache must fit +0x74..+0x83");

static __attribute__((noinline, optimize("Os"))) void pad_config(const uint8_t *pad, uint8_t *obj, struct pad_cfg *c)
{
    int v[CFG_IDS] = {0, 0, DEF_FMORPH, DEF_FATTACK, DEF_FDECAY, DEF_FSUSTAIN, DEF_FRELEASE, DEF_FDEPTH, DEF_FTYPE};
    c->routes = c->morph_routes = 0;
    c->store = 0;
    if (pad) {
        uint32_t id = *(const uint32_t *)(pad + 0x18);
        unsigned row = (id >> 8) & 0xff, col = id & 0xff;
        if (row < 4 && col < 5) {
            const void *store = (const void *)(APP_PADS + row * 0xf0u + col * 0x30u);
            const uint8_t *e = STORE_ENTRIES(store);
            unsigned count = STORE_COUNT(store);
            struct cfg_cache *cc = CFG_CACHE(obj);
            c->store = store;
            int ok = e && cc->magic == CMAGIC && cc->entries == e && cc->count == count;
            for (unsigned k = 0; ok && k < CFG_IDS; k++) {
                unsigned i = cc->idx[k];
                if (i == ABSENT)
                    continue;
                if (i >= count || ENTRY_ID(e, i) != cfg_ids[k])
                    ok = 0;
                else
                    v[k] = ENTRY_VALUE(e, i);
            }
            if (!ok && e) {
                for (unsigned k = 0; k < CFG_IDS; k++)
                    cc->idx[k] = ABSENT;
                for (unsigned i = 0; i < count; i++) {
                    unsigned eid = ENTRY_ID(e, i);
                    if (eid != 0xf1 && eid != 0xdb && eid - P_FTYPE > P_FRELEASE - P_FTYPE)
                        continue;                       /* not one of ours: most of the record */
                    for (unsigned k = 0; k < CFG_IDS; k++)
                        if (eid == cfg_ids[k]) {
                            cc->idx[k] = (uint8_t)i;
                            v[k] = ENTRY_VALUE(e, i);
                        }
                }
                cc->entries = e;
                cc->count = (uint8_t)count;
                cc->magic = CMAGIC;
            }
            /* The AD envelope's pair: records hold Attack and Decay side by side, so one position covers both */
            unsigned ai = cc->ad_idx;
            if (!(e && ai && ai + 1 < count && ENTRY_ID(e, ai) == P_ADATTACK && ENTRY_ID(e, ai + 1) == P_ADDECAY)) {
                ai = 0;
                for (unsigned i = 1; e && i + 1 < count; i++)
                    if (ENTRY_ID(e, i) == P_ADATTACK && ENTRY_ID(e, i + 1) == P_ADDECAY) {
                        ai = i;
                        break;
                    }
                cc->ad_idx = (uint8_t)ai;
            }
            /* A 3.1.9-syn preset: Type HP / BP becomes Morph 100 / 50 (BP has no Morph position: 50 is the notch)
               in the record itself, once (the next preset
               save stores it that way); Type goes back to LP so nothing converts again. */
            unsigned ti = cc->idx[8], mi = cc->idx[2];
            if (e && (v[8] == 1 || v[8] == 2) && ti != ABSENT && mi != ABSENT) {
                v[2] = v[8] == 1 ? 1000 : 500;
                *(int32_t *)(uintptr_t)(e + 8 * mi + 4) = v[2];
                *(int32_t *)(uintptr_t)(e + 8 * ti + 4) = 0;
                v[8] = 0;
            }
            /* modulation routes (12 bytes: amount at +0 as s16 / 1000, source +4, destination +6, slot +8; array at
               store + 0x10, count at + 0x14): the few this file applies (own_route). Short list, read every block. */
            const uint8_t *rt = *(const uint8_t *const *)((const uint8_t *)store + 0x10);
            unsigned nr = *(const uint16_t *)((const uint8_t *)store + 0x14);
            for (unsigned i = 0; rt && i < nr && c->routes < MAX_ROUTES; i++, rt += 12) {
                unsigned src = *(const uint16_t *)(rt + 4), dst = *(const uint16_t *)(rt + 6);
                if (src != 0 && *(const int16_t *)rt != 0 && own_route(src, dst)) {   /* amount 0 cannot move it */
                    c->source[c->routes] = (uint16_t)src;
                    c->dest[c->routes] = (uint16_t)dst;
                    c->amount[c->routes] = (float)*(const int16_t *)rt * 0.001f;
                    c->morph_routes += dst == P_FMORPH;
                    c->routes++;
                }
            }
        }
    }
    c->interp = (unsigned)v[0];
    c->drive = (unsigned)v[1];
    c->morph = v[2] < 0 ? 0.0f : v[2] > 1000 ? 1.0f : (float)v[2] * 0.001f;
    c->attack = seg_time(v[3]);
    c->decay = seg_time(v[4]);
    c->sustain = v[5] < 0 ? 0.0f : v[5] > 1000 ? 1.0f : (float)v[5] * 0.001f;
    c->release = seg_time(v[6]);
    c->depth = v[7] < -1000 ? -1.0f : v[7] > 1000 ? 1.0f : (float)v[7] * 0.001f;
}

/*
 * The filter envelope, one per voice, in the filter object at +0x44..+0x5f: the stock voice start zeroes that range
 * (FUN_08076704 via FUN_080766d0), so a new note always begins IDLE at level 0. +0x44 is also the FENV modulation
 * source object: the engine reads a source's value at +4 (here: level), and never its first word.
 */
struct envstate {
    float ad_level;              /* +0x44: 0..1, the AD source value (its object at +0x40); FENV's object word 0,
                                    which the engine never reads (it reads a source's value at pointer + 4) */
    float level;                 /* +0x48: 0..1, the FENV source value */
    uint8_t stage;               /* +0x4c */
    uint8_t amp_last;            /* +0x4d: amp envelope stage at the previous step */
    uint8_t pad[1];              /* +0x4e: BYPASSED (below) */
    uint8_t ad_stage;            /* +0x4f: the AD envelope's stage */
    float base;                  /* +0x50: smoothed cutoff position 0..1 (knob part only) */
    float t;                     /* +0x54: seconds into the decay / release segment */
};
enum { ENV_IDLE, ENV_ATTACK, ENV_DECAY, ENV_SUSTAIN, ENV_RELEASE, ENV_DONE };
enum { AD_IDLE, AD_ATTACK, AD_DECAY, AD_DONE };
#define ENV(obj) ((struct envstate *)((obj) + 0x44))
#define SUB      32              /* frames per envelope / cutoff step */
#define MAX_SUBS 16

/* 2^x, bit trick with a quadratic correction (~0.3%) */
static inline __attribute__((always_inline)) float exp2f_fast(float x)
{
    if (x < -30.0f)
        return 0.0f;
    int i = (int)x - (x < 0.0f);
    float f = x - (float)i;
    float p = 1.0f + f * (0.6565f + f * 0.3435f);
    union { float f; uint32_t u; } u = {p};
    u.u += (uint32_t)i << 23;
    return u.f;
}

/* Exponential segment: covers 99% of the way to the target in t seconds (log2(100) = 6.6439) */
static __attribute__((noinline, optimize("Os"))) float approach(float level, float target, float t, float dt)
{
    if (t <= dt)
        return target;
    return target + (level - target) * exp2f_fast(-6.6439f * dt / t);
}

/* Advance one step of dt seconds. amp = the voice's amp envelope stage (0 idle, 1 attack, 2 decay, 3 sustain,
   4 release, 5 done). A fresh attack of the amp envelope (stage back to 1 from a later stage: a mono / legato
   retrigger without a voice start) restarts the attack from the current level. */
static __attribute__((noinline, optimize("Os"))) void env_step(struct envstate *e, unsigned amp, const struct pad_cfg *c, float dt)
{
    int gate = amp >= 1 && amp <= 3;
    if (amp == 1 && e->amp_last > 1 && e->stage != ENV_ATTACK)
        e->stage = ENV_ATTACK;
    e->amp_last = (uint8_t)amp;
    switch (e->stage) {
    case ENV_IDLE:
    case ENV_DONE:                                   /* finished: a later gate (legato, amp past its attack) restarts */
        if (!gate) {
            e->level = 0.0f;
            return;
        }
        e->stage = ENV_ATTACK;
        /* fall through */
    case ENV_ATTACK:
        if (!gate) {
            e->stage = ENV_RELEASE;
            e->t = 0.0f;
            break;
        }
        e->level = c->attack <= dt ? 1.0f : e->level + dt / c->attack;
        if (e->level >= 1.0f) {
            e->level = 1.0f;
            e->stage = ENV_DECAY;
            e->t = 0.0f;
        }
        return;
    case ENV_DECAY:
        if (!gate) {
            e->stage = ENV_RELEASE;
            e->t = 0.0f;
            break;
        }
        /* exponential, 99% of the way at the Decay time, where it lands on Sustain (a step of under 1%) */
        e->t += dt;
        if (e->t >= c->decay) {
            e->level = c->sustain;
            e->stage = ENV_SUSTAIN;
        } else {
            e->level = approach(e->level, c->sustain, c->decay, dt);
        }
        return;
    case ENV_SUSTAIN:
        if (!gate) {
            e->stage = ENV_RELEASE;
            e->t = 0.0f;
            break;
        }
        e->level = c->sustain;                       /* follows the knob */
        return;
    case ENV_RELEASE:
        if (gate) {                                  /* re-gated without a voice start */
            e->stage = ENV_ATTACK;
            return;
        }
        break;
    default:
        e->stage = ENV_IDLE;
        e->level = 0.0f;
        return;
    }
    /* release, from wherever the level is: exponential, 99% of the way at the Release time, where it ends at 0 */
    e->t += dt;
    if (e->t >= c->release) {
        e->level = 0.0f;
        e->stage = ENV_DONE;
    } else {
        e->level = approach(e->level, 0.0f, c->release, dt);
    }
}

/* The AD envelope's slopes (3.1.v7): each stage follows (1 - e^(-k x)) / (1 - e^(-k)) of its time x (0..1), k from the
   Slope knob, 0 at 50 % (linear). Dec Slope: k = +10 at 0 % (a fast drop, then a tail), -10 at 100 % (holds, then falls
   late). Atk Slope the other way round (the user's choice): k = -10 at 0 % (a slow start, then late), +10 at 100 % (a
   fast rise easing into full). The attack rises along it, the decay falls along its mirror (1 - curve). Each stage still ends exactly at its time. Its place in the
   stage, x, is kept in the filter state's spare word (the 2-pole filters leave s2[1][0] unused; it survives the
   filter-type reset); a voice start zeroes the stage (+0x4f), and x restarts at 0 with it. */
#define AD_X(obj) (*(float *)((obj) + 4 + __builtin_offsetof(struct fstate, s2[1][0])))
#define LOG2E 1.4426950f

static inline float ad_k(int slope)
{
    return 10.0f * (1.0f - (float)slope * 0.002f);
}

static float ad_curve(float x, float k)
{
    if (k > -0.001f && k < 0.001f)
        return x;
    float a = -k * LOG2E;
    return (1.0f - exp2f_fast(a * x)) / (1.0f - exp2f_fast(a));
}

/* log2 for x > 0: the float's exponent plus a quadratic on the mantissa (error < 0.01) */
static float log2_fast(float x)
{
    union { float f; uint32_t u; } v = {x};
    float e = (float)((int)((v.u >> 23) & 0xff) - 128);
    v.u = (v.u & 0x007fffffu) | 0x3f800000u;
    float m = v.f;
    return e + (-0.34484843f * m + 2.02466578f) * m - 0.67487759f;
}

/* where on the attack's curve the level y sits: the retrigger point (a mono / legato note restarts the attack from
   the level the envelope is at) */
static float ad_curve_inv(float y, float k)
{
    if (y <= 0.0f)
        return 0.0f;
    if (y >= 1.0f)
        return 1.0f;
    if (k > -0.001f && k < 0.001f)
        return y;
    float a = -k * LOG2E, d = 1.0f - exp2f_fast(a);
    float x = log2_fast(1.0f - y * d) / a;
    return x < 0.0f ? 0.0f : x > 1.0f ? 1.0f : x;
}

/* The AD envelope, one step of dt seconds: one-shot per note. It starts when the voice does (the stock voice start
   zeroes +0x40..+0x5f, so a new voice is AD_IDLE at level 0) and on a fresh attack of the amp envelope without a voice
   start (retrig: mono / legato), rises over Attack, then falls to 0 at the Decay time, along the slopes' curves. It
   ignores the gate: a short note still runs it to the end. */
static __attribute__((noinline, optimize("Os"))) void ad_step(struct envstate *e, float *xp, unsigned amp, int retrig,
                                                              float attack, float decay, float ka, float kd, float dt)
{
    if (retrig) {
        *xp = ad_curve_inv(e->ad_level, ka);
        e->ad_stage = AD_ATTACK;
    } else if (e->ad_stage == AD_IDLE && amp >= 1 && amp <= 4) {
        *xp = 0.0f;
        e->ad_stage = AD_ATTACK;
    }
    float x = *xp;
    switch (e->ad_stage) {
    case AD_ATTACK:
        x = attack <= dt ? 1.0f : x + dt / attack;
        if (x >= 1.0f) {
            e->ad_level = 1.0f;
            e->ad_stage = AD_DECAY;
            x = 0.0f;
        } else {
            e->ad_level = ad_curve(x, ka);
        }
        break;
    case AD_DECAY:
        x = decay <= dt ? 1.0f : x + dt / decay;
        if (x >= 1.0f) {
            e->ad_level = 0.0f;
            e->ad_stage = AD_DONE;
            x = 0.0f;
        } else {
            e->ad_level = 1.0f - ad_curve(x, kd);
        }
        break;
    default:
        e->ad_level = 0.0f;
        break;
    }
    *xp = x;
}

_Static_assert(sizeof(struct envstate) <= 0x14, "envstate must end before +0x58 (glide.c's per-voice state)");

/* The stock LFO update (FUN_0806f108; 3.1.v7: its Depth fixed at 100 %, patches/fenv.py; it always loops: 1-Shot is
   gone, the AD envelope does that job). */
typedef void (*lfo_fn)(uint8_t *lfo, int frames);
#define fw_lfo_update ((lfo_fn)FN(0x0806f108))

#define AD_SLOPE_K 12            /* (3.1.v7) Atk Slope, Dec Slope: after Osc Track (AD Attack + 3 + 8 + 1) */

/* The voice's pad record entry k after AD Attack (0 AD Attack, 1 AD Decay, 2 Filter Type, ...), through the filter's settings
   cache (filled by pad_config every block): def for a record without it (a preset from before), -1 while the cache
   doesn't describe this record (not filled yet, or out of date: pad_config fixes it later in the block) */
static int ad_setting(const uint8_t *obj, unsigned k, unsigned id, int def)
{
    const struct cfg_cache *cc = (const struct cfg_cache *)(obj + 0x74);
    if (cc->magic != CMAGIC || !cc->entries)
        return -1;
    if (!cc->ad_idx)
        return def;
    unsigned i = cc->ad_idx + k;
    if (i >= cc->count || ENTRY_ID(cc->entries, i) != id)
        return -1;
    return ENTRY_VALUE(cc->entries, i);
}

/* The AD envelope for one block, at its start: before the voice reads its modulated parameters (pitch, level, pan ...),
   so a note's first block already has the AD's attack (Attack 0: full at once) instead of a block of 0. Same 32-frame
   steps as the filter envelope. amp = the voice's amp envelope stage. */
static __attribute__((noinline, optimize("Os"))) void ad_block(uint8_t *obj, const uint8_t *amp, int n)
{
    struct envstate *env = ENV(obj);
    unsigned a = *amp;
    int retrig = a == 1 && env->amp_last > 1;            /* the amp stage the filter envelope saw last block */
    if (n <= 0 || (!retrig && (env->ad_stage == AD_DONE || (env->ad_stage == AD_IDLE && !(a >= 1 && a <= 4))))) {
        if (env->ad_stage == AD_DONE || env->ad_stage == AD_IDLE)
            env->ad_level = 0.0f;                        /* at rest */
        return;
    }
    int va = ad_setting(obj, 0, P_ADATTACK, DEF_ADATTACK), vd = ad_setting(obj, 1, P_ADDECAY, DEF_ADDECAY);
    if (va < 0 || vd < 0)
        return;                                      /* settings not known yet: start next block, not with wrong ones */
    int sa = ad_setting(obj, AD_SLOPE_K, P_ADATKSLOPE, DEF_ADATKSLOPE);
    int sd = ad_setting(obj, AD_SLOPE_K + 1, P_ADDECSLOPE, DEF_ADDECSLOPE);
    if (sa < 0)
        sa = DEF_ADATKSLOPE;                         /* (the cache knows the record, which doesn't have them) */
    if (sd < 0)
        sd = DEF_ADDECSLOPE;
    float attack = seg_time(va), decay = seg_time(vd), ka = ad_k(1000 - sa), kd = ad_k(sd);   /* (Atk Slope reversed: 0 % slow, 100 % fast) */
    for (int at = 0; at < n; at += SUB) {
        int len = n - at < SUB ? n - at : SUB;
        ad_step(env, &AD_X(obj), a, retrig && at == 0, attack, decay, ka, kd, (float)len * (1.0f / FS));
    }
}

static __attribute__((noinline, optimize("Os"))) void lfo_update(uint8_t *lfo, int frames, uint8_t *obj, const uint8_t *amp)
{
    ad_block(obj, amp, frames);
    fw_lfo_update(lfo, frames);                      /* (3.1.v7: always looping; LFO Mode / 1-Shot is no longer read) */
}

/* Replace the LFO update calls, the first thing each voice does per block: sample voice (bl @0x08056ff8) and
   multisample voice (@0x0805800a), LFO at voice + 0x4e8, filter object at voice + 0xa8, amp stage at filter - 0x7c;
   clip / slicer voice (@0x08066838), LFO at block + 0xf0, filter at block + 0x14c, amp stage at filter + 0x110 */
void lfo_update_a(uint8_t *lfo, int frames)
{
    uint8_t *obj = lfo - 0x4e8 + 0xa8;
    lfo_update(lfo, frames, obj, obj - 0x7c);
}

void lfo_update_b(uint8_t *lfo, int frames)
{
    uint8_t *obj = lfo - 0xf0 + 0x14c;
    lfo_update(lfo, frames, obj, obj + 0x110);
}

void glide_advance(uint8_t *filter_obj, int frames);

/*
 * Morph modulation, applied here rather than through the engine's routing (its destinations are a fixed table in stock
 * code): the value of each source for this voice, read where the stock routing would point a slot.
 *   sample voices (amp stage at obj - 0x7c): voice = obj - 0xa8; VEL +0x88, KEY +0x90, LFO +0x524;
 *     MIDI pitch bend / mod wheel / volume / pan at pad +0x140 / +0x128 / +0x130 / +0x138
 *   clip / slicer voices (amp stage at obj + 0x110): block = obj - 0x14c; VEL +0x4c, KEY +0x54, LFO +0x12c;
 *     MIDI at pad +0xb64 / +0xb4c / +0xb54 / +0xb5c
 *   FENV: the voice's own envelope level, per 32-frame step. CC (0x8000) is not read: stock routes it elsewhere.
 */
static __attribute__((noinline, optimize("Os"))) float source_value(unsigned src, const uint8_t *obj, const uint8_t *pad, const uint8_t *amp)
{
    int b = amp == obj + 0x110;                          /* clip / slicer voice */
    const uint8_t *v = b ? obj - 0x14c : obj - 0xa8;
    const uint8_t *at = 0;
    switch (src) {
    case 0x0d: at = v + (b ? 0x4c : 0x88); break;        /* VEL */
    case 0x0e: at = v + (b ? 0x54 : 0x90); break;        /* KEY */
    case 0x04: at = v + (b ? 0x12c : 0x524); break;      /* LFO */
    case 0x19: at = pad ? pad + (b ? 0xb64 : 0x140) : 0; break;     /* pitch bend */
    case 0x1a: at = pad ? pad + (b ? 0xb4c : 0x128) : 0; break;     /* mod wheel */
    case 0x1c: at = pad ? pad + (b ? 0xb54 : 0x130) : 0; break;     /* MIDI volume */
    case 0x1d: at = pad ? pad + (b ? 0xb5c : 0x138) : 0; break;     /* MIDI pan */
    }
    if (!at || (amp != obj + 0x110 && amp != obj - 0x7c))
        return 0.0f;
    float x = *(const float *)at;
    return x == x && x > -4.0f && x < 4.0f ? x : 0.0f;
}

/* Morph 0..1 -> {LP, HP} weights: a plain crossfade, 1 - m and m, like the Oberheim SEM's mode pot. The sound tilts from
   LP to HP across the whole knob through the notch at 50 % (where everything else is 6 dB down per stage, 12 dB here).
   The end points are exact. */
static void morph_weights(float m, float w[2])
{
    if (m <= 0.0001f)
        m = 0.0f;
    else if (m >= 0.9999f)
        m = 1.0f;
    w[0] = 1.0f - m;
    w[1] = m;
}

/* Smoothed Morph (knob and block-rate sources) per voice, in the filter object at +0x88 (written only by the stock
   voice start, which also clears st->on, and st->on == 0 re-seeds it) */
#define MORPH_BASE(obj) (*(float *)((obj) + 0x88))
/* The {LP, HP} weights the last step ended on, +0x8c / +0x90 (the stock voice start writes 0.5 / 0 there; re-seeded
   whenever the filter starts) */
#define MPREV(obj)      (*(float *)((obj) + 0x8c))   /* the Morph value the last step ended on (its weights are
                                                         morph_weights of it); +0x90: the oscillator's phase */
/* envstate pad[0]: the filter was skipped mid-note at its open end (1: LP side, 2: HP side); zeroed at voice start */
#define FLAGS(env)      ((env)->pad[0])
#define BYPASSED(env)   (FLAGS(env) & 3u)
#define SET_BYPASSED(env, v) (FLAGS(env) = (uint8_t)((FLAGS(env) & ~3u) | (v)))
#define OSC_LIVE        0x80u    /* the oscillator has started this note (its phase is set) */
#define XFADE 32                 /* frames of dry -> filtered when the filter starts again mid-note */

/*
 * The oscillator (Osc tab, sample / multisample pads; 3.1.uo). One per voice, from the played note (KEY), the pad's
 * Pitch (with its modulation), glide, Octave (-3..+3), Tune (+-6 semitones) and Fine (+-50 cents). Wave runs
 * one of sine, square, triangle and saw (a list: not a modulation destination), each bent by Pulse W; the sine reads the stock LFO's
 * 4096-point table, square and pulse are band-limited at their edges (polyBLEP), the pulse is 25 % +- 20 % wide.
 * Every wave as loud as the sine (osc_w). Modulation only (3.1.v1: it no longer plays into the voice, the OSC/MOD
 * button is gone): silent, its signal (scaled by Level) is source OSC for the pad's Filter (cutoff, every 8 frames)
 * and Level (every frame). Off, or no route from OSC: nothing runs. (A preset's stored OSC/MOD setting is ignored.) Settings: stored after Filter Type, read by position like the AD pair.
 */
#define OSC_K      3             /* the oscillator's settings: AD Attack + 3.. (after AD Decay and Filter Type; 3.1.v7: LFO Mode gone) */
#define SINE_TABLE ((const float *)0x080e55fcu)      /* stock: 4096 floats, one cycle of sin */
#define OSC_PHASE(obj) (*(float *)((obj) + 0x90))
#define OSC_STEP   8             /* frames per cutoff step while OSC moves the filter (6 kHz; was 4: about a third
                                    of the voice's time went into the extra steps) */
#define OSC_READ   (OSC_SETTINGS + 1)                 /* + Osc Track, stored after them */
static const uint16_t osc_setting_ids[OSC_READ] = {P_OSC_ON, P_OSC_MODE, P_OSC_WAVE, P_OSC_LEVEL,
                                           P_OSC_OCT, P_OSC_TUNE, P_OSC_FINE, P_OSC_PW, P_OSC_TRACK};
static const int16_t osc_defs[OSC_READ] = {DEF_OSC_ON, DEF_OSC_MODE, DEF_OSC_WAVE, DEF_OSC_LEVEL,
                                          DEF_OSC_OCT, DEF_OSC_TUNE, DEF_OSC_FINE, DEF_OSC_PW, DEF_OSC_TRACK};

struct osc_run {
    int active;                  /* the oscillator runs this block */
    float dt, duty, gain;        /* cycles per frame, pulse width, output gain */
    int seg;                     /* the wave: 0 sine, 1 square, 2 triangle, 3 pulse */
    float to_filter, to_level;   /* MOD: route amounts OSC -> Filter, OSC -> Level */
};

/* 2^x for |x| < 30, within 3e-6 (0.004 cents): round to the nearest integer, a degree-5 polynomial on [-0.5, 0.5] */
static float exp2_acc(float x)
{
    int i = (int)(x + (x >= 0.0f ? 0.5f : -0.5f));
    float f = x - (float)i;
    float p = 1.0f + f * (0.69314718f + f * (0.24022651f + f * (0.05550411f + f * (0.00961813f + f * 0.00133336f))));
    union { float f; uint32_t u; } u = {p};
    u.u += (uint32_t)i << 23;
    return u.f;
}

static inline __attribute__((always_inline)) float blep(float t, float dt, float idt)
{
    if (t < dt) {
        t *= idt;
        return t + t - t * t - 1.0f;
    }
    if (t > 1.0f - dt) {
        t = (t - 1.0f) * idt;
        return t * t + t + t + 1.0f;
    }
    return 0.0f;
}

static inline __attribute__((always_inline)) float osc_wave(int k, float ph, float dt, float idt, float duty, float wa,
                                                           float wb)
{
    float raw = ph;
    if (k != 1)                                              /* sine / triangle / saw: the cycle bent at the width */
        ph = ph < duty ? ph * wa : 0.5f + (ph - duty) * wb;
    if (k == 0) {                                            /* sine: the stock table, linear between entries */
        float x = ph * 4096.0f;
        int i = (int)x;
        float a = SINE_TABLE[i & 4095], b = SINE_TABLE[(i + 1) & 4095];
        return a + (x - (float)i) * (b - a);
    }
    if (k == 2) {                                            /* triangle, in phase with the sine */
        float x = ph + 0.25f;
        x -= x >= 1.0f ? 1.0f : 0.0f;
        return 1.0f - 4.0f * __builtin_fabsf(x - 0.5f);
    }
    if (k == 3)                                              /* saw: rising, its drop at the cycle's end band-limited */
        return ph + ph - 1.0f - blep(raw, dt, idt);
    float d = duty;                                          /* square (a pulse off the centre), up at 0, down at d */
    float t2 = ph - d;
    t2 += t2 < 0.0f ? 1.0f : 0.0f;
    return (ph < d ? 1.0f : -1.0f) + blep(ph, dt, idt) - blep(t2, dt, idt);
}

/* Each wave's gain for the same loudness as the sine (RMS 0.707): square 1, triangle 0.577, saw 0.577 (at the centre
   width) */
static const float osc_w[4] = {1.0f, 0.70711f, 1.22474f, 1.22474f};
/* The DC a width off the centre gives each wave, per (2 width - 1): its mean is taken back out */
static const float osc_dc[4] = {0.63662f, 1.0f, 0.5f, -0.5f};

/* n frames of the oscillator into out from the voice's phase */
static void osc_render(uint8_t *obj, const struct osc_run *o, float *out, int n, float gain)
{
    float ph = OSC_PHASE(obj), dt = o->dt, idt = 1.0f / dt, duty = o->duty;
    float wa = 0.5f / duty, wb = 0.5f / (1.0f - duty);       /* (sine / triangle: each part of the bent cycle) */
    int k = o->seg;
    float g0 = gain * osc_w[k], dc = osc_dc[k] * (duty + duty - 1.0f);
    for (int i = 0; i < n; i++) {
        out[i] = g0 * (osc_wave(k, ph, dt, idt, duty, wa, wb) - dc);
        ph += dt;
        ph -= ph >= 1.0f ? 1.0f : 0.0f;
    }
    OSC_PHASE(obj) = ph;
}

/* MOD -> Filter: the wave at one phase (the renderer for one frame there; the voice's own phase is left as it was) */
static __attribute__((noinline, optimize("Os"))) float osc_at(uint8_t *obj, const struct osc_run *o, float ph)
{
    float keep = OSC_PHASE(obj), v;
    OSC_PHASE(obj) = ph - (float)(int)ph;
    osc_render(obj, o, &v, 1, o->gain);
    OSC_PHASE(obj) = keep;
    return v;
}

/* The block's oscillator from the pad's settings and their routes. Only sample voices (amp stage at obj - 0x7c) of a
   pad in Sample mode (multisample included, not granular). */
static __attribute__((noinline, optimize("Os"))) void osc_setup(uint8_t *obj, const struct pad_cfg *c, const uint8_t *pad, const uint8_t *amp,
                      struct osc_run *o)
{
    o->active = 0;
    if (amp != obj - 0x7c || !c->store || ad_setting(obj, OSC_K, P_OSC_ON, DEF_OSC_ON) != 1)
        return;
    /* (read here, not through ad_setting: its -1 for "missing" is a real value of Fine and Pulse W) */
    const struct cfg_cache *cc = (const struct cfg_cache *)(obj + 0x74);
    int v[OSC_READ];
    for (unsigned k = 0; k < OSC_READ; k++) {
        unsigned i = cc->ad_idx + OSC_K + k;
        v[k] = i < cc->count && ENTRY_ID(cc->entries, i) == osc_setting_ids[k] ? ENTRY_VALUE(cc->entries, i) : osc_defs[k];
    }
    if (fw_setting(c->store, 0x8b) != 0)                    /* pad mode: 0 sample (3 granular) */
        return;
    struct envstate *env = ENV(obj);
    float mp = 0.0f, ml = 0.0f, mt = 0.0f;
    o->to_filter = o->to_level = 0.0f;
    for (unsigned i = 0; i < c->routes; i++) {
        unsigned d = c->dest[i], src = c->source[i];
        if (src == SRC_OSC) {
            if (d == P_FILTER)
                o->to_filter += c->amount[i];
            else if (d == P_LEVEL)
                o->to_level += c->amount[i];
            continue;
        }
        float x = src == SRC_FENV ? env->level : src == SRC_AD ? env->ad_level : source_value(src, obj, pad, amp);
        float a = c->amount[i] * x;
        mp += d == P_OSC_PW ? a : 0.0f;
        ml += d == P_OSC_LEVEL ? a : 0.0f;
        mt += d == P_OSC_TUNE ? a : 0.0f;
    }
    if (o->to_filter == 0.0f && o->to_level == 0.0f)
        return;                                              /* nothing listening: no DSP */
    if (!(FLAGS(env) & OSC_LIVE)) {                          /* a new note: start the cycle */
        OSC_PHASE(obj) = 0.0f;
        FLAGS(env) |= OSC_LIVE;
    }
    const uint8_t *voice = obj - 0xa8;
    float key = *(const float *)(voice + 0x90);              /* (note - 60) / 60 */
    float tune = (float)v[5] * 0.001f + mt;
    tune = tune < 0.0f ? 0.0f : tune > 1.0f ? 1.0f : tune;
    float semis = (tune - 0.5f) * 12.0f + (float)v[6] * 0.0005f;                            /* + fine */
    float oct = (float)(v[4] - 3);
    if (v[8])                                                /* Osc Track On: the note, the pad's Pitch, glide */
        oct += key * 5.0f + fw_param((void *)(voice + 0x288)) + *(const float *)(obj + 0x58) * (1.0f / 12.0f);
    oct += semis * (1.0f / 12.0f);
    float hz = 261.6256f * exp2_acc(oct < -14.0f ? -14.0f : oct > 7.0f ? 7.0f : oct);
    o->dt = (hz > 0.45f * FS ? 0.45f * FS : hz) * (1.0f / FS);
    int wave = v[2] > 3 ? (v[2] + 166) / 333 : v[2];        /* (an older build's 0..1000 Wave: the nearest wave, */
    if (v[2] > 3 && wave == 3)                               /* its pulse -> Square) */
        wave = 1;
    o->seg = wave < 0 ? 0 : wave > 3 ? 3 : wave;
    /* Pulse W, every wave's width: 50 % +- 45 % on the knob (50 %: the plain wave; Square off the centre is a pulse);
       a route at 100 % moves it the knob's whole travel each way; 3 .. 97 % */
    float duty = 0.5f + 0.45f * ((float)v[7] * 0.001f + mp);
    o->duty = duty < 0.03f ? 0.03f : duty > 0.97f ? 0.97f : duty;
    float level = (float)v[3] * 0.001f + ml;
    level = level < 0.0f ? 0.0f : level > 1.0f ? 1.0f : level;
    o->gain = level;
    o->active = 1;
}

/* Replaces the per-voice filter call. pad = the pad object the voice belongs to, amp = the voice's amp envelope stage
   byte (thunks in filter_thunk.S). */
void filter_process(uint8_t *obj, void *buf, const uint8_t *pad, const uint8_t *amp)
{
    struct pad_cfg cfg;
    pad_config(pad, obj, &cfg);

    /* the envelope runs for every block, silent or not, so FENV keeps moving for the other destinations */
    struct envstate *env = ENV(obj);
    int n = fw_buf_frames(buf);
    glide_advance(obj, n);                              /* the voice's pitch slide (glide.c), same block clock */
    struct osc_run om;
    osc_setup(obj, &cfg, pad, amp, &om);
    int osc_filter = om.active && om.to_filter != 0.0f;
    int sub = SUB, subs = 0;
    float levels[MAX_SUBS];
    if (n > 0) {
        if (n > sub * MAX_SUBS)
            sub = (n + MAX_SUBS - 1) / MAX_SUBS;
        subs = (n + sub - 1) / sub;
        unsigned a = amp ? *amp : 0;
        int gate = a >= 1 && a <= 3;
        if (((env->stage == ENV_IDLE || env->stage == ENV_DONE) && !gate) ||
            (env->stage == ENV_SUSTAIN && gate && a != 1)) {
            /* not moving (at rest, or holding Sustain): one step for the whole block gives the same levels */
            env_step(env, a, &cfg, (float)n * (1.0f / FS));
            for (int k = 0; k < subs; k++)
                levels[k] = env->level;
        } else {
            for (int k = 0; k < subs; k++) {
                int len = k == subs - 1 ? n - k * sub : sub;
                env_step(env, a, &cfg, (float)len * (1.0f / FS));
                levels[k] = env->level;
            }
        }
    }

    if (fw_buf_silent(buf))
        return;
    struct fstate *st = (struct fstate *)(obj + 4);
    /* the pad's Filter Type (stored after AD Decay); a voice whose state is another filter's starts it afresh */
    int model = ad_setting(obj, 2, P_FMODEL, DEF_FMODEL);
    if (model < 0 || model >= FMODELS)
        model = DEF_FMODEL;
    if (st->magic != magics[model]) {
        uint32_t *w = (uint32_t *)st;
        for (unsigned i = 0; i < sizeof *st / 4; i++)
            if (i != __builtin_offsetof(struct fstate, s2[1][0]) / 4)    /* (the AD envelope's place: kept) */
                w[i] = 0;
        st->magic = magics[model];
    }
    unsigned interp = cfg.interp;
    int crunching = interp >= STOCK_INTERP && interp < STOCK_INTERP + CRUNCHES + MACHINES;
    uint8_t *params = *(uint8_t **)(obj + OBJ_PARAMS);
    float knob = params ? fw_param(params + 8) : 1.0f;
    float pos = (knob + 1.0f) * 0.5f;                       /* cutoff position 0..1 on the stock curve */
    pos = pos < 0.0f ? 0.0f : pos > 1.0f ? 1.0f : pos;
    /* Morph: the knob plus its routes; FENV routes move with the envelope per step and AD with the block (advanced at
       its start, see ad_block), both after the knob's smoothing; the rest once per block, smoothed with the knob */
    float morph = cfg.morph, morph_env = 0.0f, morph_ad = 0.0f;
    for (unsigned i = 0; i < cfg.routes; i++) {
        if (cfg.dest[i] != P_FMORPH)
            continue;
        if (cfg.source[i] == SRC_FENV)
            morph_env += cfg.amount[i];
        else if (cfg.source[i] == SRC_AD)
            morph_ad += cfg.amount[i] * env->ad_level;
        else
            morph += cfg.amount[i] * source_value(cfg.source[i], obj, pad, amp);
    }
    /* skipped only when it cannot change the sound: LP fully open or HP fully closed, nothing moving it. While it runs,
       it stops only once its own glides have reached that end (stopping as soon as the knob does jumps from filtered to
       dry: a click). */
    float res = params ? fw_param(params + 0x44) : 0.0f;
    float osc = (res - OSC_FROM) * (1.0f / (1.0f - OSC_FROM));       /* self-oscillation 0..1, smoothstep */
    osc = osc < 0.0f ? 0.0f : osc > 1.0f ? 1.0f : osc * osc * (3.0f - 2.0f * osc);
    /* (a self-oscillating filter is never skipped: it sounds even at the open ends) */
    int still = cfg.depth == 0.0f && cfg.morph_routes == 0 && osc == 0.0f && !(st->on && st->osc > 0.0001f) &&
                !om.active;                              /* (the oscillator moves the filter / level) */
    int lp_open = cfg.morph <= 0.0001f && pos >= 0.999f, hp_open = cfg.morph >= 0.9999f && pos <= 0.001f;
    if (st->on) {
        float mb = MORPH_BASE(obj), b = env->base;
        lp_open = lp_open && mb <= 0.0001f && b >= 0.999f;
        hp_open = hp_open && mb >= 0.9999f && b <= 0.001f;
    }
    int active = !(still && (lp_open || hp_open));
    if (!active) {
        if (st->on)
            SET_BYPASSED(env, lp_open ? 1u : 2u);
        st->on = 0;
        if (!crunching)
            return;
    }

    float *ch[2] = {0, 0};
    fw_buf_chans(buf, &ch[0], &ch[1]);
    if (!ch[0] || n <= 0)
        return;
    if (interp >= FIRST_MACHINE && interp < FIRST_MACHINE + MACHINES) {
        const struct machine *m = &machines[interp - FIRST_MACHINE];
        float d = (float)cfg.drive * 0.001f;
        if (d > 0.0f)
            adc_drive(ch, n, d > 1.0f ? 1.0f : d);
        if (m->hold) {
            crunch(st, ch, n, m->grid);
        } else {
            for (int k = 0; k < 2; k++)
                if (ch[k])
                    for (int i = 0; i < n; i++)
                        ch[k][i] = quantize12(ch[k][i]);
        }
        if (!m->raw)
            out_stage(obj, ch, n, m->out);
    } else if (crunching) {
        crunch(st, ch, n, crunch_rate[interp - FIRST_CRUNCH]);
    }
    if (!active)
        return;

    /* Res below noon: the stock curve (made for its 12 dB biquad) runs down to Q 0.1, which splits the resonant stage
       into two far-apart real poles: a sagging passband and a soft knee. Here it runs from a flat, no-peak Q (the SEM:
       0.541, its first stage's Butterworth Q, so it stays 24 dB/oct; the 2-pole filters: 0.707) up to the stock noon
       value 0.1 * 2^3.75 = 1.345 on a log scale. Noon and above are stock. */
    float q;
    if (res < 0.5f)
        q = Q_RES_LOW2 * exp2f_fast((res > 0.0f ? 2.0f * res : 0.0f) * 0.92806f); /* log2(1.345/0.707): both 2-pole */
    else
        q = fw_res_q(res);
    float drive = (res - 0.5f) * 2.0f;                      /* 0 up to the default Res, 1 at full */
    drive = drive < 0.0f ? 0.0f : drive > 1.0f ? 1.0f : drive * drive;
    if (!(q > 0.1f))
        q = 0.1f;                                            /* the stock curve's own minimum (Res at 0) */
    if (q > 40.0f)
        q = 40.0f;
    float r = 1.0f / q - osc * (R_FULL - (model == MODEL_PV ? R_TOP_PV : R_TOP));
    int xfade = 0;
    float osc_from = st->osc;                                /* Polivoks: its trim follows osc across the block */
    if (!st->on) {
        st->r = r;
        st->drive = drive;
        st->osc = osc;
        if (BYPASSED(env)) {
            /* starting again mid-note: from the open end it stopped at, gliding to the knob, faded in from dry */
            env->base = BYPASSED(env) == 1 ? 1.0f : 0.0f;
            MORPH_BASE(obj) = BYPASSED(env) == 1 ? 0.0f : 1.0f;
            xfade = 1;
            SET_BYPASSED(env, 0u);
        } else {
            env->base = pos;                                 /* a new note starts where the knobs are */
            MORPH_BASE(obj) = morph;
        }
        float m0 = MORPH_BASE(obj) + morph_ad + morph_env * (subs ? levels[0] : 0.0f);
        MPREV(obj) = m0 < 0.0f ? 0.0f : m0 > 1.0f ? 1.0f : m0;
        for (int k = 0; k < 2; k++)
            for (int j = 0; j < 4; j++)
                st->h[k][j] = 0.0f;
        st->on = 1;
        osc_from = osc;
    } else {
        st->r += SMOOTH * (r - st->r);
        st->drive += SMOOTH * (drive - st->drive);
        st->osc += SMOOTH * (osc - st->osc);
    }
    /* knob changes glide like the stock per-block smoothing (1/3 per block), spread over the steps */
    float glide = 1.0f - exp2f_fast(-0.585f * (float)sub / 256.0f);      /* (2/3)^(sub/256) */
    for (int k = 0; k < subs; k++) {
        int at = k * sub, len = k == subs - 1 ? n - at : sub;
        env->base += glide * (pos - env->base);
        MORPH_BASE(obj) += glide * (morph - MORPH_BASE(obj));
        float m = MORPH_BASE(obj) + morph_ad + morph_env * levels[k];
        float w[2], w0[2];
        morph_weights(MPREV(obj), w0);
        m = m < 0.0f ? 0.0f : m > 1.0f ? 1.0f : m;
        morph_weights(m, w);
        MPREV(obj) = m;
        float p = env->base + cfg.depth * levels[k];
        float om_buf[SUB], ph_step = OSC_PHASE(obj);
        int om_on = om.active && om.to_level != 0.0f && len <= SUB;
        if (om_on)                                           /* MOD -> Level: every frame, band-limited */
            osc_render(obj, &om, om_buf, len, om.gain);
        else if (osc_filter) {                               /* (otherwise just its phase moves on) */
            float ph = ph_step + om.dt * (float)len;
            OSC_PHASE(obj) = ph - (float)(int)ph;
        }
        float dry[2][XFADE];
        int xl = xfade && k == 0 ? (len < XFADE ? len : XFADE) : 0;
        for (int c = 0; c < 2; c++)
            for (int i = 0; ch[c] && i < xl; i++)
                dry[c][i] = ch[c][at + i];
        /* MOD -> Filter: the step in 8-frame chunks, each with only its cutoff moved by the oscillator (its value at
           the chunk's middle); the envelope, Morph and glide keep their 32-frame steps */
        int clen = osc_filter ? OSC_STEP : len;
        for (int c0 = 0; c0 < len; c0 += clen) {
            int cl = len - c0 < clen ? len - c0 : clen;
            float pc = p;
            if (osc_filter)
                pc += 0.5f * om.to_filter * osc_at(obj, &om, ph_step + om.dt * ((float)c0 + 0.5f * (float)cl));
            pc = pc < 0.0f ? 0.0f : pc > 1.0f ? 1.0f : pc;   /* route 100 %: the knob's whole travel each way */
            float hz = fw_cutoff_hz(pc);
            if (hz < 10.0f)
                hz = 10.0f;
            if (hz > (model == MODEL_PV ? FC_MAX : 0.45f * FS))
                hz = model == MODEL_PV ? FC_MAX : 0.45f * FS;
            float g = 0.0f, kg = 0.0f, cs = 1.0f, t0 = 1.0f, t1 = 1.0f;
            int a0 = at + c0;
            if (model == MODEL_PV) {
                /* the integrators' coefficient 2 sin(pi fc / 2 fs); the trim follows osc across the block */
                float a = PI_F * 0.5f / FS * hz, a2 = a * a;
                g = 2.0f * a * (1.0f - a2 * (1.0f / 6.0f) * (1.0f - a2 * (1.0f / 20.0f)));
                t0 = 1.0f - OSC_TRIM * (osc_from + (st->osc - osc_from) * (float)a0 / (float)n);
                t1 = 1.0f - OSC_TRIM * (osc_from + (st->osc - osc_from) * (float)(a0 + cl) / (float)n);
            } else {
                g = tan_approx(PI_F * hz / FS);
                kg = KAP * st->osc / (1.0f + g * g);
                cs = g > G_REF ? 1.0f - st->osc * (1.0f - G_REF / g) : 1.0f;
            }
            float wa[2] = {w0[0], w0[1]}, wb[2] = {w[0], w[1]};
            if (cl != len) {                                 /* Morph's ramp across the step, piece by piece */
                float fa = (float)c0 / (float)len, fb = (float)(c0 + cl) / (float)len;
                for (int q = 0; q < 2; q++) {
                    wa[q] = w0[q] + (w[q] - w0[q]) * fa;
                    wb[q] = w0[q] + (w[q] - w0[q]) * fb;
                }
            }
            if (model == MODEL_SEM && ch[0] && ch[1]) {     /* stereo: both channels in one loop */
                float rcs[2];
                for (int c = 0; c < 2; c++) {
                    float b1 = st->s1[0][c], b2 = st->s2[0][c];
                    rcs[c] = cs * (st->r + kg * (b1 * b1 + b2 * b2));
                }
                float *sv0[3] = {&st->s1[0][0], &st->s2[0][0], &st->s1[1][0]};
                float *sv1[3] = {&st->s1[0][1], &st->s2[0][1], &st->s1[1][1]};
                svf1x2(ch[0] + a0, ch[1] + a0, cl, g, rcs[0], rcs[1], sv0, sv1, wa, wb, st->drive, st->osc);
            } else if (model == MODEL_PV && ch[0] && ch[1]) {   /* Polivoks, stereo: both channels in one loop */
                pv2(ch[0] + a0, ch[1] + a0, cl, g, st->r, st->h[0], st->h[1], wa, wb, st->drive, st->osc, t0, t1);
            } else for (int c = 0; c < 2; c++) {
                if (!ch[c])
                    continue;
                if (model == MODEL_SEM) {
                    /* amplitude control: the stage's energy from its states (s1 = bp + g hp, s2 = lp + g bp, and at
                       the cutoff hp = -lp, so s1^2 + s2^2 = (1 + g^2)(bp^2 + lp^2)) */
                    float b1 = st->s1[0][c], b2 = st->s2[0][c];
                    float rc = cs * (st->r + kg * (b1 * b1 + b2 * b2));
                    float *sv[3] = {&st->s1[0][c], &st->s2[0][c], &st->s1[1][c]};
                    svf1(ch[c] + a0, cl, g, rc, sv, wa, wb, st->drive, st->osc);
                } else {
                    pv(ch[c] + a0, cl, g, st->r, st->h[c], wa, wb, st->drive, st->osc, t0, t1);
                }
            }
        }
        for (int c = 0; c < 2; c++) {
            if (!ch[c])
                continue;
            for (int i = 0; i < xl; i++)                    /* dry -> filtered over the first XFADE frames */
                ch[c][at + i] = dry[c][i] + (ch[c][at + i] - dry[c][i]) * ((float)(i + 1) / (float)xl);
            if (om_on)                                       /* MOD -> Level: per frame (AM; past 100 % ring) */
                for (int i = 0; i < len; i++)
                    ch[c][at + i] *= 1.0f + om.to_level * om_buf[i];
        }
    }
}

/*
 * The voice reader. Sample / multisample voices read their sample through FUN_08055f0c, which fetches the source into a
 * scratch buffer and resamples it with one of two kernels chosen by the stock Interp value: FUN_080619d0 (Normal,
 * 4-point cubic) or FUN_08061a64 (HighQ, Hermite). Both take (rate s0, src r0, n_src r1, int pos r2, int *newpos r3,
 * float *frac, float *dst, int n); the reading point is src[pos + frac] and moves by |rate| per output frame.
 * voice_read (below) parks FUN_08055f0c's pad, absolute source position and signed rate here, so the machine grid is anchored on the sample itself, not on each block's scratch buffer.
 * At rate exactly 1.0 the stock code copies without a kernel; the hold after the voice then does the same job.
 */
struct read_park {
    const uint8_t *pad;
    int32_t pos;
    float rate;
};
#define PARK ((volatile struct read_park *)0x2405fff4u)     /* the last 12 bytes of patch RAM */

typedef void (*kernel_fn)(float rate, const float *src, int n_src, int pos, int *newpos, float *frac, float *dst,
                          int n);
#define fw_kernel_normal ((kernel_fn)FN(0x080619d0))
#define fw_kernel_hq     ((kernel_fn)FN(0x08061a64))

static inline float floor_f(float x)
{
    int i = (int)x;
    return (float)(i - (x < (float)i));
}

static inline int round_i(float x)
{
    return (int)(x + (x >= 0.0f ? 0.5f : -0.5f));
}

static void machine_read(const struct machine *m, float rate, const float *src, int n_src, int pos, int *newpos,
                         float *frac, float *dst, int n)
{
    /* scratch index -> absolute source position. Forward: scratch[0] = source[P - 4]. Reverse: FUN_08055f0c fetched
       from round(P) - n_src + 4 and reversed the buffer, so scratch[j] = source[round(P) + 3 - j]. */
    int32_t base = PARK->pos - 4;
    float sgn = 1.0f;
    if (PARK->rate < 0.0f) {
        sgn = -1.0f;
        base = PARK->pos + 3;            /* FUN_08055f0c rounds a float that already holds an integer */
    }
    /* Keep the per-frame maths small: a float holds a sample position 2.9 M samples (60 s) in to only 0.25 of a
       sample. Anchor once per call in double (the M7 FPU has it), then work relative to the grid point below. */
    double gd = 48000.0 / (double)m->grid;
    double kb = (double)(int32_t)((double)base / gd);
    if (kb * gd > (double)base)
        kb -= 1.0;
    float a0 = (float)((double)base - kb * gd);      /* 0 <= a0 < g: where the scratch sits on the grid */
    float g = (float)gd, inv_g = m->grid * (1.0f / 48000.0f);
    const float *h = m->fir;
    int hi = n_src - 3;
    float f = *frac;
    int idx = pos;
    for (int i = 0; i < n; i++) {
        float gp = (a0 + sgn * ((float)idx + f)) * inv_g, k0 = floor_f(gp);
        int j0 = round_i(sgn * (k0 * g - a0));
        j0 = j0 < 2 ? 2 : j0 > hi ? hi : j0;
        const float *s = src + j0;
        float v = h[0] * s[-2] + h[1] * s[-1] + h[2] * s[0] + h[3] * s[1] + h[4] * s[2];
        if (m->linear) {
            int j1 = round_i(sgn * ((k0 + 1.0f) * g - a0));
            j1 = j1 < 2 ? 2 : j1 > hi ? hi : j1;
            s = src + j1;
            float w = h[0] * s[-2] + h[1] * s[-1] + h[2] * s[0] + h[3] * s[1] + h[4] * s[2];
            v += (gp - k0) * (w - v);
        }
        dst[i] = v;
        float adv = rate + f;
        int step = (int)adv;
        idx += step;
        f = adv - (float)step;
    }
    *frac = f;
    *newpos = idx;                       /* the stock kernels return (pointer - src) + 1, pointer = src + idx - 1 */
}

typedef int (*voice_read_fn)(float frac, float rate, const uint8_t *pad, void *src, int pos, int a6, int frames,
                             int offset, void *scratch, void *out);
#define fw_voice_read ((voice_read_fn)FN(0x08055f0c))

/* (3.1.v5) The grain resampler's choice for a granular pad (resamp_grain_l, filter_thunk.S): its stock cubic on HighQ,
   linear otherwise (cheaper; Normal is the default). */
int grain_linear(const uint8_t *pad)
{
    return pad_interp(pad) != 1;
}

static const struct machine *pad_machine(const uint8_t *pad)
{
    unsigned interp = pad_interp(pad);
    return interp >= FIRST_MACHINE && interp < FIRST_MACHINE + MACHINES ? &machines[interp - FIRST_MACHINE] : 0;
}

/*
 * Replaces the calls to the sample-voice reader FUN_08055f0c (@0x08057214, 0x080574ce, 0x080575d2, 0x08057694): park
 * the pad, absolute position and signed rate for the kernels. At exactly the original pitch the stock reader copies
 * the source without a kernel; in a machine mode the rate goes in as the next float above 1.0, so those voices still
 * read through the machine's grid and anti-alias taps (a real SP filtered at sampling time; holding the raw source at
 * 26 kHz would fold everything above 13 kHz). The voice's own position bookkeeping is the caller's, unaffected.
 */
int voice_read(float frac, float rate, const uint8_t *pad, void *src, int pos, int a6, int frames, int offset,
               void *scratch, void *out)
{
    PARK->pad = pad;
    PARK->pos = pos;
    PARK->rate = rate;
    if (rate == 1.0f && pad_machine(pad))
        rate = 1.00000012f;
    return fw_voice_read(frac, rate, pad, src, pos, a6, frames, offset, scratch, out);
}

static const struct machine *read_machine(void)
{
    return pad_machine(PARK->pad);
}

/* Replace the kernel calls in FUN_08055f0c: Normal @0x0805619a / 0x080561be / 0x080561d4, HighQ @0x08056010 /
   0x08056098 / 0x080560bc. */
/* (the stereo reader's call-site thunks, filter_thunk.S: a machine mode keeps the per-channel path) */
int read_is_machine(void)
{
    return read_machine() != 0;
}

void read_normal(float rate, const float *src, int n_src, int pos, int *newpos, float *frac, float *dst, int n)
{
    const struct machine *m = read_machine();
    if (m)
        machine_read(m, rate, src, n_src, pos, newpos, frac, dst, n);
    else
        fw_kernel_normal(rate, src, n_src, pos, newpos, frac, dst, n);
}

void read_hq(float rate, const float *src, int n_src, int pos, int *newpos, float *frac, float *dst, int n)
{
    const struct machine *m = read_machine();
    if (m)
        machine_read(m, rate, src, n_src, pos, newpos, frac, dst, n);
    else
        fw_kernel_hq(rate, src, n_src, pos, newpos, frac, dst, n);
}
