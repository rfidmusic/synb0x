/*
 * Grid-or-list test for the pad screen's tabs (see filt_tab.c). Stock tests "tab == 0 || tab - 2 <= 1" inline at five
 * places (grid: Main, LFO, Gran; list: Pos, Conf). Those places now call one of these and branch on Z, which is set
 * when the tab in r2 / r3 is a list tab (1 or 4), so Filt (5) is a grid tab like Main. Every register but the flags is
 * left as it was.
 */
    .syntax unified
    .thumb
    .text

    .global filt_is_list_r2
    .thumb_func
    .type filt_is_list_r2, %function
filt_is_list_r2:
    cmp     r2, #1
    it      ne
    cmpne   r2, #4
    bx      lr

    .global filt_is_list_r3
    .thumb_func
    .type filt_is_list_r3, %function
filt_is_list_r3:
    cmp     r3, #1
    it      ne
    cmpne   r3, #4
    bx      lr
