/*
 * config_serial.h - CDC serial protocol for configurator GUI
 */

#ifndef _CONFIG_SERIAL_H_
#define _CONFIG_SERIAL_H_

#include "guitar_config.h"

// Run the config-mode main loop. Reboots via watchdog on REBOOT command
// or if the serial connection is idle for too long.
void config_mode_main(guitar_config_t *config);

#endif /* _CONFIG_SERIAL_H_ */
