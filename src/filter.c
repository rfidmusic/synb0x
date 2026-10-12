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
 *   2. Filter: 24 dB/oct, two of the trapezoidal state-variable filters from Emilie Gillet's stmlib (dsp/filter.h,
 *      class Svf; MIT licence, Copyright 2014 Emilie Gillet) in series: the first at a fixed Butterworth Q, the second
 *      carrying the Res knob. Cutoff and resonance go through the stock curves, so the Filter and Res knobs keep
 *      their ranges. Drive rides on Res: below the default (noon) the filter is clean; from noon to full the input is
 *      pushed into a soft clipper (up to +12 dB) and the resonant integrator is soft-limited, so high resonance
 *      growls and saturates instead of only getting louder.
 *   3. Morph (new pad param, fenv.c): LP at 0, notch at 50 %, HP at 100 %, mixing LP and HP in each stage at full
 *      level (morph_weights), and a modulation destination (any source, applied here). The Filter knob is cutoff across its whole travel, far left
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
    float g, r, drive;           /* smoothed: SVF frequency coefficient, damping of the resonant stage, drive 0..1 */
    float s1[2][2], s2[2][2];    /* integrator states [stage][channel] */
    float phase, held[2];        /* crunch: hold phase and held sample per channel */
    uint32_t on;                 /* filter was running last block */
};
#define MAGIC 0x53564632u        /* "SVF2": bumped with the layout */
#define R_BUTTERWORTH 1.84776f   /* 1 / 0.5412: first stage of a 4-pole Butterworth */
#define SMOOTH 0.33333f          /* per-block coefficient smoothing, as the stock filter */

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
    u = u > 1.5f ? 1.5f : u < -1.5f ? -1.5f : u;
    return t * u * (1.0f - 0.148148f * u * u);
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

/*
 * Both stages in one pass per sample (and, while Res drives, the input soft clip too), so each sample is loaded and
 * stored once instead of three times. Stage 1: fixed Butterworth damping, linear. Stage 2: the Res damping, its
 * band-pass integrator soft-limited while driven. Same arithmetic as running the stages one after the other.
 * DRIVEN is a compile-time 0 / 1, so each variant is its own tight loop.
 */
#define SVF2_LOOP(OUT, DRIVEN, RAMP)                                                                               \
    for (int i = 0; i < n; i++) {                                                                                  \
        if (RAMP) {                                                                                                \
            wl += dl;                                                                                              \
            wh += dh;                                                                                              \
        }                                                                                                          \
        float v = x[i];                                                                                            \
        if (DRIVEN)                                                                                                \
            v = soft(v * pre, 1.0f, 1.0f);                                                                         \
        float hp = (v - rg1 * a1 - a2) * h1;                                                                       \
        float bp = g * hp + a1;                                                                                    \
        a1 = g * hp + bp;                                                                                          \
        float lp = g * bp + a2;                                                                                    \
        a2 = g * bp + lp;                                                                                          \
        v = OUT(hp, bp, lp, R_BUTTERWORTH);                                                                        \
        hp = (v - rg2 * b1 - b2) * h2;                                                                             \
        bp = g * hp + b1;                                                                                          \
        b1 = DRIVEN ? soft(g * hp + bp, inv, limit) : g * hp + bp;                                                 \
        lp = g * bp + b2;                                                                                          \
        b2 = g * bp + lp;                                                                                          \
        x[i] = OUT(hp, bp, lp, r);                                                                                 \
    }

/* s = {stage 1 s1, stage 1 s2, stage 2 s1, stage 2 s2} for this channel. drive 0 = clean. w0 -> w1: the {LP, HP} weights
   at the start and end of the call, ramped sample by sample when they differ (a step would click). Pure LP or pure HP
   throughout takes that output's own loop (no blending cost). */
