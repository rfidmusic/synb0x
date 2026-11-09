/*
 * Munchi Delay in the delay slot (FX1). Original 1010music Blackbox, firmware 3.1.9.
 *
 * Munchi Delay is Charles Vestal's port of CHOMPI TEMPO's dual delay (github charlesvestal/schwung-munchi-delay, MIT;
 * sources in src/munchi with their licenses): a clock-synced delay whose one "wand" knob goes, left of centre, to
 * random glitch repeats (retrigger / reverse / octave up / octave down) and, right of centre, into a diffusion reverb,
 * with a freeze and a sidechain that ducks the repeats under new material once the feedback is high. It runs here at
 * its native 48 kHz, on the stock delay's own memory.
 *
 * Selector: the unused list parameter 0x197 'FX1:' (fx1algo) becomes "Type:" [Delay, Munchi] and heads the delay's
 * settings. The knob screen has 8 slots, all taken by Type + the stock delay's 7, so the page lists the controls of the
 * selected type only (munchi_list). Munchi's are new parameters: "Wand:" 0x1d1 (0..100 %, 50 % = off, below =
 * glitch delay, above = delay into reverb; the distance from the middle picks the note length), "Random:" 0x1d2 (how
 * often a random event fires) and "Freeze:" 0x1d3; 3.1.m adds "Clock:" 0x1d4, "Width:" 0x1d5 and "Duck:" 0x1d6, which fill
 * the knob screen's 8 slots. Feedback is the delay's own (0x38), and so is the level.
 *
 * The delay's process wrapper (vtable 0x080d0660 +0xc = 0x08054f34) calls the stock process FUN_080548c8 at
 * 0x08054f3a; that call comes here. Type Delay: stock. Type Munchi: stock is not run; the send comes in through the
 * stock gate (FUN_0804f270) and the wet goes out the way stock's does (bus += level x wet).
 *
 * Memory (the stock delay's three lines, allocated in its constructor and only used by its process):
 *   line 1 (obj+0x30, 192256 floats)  -> Munchi's live buffer, 16-bit stereo: 192256 frames = 4.0 s
 *   line 3 (obj+0x68, 192256 floats)  -> the freeze buffer, same size
 *   line 2 (obj+0x4c, 96256 floats)   -> everything else (delay, reverb incl. its 64 KB, ducker, clock)
 * A delay longer than ~3 s (a bar below ~80 BPM, or at Clock 1/2x) is clamped to the buffer in granularDelay.h.
 * All of it is cleared when the type changes either way. A magic word guards the state: if anything else ever clears
 * the lines, the next block starts Munchi afresh instead of following zeroed pointers.
 */
#include <stddef.h>
#include <stdint.h>
#include <new>

#pragma GCC optimize("O2", "no-tree-loop-distribute-patterns")

#include "munchi/tempo/granularDelay.h"
#include "munchi/tempo/reverb.h"
#include "munchi/tempo/SimpleCompressor.h"

#define FN(addr) ((addr) | 1u)

extern "C" {
void bkp_enable(void);
}

typedef int (*process_fn)(uint8_t *obj, uint32_t *bufs);
typedef void (*register_list_fn)(void *table, int param, const char *label, const char *const *names, int count,
                                 const char *xml);
typedef void (*register_num_fn)(void *table, int param, int type, const char *label, int min, int max, const char *xml);
typedef void (*store_add_fn)(void *store, int param, int value);
typedef int (*setting_fn)(const void *store, unsigned param);
typedef void *(*bus_fn)(uint32_t *bufs, int ch);
typedef void (*ptrs_fn)(void *buf, float **l, float **r);
typedef int (*len_fn)(void *buf);
typedef void (*setlen_fn)(void *buf, int n);
typedef void (*gate_fn)(void *gate, void *bus);
typedef void (*gate_in_fn)(void *gate, void *bus, void **in, int consume);
typedef void (*mixadd_fn)(float gain, const float *src, int n, float *dst);
typedef void (*line_clear_fn)(void *line);
typedef int (*chan_fn)(uint8_t *obj);
typedef void (*list_fill_fn)(void *list, void *store);
typedef void (*list_remove_fn)(void *list, unsigned param);
typedef int (*cell_type_fn)(void *store);

