/*
 * pedal_config_serial.h - CDC serial protocol for configurator GUI
 */

#ifndef _PEDAL_CONFIG_SERIAL_H_
#define _PEDAL_CONFIG_SERIAL_H_

#include "pedal_config.h"

// Run the config-mode main loop. Reboots via watchdog on REBOOT command
// or if the serial connection is idle for too long.
void config_mode_main(pedal_config_t *config);

#endif /* _PEDAL_CONFIG_SERIAL_H_ */
