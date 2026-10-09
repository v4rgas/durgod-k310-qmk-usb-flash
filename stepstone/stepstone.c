/*
 * Stepping-stone image for a Durgod Taurus K310 (STM32F070RB, hardware type 4).
 *
 * Flashed through Durgod's own USB bootloader in place of the stock firmware
 * (so it lives at 0x08003000). It uses no interrupts: it re-arms Durgod's
 * "stay in bootloader" flag as a way back, returns the chip to a reset-like
 * state and jumps to the ST ROM bootloader, which enumerates as 0483:df11.
 */
#include <stdint.h>

#define REG(addr) (*(volatile uint32_t *)(addr))
#define REG16(addr) (*(volatile uint16_t *)(addr))

#define RCC_CR        REG(0x40021000)
#define RCC_CFGR      REG(0x40021004)
#define RCC_CIR       REG(0x40021008)
#define RCC_APB2RSTR  REG(0x4002100C)
#define RCC_APB1RSTR  REG(0x40021010)
#define RCC_AHBENR    REG(0x40021014)
#define RCC_APB2ENR   REG(0x40021018)
#define RCC_APB1ENR   REG(0x4002101C)
#define RCC_AHBRSTR   REG(0x40021028)
#define RCC_CFGR2     REG(0x4002102C)
#define RCC_CFGR3     REG(0x40021030)

#define FLASH_KEYR    REG(0x40022004)
#define FLASH_SR      REG(0x4002200C)
#define FLASH_CR      REG(0x40022010)
#define FLASH_AR      REG(0x40022014)

#define SYSCFG_CFGR1  REG(0x40010000)
#define IWDG_KR       REG(0x40003000)

#define SYST_CSR      REG(0xE000E010)
#define SYST_RVR      REG(0xE000E014)
#define SYST_CVR      REG(0xE000E018)
#define NVIC_ICER     REG(0xE000E180)
#define NVIC_ICPR     REG(0xE000E280)
#define SCB_ICSR      REG(0xE000ED04)
#define SCB_AIRCR     REG(0xE000ED0C)

#define STACK_TOP       0x20001000u
#define ROM_BOOTLOADER  0x1FFFC800u /* STM32F070xB / F072 system memory */

/* Same flag the stock firmware sets before resetting into Durgod's bootloader. */
#define BOOT_FLAG_ADDR   0x0801C800u
#define BOOT_FLAG_VALUE  0x12345678u

#define WAIT_LIMIT 4000000u /* every wait is bounded so nothing can hang */

void reset_entry(void);
void fault_handler(void);
void ignore_handler(void);

__attribute__((section(".vectors"), used))
const uint32_t vectors[48] = {
    STACK_TOP,
    (uint32_t)reset_entry,
    (uint32_t)fault_handler,  /* NMI */
    (uint32_t)fault_handler,  /* HardFault */
    0, 0, 0,
    0,                        /* 0x1C: vector checksum, patched by mkimage.py */
    0, 0, 0,
    (uint32_t)ignore_handler, /* SVCall */
    0, 0,
    (uint32_t)ignore_handler, /* PendSV */
    (uint32_t)ignore_handler, /* SysTick */
    [16 ... 47] = (uint32_t)ignore_handler,
};

/* Image header the stock firmware carries at 0xC0: VID, PID, hw type, version 1.06. */
__attribute__((section(".header"), used))
const uint8_t image_header[8] = {0x68, 0x2f, 0x42, 0x00, 0x04, 0x00, 0x06, 0x01};

static void system_reset(void) {
    SCB_AIRCR = 0x05FA0004;
    for (;;) {
    }
}

void fault_handler(void) {
    system_reset();
}

void ignore_handler(void) {
}

static void flash_wait(void) {
    for (uint32_t i = WAIT_LIMIT; i && (FLASH_SR & 1); i--) {
    }
    FLASH_SR = 0x34; /* clear EOP, WRPRTERR, PGERR */
}