#define fw_process       ((process_fn)FN(0x080548c8))
#define fw_register_list ((register_list_fn)FN(0x0808c0d8))
#define fw_register_num  ((register_num_fn)FN(0x0808c12c))
#define fw_store_add     ((store_add_fn)FN(0x08093ef6))
#define fw_setting       ((setting_fn)FN(0x08093e9c))
#define fw_bus           ((bus_fn)FN(0x0805f37c))
#define fw_ptrs          ((ptrs_fn)FN(0x0804d9c0))
#define fw_len           ((len_fn)FN(0x0804d8e8))
#define fw_setlen        ((setlen_fn)FN(0x0804d8d0))
#define fw_gate          ((gate_fn)FN(0x0804f0d4))
#define fw_gate_in       ((gate_in_fn)FN(0x0804f270))
#define fw_mixadd        ((mixadd_fn)FN(0x08061844))
#define fw_line_clear    ((line_clear_fn)FN(0x0806aac0))
#define fw_list_fill     ((list_fill_fn)FN(0x080a50fc))
#define fw_list_remove   ((list_remove_fn)FN(0x080a506c))
#define FW_CHAN_DEFAULT  0x08046a15u

#define APP_FX       (0x24020088u + 0x2fc0u)    /* app: FX cell records, 0x18 each, by row */
#define OBJ_ID       0x18
#define OBJ_CHAN     0x1e
#define OBJ_LEVEL    0x2c                       /* float: the delay's output level (stock: obj[0xb]) */
#define OBJ_GATE     0xd0
#define OBJ_MIXADD   0x21f
#define LINE_LIVE    0x30
#define LINE_STATE   0x4c
#define LINE_FREEZE  0x68

#define P_TYPE   0x197
#define P_FEEDBK 0x38
#define P_WAND   0x1d1
#define P_RANDOM 0x1d2
#define P_FREEZE 0x1d3
#define P_CLOCK  0x1d4           /* 3.1.m: 1x / 1/2x / 2x: TEMPO's clock multiplier */
#define P_WIDTH  0x1d5           /* 3.1.m: stereo offset of the repeats: TEMPO's 20 / 10 ms, mono, x2.5, x5 */
#define P_DUCK   0x1d6           /* 3.1.m: sidechain ducking: Auto (TEMPO's: rises with Feedback past 60 %), Off, fixed */
#define P_ROOM_FIRST 0x1d7       /* fx2.c: Room's Size / Mod / Early / Width, 0x1d7..0x1da */
#define P_ROOM_LAST  0x1da
#define P_FX2_TYPE   0x198
#define CELL_REVERB  0x4b
#define ROOM 1
#define TYPE_PCT 8
#define CELL_DELAY 0x26

enum { ALG_DELAY, ALG_MUNCHI, ALGS };
static const char *const type_names[ALGS] = {"Delay", "Munchi"};
static const char *const freeze_names[2] = {"Off", "On"};
static const char *const clock_names[3] = {"1x", "1/2x", "2x"};
static const float clock_mul[3] = {1.f, .5f, 2.f};
static const char *const width_names[4] = {"TEMPO", "Mono", "Wide", "Huge"};
static const float width_mul[4] = {1.f, 0.f, 2.5f, 5.f};
static const char *const duck_names[4] = {"Auto", "Off", "Light", "Heavy"};

#define MODE (*(volatile uint32_t *)0x38800b14u)          /* backup SRAM: which type ran last */
#define MAGIC 0x4d554e31u                                 /* "MUN1" */
#define MAXN 128

