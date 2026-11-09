.syntax unified
.thumb
.arch armv7e-m
@ fake LTDC line IRQ at 0x00000200: FUN_08041b60() (gives the UI frame semaphore)
push {r4, lr}
ldr r2, =0x08041b61
blx r2
pop {r4, pc}
.ltorg
