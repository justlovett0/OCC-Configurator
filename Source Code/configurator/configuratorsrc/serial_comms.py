import serial
import serial.tools.list_ports
import time
from .constants import CONFIG_MODE_VID, CONFIG_MODE_PIDS, BAUD_RATE, TIMEOUT
#  SERIAL COMMUNICATION


class PicoSerial:
    def __init__(self):
        self.ser = None

    @staticmethod
    def find_config_port():
        """Return the first COM port that belongs to any known OCC firmware variant."""
        for p in serial.tools.list_ports.comports():
            if p.vid == CONFIG_MODE_VID and p.pid in CONFIG_MODE_PIDS:
                return p.device
        return None

    @staticmethod
    def list_ports():
        result = []
        for p in serial.tools.list_ports.comports():
            is_pico = (p.vid == CONFIG_MODE_VID and p.pid in CONFIG_MODE_PIDS)
            device_label = CONFIG_MODE_PIDS.get(p.pid, "OCC Device") if is_pico else p.description
            label = f"{p.device} — {device_label}" if is_pico else f"{p.device} — {p.description}"
            result.append((p.device, label, is_pico))
        return result

    def connect(self, port):
        self.disconnect()
        last_exc = None
        for attempt in range(5):
            try:
                self.ser = serial.Serial(port, BAUD_RATE, timeout=TIMEOUT)
                time.sleep(0.2)
                self.ser.reset_input_buffer()
                return
            except (serial.SerialException, OSError) as exc:
                last_exc = exc
                if attempt < 4:
                    time.sleep(0.4)
        raise last_exc

    def flush_input(self):
        """Discard any bytes sitting in the OS receive buffer.

        Call this after stopping a SCAN/MONITOR session and before sending new
        commands.  The firmware streams PIN:/MVAL: lines continuously while in
        scan mode; those lines accumulate in the OS buffer and will be returned
        by the next readline() call — corrupting the response to whatever
        command follows.  reset_input_buffer() atomically discards them all.
        """
        try:
            if self.connected:
                self.ser.reset_input_buffer()
        except Exception:
            pass

    def disconnect(self):
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None

    @property
    def connected(self):
        return self.ser is not None and self.ser.is_open

    def send(self, cmd):
        if not self.connected:
            raise ConnectionError("Not connected")
        self.ser.write((cmd + "\n").encode("ascii"))
        self.ser.flush()
        return self.ser.readline().decode("ascii", errors="replace").strip()

    def ping(self):
        try:
            return self.send("PING") == "PONG"
        except Exception:
            return False

    def get_fw_date(self):
        """Query the firmware build date via GET_FW_DATE.

        Returns the raw date string (e.g. 'Jun 15 2025') or None if
        the firmware doesn't support this command (older builds).
        """
        try:
            r = self.send("GET_FW_DATE")
            if r.startswith("FW_DATE:"):
                return r[8:].strip()
        except Exception:
            pass
        return None

    def get_config(self):
        """Read config.
        Firmware sends:
          DEVTYPE:<type>
          CFG:...
          LED:...
          LED_COLORS:...
          LED_MAP:...
        Returns a dict with all key/value pairs plus 'device_type'.
        """
        # First line is now DEVTYPE (added in firmware v12+).
        # For backward compatibility with older firmware that sends CFG: directly,
        # we peek at the first line and handle both cases.
        r = self.send("GET_CONFIG")

        device_type = "unknown"
        cfg_line = None

        if r.startswith("DEVTYPE:"):
            device_type = r[8:].strip()
            # Next line should be CFG:
            cfg_line = self.ser.readline().decode("ascii", errors="replace").strip()
        elif r.startswith("CFG:"):
            # Old firmware without DEVTYPE — treat as unknown
            cfg_line = r
        else:
            raise ValueError(f"Bad response: {r}")

        if not cfg_line.startswith("CFG:"):
            raise ValueError(f"Expected CFG: line, got: {cfg_line}")

        cfg = {"device_type": device_type}
        for kv in cfg_line[4:].split(","):
            kv = kv.strip()
            if "=" in kv:
                k, v = kv.split("=", 1)
                cfg[k.strip()] = v.strip()
        for _ in range(3):
            line = self.ser.readline().decode("ascii", errors="replace").strip()
            if line.startswith("LED:"):
                for kv in line[4:].split(","):
                    kv = kv.strip()
                    if "=" in kv:
                        k, v = kv.split("=", 1)
                        cfg["led_" + k.strip()] = v.strip()
            elif line.startswith("LED_COLORS:"):
                cfg["led_colors_raw"] = line[11:]
            elif line.startswith("LED_MAP:"):
                cfg["led_map_raw"] = line[8:]
        return cfg

    def set_value(self, key, val):
        r = self.send(f"SET:{key}={val}")
        if r != "OK":
            raise ValueError(f"SET {key}: {r}")

    def save(self):
        if self.send("SAVE") != "OK":
            raise ValueError("SAVE failed")

    def defaults(self):
        if self.send("DEFAULTS") != "OK":
            raise ValueError("DEFAULTS failed")

    def start_scan(self):
        """Start SCAN. Returns list of pre-scan lines (like I2C:ADXL345) before OK."""
        self.ser.write(b"SCAN\n")
        self.ser.flush()
        pre_lines = []
        deadline = time.time() + 5.0
        while time.time() < deadline:
            line = self.ser.readline().decode("ascii", errors="replace").strip()
            if line == "OK":
                return pre_lines
            elif line:
                pre_lines.append(line)
        raise ValueError("SCAN: no OK response")

    def stop_scan(self):
        self.ser.write(b"STOP\n")
        self.ser.flush()
        deadline = time.time() + 2.0
        while time.time() < deadline:
            line = self.ser.readline().decode("ascii", errors="replace").strip()
            if line == "OK":
                return

    def read_scan_line(self, timeout=0.15):
        old_timeout = self.ser.timeout
        self.ser.timeout = timeout
        try:
            line = self.ser.readline().decode("ascii", errors="replace").strip()
            return line if line else None
        finally:
            self.ser.timeout = old_timeout

    def start_monitor_adc(self, pin):
        """Start ADC monitoring. Returns 'OK' or raises."""
        r = self.send(f"MONITOR_ADC:{pin}")
        if r != "OK":
            raise ValueError(f"MONITOR_ADC: {r}")

    def start_monitor_i2c(self, axis=None):
        """Start I2C accelerometer monitoring.

        axis=0/1/2 — single-axis mode (MONITOR_I2C:<axis>): firmware sends only
        MVAL:<value> at 50 Hz. Used by the live bar graph in the configurator.

        axis=None — all-axes debug mode (MONITOR_I2C): firmware sends MVAL_X/Y/Z
        at 20 Hz. Used by the debug console MONITOR I2C button.
        """
        cmd = f"MONITOR_I2C:{axis}" if axis is not None else "MONITOR_I2C"
        r = self.send(cmd)
        if r != "OK":
            raise ValueError(f"{cmd}: {r}")

    def start_monitor_digital(self, pin):
        """Start digital pin monitoring."""
        r = self.send(f"MONITOR_DIG:{pin}")
        if r != "OK":
            raise ValueError(f"MONITOR_DIG: {r}")

    def stop_monitor(self):
        """Stop monitoring (same as stop_scan)."""
        self.stop_scan()

    def drain_monitor_latest(self, timeout=0.05):
        """Drain ALL buffered MVAL lines and return only the most recent value.

        This prevents the serial buffer from building up a backlog of stale
        readings. If the consumer (UI) is slower than the producer (firmware),
        older queued values are discarded so the bar graph always shows the
        current sensor state.

        Returns (latest_int_value_or_None, list_of_non_mval_lines).
        The non-MVAL lines (ERR:, etc.) are returned for the debug console.
        """
        latest_val = None
        passthrough = []

        try:
            # Block briefly waiting for at least one line to arrive
            old_timeout = self.ser.timeout
            self.ser.timeout = timeout
            try:
                raw = self.ser.readline()
                line = raw.decode("ascii", errors="replace").strip() if raw else ""
                if line.startswith("MVAL:"):
                    try:
                        latest_val = int(line[5:])
                    except ValueError:
                        pass
                elif line:
                    passthrough.append(line)
            finally:
                self.ser.timeout = old_timeout

            # Now drain everything else already sitting in the OS buffer —
            # no blocking, just consume what's there right now.
            self.ser.timeout = 0
            try:
                while self.ser.in_waiting:
                    raw = self.ser.readline()
                    line = raw.decode("ascii", errors="replace").strip() if raw else ""
                    if not line:
                        break
                    if line.startswith("MVAL:"):
                        try:
                            latest_val = int(line[5:])
                        except ValueError:
                            pass
                    else:
                        passthrough.append(line)
            finally:
                self.ser.timeout = old_timeout

        except Exception:
            pass

        return latest_val, passthrough

    def reboot(self):
        try:
            self.send("REBOOT")
        except Exception:
            pass
        self.disconnect()

    def bootsel(self):
        try:
            self.send("BOOTSEL")
        except Exception:
            pass
        self.disconnect()

    def led_flash(self, idx):
        r = self.send(f"LED_FLASH:{idx}")
        if r != "OK":
            raise ValueError(f"LED_FLASH: {r}")

    def led_solid(self, idx):
        r = self.send(f"LED_SOLID:{idx}")
        if r != "OK":
            raise ValueError(f"LED_SOLID: {r}")

    def led_off(self):
        r = self.send("LED_OFF")
        if r != "OK":
            raise ValueError(f"LED_OFF: {r}")

