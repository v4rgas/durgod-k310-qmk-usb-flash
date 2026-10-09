MEMORY { FLASH (rx) : ORIGIN = 0x08003000, LENGTH = 0x1000 }
ENTRY(reset_entry)
SECTIONS {
    .text : {
        KEEP(*(.vectors))
        KEEP(*(.header))
        KEEP(*(.entry))
        *(.text*)
        *(.rodata*)
        . = ALIGN(4);
    } > FLASH
    /DISCARD/ : { *(.ARM.exidx*) *(.ARM.attributes) *(.comment) }
    .bad (NOLOAD) : { *(.data*) *(.bss*) *(COMMON) }
    ASSERT(SIZEOF(.bad) == 0, "stepstone must not use RAM data")
}
