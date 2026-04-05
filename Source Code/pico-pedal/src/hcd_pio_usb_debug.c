/*
 * Local copy of TinyUSB's RP2040 PIO-USB HCD with a couple of debug counters
 * so we can tell whether EP0 completion reaches TinyUSB and whether TinyUSB
 * queues the EP0 IN data stage.
 */

#include "tusb_option.h"

#if CFG_TUH_ENABLED && (CFG_TUSB_MCU == OPT_MCU_RP2040) && CFG_TUH_RPI_PIO_USB

#include "pico.h"
#include "pio_usb.h"
#include "pio_usb_ll.h"
#include "osal/osal.h"
#include "host/hcd.h"
#include "host/usbh.h"

// Debug counters exported from xinput_host.c
extern volatile uint16_t _xinput_hcd_ep0_complete_count;
extern volatile uint16_t _xinput_hcd_ep0_in_submit_count;
extern volatile uint16_t _xinput_hcd_ep0_in_submit_fail_count;
extern volatile uint16_t _xinput_hcd_ep0_out_submit_count;
extern volatile uint16_t _xinput_hcd_ep0_out_submit_fail_count;
extern volatile uint8_t _xinput_last_setup_addr;
extern volatile uint8_t _xinput_last_setup_bmRequestType;
extern volatile uint8_t _xinput_last_setup_bRequest;
extern volatile uint16_t _xinput_last_setup_wValue;

#define RHPORT_OFFSET     1
#define RHPORT_PIO(_x)    ((_x)-RHPORT_OFFSET)

static pio_usb_configuration_t pio_host_cfg = PIO_USB_DEFAULT_CONFIG;

bool hcd_configure(uint8_t rhport, uint32_t cfg_id, const void *cfg_param) {
  (void) rhport;
  TU_VERIFY(cfg_id == TUH_CFGID_RPI_PIO_USB_CONFIGURATION);
  memcpy(&pio_host_cfg, cfg_param, sizeof(pio_usb_configuration_t));
  return true;
}

bool hcd_init(uint8_t rhport, const tusb_rhport_init_t* rh_init) {
  (void) rhport;
  (void) rh_init;
  pio_usb_host_init(&pio_host_cfg);
  return true;
}

void hcd_port_reset(uint8_t rhport) {
  pio_usb_host_port_reset_start(RHPORT_PIO(rhport));
}

void hcd_port_reset_end(uint8_t rhport) {
  pio_usb_host_port_reset_end(RHPORT_PIO(rhport));
}

bool hcd_port_connect_status(uint8_t rhport) {
  uint8_t const pio_rhport = RHPORT_PIO(rhport);
  root_port_t *root = PIO_USB_ROOT_PORT(pio_rhport);
  return pio_usb_bus_get_line_state(root) != PORT_PIN_SE0;
}

tusb_speed_t hcd_port_speed_get(uint8_t rhport) {
  uint8_t const pio_rhport = RHPORT_PIO(rhport);
  return PIO_USB_ROOT_PORT(pio_rhport)->is_fullspeed ? TUSB_SPEED_FULL : TUSB_SPEED_LOW;
}

void hcd_device_close(uint8_t rhport, uint8_t dev_addr) {
  pio_usb_host_close_device(RHPORT_PIO(rhport), dev_addr);
}

uint32_t hcd_frame_number(uint8_t rhport) {
  (void) rhport;
  return pio_usb_host_get_frame_number();
}

void hcd_int_enable(uint8_t rhport) {
  (void) rhport;
}

void hcd_int_disable(uint8_t rhport) {
  (void) rhport;
}

bool hcd_edpt_open(uint8_t rhport, uint8_t dev_addr, tusb_desc_endpoint_t const *desc_ep) {
  hcd_devtree_info_t dev_tree;
  hcd_devtree_get_info(dev_addr, &dev_tree);
  bool const need_pre = (dev_tree.hub_addr && dev_tree.speed == TUSB_SPEED_LOW);
  return pio_usb_host_endpoint_open(RHPORT_PIO(rhport), dev_addr, (uint8_t const *) desc_ep, need_pre);
}

