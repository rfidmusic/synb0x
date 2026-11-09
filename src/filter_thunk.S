/*
 * Per-voice filter call sites. r0 = filter object, r1 = audio buffer; filter_process also gets r2 = the pad object the
 * voice belongs to and r3 = the voice's amp envelope stage byte (the envelope object's +4).
 * Sample pads (class A, stock call 0x08055c60, now run from 0x08055bd6): voice = obj - 0xa8, amp envelope at voice +
 * 0x28, pad in r6. Clip / slicer pads (class B, stock call 0x080669d6, now run from 0x080669c0): two voice blocks per pad (pad + 0x260 + v * 0x410), filter object at
 * block + 0x14c, amp envelope at block + 0x258, pad in r6 (FUN_080667b8 sets it once, at 0x080667dc). Before this
 * build the pad was taken as obj - 0x3ac, which is right only for the first voice.
 */
    .syntax unified
    .thumb
    .text

/*
 * Sample / multisample voices: the filter (with Fidelity and the oscillator) runs FIRST in the voice's closing routine
 * FUN_08055bb8, before the stock Level (with velocity), Pan and amp envelope, so those shape the filtered voice and the
 * oscillator like a synth's VCA after its VCF. Stock order: Level, Pan, amp envelope, filter (its call at 0x08055c60 is
 * now two nops). Replaces the stock call at 0x08055bd6 (FUN_0804d8d0, buffer r0, frames r1: the buffer's frame count),
 * then r4 = voice, r5 = audio buffer, r6 = pad.
 */
    .global filter_voice_a
    .thumb_func
    .type filter_voice_a, %function
filter_voice_a:
    push    {r3, lr}
    ldr     r12, =0x0804d8d0 + 1
    blx     r12
    pop     {r3, lr}
    add.w   r0, r4, #0xa8               /* filter object */
    mov     r1, r5
    mov     r2, r6
    add.w   r3, r4, #0x2c               /* amp envelope stage = obj - 0x7c */
    b.w     filter_process
    .ltorg

/*
 * Clip / slicer voices: the same order, the filter before the stock amp envelope (block + 0x258, FUN_0806a6c0 at
 * 0x08066d24, run when the voice's start delay +0x138 is 0; stock ran the filter after it, at 0x080669d6, now nops).
 * Replaces the stock call at 0x080669c0 (FUN_0804d944: buffer r0, &left r1, &right r2; reached every block), then
 * r5 = voice block, fp = audio buffer, r6 = pad.
 */
    .global filter_voice_b
    .thumb_func
    .type filter_voice_b, %function
filter_voice_b:
    push    {r3, lr}
    ldr     r12, =0x0804d944 + 1
    blx     r12
    pop     {r3, lr}
    add.w   r0, r5, #0x14c              /* filter object */
    mov     r1, fp
    mov     r2, r6
    add.w   r3, r5, #0x25c              /* amp envelope stage = obj + 0x110 */
    b.w     filter_process
    .ltorg

/*
 * The stock buffer loops, four at a time (CPU): stock does one value per pass (load, op, store, count, branch). Same
 * operation per element: bit-identical. Reached from the stock wrappers' tail jumps (patches/filter.py): scale
 * y = x * g (FUN_0805fd14 -> 0x080c7550: settled Level / Pan gains, ~4 passes per voice block), copy (FUN_0805f5c0 ->
 * 0x080c7566: the sample fetch), fill (FUN_0805f614 -> 0x080c7578: clearing). A copy overlapping just ahead of its
 * source goes one by one, as stock.
 */
    .global fast_scale                  /* r0 x, r1 y, r2 n, s0 g */
    .thumb_func
    .type fast_scale, %function
fast_scale:
    subs    r2, #4
    blt     2f
1:  vldmia  r0!, {s4-s7}
    vmul.f32 s4, s4, s0
    vmul.f32 s5, s5, s0
    vmul.f32 s6, s6, s0
    vmul.f32 s7, s7, s0
    subs    r2, #4
    vstmia  r1!, {s4-s7}
    bge     1b
2:  adds    r2, #4
    beq     4f
3:  vldmia  r0!, {s4}
    vmul.f32 s4, s4, s0
    subs    r2, #1
    vstmia  r1!, {s4}
    bne     3b
