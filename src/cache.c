/*
 * The sample cache's page lookup for long files (3.1.v6). The cache (stock 3.1.9) holds samples in pages of 8192
 * frames: 615 slots of 0x1c bytes from the cache object (+0x0c page, +0x18 file id, +0x1e channel, +0x1f state); each
 * file's page -> slot table covers its first 1500 pages (256 s at 48 kHz). Past that, every read (FUN_08074a00, the
 * grain / sample read) and its look-ahead (FUN_08074554, the next 4 pages) searched all 615 slots: ~13,000
 * instructions per read instead of ~440 (a 387 s file on four granular pads: ~230,000 per block, the meter at 100),
 * and a page that is not in the cache always costs the whole search.
 *
 * Here those pages have an index of their own, kept exact: every slot the loader takes comes from one of two
 * allocators (FUN_08071d64, FUN_080713bc); hooks log each one (with the file / page it held), and each lookup first
 * enters the logged slots' new file / page. A page's entry is its lowest first-channel slot, and a flag says when more
 * than one slot holds the page (then the full search decides, as stock's lowest-match rule). A lookup checks the slot
 * exactly as the full search would. So the slot found (or none) is stock's: the same samples, the same requests.
 * Before the index search: the file's recent list, exactly as stock. If the log overflows, or a file's index finds no
 * room (24 KB of ITCM), the index is rebuilt / that file keeps the full search.
 */
#include <stdint.h>

#define SLOTS      0x267u
#define SLOT(c, s) ((const uint8_t *)(c) + (uint32_t)(s) * 0x1cu)
#define S_PAGE(e)  (*(const volatile uint32_t *)((e) + 0x0c))
#define S_FILE(e)  (*(const volatile uint32_t *)((e) + 0x18))
#define S_CH(e)    (*(const volatile uint8_t *)((e) + 0x1e))
#define S_STATE(e) (*(const volatile uint8_t *)((e) + 0x1f))
#define FILES(c)   (*(uint8_t *const *)((const uint8_t *)(c) + 0x4348))
#define NFILES     0x240u
#define FIRST      1500u                               /* pages below: the stock tables */
#define DWT_CYCCNT (*(volatile uint32_t *)0xe0001004u)

/* ITCM (64 KB, unused by the firmware past 0x400; grain.c's window at 0x8000) */
struct dir_entry { uint16_t file, chunk, pool, pad; };
struct pend { uint32_t slot, when, file, page; };
#define CHUNK_PAGES 512u
#define DIRS        24u
#define DIR    ((volatile struct dir_entry *)0x00001000u)      /* 24 x 8 */
#define OVER   ((volatile uint8_t *)0x000010c0u)               /* 0x240 bits: the file has no index (no room) */
#define STATE  ((volatile uint32_t *)0x00001110u)              /* [0] head, [1] tail, [2] ready, [3] cache, [4] lost */
#define PEND   ((volatile struct pend *)0x00001200u)           /* 512 x 16 = 8 KB */
#define NPEND  512u
#define POOL   ((volatile uint16_t *)0x00003200u)              /* 24 chunks x 512 x 2 = 24 KB, to 0x9200? no: */
#define NPOOL  ((0x8000u - 0x3200u) / (CHUNK_PAGES * 2u))      /* 19 chunks (to the window at 0x8000) */
#define DUP    0x8000u                                          /* entry flag: more than one slot holds the page */
#define EMPTY  0xffffu
#define AGE    50000000u                                        /* a logged slot's key written within ~100 ms */

void cache_hint_init(void)                                      /* at boot (grain_tab_init) */
{
    for (unsigned i = 0; i < DIRS; i++)
        DIR[i].file = EMPTY;
    for (unsigned i = 0; i < NFILES / 8u; i++)
        OVER[i] = 0;
    STATE[0] = STATE[1] = STATE[2] = STATE[3] = STATE[4] = 0;
}

