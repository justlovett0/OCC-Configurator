import serial
import serial.tools.list_ports
import time

from .constants import BAUD_RATE, TIMEOUT, get_occ_port_metadata, get_esp_download_metadata


class PicoSerial:
    def __init__(self):
        self.ser = None
        self.platform = None
        self.usb_vid = None
        self.usb_pid = None

    @staticmethod
    def _port_metadata(port_info):
        return get_occ_port_metadata(port_info.vid, port_info.pid)

    @staticmethod
    def _esp_download_metadata(port_info):
        return get_esp_download_metadata(port_info.vid, port_info.pid)

    @classmethod
    def find_port_record(cls, device=None):
        """Return metadata for the first OCC config port, or the named device."""
        for p in serial.tools.list_ports.comports():
            meta = cls._port_metadata(p)
            if not meta:
                continue
            if device is None or p.device == device:
                return {
                    "device": p.device,
                    "label": meta["label"],
                    "platform": meta.get("platform", "rp2040"),
                    "vid": p.vid,
                    "pid": p.pid,
                }
        return None

    @classmethod
    def find_esp_download_port_record(cls, device=None):
        """Return metadata for the first supported ESP download-mode port."""
        for p in serial.tools.list_ports.comports():
            meta = cls._esp_download_metadata(p)
            if not meta:
                continue
            if device is None or p.device == device:
                return {
                    "device": p.device,
                    "label": meta["label"],
                    "platform": meta.get("platform", "esp32s3"),
                    "vid": p.vid,
                    "pid": p.pid,
                    "description": p.description,
                }
        return None

    @staticmethod
    def find_esp_download_port():
        record = PicoSerial.find_esp_download_port_record()
        return record["device"] if record else None

    @staticmethod
    def find_config_port():
        """Return the first COM port that belongs to any known OCC firmware variant."""
        record = PicoSerial.find_port_record()
        return record["device"] if record else None

    @staticmethod
    def list_ports():
        result = []
        for p in serial.tools.list_ports.comports():
            meta = PicoSerial._port_metadata(p)
            is_occ = meta is not None
            device_label = meta["label"] if is_occ else p.description
            label = f"{p.device} - {device_label}" if is_occ else f"{p.device} - {p.description}"
            result.append((p.device, label, is_occ))
        return result

    def connect(self, port):
        self.disconnect()
        record = self.find_port_record(port)
        if record:
            self.platform = record["platform"]
            self.usb_vid = record["vid"]
            self.usb_pid = record["pid"]
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
        """Discard any bytes sitting in the OS receive buffer."""
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
        self.platform = None
        self.usb_vid = None
        self.usb_pid = None

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
        try:
            r = self.send("GET_FW_DATE")
            if r.startswith("FW_DATE:"):
                return r[8:].strip()
        except Exception:
            pass
        return None

    def get_config(self):
        """Read config and return a dict with all key/value pairs plus device_type."""
        self.ser.write(b"GET_CONFIG\n")
        self.ser.flush()

        def _read_config_line():
            for _ in range(8):
                line = self.ser.readline().decode("ascii", errors="replace").strip()
                if not line:
                    continue
                if line.startswith("DEVTYPE:") or line.startswith("CFG:"):
                    return line
            return ""

        r = _read_config_line()
        if not r:
            raise ValueError("Timed out waiting for GET_CONFIG response")

        device_type = "unknown"
        cfg_line = None

        if r.startswith("DEVTYPE:"):
            device_type = r[8:].strip()
            cfg_line = _read_config_line()
        elif r.startswith("CFG:"):
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
            if not line:
                break
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

    def rotate_ble_identity(self):
        if self.send("ROTATE_BLE_IDENTITY") != "OK":
            raise ValueError("ROTATE_BLE_IDENTITY failed")

    def start_scan(self):
        old_timeout = self.ser.timeout
        try:
            self.ser.write(b"STOP\n")
            self.ser.flush()
            self.ser.timeout = 0.03
            deadline = time.time() + 0.12
            while time.time() < deadline:
                line = self.ser.readline().decode("ascii", errors="replace").strip()
                if not line:
                    break
                if line == "OK":
                    break
        except Exception:
            pass
        finally:
            try:
                self.ser.timeout = old_timeout
            except Exception:
                pass
        self.flush_input()
        self.ser.write(b"SCAN\n")
        self.ser.flush()
        pre_lines = []
        deadline = time.time() + 5.0
        old_timeout = self.ser.timeout
        self.ser.timeout = 0.05
        try:
            while time.time() < deadline:
                line = self.ser.readline().decode("ascii", errors="replace").strip()
                if line == "OK":
                    return pre_lines
                if line:
                    pre_lines.append(line)
        finally:
            self.ser.timeout = old_timeout
        raise ValueError("SCAN: no OK response")

    def stop_scan(self):
        self.ser.write(b"STOP\n")
        self.ser.flush()
        deadline = time.time() + 2.0
        while time.time() < deadline:
            line = self.ser.readline().decode("ascii", errors="replace").strip()
            if line == "OK":
                return

    def request_stop_scan(self):
        try:
            if self.connected:
                self.ser.write(b"STOP\n")
                self.ser.flush()
        except Exception:
            pass

    def read_scan_line(self, timeout=0.15):
        old_timeout = self.ser.timeout
        self.ser.timeout = timeout
        try:
            line = self.ser.readline().decode("ascii", errors="replace").strip()
            return line if line else None
        finally:
            self.ser.timeout = old_timeout

    def start_monitor_adc(self, pin):
        r = self.send(f"MONITOR_ADC:{pin}")
        if r != "OK":
            raise ValueError(f"MONITOR_ADC: {r}")

    def start_monitor_i2c(self, axis=None):
        cmd = f"MONITOR_I2C:{axis}" if axis is not None else "MONITOR_I2C"
        r = self.send(cmd)
        if r != "OK":
            raise ValueError(f"{cmd}: {r}")

    def start_monitor_digital(self, pin):
        r = self.send(f"MONITOR_DIG:{pin}")
        if r != "OK":
            raise ValueError(f"MONITOR_DIG: {r}")

    def stop_monitor(self):
        self.stop_scan()

    def request_stop_monitor(self):
        self.request_stop_scan()

    def drain_monitor_latest(self, timeout=0.05):
        latest_val = None
        passthrough = []

        try:
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