4:  bx      lr

    .global fast_copy                   /* r0 src, r1 dst, r2 n words */
    .thumb_func
    .type fast_copy, %function
fast_copy:
    subs    r3, r1, r0
    cmp     r3, #32
    bhs     5f                          /* (dst at or behind src, or 8+ words ahead: eight at a time) */
    cmp     r3, #0
    bne     7f                          /* (just ahead: one by one) */
5:  push    {r4, r5, r6, r7, r8, r9}
    subs    r2, #8
    blt     15f
8:  pld     [r0, #256]                  /* (3.1.v4) a cache line at a time, the source asked for 8 lines ahead: */
    ldmia   r0!, {r3, r4, r5, r6, r7, r8, r9, r12}   /* the slow part is the source in SDRAM (a grain's */
    subs    r2, #8                      /* samples from the sample cache), and the preload overlaps its wait */
    stmia   r1!, {r3, r4, r5, r6, r7, r8, r9, r12}
    bge     8b
15: adds    r2, #4
    blt     6f
    ldmia   r0!, {r3, r4, r5, r12}
    subs    r2, #4
    stmia   r1!, {r3, r4, r5, r12}
6:  pop     {r4, r5, r6, r7, r8, r9}
    adds    r2, #4
7:  cbz     r2, 9f
10: ldr     r3, [r0], #4
    subs    r2, #1
    str     r3, [r1], #4
    bne     10b
9:  bx      lr

    .global fast_fill                   /* r0 dst, r1 n, s0 value */
    .thumb_func
    .type fast_fill, %function
fast_fill:
    vmov.f32 s1, s0
    vmov.f32 s2, s0
    vmov.f32 s3, s0
    subs    r1, #4
    blt     12f
11: vstmia  r0!, {s0-s3}
    subs    r1, #4
    bge     11b
12: adds    r1, #4
    beq     14f
13: vstmia  r0!, {s0}
    subs    r1, #1
    bne     13b
14: bx      lr

/* The stock bus mix (FUN_080617c0, entered by a jump at its first instruction): y += x, n values (r0 x, r1 n, r2 y),
   four at a time with multi-register loads (stock: four per pass but each value loaded / stored on its own). The same
   additions: bit-identical. */
    .global fast_mixadd
    .thumb_func
    .type fast_mixadd, %function
fast_mixadd:
    vpush   {s16-s19}
    subs    r1, #4
    blt     16f
15: vldmia  r0!, {s4-s7}
    vldmia  r2, {s16-s19}
    vadd.f32 s16, s16, s4
    vadd.f32 s17, s17, s5
    vadd.f32 s18, s18, s6
    vadd.f32 s19, s19, s7
    subs    r1, #4
    vstmia  r2!, {s16-s19}
    bge     15b
16: vpop    {s16-s19}
    adds    r1, #4
    beq     18f
17: vldmia  r0!, {s4}
    vldr    s5, [r2]
    vadd.f32 s5, s5, s4
    subs    r1, #1
    vstmia  r2!, {s5}
    bne     17b
18: bx      lr

/*
 * The stock amp envelope's per-sample glide (FUN_0806a6c0, from 0x0806a822, while its gain moves towards the
 * stage's target): g += (target - g) x coef per sample, the voice multiplied by g, until |target - g| < eps, then
 * g = target and the rest of the call multiplied by target. Stock keeps g, target and coef in the envelope object
 * and loads / stores them every sample (20 instructions a sample, stereo); here they stay in registers. The same
 * arithmetic in the same order (fused multiply-add included): bit-identical. Its registers, as stock leaves them:
 * r4 envelope, r0 left + offset, r3 offset (bytes), sb right (0: mono), r5 frames, s15 g, s16 target, s17 coef,
 * s18 eps. Returns to the stock code at 0x0806a780.
 */
    .global env_glide
    .thumb_func
    .type env_glide, %function
env_glide:
    vstr    s17, [r4, #0x24]            /* (the instruction it replaces) */
    cmp     r5, #0
    ble     29f
    mov     r1, r0
    add.w   r2, sb, r3
    mov     r12, r5
    cmp     sb, #0
    beq     24f
21: vsub.f32 s14, s16, s15              /* stereo */
    vfma.f32 s15, s14, s17
    vabs.f32 s14, s14
    vcmpe.f32 s14, s18
    vmrs    APSR_nzcv, fpscr
    bmi     22f
    vldr    s13, [r1]
    vmul.f32 s13, s13, s15
    vstmia  r1!, {s13}
    vldr    s12, [r2]
    vmul.f32 s12, s12, s15
    vstmia  r2!, {s12}
    subs    r12, #1
    bne     21b
    vstr    s15, [r4, #0x1c]
    b       29f
22: bl      27f                         /* arrived: g = target, glide off; the rest x target unless 1 */
    beq     29f
23: vldr    s13, [r1]
    vmul.f32 s13, s13, s16
    vstmia  r1!, {s13}
    vldr    s12, [r2]
    vmul.f32 s12, s12, s16
    vstmia  r2!, {s12}
    subs    r12, #1
    bne     23b
    b       29f
24: vsub.f32 s14, s16, s15              /* mono */
    vfma.f32 s15, s14, s17
    vabs.f32 s14, s14
    vcmpe.f32 s14, s18
    vmrs    APSR_nzcv, fpscr
    bmi     25f
    vldr    s13, [r1]
    vmul.f32 s13, s13, s15
    vstmia  r1!, {s13}
    subs    r12, #1
    bne     24b
    vstr    s15, [r4, #0x1c]
    b       29f
25: bl      27f
    beq     29f
26: vldr    s13, [r1]
    vmul.f32 s13, s13, s16
    vstmia  r1!, {s13}
    subs    r12, #1
    bne     26b
    b       29f
27: vstr    s16, [r4, #0x1c]            /* (arrived: Z set when the target is 1.0) */
    movs    r3, #0
    str     r3, [r4, #0x24]
    vmov.f32 s14, #1.0
    vcmp.f32 s16, s14
    vmrs    APSR_nzcv, fpscr
    bx      lr
29: ldr     r3, =0x0806a780 + 1
    bx      r3
    .ltorg

/*
 * The shared reader (3.1.v1, CPU). FUN_08055f0c reads a stereo sample with two kernel calls in a row, left then right,
 * with the same rate, position and length and equal starting fractions (its local_34, a copy of local_4c), so the
 * reading point moves the same way twice. Here the left call does both channels in one loop: the position steps once,
 * each channel's interpolation is stock's, operation for operation (bit-identical), and the right call does nothing. A
 * machine mode (read_is_machine) keeps the per-channel path (read_normal). At the left call (0x0805619a): s0 rate,
 * r0 left source, r2 position, r3 &newpos, [sp] &frac (left), [sp+4] left out, [sp+8] frames; the caller's frame gives
 * the right call's: [sp+0x24] right source, [sp+0x2c] + 4 x [sp+0x6c] right out, sp+0x1c &frac (right).
 */
    .global read_normal_l
    .thumb_func
    .type read_normal_l, %function
read_normal_l:
    push    {r0, r1, r2, r3, r12, lr}
    vpush   {d0}
    bl      read_is_machine
    cmp     r0, #0
    vpop    {d0}
    pop     {r0, r1, r2, r3, r12, lr}
    bne.w   read_normal
    push    {r4, r5, r6, r7, r8, r9, r10, r11, lr}
    vpush   {s16-s20}
    add     r12, sp, #56                /* the caller's frame */
    ldr     r4, [r12]                   /* &frac (left) */
    ldr     r5, [r12, #4]               /* left out */
    ldr     r6, [r12, #8]               /* frames */
    ldr     r7, [r12, #0x24]            /* right source */
    ldr     r8, [r12, #0x2c]
    ldr     r9, [r12, #0x6c]
    add.w   r8, r8, r9, lsl #2          /* right out */
    add.w   r9, r12, #0x1c              /* &frac (right) */
    mvn     r1, #0xc0000000
    adds    r1, r2, r1                  /* position - 1 */
    add.w   r10, r0, r1, lsl #2         /* left reading point */
    add.w   r11, r7, r1, lsl #2         /* right reading point */
    vldr    s13, [r4]
    cmp     r6, #0
    ble     32f
31: vldr    s1, [r10, #8]
    vldr    s16, [r11, #8]
    vmul.f32 s8, s13, s13
    vldr    s2, [r10, #12]
    vldr    s17, [r11, #12]
    vadd.f32 s9, s0, s13
    vldr    s3, [r10]
    vldr    s18, [r11]
    vsub.f32 s2, s2, s1
    vsub.f32 s17, s17, s16
    vldr    s4, [r10, #4]
    vldr    s19, [r11, #4]
    vsub.f32 s1, s1, s3
    vsub.f32 s16, s16, s18
    vsub.f32 s5, s3, s4
    vsub.f32 s20, s18, s19
    vsub.f32 s2, s2, s3
    vsub.f32 s17, s17, s18
    vcvt.s32.f32 s6, s9
    vadd.f32 s2, s2, s4
    vadd.f32 s17, s17, s19
    vcvt.f32.s32 s7, s6
    vmov    r1, s6
    vsub.f32 s5, s5, s2
    vsub.f32 s20, s20, s17
    add.w   r10, r10, r1, lsl #2
    add.w   r11, r11, r1, lsl #2
    vmul.f32 s2, s2, s13
    vmul.f32 s17, s17, s13
    vmul.f32 s5, s5, s8
    vmul.f32 s20, s20, s8
    vfma.f32 s5, s2, s8
    vfma.f32 s20, s17, s8
    vfma.f32 s5, s1, s13
    vfma.f32 s20, s16, s13
    vsub.f32 s13, s9, s7
    vadd.f32 s5, s5, s4
    vadd.f32 s20, s20, s19
    vstmia  r5!, {s5}
    vstmia  r8!, {s20}
    subs    r6, #1
    bne     31b
32: vstr    s13, [r4]
    vstr    s13, [r9]
    subs    r1, r10, r0
    asrs    r1, r1, #2
    adds    r1, #1
    str     r1, [r3]
    vpop    {s16-s20}
    pop     {r4, r5, r6, r7, r8, r9, r10, r11, pc}

    .global read_normal_r               /* the right call: done by the left one, unless a machine mode reads */
    .thumb_func
    .type read_normal_r, %function
read_normal_r:
    push    {r0, r1, r2, r3, r12, lr}
    vpush   {d0}
    bl      read_is_machine
    cmp     r0, #0
    vpop    {d0}
    pop     {r0, r1, r2, r3, r12, lr}
    bne.w   read_normal
    bx      lr

/*
 * HighQ (FUN_08061a64, its 4-point Hermite in double precision), both channels per sample the same way: the left
 * call (0x08056098) does both, the right one (0x080560bc) nothing unless a machine mode reads. Stock's own register
 * use leaves no room to run the channels side by side, so each sample works out the left channel, then the right,
 * with stock's instructions in stock's order; the shared parts (frac^2, frac in double, rate + frac, the step and the
 * next frac) once. Same arguments and caller frame as the Normal pair.
 */
    .global read_hq_l
    .thumb_func
    .type read_hq_l, %function
read_hq_l:
    push    {r0, r1, r2, r3, r12, lr}
    vpush   {d0}
    bl      read_is_machine
    cmp     r0, #0
    vpop    {d0}
    pop     {r0, r1, r2, r3, r12, lr}
    bne.w   read_hq
    push    {r4, r5, r6, r7, r8, r9, r10, r11, lr}
    vpush   {d8-d15}
    add     r12, sp, #100               /* the caller's frame (9 x 4 + 8 x 8) */
    ldr     r4, [r12]
    ldr     r5, [r12, #4]
    ldr     r6, [r12, #8]
    ldr     r7, [r12, #0x24]
    ldr     r8, [r12, #0x2c]
    ldr     r9, [r12, #0x6c]
    add.w   r8, r8, r9, lsl #2
    add.w   r9, r12, #0x1c
    mvn     r1, #0xc0000000
    adds    r1, r2, r1
    add.w   r10, r0, r1, lsl #2
    add.w   r11, r7, r1, lsl #2
    vldr    s22, [r4]
    cmp     r6, #0
    ble     42f
    vmov.f32 s28, s0
    vmov.f64 d9, #1.5
    vmov.f64 d8, #-0.5
    vmov.f64 d1, #0.5
    vmov.f64 d15, #2.5
41: vmul.f32 s23, s22, s22
    vcvt.f64.f32 d13, s22
    vadd.f32 s24, s28, s22
    vldr    s8, [r10, #4]
    vldr    s20, [r10]
    vcvt.f64.f32 d4, s8
    vldr    s10, [r10, #8]
    vcvt.f64.f32 d10, s20
    vldr    s6, [r10, #12]
    vcvt.f64.f32 d0, s10
    vmul.f64 d6, d4, d9
    vmov.f64 d7, d10
    vadd.f32 s10, s10, s10
    vcvt.f64.f32 d3, s6
    vfma.f64 d6, d10, d8
    vfms.f64 d7, d4, d15
    vcvt.f64.f32 d5, s10
    vmul.f64 d2, d0, d1
    vfms.f64 d6, d0, d9
    vadd.f64 d7, d7, d5
    vfma.f64 d2, d10, d8
    vfms.f64 d7, d3, d1
    vfma.f64 d6, d3, d1
    vcvt.f32.f64 s14, d7
    vmul.f32 s14, s14, s23
    vcvt.f32.f64 s12, d6
    vmul.f32 s12, s12, s22
    vfma.f32 s14, s12, s23
    vcvt.f64.f32 d7, s14
    vfma.f64 d7, d2, d13
    vadd.f64 d7, d7, d4
    vcvt.f32.f64 s14, d7
    vstmia  r5!, {s14}
    vldr    s8, [r11, #4]
    vldr    s20, [r11]
    vcvt.f64.f32 d4, s8
    vldr    s10, [r11, #8]
    vcvt.f64.f32 d10, s20
    vldr    s6, [r11, #12]
    vcvt.f64.f32 d0, s10
    vmul.f64 d6, d4, d9
    vmov.f64 d7, d10
    vadd.f32 s10, s10, s10
    vcvt.f64.f32 d3, s6
    vfma.f64 d6, d10, d8
    vfms.f64 d7, d4, d15
    vcvt.f64.f32 d5, s10
    vmul.f64 d2, d0, d1
    vfms.f64 d6, d0, d9
    vadd.f64 d7, d7, d5
    vfma.f64 d2, d10, d8
    vfms.f64 d7, d3, d1
    vfma.f64 d6, d3, d1
    vcvt.f32.f64 s14, d7
    vmul.f32 s14, s14, s23
    vcvt.f32.f64 s12, d6
    vmul.f32 s12, s12, s22
    vfma.f32 s14, s12, s23
    vcvt.f64.f32 d7, s14
    vfma.f64 d7, d2, d13
    vadd.f64 d7, d7, d4
    vcvt.f32.f64 s14, d7
    vstmia  r8!, {s14}
    vcvt.s32.f32 s25, s24
    vmov    r1, s25
    vcvt.f32.s32 s29, s25
    add.w   r10, r10, r1, lsl #2
    add.w   r11, r11, r1, lsl #2
    vsub.f32 s22, s24, s29
    subs    r6, #1
    bne     41b
42: vstr    s22, [r4]
    vstr    s22, [r9]
    subs    r1, r10, r0
    asrs    r1, r1, #2
    adds    r1, #1
    str     r1, [r3]
    vpop    {d8-d15}
    pop     {r4, r5, r6, r7, r8, r9, r10, r11, pc}

    .global read_hq_r
    .thumb_func
    .type read_hq_r, %function
read_hq_r:
    push    {r0, r1, r2, r3, r12, lr}
    vpush   {d0}
    bl      read_is_machine
    cmp     r0, #0
    vpop    {d0}
    pop     {r0, r1, r2, r3, r12, lr}
    bne.w   read_hq
    bx      lr

/*
 * The grain / clip resampler (FUN_080603ec: s0 rate, r0 source, r1 end, r2 &pos, r3 &frac, [sp] out, [sp+4] frames;
 * the reading point starts at 0, steps by rate, stops early at the source's end), both channels in one loop
 * (3.1.v1, CPU). Its two stereo callers read left then right with the same rate, end and frames and equal starting
 * fractions: the grain renderer (0x08057f78 / 0x08057f92; right: [sp+0x28] source, [sp+0x30] out, sp+0x34 &pos,
 * r4 + 0x20 &frac) and the clip / slicer voice (0x080663ec / 0x08066404; right: [sp+0x14] source, [sp+0x1c] out,
 * [sp+0x4c] &pos, [sp+0x50] &frac). The left call does both, each channel's interpolation stock's sequence (bit-
 * identical), the shared position once; the right call returns.
 * Core registers: r0 / r7 sources, r1 end, r5 / r8 outs, r6 frames, r9 / r10 &pos, r3 / r11 &frac.
 */
    .global resamp_grain_l
    .thumb_func
    .type resamp_grain_l, %function
resamp_grain_l:
    push    {r4, r5, r6, r7, r8, r9, r10, r11, lr}
    vpush   {s16-s20}
    push    {r0, r1, r2, r3}            /* (3.1.v5) the pad's Fidelity: HighQ keeps this cubic, anything else */
    vpush   {s0, s1}                    /* reads linearly (grain_linear, filter.c; r8 = the renderer's pad) */
    mov     r0, r8
    bl      grain_linear
    mov     lr, r0
    vpop    {s0, s1}
    pop     {r0, r1, r2, r3}
    add     r12, sp, #56                /* the caller's frame */
    ldr     r5, [r12]
    ldr     r6, [r12, #4]
    ldr     r7, [r12, #0x28]
    ldr     r8, [r12, #0x30]
    mov     r9, r2
    add.w   r10, r12, #0x34
    add.w   r11, r4, #0x20
    cmp     lr, #0
    beq     50f

/* (3.1.v5) Linear, for granular pads not on HighQ: x1 + t (x2 - x1) per channel (the cubic's middle two points), the
   reading point stepped and stopped exactly as the cubic does, so grains keep their lengths and positions. */
    vldr    s13, [r3]
    movs    r2, #0
    cmp     r6, #0
    ble     53f
    vmov.f32 s8, #1.0
61: add.w   r12, r0, r2, lsl #2
    add.w   r4, r7, r2, lsl #2
    vldr    s11, [r12, #4]
    vldr    s12, [r12, #8]
    vldr    s19, [r4, #4]
    vldr    s16, [r4, #8]
    vsub.f32 s12, s12, s11
    vsub.f32 s16, s16, s19
    vfma.f32 s11, s12, s13
    vfma.f32 s19, s16, s13
    vadd.f32 s13, s13, s0
    vcmpe.f32 s13, s8
    vstmia  r5!, {s11}
    vstmia  r8!, {s19}
    vmrs    APSR_nzcv, fpscr
    blt     62f
    vcvt.s32.f32 s15, s13
    vmov    r12, s15
    vcvt.f32.s32 s15, s15
    add     r2, r12
    vsub.f32 s13, s13, s15
    add.w   r12, r2, #4
    cmp     r12, r1
    bge     53f
62: subs    r6, #1
    bne     61b
    b       53f

    .global resamp_clip_l
    .thumb_func
    .type resamp_clip_l, %function
resamp_clip_l:
    push    {r4, r5, r6, r7, r8, r9, r10, r11, lr}
    vpush   {s16-s20}
    add     r12, sp, #56
    ldr     r5, [r12]
    ldr     r6, [r12, #4]
    ldr     r7, [r12, #0x14]
    ldr     r8, [r12, #0x1c]
    mov     r9, r2
    ldr     r10, [r12, #0x4c]
    ldr     r11, [r12, #0x50]
50: vldr    s13, [r3]
    movs    r2, #0
    cmp     r6, #0
    ble     53f
    vmov.f32 s8, #1.0
    vcmpe.f32 s0, #0.0                  /* (3.1.v5) rate > 0 and fraction >= 0 (always, in practice): the */
    vmrs    APSR_nzcv, fpscr            /* pipelined loop below; otherwise this one, as before */
    ble     51f
    vcmpe.f32 s13, #0.0
    vmrs    APSR_nzcv, fpscr
    bge     70f
51: add.w   r12, r0, r2, lsl #2
    add.w   r4, r7, r2, lsl #2
    vmul.f32 s9, s13, s13
    vldr    s12, [r12, #8]
    vldr    s16, [r4, #8]
    vldr    s14, [r12, #12]
    vldr    s17, [r4, #12]
    vldr    s10, [r12]
    vldr    s18, [r4]
    vsub.f32 s14, s14, s12
    vsub.f32 s17, s17, s16
    vldr    s11, [r12, #4]
    vldr    s19, [r4, #4]
    vsub.f32 s12, s12, s10
    vsub.f32 s16, s16, s18
    vsub.f32 s15, s10, s11
    vsub.f32 s20, s18, s19
    vsub.f32 s14, s14, s10
    vsub.f32 s17, s17, s18
    vadd.f32 s14, s14, s11
    vadd.f32 s17, s17, s19
    vsub.f32 s15, s15, s14
    vsub.f32 s20, s20, s17
    vmul.f32 s14, s14, s13
    vmul.f32 s17, s17, s13
    vmul.f32 s15, s15, s9
    vmul.f32 s20, s20, s9
    vfma.f32 s15, s9, s14
    vfma.f32 s20, s9, s17
    vfma.f32 s15, s12, s13
    vfma.f32 s20, s16, s13
    vadd.f32 s13, s13, s0
    vcmpe.f32 s13, s8
    vadd.f32 s15, s15, s11
    vadd.f32 s20, s20, s19
    vmrs    APSR_nzcv, fpscr
    vstmia  r5!, {s15}
    vstmia  r8!, {s20}
    blt     52f
    vcvt.s32.f32 s15, s13
    vmov    r12, s15
    vcvt.f32.s32 s15, s15
    add     r2, r12
    vsub.f32 s13, s13, s15
    add.w   r12, r2, #4
    cmp     r12, r1
    bge     53f
52: subs    r6, #1
    bne     51b
    b       53f

/* (3.1.v5) The same cubic, the next reading point worked out while this sample's arithmetic runs (the core waits
   less): t + rate, its whole part k (0 while below 1: t + rate - 0 is t + rate exactly, as stock's no-step path), the
   new fraction t + rate - k. Each channel's operations stock's, in stock's order: bit for bit the same output. */
70: add.w   r12, r0, r2, lsl #2
    add.w   r4, r7, r2, lsl #2
    vmul.f32 s9, s13, s13
    vldr    s12, [r12, #8]
    vldr    s16, [r4, #8]
    vldr    s14, [r12, #12]
    vldr    s17, [r4, #12]
    vadd.f32 s1, s13, s0
    vldr    s10, [r12]
    vldr    s18, [r4]
    vsub.f32 s14, s14, s12
    vsub.f32 s17, s17, s16
    vldr    s11, [r12, #4]
    vldr    s19, [r4, #4]
    vcvt.s32.f32 s3, s1
    vsub.f32 s12, s12, s10
    vsub.f32 s16, s16, s18
    vsub.f32 s15, s10, s11
    vsub.f32 s20, s18, s19
    vmov    lr, s3
    vsub.f32 s14, s14, s10
    vsub.f32 s17, s17, s18
    vcvt.f32.s32 s2, s3
    vadd.f32 s14, s14, s11
    vadd.f32 s17, s17, s19
    add     r2, lr
    vsub.f32 s15, s15, s14
    vsub.f32 s20, s20, s17
    vmul.f32 s14, s14, s13
    vmul.f32 s17, s17, s13
    vmul.f32 s15, s15, s9
    vmul.f32 s20, s20, s9
    vfma.f32 s15, s9, s14
    vfma.f32 s20, s9, s17
    vfma.f32 s15, s12, s13
    vfma.f32 s20, s16, s13
    vsub.f32 s13, s1, s2
    vadd.f32 s15, s15, s11
    vadd.f32 s20, s20, s19
    vstmia  r5!, {s15}
    vstmia  r8!, {s20}
    cmp     lr, #0
    beq     72f
    add.w   r12, r2, #4
    cmp     r12, r1
    bge     53f
72: subs    r6, #1
    bne     70b
53: str     r2, [r9]
    str     r2, [r10]
    vstr    s13, [r3]
    vstr    s13, [r11]
    vpop    {s16-s20}
    pop     {r4, r5, r6, r7, r8, r9, r10, r11, pc}

    .global resamp_r                    /* the right call: done by the left one */
    .thumb_func
    .type resamp_r, %function
resamp_r:
    bx      lr
