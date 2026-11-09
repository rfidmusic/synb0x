/*
 * Pad overdrive replacement. Original 1010music Blackbox, firmware 3.1.9.
 *
 * Stock (FUN_0807081c, once per pad per block, after the pad's voices are summed): pre-gain 2^(6 x Overdrive)
 * (1x..64x) into a lopsided table curve (positive half hard-clips at 0.63, negative half never limits), then -12 dB.
 * Harsh, DC-shifted, no gentle range.
 *
 * This keeps the knob and the stock make-up gain, and replaces the curve:
 *   drive d = Overdrive 0..1 (recovered from the stock pre-gain)
 *   input gain 1 + 24 d^2 (gentle at the start of the knob, up to +28 dB)
 *   soft clip with headroom 2 - d: nearly linear at low drive, a full soft clip at the top
 *   plus k c^2 on the clipped signal, k = 0.3 x min(1, 4 d): a second harmonic (warmth) that leads at low and mid drive
 *   DC blocker (~10 Hz) for the offset the squared term leaves behind
 *   tape-style tone: one-pole low-pass that closes from open to ~7 kHz as drive rises, so heavy settings get darker
 *   level compensation 1 / sqrt(input gain)
 * Per-pad filter states live in the backup SRAM (4 KB at 0x38800000, unused by the firmware; this bank is the first
 * 0x384 bytes, comp.c uses 0x38800400 on), keyed by the pad's overdrive object. Stock firmware is unaffected: the knob value is the same parameter.
 */
#include <stdint.h>

#define RCC_AHB4ENR (*(volatile uint32_t *)0x580244e0u)
#define BKPRAMEN    (1u << 28)
#define PWR_CR1     (*(volatile uint32_t *)0x58024800u)
#define DBP         (1u << 8)
#define BKPSRAM     0x38800000u

#define OD_ON    0x00            /* stock object: byte, overdrive enabled */
#define OD_PRE   0x04            /* float, 2^(6 x Overdrive) */
#define OD_MAKEUP 0x0c           /* float, stock make-up gain (applied by stock whether on or off) */

#define SLOTS 32
struct od_slot {
    const void *obj;
    float hp_x[2], hp_y[2], lp[2];
};
struct od_bank {
    uint32_t magic;
    struct od_slot slot[SLOTS];
};
#define BANK ((volatile struct od_bank *)BKPSRAM)
#define MAGIC 0x4f445631u        /* "ODV1" */
#define DC_R  0.99869f           /* one-pole DC blocker, ~10 Hz at 48 kHz */

/* Backup SRAM: clock on, backup-domain writes allowed. Also used by comp.c (which owns 0x38800400 onward). */
void bkp_enable(void)
{
    if (!(RCC_AHB4ENR & BKPRAMEN)) {
        RCC_AHB4ENR |= BKPRAMEN;
        (void)RCC_AHB4ENR;                                   /* let the clock settle before the first access */
    }
    if (!(PWR_CR1 & DBP))
        PWR_CR1 |= DBP;                                      /* backup domain writes */
}

static volatile struct od_slot *slot_for(const void *obj)
{
    bkp_enable();
    if (BANK->magic != MAGIC) {
        for (int i = 0; i < SLOTS; i++)
            BANK->slot[i].obj = 0;
        BANK->magic = MAGIC;
    }
    int free = -1;
    for (int i = 0; i < SLOTS; i++) {
        if (BANK->slot[i].obj == obj)
            return &BANK->slot[i];
        if (free < 0 && BANK->slot[i].obj == 0)
            free = i;
    }
    if (free < 0)
        return 0;
    volatile struct od_slot *s = &BANK->slot[free];
    for (int c = 0; c < 2; c++)
        s->hp_x[c] = s->hp_y[c] = s->lp[c] = 0.0f;
    s->obj = obj;
    return s;
}

/* log2 for 1 <= x <= 64, from the float's exponent plus a quadratic on the mantissa (error < 0.01). */
static float log2_approx(float x)
{
    union { float f; uint32_t u; } v = {x};
    float e = (float)((int)((v.u >> 23) & 0xff) - 128);     /* the polynomial below carries the missing +1 */
    v.u = (v.u & 0x007fffffu) | 0x3f800000u;                /* mantissa in [1, 2) */
    float m = v.f;
    return e + (-0.34484843f * m + 2.02466578f) * m - 0.67487759f;
}

/* Soft clip: unity slope at zero, flat at |u| = 1.5, ceiling 1. */
static inline __attribute__((always_inline)) float clip(float u)
{
    u = __builtin_fminf(__builtin_fmaxf(u, -1.5f), 1.5f);    /* vmaxnm / vminnm: no branch in the sample loop */
    return u * (1.0f - 0.148148f * u * u);
}

/*
 * The sample loop. Per sample the arithmetic is one long dependent chain (clip, warmth, DC blocker, tone, level), so
 * one channel at a time leaves the FPU waiting on each result. These do two samples of both channels (or two samples of
 * the one channel) together: the clip and warmth of each are independent, only the DC blocker and the tone carry from
 * sample to sample. The same operations in the same order as before on every sample: the output is bit for bit the
 * same. (-O2 here: its scheduler interleaves the chains; -Os keeps them apart.)
 */
struct od_k { float gain, inv_head, head, k, tone, post; };

static inline __attribute__((always_inline)) float od_shape(const struct od_k *q, float x)
{
    float c = q->head * clip(x * q->gain * q->inv_head);
    return c + q->k * c * c;
}

