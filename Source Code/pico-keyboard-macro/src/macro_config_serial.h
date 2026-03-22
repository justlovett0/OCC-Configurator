/*
 * macro_config_serial.h - Non-blocking CDC serial command handler
 */

#ifndef _MACRO_CONFIG_SERIAL_H_
#define _MACRO_CONFIG_SERIAL_H_

#include "macro_config.h"

// Call from main loop every iteration — non-blocking, accumulates bytes
// and dispatches commands when a full line is received.
void config_serial_task(macro_config_t *config);

#endif /* _MACRO_CONFIG_SERIAL_H_ */