static volatile uint16_t *entry(uint32_t file, uint32_t page, int make)
{
    uint32_t c = (page - FIRST) / CHUNK_PAGES, off = (page - FIRST) % CHUNK_PAGES;
    if (c > 0xfffeu)
        return 0;
    unsigned free = DIRS;
    for (unsigned i = 0; i < DIRS; i++) {
        if (DIR[i].file == file && DIR[i].chunk == c)
            return POOL + DIR[i].pool * CHUNK_PAGES + off;
        if (DIR[i].file == EMPTY && free == DIRS)
            free = i;
    }
    if (!make)
        return 0;
    unsigned used = 0;
    for (unsigned i = 0; i < DIRS; i++)
        used += DIR[i].file != EMPTY;
    if (free == DIRS || used >= NPOOL) {
        OVER[file >> 3] |= (uint8_t)(1u << (file & 7u));
        return 0;
    }
    volatile uint16_t *ch = POOL + used * CHUNK_PAGES;          /* chunks handed out in order, never returned */
    for (unsigned k = 0; k < CHUNK_PAGES; k++)
        ch[k] = EMPTY;
    DIR[free].chunk = (uint16_t)c;
    DIR[free].pool = (uint16_t)used;
    DIR[free].file = (uint16_t)file;
    return ch + off;
}

static inline int over(uint32_t file)
{
    return (OVER[file >> 3] >> (file & 7u)) & 1u;
}

/* Slot s now holds (file, page): enter it (lowest slot; the DUP flag when another slot holds the page too). */
static void record(const uint8_t *cache, unsigned s)
{
    const uint8_t *e = SLOT(cache, s);
    uint32_t file = S_FILE(e), page = S_PAGE(e);
    if (S_CH(e) || file >= NFILES || page < FIRST || over(file))
        return;
    volatile uint16_t *p = entry(file, page, 1);
    if (!p)
        return;
    unsigned cur = *p, cs = cur & ~DUP;
    if (cur == EMPTY) {
        *p = (uint16_t)s;
        return;
    }
    if (cs == s)
        return;
    const uint8_t *ce = SLOT(cache, cs);
    int still = cs < SLOTS && S_FILE(ce) == file && S_PAGE(ce) == page && !S_CH(ce);
    if (!still)
        *p = (uint16_t)(s | (cur & DUP));                       /* (the old slot moved on; a DUP stays: the full */
    else                                                        /*  search will settle it) */
        *p = (uint16_t)((cs < s ? cs : s) | DUP);
}

/* Rebuild the whole index from the slots (first use, or the log overflowed). */
static void rebuild(const uint8_t *cache)
{
    unsigned used = 0;
    for (unsigned i = 0; i < DIRS; i++)
        used += DIR[i].file != EMPTY;
    for (unsigned k = 0; k < used * CHUNK_PAGES; k++)
        POOL[k] = EMPTY;
    for (unsigned s = 0; s < SLOTS; s++)
        record(cache, s);
}

/* The allocator hooks (the loader task): log the slot with the file / page it holds now. */
static void pend_add(const uint8_t *cache, unsigned s)
{
    if (s >= SLOTS)
        return;
    uint32_t h = STATE[0];
    if (h - STATE[1] >= NPEND) {
        STATE[4] = 1;                                           /* lost: the next lookup rebuilds */
        return;
    }
    volatile struct pend *q = &PEND[h % NPEND];
    const uint8_t *e = SLOT(cache, s);
    q->slot = s;
    q->when = DWT_CYCCNT;
    q->file = S_FILE(e);
    q->page = S_PAGE(e);
    __asm volatile("dmb" ::: "memory");
    STATE[0] = h + 1u;
}

typedef int (*d64_fn)(void *cache);
typedef void (*a13_fn)(void *cache, unsigned fentry, uint32_t page, uint16_t *out);
#define fw_slot_take  ((d64_fn)(0x08071d64u | 1u))
#define fw_slots_take ((a13_fn)(0x080713bcu | 1u))

int cache_slot_take(void *cache)                                /* bl FUN_08071d64 (6 calls) */
{
    int s = fw_slot_take(cache);
    pend_add(cache, (unsigned)s);
    return s;
}