struct Munchi {
    uint32_t magic;
    mbuf_t *live, *frozen;
    granularDelay delay;
    daisysp::Reverb reverb;
    SimpleCompressor comp;
    clockManager clock;
    float wet_amt, reverb_amt, reverb_amt_target, reverb_boost, reverb_boost_target;
    float pulse_phase;
    long pulses;
    int last_wand, last_random, last_feedback, last_freeze, last_duck;
    float clock_mul;
    int rev_idle;                   /* blocks the reverb has been silent and skipped (its memory cleared over 16) */
    float wl[MAXN], wr[MAXN];
};

static_assert(sizeof(Munchi) <= 96000 * 4, "Munchi's state must fit the stock delay's 2 s line");

static inline void *line_ptr(uint8_t *obj, int line)
{
    return *(void **)(obj + line);
}

static inline uint32_t line_floats(uint8_t *obj, int line)
{
    return *(uint32_t *)(obj + line + 0x14);
}

extern "C" {

/* the compiler's own zeroing (value-initialising Munchi) calls this; there is no C library */
void *memset(void *d, int c, size_t n)
{
    uint8_t *p = (uint8_t *)d;
    while (n--)
        *p++ = (uint8_t)c;
    return d;
}

/* Replaces the registration of 0x197 (bl @0x0808de8e): the type list, then Munchi's three settings. */
void munchi_register(void *table, int param, const char *label, const char *const *names, int count, const char *xml)
{
    (void)label;
    (void)names;
    (void)count;
    fw_register_list(table, param, "Type:", type_names, ALGS, xml);
    fw_register_num(table, P_WAND, TYPE_PCT, "Wand:", 0, 1000, "munchiwand");
    fw_register_num(table, P_RANDOM, TYPE_PCT, "Random:", 0, 1000, "munchirandom");
    fw_register_list(table, P_FREEZE, "Freeze:", freeze_names, 2, "munchifreeze");
    fw_register_list(table, P_CLOCK, "Clock:", clock_names, 3, "munchiclock");
    fw_register_list(table, P_WIDTH, "Width:", width_names, 4, "munchiwidth");
    fw_register_list(table, P_DUCK, "Duck:", duck_names, 4, "munchiduck");
}

/* Replaces the delay cell's first default, Time 400 (bl @0x0809444a): Type first. */
void munchi_defaults_first(void *store, int param, int value)
{
    fw_store_add(store, P_TYPE, ALG_DELAY);
    fw_store_add(store, param, value);
}

/* Replaces the delay cell's last default, Ping Pong on (bl @0x08094494): Munchi's settings at the end. */
void munchi_defaults_last(void *store, int param, int value)
{
    fw_store_add(store, param, value);
    fw_store_add(store, P_WAND, 250);
    fw_store_add(store, P_RANDOM, 300);
    fw_store_add(store, P_FREEZE, 0);
    fw_store_add(store, P_CLOCK, 0);
    fw_store_add(store, P_WIDTH, 0);
    fw_store_add(store, P_DUCK, 0);
}

/*
 * Replaces the settings-list fill in the page builder (bl FUN_080a50fc @0x08098e72). The FX knob screen shows the first
 * 8 entries only (FUN_080a87b6), and the stock delay already has 7 (Delay, Feedback, Width, Cutoff, Beat, Filter,
 * Ping), so the delay's list depends on its Type: Delay shows Type + the stock 7, Munchi shows Type, Feedback, Wand,
 * Random, Freeze.
 */
void munchi_list(void *list, void *store)
{
    static const uint16_t stock_only[] = {0x32, 0x33, 0x0e, 0xca, 0x34, 0xc9, 0x35};
    static const uint16_t munchi_only[] = {P_WAND, P_RANDOM, P_CLOCK, P_WIDTH, P_DUCK, P_FREEZE};
    fw_list_fill(list, store);
    int cell = (*(cell_type_fn *)*(uint8_t **)store)(store);
    if (cell == CELL_REVERB) {               /* Room's four settings only when Type is Room */
        if (fw_setting(store, P_FX2_TYPE) != ROOM)
            for (unsigned id = P_ROOM_FIRST; id <= P_ROOM_LAST; id++)
                fw_list_remove(list, id);
        return;
    }
    if (cell != CELL_DELAY)
        return;
    if (fw_setting(store, P_TYPE) == ALG_MUNCHI)
        for (unsigned i = 0; i < sizeof stock_only / sizeof *stock_only; i++)
            fw_list_remove(list, stock_only[i]);
    else
        for (unsigned i = 0; i < sizeof munchi_only / sizeof *munchi_only; i++)
            fw_list_remove(list, munchi_only[i]);
}

static void zero(void *p, uint32_t bytes)
{
    uint32_t *w = (uint32_t *)p;
    for (uint32_t i = 0; i < bytes / 4; i++)
        w[i] = 0;
}

static Munchi *start(uint8_t *obj)
{
    void *live = line_ptr(obj, LINE_LIVE), *frozen = line_ptr(obj, LINE_FREEZE), *st = line_ptr(obj, LINE_STATE);
    if (!live || !frozen || !st || line_floats(obj, LINE_STATE) * 4 < sizeof(Munchi))
        return nullptr;
    uint32_t frames = line_floats(obj, LINE_LIVE);              /* floats -> 16-bit stereo frames: same count */
    if (line_floats(obj, LINE_FREEZE) < frames)
        frames = line_floats(obj, LINE_FREEZE);
    zero(live, frames * 4);
    zero(frozen, frames * 4);
    zero(st, sizeof(Munchi));
    Munchi *m = new (st) Munchi();                              /* TEMPO's classes expect zeroed memory */
    m->live = (mbuf_t *)live;
    m->frozen = (mbuf_t *)frozen;
    m->reverb.Init(48000.f);
    m->reverb.SetAmount(0.f);
    m->reverb.SetInputGain(.3f);
    m->reverb.SetLowpass(1.f);
    m->comp.Init();
    m->delay.Init(m->live, m->frozen, frames, &m->clock, false);
    m->wet_amt = 1.f;
    m->last_wand = m->last_random = m->last_feedback = m->last_freeze = m->last_duck = -1;
    m->clock_mul = 1.f;
    if (!MUNCHI_RNG)
        MUNCHI_RNG = 0x2545f491u;
    m->magic = MAGIC;
    return m;
}

/* FxEngine::setGranularMain / setGranularFeedback, as Munchi's wrapper has them */
static void set_main(Munchi *m, float val)
{
    m->delay.setMainControl(val);
    if (val > .55f) {
        float norm = (val - .55f) / (1.f - .55f);
        float r = chompi::fast_sqrt(norm);                     /* powf(norm, .5f) */
        m->reverb_amt_target = .25f + .65f * r;
        m->reverb_boost_target = val > .6f ? .3f : 0.f;
    } else {
        m->reverb_amt_target = 0.f;
        m->reverb_boost_target = 0.f;
    }
}

static void controls(Munchi *m, const void *store)
{
    int wand = fw_setting(store, P_WAND), random = fw_setting(store, P_RANDOM);
    int feedback = fw_setting(store, P_FEEDBK), freeze = fw_setting(store, P_FREEZE) != 0;
    unsigned clock = (unsigned)fw_setting(store, P_CLOCK), width = (unsigned)fw_setting(store, P_WIDTH);
    int duck = fw_setting(store, P_DUCK);
    m->clock_mul = clock_mul[clock < 3 ? clock : 0];
    MUNCHI_SPREAD = width_mul[width < 4 ? width : 0];
    if (wand != m->last_wand)
        set_main(m, daisysp::fclamp(wand * .001f, 0.f, 1.f));
    if (random != m->last_random)
        m->delay.setAltControl(daisysp::fclamp(random * .001f, 0.f, 1.f));
    if (feedback != m->last_feedback || duck != m->last_duck) {
        float v = daisysp::fclamp(feedback * .001f, 0.f, 1.f);
        m->delay.setFeedback(v);
        float amount = duck == 1 ? 0.f : duck == 2 ? .5f : duck == 3 ? 1.f : (v > .6f ? (v - .6f) / (1.f - .6f) : 0.f);
        m->comp.setAmount(amount);
    }
    if (m->last_freeze >= 0 && freeze != m->last_freeze && freeze != m->delay.getBufferLock())
        m->delay.toggleBufferLock();
    m->last_wand = wand;
    m->last_random = random;
    m->last_feedback = feedback;
    m->last_freeze = freeze;
    m->last_duck = duck;
}

static void run_clock(Munchi *m, float bpm, int frames)
{
    if (!(bpm > 0.f))
        bpm = 120.f;
    bpm *= m->clock_mul;            /* note lengths that would not fit the 4 s buffer are clamped in granularDelay.h */
    m->clock.setBpm(bpm);
    m->pulse_phase += bpm * (24.f / 60.f) * (float)frames * (1.f / 48000.f);
    while (m->pulse_phase >= 1.f) {
        m->pulse_phase -= 1.f;
        m->delay.setClockPulse();
        if (++m->pulses % 12 == 0)
            m->delay.setClockEdge();
    }
}

static inline void process48(Munchi *m, float xl, float xr, float *ol, float *orr, bool rev_on)
{
    fonepole(m->wet_amt, 1.f, .001f);
    fonepole(m->reverb_amt, m->reverb_amt_target, .001f);
    fonepole(m->reverb_boost, m->reverb_boost_target, .001f);
    float wl = xl * m->wet_amt, wr = xr * m->wet_amt;
    float dl = xl, dr = xr;                         /* the ducking sidechain: the send itself */
    float yl = 0.f, yr = 0.f;
    m->delay.write(wl, wr);
    m->delay.read(&yl, &yr);
    yl += wl * m->reverb_boost;
    yr += wr * m->reverb_boost;
    if (rev_on)
        m->reverb.Process(&yl, &yr);
    m->comp.Process(&yl, &yr, &dl, &dr);
    *ol = yl;
    *orr = yr;
}

/* Replaces the delay process call in the delay's vtable wrapper (bl FUN_080548c8 @0x08054f3a). */
int munchi_process(uint8_t *obj, uint32_t *bufs)
{
    unsigned row = (*(uint32_t *)(obj + OBJ_ID) >> 8) & 0xff;
    const void *store = (const void *)(APP_FX + (row < 5 ? row : 0) * 0x18u);
    unsigned alg = row < 5 ? (unsigned)fw_setting(store, P_TYPE) : ALG_DELAY;
    bkp_enable();
    if (alg != ALG_MUNCHI) {
        if (MODE == ALG_MUNCHI) {                   /* back to the stock delay: clear what Munchi left in its lines */
            fw_line_clear(obj + LINE_LIVE);
            fw_line_clear(obj + LINE_STATE);
            fw_line_clear(obj + LINE_FREEZE);
        }
        MODE = ALG_DELAY;
        return fw_process(obj, bufs);
    }

    Munchi *m = (Munchi *)line_ptr(obj, LINE_STATE);
    if (MODE != ALG_MUNCHI || !m || m->magic != MAGIC || m->live != line_ptr(obj, LINE_LIVE) ||
        m->frozen != line_ptr(obj, LINE_FREEZE))
        m = start(obj);
    MODE = ALG_MUNCHI;
    if (!m)
        return fw_process(obj, bufs);

    chan_fn chan = *(chan_fn *)(*(uint8_t **)obj + 0x54);
    int ch = (uint32_t)chan == FW_CHAN_DEFAULT ? *(uint16_t *)(obj + OBJ_CHAN) : chan(obj);
    void *bus = fw_bus(bufs, ch);
    int n = fw_len(bus);
    if (n > MAXN)
        n = MAXN;
    fw_gate(obj + OBJ_GATE, bus);
    void *in = nullptr;
    fw_gate_in(obj + OBJ_GATE, bus, &in, 1);
    float *il = nullptr, *ir = nullptr;
    fw_ptrs(in, &il, &ir);

    controls(m, store);
    run_clock(m, *(float *)((uint8_t *)bufs[0] + 0x18), n);
    /* the reverb's settings follow its (slowly gliding) amount once per block, not every sample; with Wand at or left
       of centre its amount is 0 and it is skipped (it was 40 % of Munchi's time), its memory emptied over the next 16
       blocks so a later reverb starts clean instead of replaying a stale tail */
    m->reverb.SetAmount(m->reverb_amt * m->reverb_amt * .8f);
    m->reverb.SetTime(m->reverb_amt);
    m->reverb.SetLowpass(m->reverb_amt * .55f + .4f);
    m->reverb.SetDiffusion(m->reverb_amt * .6f);
    bool rev_on = m->reverb_amt_target > 0.f || m->reverb_amt > 1e-4f;
    if (rev_on)
        m->rev_idle = 0;
    else if (m->rev_idle < 16)
        m->reverb.ClearPart(m->rev_idle++);
    for (int i = 0; i < n; i++)
        process48(m, il[i], ir[i], &m->wl[i], &m->wr[i], rev_on);

    float *ol = nullptr, *orr = nullptr;
    fw_ptrs(bus, &ol, &orr);
    fw_setlen(bus, n);
    float level = *(float *)(obj + OBJ_LEVEL);
    if (obj[OBJ_MIXADD]) {
        fw_mixadd(level, m->wl, n, ol);
        fw_mixadd(level, m->wr, n, orr);
    } else {
        for (int i = 0; i < n; i++) {
            ol[i] = m->wl[i];
            orr[i] = m->wr[i];
        }
    }
    return 1;
}

/*
 * The FX knob screen's message handler (vtable 0x080f07e0 +0x10 = FUN_080ab900). Message 0x32 updates one knob's
 * value in place; message 0x66 rebuilds the whole page from the settings list. The page only rebuilt on some other
 * event, so after turning Type the old type's controls stayed until later (his 3.1.l report: the delay's Beat / Filter
 * / Ping buttons lingered on the Munchi page). When a 0x32 lands on a Type slot (0x197 delay, 0x198 reverb), follow it
 * with a 0x66, so the page always shows the selected type's controls. UI task, like the handler itself.
 * Slot layout (FUN_080a86a0): knob view at screen +0x450, its page at +0x3c, slot k at +0x40 + k * 0x3d0, the slot's
 * parameter id at slot +0x94 (= view + 0xd4 + k * 0x3d0, as FUN_080a8598 reads it).
 */
typedef void (*screen_msg_fn)(uint8_t *screen, const uint16_t *msg);
#define fw_screen_msg ((screen_msg_fn)FN(0x080ab900))

void fx_screen_msg(uint8_t *screen, const uint16_t *msg)
{
    fw_screen_msg(screen, msg);
    if (!msg || msg[0] != 0x32)
        return;
    uint8_t *view = screen + 0x450;
    int slot = (int)*(const int16_t *)((const uint8_t *)msg + 0xc) + *(int32_t *)(view + 0x3c) * 4;
    if (slot < 0 || slot >= 8)
        return;
    uint16_t id = *(uint16_t *)(view + 0xd4 + slot * 0x3d0);
    if (id != P_TYPE && id != P_FX2_TYPE)
        return;
    uint16_t rebuild[16] = {0x66};
    fw_screen_msg(screen, rebuild);
}

}  /* extern "C" */