static void svf2(float *x, int n, float g, float r, float *s[4], const float w0[2], const float w1[2], float drive)
{
    int ramp = w0[0] != w1[0] || w0[1] != w1[1];
    float wl = w0[0], wh = w0[1];
    float dl = ramp && n > 0 ? (w1[0] - w0[0]) / (float)n : 0.0f, dh = ramp && n > 0 ? (w1[1] - w0[1]) / (float)n : 0.0f;
    int type = ramp ? TYPE_MIX : wh == 0.0f ? TYPE_LP : wl == 0.0f ? TYPE_HP : TYPE_MIX;
    float h1 = 1.0f / (1.0f + R_BUTTERWORTH * g + g * g), rg1 = R_BUTTERWORTH + g;
    float h2 = 1.0f / (1.0f + r * g + g * g), rg2 = r + g;
    float a1 = *s[0], a2 = *s[1], b1 = *s[2], b2 = *s[3];
    if (drive > 0.001f) {
        float pre = 1.0f + 3.0f * drive;
        float limit = 4.0f - 3.0f * drive, inv = 1.0f / limit;  /* resonant stage ceiling, 4 down to 1 */
        if (type == TYPE_HP)
            SVF2_LOOP(OUT_HP, 1, 0)
        else if (type == TYPE_MIX && ramp)
            SVF2_LOOP(OUT_MIX, 1, 1)
        else if (type == TYPE_MIX)
            SVF2_LOOP(OUT_MIX, 1, 0)
        else
            SVF2_LOOP(OUT_LP, 1, 0)
    } else {
        float pre = 1.0f, limit = 1.0f, inv = 1.0f;
        (void)pre;
        (void)limit;
        (void)inv;
        if (type == TYPE_HP)
            SVF2_LOOP(OUT_HP, 0, 0)
        else if (type == TYPE_MIX && ramp)
            SVF2_LOOP(OUT_MIX, 0, 1)
        else if (type == TYPE_MIX)
            SVF2_LOOP(OUT_MIX, 0, 0)
        else
            SVF2_LOOP(OUT_LP, 0, 0)
    }
    *s[0] = a1;
    *s[1] = a2;
    *s[2] = b1;
    *s[3] = b2;
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

static unsigned pad_interp(const uint8_t *pad)
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
#define MORPH_ROUTES 3             /* a parameter has three modulation slots */
struct pad_cfg {
    unsigned interp, drive;
    float morph;                                     /* 0 LP .. 0.5 notch .. 1 HP, before modulation */
    float attack, decay, sustain, release, depth;    /* seconds, seconds, level, seconds, cutoff travel -1..1 */
    unsigned routes;                                 /* modulation routes to Morph, from the pad record */
    uint16_t source[MORPH_ROUTES];
    float amount[MORPH_ROUTES];
};

static float seg_time(int v)                       /* knob 0..1000 -> 60 x^3 seconds, 0 at 0 */
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
    uint16_t magic;
};
#define CFG_CACHE(obj) ((struct cfg_cache *)((obj) + 0x74))
#define CMAGIC 0x4347u           /* "CG": bumped with the layout */
_Static_assert(sizeof(struct cfg_cache) == 16, "the cache must fit +0x74..+0x83");

