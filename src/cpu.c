/*
 * CPU meter for the audio engine. Original 1010music Blackbox, firmware 3.1.9.
 *
 * The audio task (FUN_08041470) waits on a queue for the SAI DMA half / full interrupts, then renders 256 frames
 * (5.33 ms at 48 kHz) and waits again. This wraps that wait: busy = cycles from waking to waiting again,
 * period = cycles between wake-ups, both from the Cortex-M7 DWT cycle counter. Once a second the version label(s)
 * that show the version ("3.1.t") get " avg/peak%" appended, the average and the worst 5.33 ms block of the last second, and so
 * does the global cell's name (FUN_0809ad74, address 0x40), which is where the version actually shows on screen.
 * If the cycle counter never moves, the text reads " --%" instead, so a dead counter is visible, not silent.
 * The labels are filled in when their screens are built; the meter rewrites their text from the audio task (a plain
 * character copy plus the label's own dirty flag), and only when the label still starts with "3.1.", so a stale
 * pointer from an earlier boot is never written through.
 */
#include <stdint.h>

#define FN(addr) ((addr) | 1u)

typedef int (*receive_fn)(void *queue, void *item, uint32_t ticks, int peek);
typedef int (*text_fn)(uint8_t *text, const char *s);
typedef void (*label_fn)(uint8_t *label, const char *s);

#define fw_receive  ((receive_fn)FN(0x08088756))     /* FreeRTOS queue receive */
#define fw_text_set ((text_fn)FN(0x080c3b98))        /* text object: copy string (<= 31 chars), mark dirty */
#define fw_label_set ((label_fn)FN(0x080a3dec))      /* label: text object at +0x34, then redraw */

/* The firmware version the screens show. patches/cave.py points the four stock references to the stock "3.1.9" (literal
   pool words @0x0809af30, 0x080aeaf4, 0x080c55e8, 0x080c72c8) here, so the name is not limited by the stock slot. */
const char mod_version[] = "3.1.t";
#define VERSION     mod_version
#define TEXT_CHARS  0x31                             /* text object: characters */
#define LABEL_TEXT  0x34                             /* label -> its text object */
#define LABELS      3

#define DEMCR      (*(volatile uint32_t *)0xe000edfcu)
#define DWT_CTRL   (*(volatile uint32_t *)0xe0001000u)
#define DWT_CYCCNT (*(volatile uint32_t *)0xe0001004u)
#define DWT_LAR    (*(volatile uint32_t *)0xe0001fb0u)

#define BLOCKS_PER_REPORT 188    /* ~1 s of 5.33 ms blocks */

/* Patch RAM (see solo.c): 36 bytes after the chord state. Not zeroed at boot. */
struct cpu_state {
    uint32_t magic;
    uint32_t woke;               /* cycle count when the task last woke */
    uint32_t sum;                /* per-mille loads this report */
    uint16_t n, peak;            /* measured blocks, worst block, this report */
    uint16_t wakes;              /* all wake-ups this report, measured or not */
    uint16_t avg_shown, peak_shown;
    uint8_t armed, status;
    uint8_t *text[LABELS];       /* text objects of the version labels */
};
#define M ((volatile struct cpu_state *)0x2405ffd0u)
#define MAGIC 0x43505532u        /* "CPU2": bumped with the layout */
#define STATUS_NONE    0         /* nothing measured yet */
#define STATUS_OK      1
#define STATUS_NO_CLOCK 2        /* a second of wake-ups and the cycle counter never moved */

static void start(void)
{
    DEMCR |= 1u << 24;           /* TRCENA */
    DWT_LAR = 0xc5acce55u;       /* unlock (Cortex-M7) */
    DWT_CTRL |= 1u;              /* CYCCNTENA */
    M->armed = 0;
    M->status = STATUS_NONE;
    M->sum = 0;
    M->n = M->peak = M->wakes = 0;
    M->magic = MAGIC;
}

static char *put_uint(char *p, unsigned v)
{
    char tmp[4];
    int n = 0;
    do {
        tmp[n++] = (char)('0' + v % 10);
        v /= 10;
    } while (v && n < 4);
    while (n)
        *p++ = tmp[--n];
    return p;
}

/* "3.1.s 34/71%", "3.1.s --%" (a version with a '-' is shortened to what follows it), or the version alone before
   the first second. Writes at most 25 bytes
   (16 of version, " 100/100%", NUL); every destination has room: report()'s buffer 32, text objects 31 characters,
   the global cell's name 64. */