void cache_slots_take(void *cache, unsigned fentry, uint32_t page, uint16_t *out)   /* bl FUN_080713bc */
{
    fw_slots_take(cache, fentry, page, out);
    for (unsigned i = 0; i < 4; i++)
        pend_add(cache, out[i]);
}

/* Enter the logged slots; drop the ones whose new file / page is in (or that are old enough). */
static void drain(const uint8_t *cache)
{
    if (!STATE[2] || STATE[3] != (uint32_t)cache || STATE[4]) {
        STATE[4] = 0;
        STATE[1] = STATE[0];
        STATE[3] = (uint32_t)cache;
        STATE[2] = 1;
        rebuild(cache);
        return;
    }
    uint32_t t = STATE[1], h = STATE[0], now = DWT_CYCCNT;
    int keep = 0;
    for (uint32_t i = t; i != h; i++) {
        volatile struct pend *q = &PEND[i % NPEND];
        const uint8_t *e = SLOT(cache, q->slot);
        record(cache, q->slot);
        int done = S_FILE(e) != q->file || S_PAGE(e) != q->page || now - q->when > AGE;
        if (!done)
            keep = 1;
        if (!keep)
            STATE[1] = i + 1u;                                  /* (only a done prefix leaves the log) */
    }
}

static inline int holds(const uint8_t *e, uint32_t file, uint32_t page)    /* the full search's test */
{
    return S_FILE(e) == file && S_STATE(e) && !S_CH(e) && S_PAGE(e) == page;
}

static void recent_push(uint8_t *fs, unsigned slot)                       /* stock's, after a full search */
{
    uint32_t n = *(uint32_t *)(fs + 0x48);
    *(uint16_t *)(fs + 0x30 + 2u * (n % 12u)) = (uint16_t)slot;
    *(uint32_t *)(fs + 0x48) = n + 1u;
}

static int full_search(const uint8_t *cache, uint8_t *fs, uint32_t file, uint32_t page)
{
    for (unsigned s = 0; s < SLOTS; s++)
        if (holds(SLOT(cache, s), file, page)) {
            recent_push(fs, s);
            return (int)s;
        }
    return -1;
}

/* The slot holding (file, page), page >= 1500, or -1: the cache object, the file's entry (its table index), file id. */
int cache_find(const uint8_t *cache, unsigned fentry, uint32_t file, uint32_t page)
{
    uint8_t *fs = FILES(cache) + fentry * 0x170u;
    for (unsigned k = 0; k < 12; k++) {                                    /* the recent list (stock's test) */
        unsigned s = *(const uint16_t *)(fs + 0x30 + 2u * k);
        const uint8_t *e = SLOT(cache, s);
        if (S_FILE(e) == file && S_STATE(e) && S_PAGE(e) == page)
            return (int)s;
    }
    if (file >= NFILES)
        return full_search(cache, fs, file, page);
    drain(cache);
    if (over(file))
        return full_search(cache, fs, file, page);
    volatile uint16_t *p = entry(file, page, 0);
    unsigned cur = p ? *p : EMPTY;
    if (cur == EMPTY)
        return -1;                                              /* no slot holds the page */
    if (cur & DUP) {                                            /* more than one: stock's lowest match decides, */
        int s = full_search(cache, fs, file, page);             /* and the entry is set again exactly */
        unsigned lo = EMPTY, n = 0;
        for (unsigned k = 0; k < SLOTS; k++) {
            const uint8_t *e = SLOT(cache, k);
            if (S_FILE(e) == file && S_PAGE(e) == page && !S_CH(e)) {
                if (lo == EMPTY)
                    lo = k;
                n++;
            }
        }
        *p = (uint16_t)(n == 0 ? EMPTY : (lo | (n > 1 ? DUP : 0u)));
        return s;
    }
    const uint8_t *e = SLOT(cache, cur);
    if (cur < SLOTS && S_FILE(e) == file && S_PAGE(e) == page && !S_CH(e)) {
        if (!S_STATE(e))
            return -1;                                          /* the only slot with it, not ready: stock finds none */
        recent_push(fs, cur);
        return (int)cur;
    }
    *p = EMPTY;                                                 /* the slot moved on and none other holds the page */
    return -1;
}
