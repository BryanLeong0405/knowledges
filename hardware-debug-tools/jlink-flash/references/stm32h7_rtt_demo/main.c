/* Minimal STM32H7 RTT demo: SEGGER RTT compatible control block + tick output.
 * No libc, no PLL config (runs on reset HSI clock), no interrupts used.
 * Control block placed at RAM start (0x20000000 on H7 DTCM) via .rtt_cb section.
 */
#include <stdint.h>
#include <stddef.h>

/* ---- SEGGER RTT compatible structures (layout must match SEGGER_RTT.h) ---- */
typedef struct {
    char        sName[16];      /* optional name */
    char*       pBuffer;        /* pointer to ring buffer */
    unsigned    SizeOfBuffer;   /* buffer size in bytes */
    unsigned    WrOff;          /* next write position (target writes Up) */
    unsigned    RdOff;          /* next read position (host reads Up) */
    unsigned    Flags;          /* 0: default, 1: blocking */
} RTT_BUF_UP;

typedef struct {
    char        sName[16];
    char*       pBuffer;
    unsigned    SizeOfBuffer;
    unsigned    WrOff;          /* host writes Down */
    unsigned    RdOff;          /* target reads Down */
    unsigned    Flags;
} RTT_BUF_DOWN;

typedef struct {
    char        acID[16];       /* "SEGGER RTT" + zero padding */
    int         MaxNumUpBuffers;
    int         MaxNumDownBuffers;
    RTT_BUF_UP  aUp[1];
    RTT_BUF_DOWN aDown[1];
} RTT_CB;

#define RTT_UP_SIZE   256
#define RTT_DOWN_SIZE 32

static char _up_buf[RTT_UP_SIZE] __attribute__((section(".bss")));
static char _down_buf[RTT_DOWN_SIZE] __attribute__((section(".bss")));

/* Control block lives at RAM start: linker puts .rtt_cb first in RAM. */
RTT_CB _SEGGER_RTT __attribute__((section(".rtt_cb"))) = {
    .acID = "SEGGER RTT",       /* pads to 16 with zeros */
    .MaxNumUpBuffers = 1,
    .MaxNumDownBuffers = 1,
    .aUp[0] = { "Terminal", _up_buf, RTT_UP_SIZE, 0, 0, 0 },
    .aDown[0] = { "Terminal", _down_buf, RTT_DOWN_SIZE, 0, 0, 0 },
};

/* Ring-buffer write (same strategy as SEGGER: keep 1 byte free to
 * distinguish full from empty). Returns bytes actually written. */
unsigned rtt_write(unsigned idx, const char* p, unsigned n) {
    RTT_BUF_UP* pUp;
    char* pBuf;
    unsigned size, wr, rd, free_bytes, first;

    if (idx >= (unsigned)_SEGGER_RTT.MaxNumUpBuffers) return 0;
    pUp = &_SEGGER_RTT.aUp[idx];
    pBuf = pUp->pBuffer;
    size = pUp->SizeOfBuffer;
    wr = pUp->WrOff;
    rd = pUp->RdOff;
    free_bytes = (rd <= wr) ? (size - (wr - rd) - 1u) : (rd - wr - 1u);
    if (n > free_bytes) n = free_bytes;
    if (n == 0) return 0;
    first = size - wr;
    if (n <= first) {
        for (unsigned i = 0; i < n; i++) pBuf[wr + i] = p[i];
    } else {
        for (unsigned i = 0; i < first; i++) pBuf[wr + i] = p[i];
        for (unsigned i = 0; i < n - first; i++) pBuf[i] = p[first + i];
    }
    pUp->WrOff = (wr + n) % size;
    return n;
}

static void _put_u32(unsigned v) {
    char buf[11];
    int i = 10;
    buf[i--] = 0;
    do { buf[i--] = (char)('0' + (v % 10)); v /= 10; } while (v);
    rtt_write(0, &buf[i + 1], (unsigned)(10 - i - 1));
}

static void _delay(unsigned n) {
    volatile unsigned i;
    for (i = 0; i < n; i++) __asm volatile ("");
}

int main(void) {
    unsigned counter = 0;
    for (;;) {
        rtt_write(0, "STM32H7 RTT demo: tick=", 23);
        _put_u32(counter++);
        rtt_write(0, "\r\n", 2);
        _delay(500000);
    }
    /* not reached */
}
