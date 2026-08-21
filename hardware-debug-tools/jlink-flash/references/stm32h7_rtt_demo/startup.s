@ Cortex-M7 startup: vector table + reset handler (minimal, no libc)
.syntax unified
.cpu cortex-m7
.thumb

.section .isr_vector,"a",%progbits
.type g_pfnVectors, %object
g_pfnVectors:
    .word _estack                  @ 0x00: initial SP
    .word Reset_Handler            @ 0x04: Reset
    .word Default_Handler          @ 0x08: NMI
    .word Default_Handler          @ 0x0C: HardFault
    .word Default_Handler          @ 0x10: MemManage
    .word Default_Handler          @ 0x14: BusFault
    .word Default_Handler          @ 0x18: UsageFault
    .word 0                        @ 0x1C: reserved
    .word 0                        @ 0x20: reserved
    .word 0                        @ 0x24: reserved
    .word 0                        @ 0x28: reserved
    .word Default_Handler          @ 0x2C: SVCall
    .word 0                        @ 0x30: DebugMon
    .word 0                        @ 0x34: reserved
    .word Default_Handler          @ 0x38: PendSV
    .word Default_Handler          @ 0x3C: SysTick
    .rept 100                      @ external IRQs (padding)
    .word Default_Handler
    .endr
.size g_pfnVectors, .-g_pfnVectors

.section .text
.thumb_func
.weak Default_Handler
.type Default_Handler, %function
Default_Handler:
    b Default_Handler
.size Default_Handler, .-Default_Handler

.thumb_func
.global Reset_Handler
.type Reset_Handler, %function
Reset_Handler:
    ldr r0, =_sidata
    ldr r1, =_sdata
    ldr r2, =_edata
copy_loop:
    cmp r1, r2
    bge zero_bss
    ldr r3, [r0], #4
    str r3, [r1], #4
    b copy_loop
zero_bss:
    ldr r1, =_sbss
    ldr r2, =_ebss
    movs r3, #0
z_loop:
    cmp r1, r2
    bge call_main
    str r3, [r1], #4
    b z_loop
call_main:
    bl main
hang:
    b hang
.size Reset_Handler, .-Reset_Handler

.end