static inline __attribute__((always_inline)) float od_tail(const struct od_k *q, float y, float *hx, float *hy,
                                                           float *lp)
{
    float h = y - *hx + DC_R * *hy;
    *hx = y;
    *hy = h;
    *lp += q->tone * (h - *lp);
    return *lp * q->post;
}

__attribute__((optimize("O2"), noinline))
static void od_stereo(const struct od_k *qp, float *l, float *r, int n, float *sl, float *sr)
{
    const struct od_k q = *qp;
    float lx = sl[0], ly = sl[1], ll = sl[2], rx = sr[0], ry = sr[1], rl = sr[2];
    int i = 0;
    for (; i + 1 < n; i += 2) {
        float a0 = od_shape(&q, l[i]), b0 = od_shape(&q, r[i]);
        float a1 = od_shape(&q, l[i + 1]), b1 = od_shape(&q, r[i + 1]);
        l[i] = od_tail(&q, a0, &lx, &ly, &ll);
        r[i] = od_tail(&q, b0, &rx, &ry, &rl);
        l[i + 1] = od_tail(&q, a1, &lx, &ly, &ll);
        r[i + 1] = od_tail(&q, b1, &rx, &ry, &rl);
    }
    if (i < n) {
        l[i] = od_tail(&q, od_shape(&q, l[i]), &lx, &ly, &ll);
        r[i] = od_tail(&q, od_shape(&q, r[i]), &rx, &ry, &rl);
    }
    sl[0] = lx; sl[1] = ly; sl[2] = ll;
    sr[0] = rx; sr[1] = ry; sr[2] = rl;
}

__attribute__((optimize("O2"), noinline))
static void od_mono(const struct od_k *qp, float *x, int n, float *st)
{
    const struct od_k q = *qp;
    float hx = st[0], hy = st[1], lp = st[2];
    int i = 0;
    for (; i + 1 < n; i += 2) {
        float a0 = od_shape(&q, x[i]), a1 = od_shape(&q, x[i + 1]);
        x[i] = od_tail(&q, a0, &hx, &hy, &lp);
        x[i + 1] = od_tail(&q, a1, &hx, &hy, &lp);
    }
    if (i < n)
        x[i] = od_tail(&q, od_shape(&q, x[i]), &hx, &hy, &lp);
    st[0] = hx; st[1] = hy; st[2] = lp;
}

/* Replaces both calls to the stock overdrive process (sample pads @0x08059ab6, clip / slicer pads @0x08068b12). */
void od_process(const uint8_t *obj, float *left, float *right, int n)
{
    float makeup = *(const float *)(obj + OD_MAKEUP);
    if (!obj[OD_ON]) {                                       /* off: what stock does, make-up gain only */
        if (makeup != 1.0f)
            for (int i = 0; i < n; i++) {
                left[i] *= makeup;
                if (right)
                    right[i] *= makeup;
            }
        return;
    }
    float d = log2_approx(*(const float *)(obj + OD_PRE)) * (1.0f / 6.0f);
    d = d < 0.0f ? 0.0f : d > 1.0f ? 1.0f : d;
    float gain = 1.0f + 24.0f * d * d;
    float head = 2.0f - d, inv_head = 1.0f / head;
    float k = 0.3f * (d < 0.25f ? 4.0f * d : 1.0f);
    float post = makeup / (1.0f + 0.5f * (gain - 1.0f) / (1.0f + 0.12f * gain));   /* ~1/sqrt(gain) without a sqrt */
    float tone = 1.0f - 0.4f * d;                            /* one-pole coefficient: 1 = open */

    volatile struct od_slot *s = slot_for(obj);
    struct od_k q = {gain, inv_head, head, k, tone, post};
    float st[2][3];                                          /* per channel: hp_x, hp_y, lp */
    for (int c = 0; c < 2; c++) {
        st[c][0] = s ? s->hp_x[c] : 0.0f;
        st[c][1] = s ? s->hp_y[c] : 0.0f;
        st[c][2] = s ? s->lp[c] : 0.0f;
    }
    if (right)
        od_stereo(&q, left, right, n, st[0], st[1]);
    else
        od_mono(&q, left, n, st[0]);
    if (s)
        for (int c = 0; c < (right ? 2 : 1); c++) {
            s->hp_x[c] = st[c][0];
            s->hp_y[c] = st[c][1];
            s->lp[c] = st[c][2];
        }
}

int pad_machine_mode(const uint8_t *pad);       /* filter.c */

/*
 * Sample pads (@0x08059ab6): the overdrive object is pad + 0x560 (FUN_080596b0 builds it as r4 + 0x560). When the pad's
 * Fidelity is a machine mode, filter.c uses the Saturation knob as the machine's input drive, so stand aside here:
 * make-up gain only, as with the overdrive off. (Clip / slicer pads keep od_process: their object's link to the pad is
 * not mapped yet.)
 */
void od_process_a(const uint8_t *obj, float *left, float *right, int n)
{
    if (obj && pad_machine_mode(obj - 0x560)) {
        float makeup = *(const float *)(obj + OD_MAKEUP);
        if (makeup != 1.0f)
            for (int i = 0; i < n; i++) {
                left[i] *= makeup;
                if (right)
                    right[i] *= makeup;
            }
        return;
    }
    od_process(obj, left, right, n);
}

/* The pad Overdrive knob's label (patches/od.py points the registration's literal here; the xml name stays) */
const char od_label[] = "Saturation:";
