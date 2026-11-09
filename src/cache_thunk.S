/* The sample cache's slow page lookups -> cache_find (cache.c), back into the stock code with its registers. */
    .syntax unified
    .thumb
    .text

/* FUN_08074a00 @0x08074ad6 (b.w here): fp cache, r7 file entry, r6 file id, r5 page; r3 live (position high).
   Found: r4 slot, sl = slot << 3, r1 = cache + 0x4000, on at 0x08074b5c. Not found: on at 0x08074a98. */
    .global cache_read_find
    .thumb_func
    .type cache_read_find, %function
cache_read_find:
    push    {r3, r4}
    mov     r0, fp
    mov     r1, r7
    mov     r2, r6
    mov     r3, r5
    bl      cache_find
    pop     {r3, r4}
    cmp     r0, #0
    blt     1f
    mov     r4, r0
    lsl.w   sl, r0, #3
    add.w   r1, fp, #0x4000
    ldr     r12, =0x08074b5d
    bx      r12
1:  ldr     r12, =0x08074a99
    bx      r12

/* FUN_08074554 @0x080745e2 (b.w here): r7 cache, r2 file entry, r4 file id, r6 page. Found: r3 slot, on at 0x0807466c.
   Not found: r2 = the file entry, on at 0x080745ae. */
    .global cache_ahead_find
    .thumb_func
    .type cache_ahead_find, %function
cache_ahead_find:
    push    {r2, r3}
    mov     r0, r7
    mov     r1, r2
    mov     r2, r4
    mov     r3, r6
    bl      cache_find
    pop     {r2, r3}
    cmp     r0, #0
    blt     2f
    mov     r3, r0
    ldr     r12, =0x0807466d
    bx      r12
2:  ldr     r12, =0x080745af
    bx      r12
    .ltorg
