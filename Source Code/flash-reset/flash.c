#include "hardware/flash.h"
#include "pico/bootrom.h"

#if PICO_RP2040
#include "hardware/structs/io_qspi.h"
#include "hardware/structs/ssi.h"
#else
#include "hardware/structs/qmi.h"
#endif

// NOTE: The contents of this file are copied from: https://github.com/raspberrypi/pico-sdk/blob/2.0.0/src/rp2_common/hardware_flash/flash.c
// This is because they are excluded by default by PICO_NO_FLASH, but we need them!

// Bitbanging the chip select using IO overrides, in case RAM-resident IRQs
// are still running, and the FIFO bottoms out. (the bootrom does the same)
static void __no_inline_not_in_flash_func(flash_cs_force)(bool high) {
#if PICO_RP2040
    uint32_t field_val = high ?
        IO_QSPI_GPIO_QSPI_SS_CTRL_OUTOVER_VALUE_HIGH :
        IO_QSPI_GPIO_QSPI_SS_CTRL_OUTOVER_VALUE_LOW;
    hw_write_masked(&io_qspi_hw->io[1].ctrl,
        field_val << IO_QSPI_GPIO_QSPI_SS_CTRL_OUTOVER_LSB,
        IO_QSPI_GPIO_QSPI_SS_CTRL_OUTOVER_BITS
    );
#else
    if (high) {
        hw_clear_bits(&qmi_hw->direct_csr, QMI_DIRECT_CSR_ASSERT_CS0N_BITS);
    } else {
        hw_set_bits(&qmi_hw->direct_csr, QMI_DIRECT_CSR_ASSERT_CS0N_BITS);
    }
#endif
}

static void __no_inline_not_in_flash_func(flash_enable_xip_via_boot2)(void) {
    // Set up XIP for 03h read on bus access (slow but generic)
    rom_flash_enter_cmd_xip_fn flash_enter_cmd_xip_func = (rom_flash_enter_cmd_xip_fn)rom_func_lookup_inline(ROM_FUNC_FLASH_ENTER_CMD_XIP);
    assert(flash_enter_cmd_xip_func);
    flash_enter_cmd_xip_func();
}

void __no_inline_not_in_flash_func(flash_do_cmd)(const uint8_t *txbuf, uint8_t *rxbuf, size_t count) {
    rom_connect_internal_flash_fn connect_internal_flash_func = (rom_connect_internal_flash_fn)rom_func_lookup_inline(ROM_FUNC_CONNECT_INTERNAL_FLASH);
    rom_flash_exit_xip_fn flash_exit_xip_func = (rom_flash_exit_xip_fn)rom_func_lookup_inline(ROM_FUNC_FLASH_EXIT_XIP);
    rom_flash_flush_cache_fn flash_flush_cache_func = (rom_flash_flush_cache_fn)rom_func_lookup_inline(ROM_FUNC_FLASH_FLUSH_CACHE);
    assert(connect_internal_flash_func && flash_exit_xip_func && flash_flush_cache_func);
    //flash_init_boot2_copyout(); // Declared as an empty function if PICO_NO_FLASH
    __compiler_memory_barrier();
    connect_internal_flash_func();
    flash_exit_xip_func();

    flash_cs_force(0);
    size_t tx_remaining = count;
    size_t rx_remaining = count;
#if PICO_RP2040
    // Synopsys SSI version
    // We may be interrupted -- don't want FIFO to overflow if we're distracted.
    const size_t max_in_flight = 16 - 2;
    while (tx_remaining || rx_remaining) {
        uint32_t flags = ssi_hw->sr;
        bool can_put = flags & SSI_SR_TFNF_BITS;
        bool can_get = flags & SSI_SR_RFNE_BITS;
        if (can_put && tx_remaining && rx_remaining - tx_remaining < max_in_flight) {
            ssi_hw->dr0 = *txbuf++;
            --tx_remaining;
        }
        if (can_get && rx_remaining) {
            *rxbuf++ = (uint8_t)ssi_hw->dr0;
            --rx_remaining;
        }
    }
#else
    // QMI version -- no need to bound FIFO contents as QMI stalls on full DIRECT_RX.
    hw_set_bits(&qmi_hw->direct_csr, QMI_DIRECT_CSR_EN_BITS);
    while (tx_remaining || rx_remaining) {
        uint32_t flags = qmi_hw->direct_csr;
        bool can_put = !(flags & QMI_DIRECT_CSR_TXFULL_BITS);
        bool can_get = !(flags & QMI_DIRECT_CSR_RXEMPTY_BITS);
        if (can_put && tx_remaining) {
            qmi_hw->direct_tx = *txbuf++;
            --tx_remaining;
        }
        if (can_get && rx_remaining) {
            *rxbuf++ = (uint8_t)qmi_hw->direct_rx;
            --rx_remaining;
        }
    }
    hw_clear_bits(&qmi_hw->direct_csr, QMI_DIRECT_CSR_EN_BITS);
#endif
    flash_cs_force(1);

    flash_flush_cache_func();
    flash_enable_xip_via_boot2();
}