/* With numbers a version containing '-' is shortened to what follows it, so the text stays within the 12 characters of
   the original mod's "3.1.n 34/71%" that fit where the screens show the version. "3.1.s" has none: "3.1.s 34/71%". */
static const char *short_version(void)
{
    const char *v = VERSION;
    for (const char *c = VERSION; *c; c++)
        if (*c == '-')
            v = c + 1;
    return v;
}

static void compose(char *buf)
{
    char *p = buf;
    int numbers = M->magic == MAGIC && (M->status == STATUS_OK || M->status == STATUS_NO_CLOCK);
    for (const char *v = numbers ? short_version() : VERSION; *v && p < buf + 16; v++)
        *p++ = *v;
    if (M->magic == MAGIC && M->status == STATUS_OK) {
        *p++ = ' ';
        p = put_uint(p, (M->avg_shown + 5u) / 10u);
        *p++ = '/';
        p = put_uint(p, (M->peak_shown + 5u) / 10u);
        *p++ = '%';
    } else if (M->magic == MAGIC && M->status == STATUS_NO_CLOCK) {
        *p++ = ' ';
        *p++ = '-';
        *p++ = '-';
        *p++ = '%';
    }
    *p = 0;
}

static void report(void)
{
    char buf[32];
    compose(buf);
    for (int i = 0; i < LABELS; i++) {
        uint8_t *t = M->text[i];
        /* the screens are one large object the stock boot code takes from the SDRAM pool (FUN_080443a8, 593 KB), so
           their labels live in SDRAM; AXI RAM is accepted too. Anything else is not a label of ours. */
        uint32_t a = (uint32_t)t;
        if (!((a >= 0x24000000u && a < 0x24080000u) || (a >= 0xc0000000u && a < 0xc4000000u)))
            continue;
        const char *c = (const char *)(t + TEXT_CHARS), *sv = short_version();
        int ours = c[0] == '3' && c[1] == '.' && c[2] == '1' && c[3] == '.';     /* full version */
        for (int k = 0; !ours && sv[k] == c[k]; k++)                              /* or the short one */
            if (sv[k + 1] == 0)
                ours = 1;
        if (ours)
            fw_text_set(t, buf);
    }
}

/* Replaces the audio task's queue wait (bl @0x080414e4). */
int cpu_wait(void *queue, void *item, uint32_t ticks, int peek)
{
    if (M->magic != MAGIC)
        start();
    uint32_t idle_from = DWT_CYCCNT, busy = idle_from - M->woke;
    int got = fw_receive(queue, item, ticks, peek);
    uint32_t now = DWT_CYCCNT, period = now - M->woke;
    if (got != 1) {
        M->armed = 0;
        return got;
    }
    if (M->armed && period > 1000u) {
        uint32_t load = busy / (period / 1000u + 1u);        /* per mille */
        if (load > 9990u)
            load = 9990u;
        M->sum += load;
        if (load > M->peak)
            M->peak = (uint16_t)load;
        if (++M->n >= BLOCKS_PER_REPORT) {
            M->avg_shown = (uint16_t)(M->sum / M->n);
            M->peak_shown = M->peak;
            M->status = STATUS_OK;
            report();
            M->sum = 0;
            M->n = M->peak = M->wakes = 0;
        }
    }
    if (++M->wakes >= 2 * BLOCKS_PER_REPORT) {
        if (M->n == 0) {
            M->status = STATUS_NO_CLOCK;
            report();
        }
        M->wakes = 0;
    }
    M->woke = now;
    M->armed = 1;
    return got;
}

/*
 * Replaces the 6-byte copy of the version string into the global cell's info (FUN_0809ad74, address 0x40, the
 * `ldr; ldr; str; ldrh; strh` @0x0809ad84). dest is the info's name field, which has room for 64 bytes.
 */
void cpu_name(char *dest)
{
    compose(dest);
}

static void remember(int slot, uint8_t *text)
{
    if (M->magic != MAGIC)
        start();
    M->text[slot] = text;
}

/* The three places that build a version label (screen constructors at boot). */
void cpu_label_a(uint8_t *label, const char *s)            /* FUN_080c5450: a label, text at +0x34 */
{
    remember(0, label + LABEL_TEXT);
    fw_label_set(label, s);
}

int cpu_text_b(uint8_t *text, const char *s)               /* FUN_080ae8f0 */
{
    remember(1, text);
    return fw_text_set(text, s);
}

int cpu_text_c(uint8_t *text, const char *s)               /* FUN_080c70b8 */
{
    remember(2, text);
    return fw_text_set(text, s);
}