bool hcd_edpt_xfer(uint8_t rhport, uint8_t dev_addr, uint8_t ep_addr, uint8_t *buffer, uint16_t buflen) {
  if (dev_addr == 0 && ep_addr == 0x80) {
    _xinput_hcd_ep0_in_submit_count++;
  }
  if (dev_addr == 0 && ep_addr == 0x00) {
    _xinput_hcd_ep0_out_submit_count++;
  }
  bool ok = pio_usb_host_endpoint_transfer(RHPORT_PIO(rhport), dev_addr, ep_addr, buffer, buflen);
  if (dev_addr == 0 && ep_addr == 0x80 && !ok) {
    _xinput_hcd_ep0_in_submit_fail_count++;
  }
  if (dev_addr == 0 && ep_addr == 0x00 && !ok) {
    _xinput_hcd_ep0_out_submit_fail_count++;
  }
  return ok;
}

bool hcd_edpt_abort_xfer(uint8_t rhport, uint8_t dev_addr, uint8_t ep_addr) {
  return pio_usb_host_endpoint_abort_transfer(RHPORT_PIO(rhport), dev_addr, ep_addr);
}

bool hcd_setup_send(uint8_t rhport, uint8_t dev_addr, uint8_t const setup_packet[8]) {
  _xinput_last_setup_addr = dev_addr;
  _xinput_last_setup_bmRequestType = setup_packet[0];
  _xinput_last_setup_bRequest = setup_packet[1];
  _xinput_last_setup_wValue = (uint16_t) setup_packet[2] | ((uint16_t) setup_packet[3] << 8);
  return pio_usb_host_send_setup(RHPORT_PIO(rhport), dev_addr, setup_packet);
}

bool hcd_edpt_clear_stall(uint8_t rhport, uint8_t dev_addr, uint8_t ep_addr) {
  (void) rhport;
  (void) dev_addr;
  (void) ep_addr;
  return true;
}

static void __no_inline_not_in_flash_func(handle_endpoint_irq)(root_port_t *rport, xfer_result_t result,
                                                               volatile uint32_t *ep_reg) {
  (void) rport;
  const uint32_t ep_all = *ep_reg;

  for (uint8_t ep_idx = 0; ep_idx < PIO_USB_EP_POOL_CNT; ep_idx++) {
    uint32_t const mask = (1u << ep_idx);
    if (ep_all & mask) {
      endpoint_t *ep = PIO_USB_ENDPOINT(ep_idx);
      if (ep->dev_addr == 0 && ((ep->ep_num & 0x7f) == 0)) {
        _xinput_hcd_ep0_complete_count++;
      }
      hcd_event_xfer_complete(ep->dev_addr, ep->ep_num, ep->actual_len, result, true);
    }
  }

  (*ep_reg) &= ~ep_all;
}

void __no_inline_not_in_flash_func(pio_usb_host_irq_handler)(uint8_t root_id) {
  uint8_t const tu_rhport = root_id + 1;
  root_port_t *rport = PIO_USB_ROOT_PORT(root_id);
  uint32_t const ints = rport->ints;

  if (ints & PIO_USB_INTS_ENDPOINT_COMPLETE_BITS) {
    handle_endpoint_irq(rport, XFER_RESULT_SUCCESS, &rport->ep_complete);
  }

  if (ints & PIO_USB_INTS_ENDPOINT_STALLED_BITS) {
    handle_endpoint_irq(rport, XFER_RESULT_STALLED, &rport->ep_stalled);
  }

  if (ints & PIO_USB_INTS_ENDPOINT_ERROR_BITS) {
    handle_endpoint_irq(rport, XFER_RESULT_FAILED, &rport->ep_error);
  }

  if (ints & PIO_USB_INTS_CONNECT_BITS) {
    hcd_event_device_attach(tu_rhport, true);
  }

  if (ints & PIO_USB_INTS_DISCONNECT_BITS) {
    hcd_event_device_remove(tu_rhport, true);
  }

  rport->ints &= ~ints;
}

#endif