static void pad_config(const uint8_t *pad, uint8_t *obj, struct pad_cfg *c)
{
    int v[CFG_IDS] = {0, 0, DEF_FMORPH, DEF_FATTACK, DEF_FDECAY, DEF_FSUSTAIN, DEF_FRELEASE, DEF_FDEPTH, DEF_FTYPE};
    c->routes = 0;
    if (pad) {
        uint32_t id = *(const uint32_t *)(pad + 0x18);
        unsigned row = (id >> 8) & 0xff, col = id & 0xff;
        if (row < 4 && col < 5) {
            const void *store = (const void *)(APP_PADS + row * 0xf0u + col * 0x30u);
            const uint8_t *e = STORE_ENTRIES(store);
            unsigned count = STORE_COUNT(store);
            struct cfg_cache *cc = CFG_CACHE(obj);
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
               store + 0x10, count at + 0x14): the few that target Morph. Short list, read every block. */
            const uint8_t *rt = *(const uint8_t *const *)((const uint8_t *)store + 0x10);
            unsigned nr = *(const uint16_t *)((const uint8_t *)store + 0x14);
            for (unsigned i = 0; rt && i < nr && c->routes < MORPH_ROUTES; i++, rt += 12)
                if (*(const uint16_t *)(rt + 6) == P_FMORPH && *(const uint16_t *)(rt + 4) != 0 &&
                    *(const int16_t *)rt != 0) {                    /* amount 0 cannot move it */
                    c->source[c->routes] = *(const uint16_t *)(rt + 4);
                    c->amount[c->routes] = (float)*(const int16_t *)rt * 0.001f;
                    c->routes++;
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
    uint32_t src_word;           /* +0x44: source object word 0, unused */
    float level;                 /* +0x48: 0..1, the FENV source value */
    uint8_t stage;               /* +0x4c */
    uint8_t amp_last;            /* +0x4d: amp envelope stage at the previous step */
    uint8_t pad[2];
    float base;                  /* +0x50: smoothed cutoff position 0..1 (knob part only) */
    float t;                     /* +0x54: seconds into the decay / release segment */
};
enum { ENV_IDLE, ENV_ATTACK, ENV_DECAY, ENV_SUSTAIN, ENV_RELEASE, ENV_DONE };
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
static float approach(float level, float target, float t, float dt)
{
    if (t <= dt)
        return target;
    return target + (level - target) * exp2f_fast(-6.6439f * dt / t);
}

/* Advance one step of dt seconds. amp = the voice's amp envelope stage (0 idle, 1 attack, 2 decay, 3 sustain,
   4 release, 5 done). A fresh attack of the amp envelope (stage back to 1 from a later stage: a mono / legato
   retrigger without a voice start) restarts the attack from the current level. */
static void env_step(struct envstate *e, unsigned amp, const struct pad_cfg *c, float dt)
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

_Static_assert(sizeof(struct envstate) <= 0x14, "envstate must end before +0x58 (glide.c's per-voice state)");

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
static float source_value(unsigned src, const uint8_t *obj, const uint8_t *pad, const uint8_t *amp)
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

/* Morph 0..1 -> {LP, HP} weights: LP stays full while HP comes in (0 -> 50 %), then HP stays full while LP goes out.
   Halfway it is LP + HP, the notch at full level; a plain 50 / 50 crossfade (the SEM pot) would drop everything else by
   6 dB per stage, 12 dB here. The end points are exact. */
static void morph_weights(float m, float w[2])
{
    if (m <= 0.0001f)
        m = 0.0f;
    else if (m >= 0.9999f)
        m = 1.0f;
    w[0] = m <= 0.5f ? 1.0f : 2.0f * (1.0f - m);
    w[1] = m >= 0.5f ? 1.0f : 2.0f * m;
}

/* Smoothed Morph (knob and block-rate sources) per voice, in the filter object at +0x88 (written only by the stock
   voice start, which also clears st->on, and st->on == 0 re-seeds it) */
#define MORPH_BASE(obj) (*(float *)((obj) + 0x88))
/* The {LP, HP} weights the last step ended on, +0x8c / +0x90 (the stock voice start writes 0.5 / 0 there; re-seeded
   whenever the filter starts) */
#define WPREV(obj)      ((float *)((obj) + 0x8c))
/* envstate pad[0]: the filter was skipped mid-note at its open end (1: LP side, 2: HP side); zeroed at voice start */
#define BYPASSED(env)   ((env)->pad[0])
#define XFADE 32                 /* frames of dry -> filtered when the filter starts again mid-note */

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
    int sub = SUB, subs = 0;
    float levels[MAX_SUBS];
    if (n > 0) {
        if (n > SUB * MAX_SUBS)
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
    if (st->magic != MAGIC) {
        uint32_t *w = (uint32_t *)st;
        for (unsigned i = 0; i < sizeof *st / 4; i++)
            w[i] = 0;
        st->magic = MAGIC;
    }
    unsigned interp = cfg.interp;
    int crunching = interp >= STOCK_INTERP && interp < STOCK_INTERP + CRUNCHES + MACHINES;
    uint8_t *params = *(uint8_t **)(obj + OBJ_PARAMS);
    float knob = params ? fw_param(params + 8) : 1.0f;
    float pos = (knob + 1.0f) * 0.5f;                       /* cutoff position 0..1 on the stock curve */
    pos = pos < 0.0f ? 0.0f : pos > 1.0f ? 1.0f : pos;
    /* Morph: the knob plus its routes; FENV routes move with the envelope, the rest once per block */
    float morph = cfg.morph, morph_env = 0.0f;
    for (unsigned i = 0; i < cfg.routes; i++) {
        if (cfg.source[i] == 1)
            morph_env += cfg.amount[i];
        else
            morph += cfg.amount[i] * source_value(cfg.source[i], obj, pad, amp);
    }
    /* skipped only when it cannot change the sound: LP fully open or HP fully closed, nothing moving it. While it runs,
       it stops only once its own glides have reached that end (stopping as soon as the knob does jumps from filtered to
       dry: a click). */
    int still = cfg.depth == 0.0f && cfg.routes == 0;
    int lp_open = cfg.morph <= 0.0001f && pos >= 0.999f, hp_open = cfg.morph >= 0.9999f && pos <= 0.001f;
    if (st->on && st->magic == MAGIC) {
        float mb = MORPH_BASE(obj), b = env->base;
        lp_open = lp_open && mb <= 0.0001f && b >= 0.999f;
        hp_open = hp_open && mb >= 0.9999f && b <= 0.001f;
    }
    int active = !(still && (lp_open || hp_open));
    if (!active) {
        if (st->on)
            BYPASSED(env) = lp_open ? 1 : 2;
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

    float res = params ? fw_param(params + 0x44) : 0.0f;
    float q = fw_res_q(res);
    float drive = (res - 0.5f) * 2.0f;                      /* 0 up to the default Res, 1 at full */
    drive = drive < 0.0f ? 0.0f : drive > 1.0f ? 1.0f : drive * drive;
    if (!(q > 0.1f))
        q = 0.1f;                                            /* the stock curve's own minimum (Res at 0) */
    if (q > 40.0f)
        q = 40.0f;
    float r = 1.0f / q;
    int xfade = 0;
    if (!st->on) {
        st->r = r;
        st->drive = drive;
        if (BYPASSED(env)) {
            /* starting again mid-note: from the open end it stopped at, gliding to the knob, faded in from dry */
            env->base = BYPASSED(env) == 1 ? 1.0f : 0.0f;
            MORPH_BASE(obj) = BYPASSED(env) == 1 ? 0.0f : 1.0f;
            xfade = 1;
            BYPASSED(env) = 0;
        } else {
            env->base = pos;                                 /* a new note starts where the knobs are */
            MORPH_BASE(obj) = morph;
        }
        float m0 = MORPH_BASE(obj) + morph_env * (subs ? levels[0] : 0.0f);
        morph_weights(m0 < 0.0f ? 0.0f : m0 > 1.0f ? 1.0f : m0, WPREV(obj));
        for (int k = 0; k < 2; k++)
            st->s1[k][0] = st->s1[k][1] = st->s2[k][0] = st->s2[k][1] = 0.0f;
        st->on = 1;
    } else {
        st->r += SMOOTH * (r - st->r);
        st->drive += SMOOTH * (drive - st->drive);
    }
    /* knob changes glide like the stock per-block smoothing (1/3 per block), spread over the steps */
    float glide = 1.0f - exp2f_fast(-0.585f * (float)sub / 256.0f);      /* (2/3)^(sub/256) */
    for (int k = 0; k < subs; k++) {
        int at = k * sub, len = k == subs - 1 ? n - at : sub;
        env->base += glide * (pos - env->base);
        MORPH_BASE(obj) += glide * (morph - MORPH_BASE(obj));
        float m = MORPH_BASE(obj) + morph_env * levels[k];
        float w[2], w0[2] = {WPREV(obj)[0], WPREV(obj)[1]};
        morph_weights(m < 0.0f ? 0.0f : m > 1.0f ? 1.0f : m, w);
        WPREV(obj)[0] = w[0];
        WPREV(obj)[1] = w[1];
        float p = env->base + cfg.depth * levels[k];
        p = p < 0.0f ? 0.0f : p > 1.0f ? 1.0f : p;
        float hz = fw_cutoff_hz(p);
        if (hz < 10.0f)
            hz = 10.0f;
        if (hz > 0.45f * FS)
            hz = 0.45f * FS;
        float g = tan_approx(PI_F * hz / FS);
        st->g = g;
        for (int c = 0; c < 2; c++) {
            if (!ch[c])
                continue;
            float *sv[4] = {&st->s1[0][c], &st->s2[0][c], &st->s1[1][c], &st->s2[1][c]};
            float dry[XFADE];
            int xl = xfade && k == 0 ? (len < XFADE ? len : XFADE) : 0;
            for (int i = 0; i < xl; i++)
                dry[i] = ch[c][at + i];
            svf2(ch[c] + at, len, g, st->r, sv, w0, w, st->drive);
            for (int i = 0; i < xl; i++)                    /* dry -> filtered over the first XFADE frames */
                ch[c][at + i] = dry[i] + (ch[c][at + i] - dry[i]) * ((float)(i + 1) / (float)xl);
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
