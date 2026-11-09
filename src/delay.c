/*
 * The stock delay-line reader (FUN_0806ab70, firmware 3.1.9), without its divisions. The Delay effect reads its line
 * through it (and so does a second effect, FUN_0806b6b4 / FUN_0806b87c). When the read point is at the target distance
 * behind the write point it copies; otherwise it reads at a rate of 1 + (distance error) / block, held to 0.5..2, with
 * linear interpolation, so the distance comes back to the target within the block. In that varispeed loop stock wraps
 * both read indexes with an integer division per sample (udiv + mls, two per sample per channel), and turns the
 * position into its whole and fractional part through two conversions. Here a step is 0..2 samples, so one compare
 * wraps it, and vrintz gives the whole part in one. Same arithmetic on every value: bit for bit the same output.
 *
 * Line (r0): +0 buffer (float), +4 write index, +8 read index, +0xc fraction (float), +0x10 target distance,
 * +0x14 length, byte +0x18 "at target". Frame (r1): its sample count (FUN_0804d8e8) and channel pointers
 * (FUN_0804d9c0); r2 picks the left (1) or right (0) channel.
 */
#include <stdint.h>

#define FN(a) ((void *)((a) | 1u))
typedef int (*frame_n_fn)(void *frame);
typedef void (*frame_ch_fn)(void *frame, float **l, float **r);
typedef void (*copy_fn)(const float *src, int n, float *dst);
#define fw_frame_n  ((frame_n_fn)FN(0x0804d8e8))
#define fw_frame_ch ((frame_ch_fn)FN(0x0804d9c0))
#define fw_copy     ((copy_fn)FN(0x0805f5c0))

struct dline {
    float *buf;
    uint32_t wr, rd;
    float frac;
    uint32_t target, len;
    uint8_t at_target;
};

static inline float trunc_f(float x)
{
    float r;
    __asm("vrintz.f32 %0, %1" : "=t"(r) : "t"(x));
    return r;
}

void delay_read(struct dline *d, void *frame, int left)
{
    int n = fw_frame_n(frame);
    float *l = 0, *r = 0;
    fw_frame_ch(frame, &l, &r);
    float *out = left ? l : r;
    uint32_t rd = d->rd, len = d->len, wr = d->wr;
    if (rd >= wr)
        wr += len;
    uint32_t dist = wr - rd;
    if (d->target == dist) {                         /* at target: copy (as stock) */
        d->at_target = 1;
        d->frac = 0.0f;
        int done = 0;
        while (n > 0) {
            uint32_t room = d->len - d->rd;
            const float *src = d->buf + d->rd;
            if ((uint32_t)n <= room) {
                fw_copy(src, n, out + done);
                d->rd = (d->rd + n) % d->len;
                return;
            }
            fw_copy(src, room, out + done);
            d->rd = (d->rd + room) % d->len;
            n -= room;
            done += room;
        }
        return;
    }
    float ratio = (float)(int)(dist - d->target + n) / (float)n;
    float rate = 0.5f;
    if (ratio >= 0.5f)
        rate = ratio > 2.0f ? 2.0f : ratio;
    float frac = d->frac;
    if (n > 0) {
        const float *buf = d->buf;
        if (rd < len && len > 2 && frac >= 0.0f && frac < 1.0f) {   /* steps of 0..2: one wrap each */
            for (int i = 0; i < n; i++) {
                float pos = rate + frac;
                float y0 = buf[rd];
                uint32_t r1 = rd + 1;
                if (r1 >= len)
                    r1 -= len;
                float whole = trunc_f(pos);
                rd += (uint32_t)(int)pos;
                if (rd >= len)
                    rd -= len;
                float y1 = buf[r1];
                out[i] = y0 - (y0 - y1) * frac;
                frac = pos - whole;
            }
        } else {                                     /* (an index past the end: the stock divisions) */
            for (int i = 0; i < n; i++) {
                float pos = rate + frac;
                float y0 = buf[rd], y1 = buf[(rd + 1) % len];
                int step = (int)pos;
                rd = (rd + step) % len;
                out[i] = y0 - (y0 - y1) * frac;
                frac = pos - (float)step;
            }
        }
        d->rd = rd;
    }
    d->frac = frac;
}