static void arm_boot_flag(void) {
    if (REG(BOOT_FLAG_ADDR) == BOOT_FLAG_VALUE) return;

    flash_wait();
    if (FLASH_CR & 0x80) {
        FLASH_KEYR = 0x45670123;
        FLASH_KEYR = 0xCDEF89AB;
    }
    if (REG(BOOT_FLAG_ADDR) != 0xFFFFFFFF) {
        FLASH_CR |= 0x02; /* PER */
        FLASH_AR = BOOT_FLAG_ADDR;
        FLASH_CR |= 0x40; /* STRT */
        flash_wait();
        FLASH_CR &= ~0x02u;
    }
    FLASH_CR |= 0x01; /* PG */
    REG16(BOOT_FLAG_ADDR) = BOOT_FLAG_VALUE & 0xFFFF;
    flash_wait();
    REG16(BOOT_FLAG_ADDR + 2) = BOOT_FLAG_VALUE >> 16;
    flash_wait();
    FLASH_CR &= ~0x01u;
    FLASH_CR |= 0x80; /* LOCK */
}

__attribute__((noreturn)) void stepstone_main(void) {
    __asm__ volatile("cpsid i");

    SYST_CSR  = 0;
    SYST_RVR  = 0;
    SYST_CVR  = 0;
    NVIC_ICER = 0xFFFFFFFF;
    NVIC_ICPR = 0xFFFFFFFF;
    SCB_ICSR  = (1u << 27) | (1u << 25); /* clear pending PendSV, SysTick */

    /* Run from the internal 8 MHz oscillator, as after reset. */
    RCC_CR |= 1;
    for (uint32_t i = WAIT_LIMIT; i && !(RCC_CR & 2); i--) {
    }
    RCC_CFGR &= ~3u;
    for (uint32_t i = WAIT_LIMIT; i && (RCC_CFGR & 0xC); i--) {
    }

    arm_boot_flag();

    RCC_CR &= ~0x010D0000u; /* PLL, CSS, HSE bypass, HSE off */
    RCC_CFGR  = 0;
    RCC_CFGR2 = 0;
    RCC_CFGR3 = 0;
    RCC_CIR   = 0;

    /* Reset every peripheral; this also drops the USB pull-up. */
    RCC_APB1RSTR = 0xFFFFFFFF;
    RCC_APB1RSTR = 0;
    RCC_APB2RSTR = 0xFFFFFFFF;
    RCC_APB2RSTR = 0;
    RCC_AHBRSTR  = 0xFFFFFFFF;
    RCC_AHBRSTR  = 0;
    RCC_AHBENR   = 0x14;
    RCC_APB1ENR  = 0;

    /* Let the host notice the disconnect before the ROM re-enumerates. */
    for (volatile uint32_t i = 600000; i; i--) {
        IWDG_KR = 0xAAAA; /* harmless unless a watchdog was left running */
    }

    const uint32_t rom_sp    = REG(ROM_BOOTLOADER);
    const uint32_t rom_entry = REG(ROM_BOOTLOADER + 4);
    if ((rom_sp >> 20) != 0x200 || (rom_entry >> 16) != 0x1FFF) {
        system_reset(); /* no ROM bootloader here; the armed flag takes us back */
    }

    /* Map system memory at 0, as a BOOT0 start does. */
    RCC_APB2ENR  = 1;
    SYSCFG_CFGR1 = 1;

    __asm__ volatile(
        "movs r2, #0\n"
        "msr control, r2\n"
        "msr msp, %0\n"
        "cpsie i\n"
        "bx %1\n"
        : : "r"(rom_sp), "r"(rom_entry) : "r2");
    __builtin_unreachable();
}

/* Placed right after the header, where the stock image has its entry stub. */
__attribute__((naked, section(".entry"))) void reset_entry(void) {
    __asm__ volatile(
        "ldr r0, =0x20001000\n"
        "mov sp, r0\n"
        "bl stepstone_main\n");
}
