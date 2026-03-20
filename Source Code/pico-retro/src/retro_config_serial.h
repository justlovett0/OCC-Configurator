/*
 * retro_config_serial.h - CDC serial protocol for retro controller configurator
 *
 * Declares the config-mode main loop. Called after watchdog-scratch trigger
 * at boot selects config mode instead of normal XInput play mode.
 */

#ifndef _RETRO_CONFIG_SERIAL_H_
#define _RETRO_CONFIG_SERIAL_H_

#include "retro_config.h"

// Run the config-mode serial command loop.
// Handles PING, GET_CONFIG, SET:key=value, SAVE, DEFAULTS, REBOOT, BOOTSEL.
// Reboots via watchdog on REBOOT command or if the serial connection is idle
// for too long.
void config_serial_loop(retro_config_t *config);

#endif /* _RETRO_CONFIG_SERIAL_H_ */
