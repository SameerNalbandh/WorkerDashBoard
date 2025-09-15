#!/usr/bin/env python3
"""
WorkerDashboard.py (Miner Safety Monitor)

Touch-screen friendly dashboard (4.3") for:
- Winsen ZE03-CO (UART)
- Quectel EC200U (USB) for SMS, GNSS
Features:
- SOS (predefined SMS)
- Custom message (dropdown IDs -> assignable phone numbers)
- Live GNSS location
- Touch-friendly UI, no emojis, no uploads
- Robust SMS logic (10s wait). UI loading state & success/fail notifications.
- GUI updates via Qt signals to avoid painter conflicts.
"""

import os
os.environ["QT_QPA_PLATFORM"] = "xcb"   # prefer XCB backend (avoid Wayland issues)

import sys
import time
import threading
import queue
import traceback
from datetime import datetime
import glob

import serial
from serial import SerialException

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QMessageBox, QProgressBar, QComboBox, QLineEdit, QDialog, QFormLayout,
    QDialogButtonBox, QSizePolicy
)
from PyQt5.QtGui import QFont

# -----------------------------
# CONFIG
# -----------------------------
ZE03_SERIAL = "/dev/ttyS0"
ZE03_BAUD = 9600

# EC200U-CNAA on AMA5 port
MODEM_PORT = "/dev/ttyAMA5"
MODEM_BAUD = 115200

SOS_SMS_TEXT = "SOS: Dangerous gas levels detected!"
PPM_WARN = 40
PPM_DANGER = 50

APP_TITLE = "Miner Safety Monitor"
WINDOW_WIDTH = 480
WINDOW_HEIGHT = 320

# Predefined message IDs
DEFAULT_MESSAGE_IDS = {
    "sameer": "+919825186687",
    "ramsha": "+918179489703",
    "surya" : "+917974560541",
    "anupam": "+917905030839",
    "shanmukesh":"+919989278339",
    "kartika":"+919871390413"
}

# -----------------------------
# Utilities
# -----------------------------
def current_ts():
    return datetime.utcnow().isoformat() + "Z"

# -----------------------------
# ZE03 Parser
# -----------------------------
class ZE03Parser:
    def __init__(self):
        self.buf = bytearray()

    def feed(self, data_bytes):
        self.buf.extend(data_bytes)

    def extract_frames(self):
        results = []
        buf = self.buf
        i = 0
        while i + 9 <= len(buf):
            if buf[i] != 0xFF:
                i += 1
                continue
            frame = buf[i:i+9]
            checksum = (~sum(frame[1:8]) + 1) & 0xFF
            if frame[1] == 0x86 and checksum == frame[8]:
                ppm = (frame[2] << 8) | frame[3]
                results.append((ppm, bytes(frame)))
                i += 9
            else:
                i += 1
        if i > 0:
            del buf[:i]
        return results

# -----------------------------
# Serial Reader (for ZE03)
# -----------------------------
class SerialReaderThread(threading.Thread):
    def __init__(self, device, baud, out_queue, name="SerialReader", reconnect_delay=3):
        super().__init__(daemon=True, name=name)
        self.device = device
        self.baud = baud
        self.out_queue = out_queue
        self.reconnect_delay = reconnect_delay
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def stopped(self):
        return self._stop_event.is_set()

    def run(self):
        ser = None
        while not self.stopped():
            try:
                if ser is None:
                    ser = serial.Serial(self.device, self.baud, timeout=1)
                    ser.reset_input_buffer()
                b = ser.read(256)
                if b:
                    self.out_queue.put(b)
            except SerialException as e:
                try:
                    self.out_queue.put(b"__SERIAL_ERROR__: " + str(e).encode())
                except Exception:
                    pass
                try:
                    if ser:
                        ser.close()
                except Exception:
                    pass
                ser = None
                time.sleep(self.reconnect_delay)
            except Exception as e:
                try:
                    self.out_queue.put(b"__SERIAL_EXCEPTION__: " + str(e).encode())
                except Exception:
                    pass
                time.sleep(self.reconnect_delay)
        try:
            if ser:
                ser.close()
        except Exception:
            pass

# -----------------------------
# Modem controller (EC200U)
# -----------------------------
class ModemController:
    def __init__(self, dev, baud=MODEM_BAUD, timeout=2):
        self.dev = dev
        self.baud = baud
        self.timeout = timeout
        self.lock = threading.Lock()

    def _open(self):
        return serial.Serial(self.dev, self.baud, timeout=self.timeout)

    def send_at(self, cmd, wait_for=b"OK", timeout=None):
        with self.lock:
            out = bytearray()
            ser = self._open()
            try:
                ser.write((cmd + "\r").encode())
                deadline = time.time() + (timeout or self.timeout)
                while time.time() < deadline:
                    chunk = ser.read(512)
                    if chunk:
                        out.extend(chunk)
                        if wait_for and wait_for in out:
                            break
                    else:
                        time.sleep(0.05)
                return bytes(out)
            finally:
                ser.close()

    def is_alive(self):
        try:
            resp = self.send_at("AT", wait_for=b"OK", timeout=2)
            return b"OK" in resp
        except Exception:
            return False

    def get_signal_quality(self):
        try:
            resp = self.send_at("AT+CSQ", wait_for=b"OK", timeout=2)
            s = resp.decode(errors="ignore")
            for line in s.splitlines():
                if "+CSQ" in line:
                    parts = line.split(":")[1].strip().split(",")
                    return int(parts[0])
        except Exception:
            return None

    def send_sms_textmode(self, number, text, timeout=10):
        with self.lock:
            ser = self._open()
            try:
                ser.write(b"AT+CMGF=1\r")
                time.sleep(0.2)
                _ = ser.read(512)

                cmd = f'AT+CMGS="{number}"\r'.encode()
                ser.write(cmd)

                # wait for '>' prompt
                deadline = time.time() + 5
                buf = bytearray()
                while time.time() < deadline:
                    chunk = ser.read(256)
                    if chunk:
                        buf.extend(chunk)
                        if b">" in buf:
                            break
                    else:
                        time.sleep(0.05)

                ser.write(text.encode() + b"\x1A")

                # wait for result
                resp = bytearray()
                deadline = time.time() + timeout
                while time.time() < deadline:
                    chunk = ser.read(512)
                    if chunk:
                        resp.extend(chunk)
                        if b"+CMGS" in resp or b"OK" in resp or b"ERROR" in resp or b"+CMS ERROR" in resp:
                            break
                    else:
                        time.sleep(0.05)

                s = resp.decode(errors="ignore")
                if "ERROR" in s or "+CMS ERROR" in s:
                    return False, s
                if "+CMGS" in s or "OK" in s:
                    return True, s
                return True, s
            except Exception as e:
                return False, str(e)
            finally:
                try:
                    ser.close()
                except Exception:
                    pass

    def start_gnss(self):
        try_cmds = ["AT+QGNSS=1", "AT+QGPS=1", "AT+CGNSPWR=1"]
        results = {}
        for cmd in try_cmds:
            try:
                raw = self.send_at(cmd, wait_for=b"OK", timeout=1)
                results[cmd] = raw.decode(errors="ignore")
            except Exception as e:
                results[cmd] = f"ERR:{e}"
        return results

    def get_gnss_location(self, timeout=6):
        with self.lock:
            ser = self._open()
            try:
                ser.write(b"AT+QGNSSLOC?\r")
                time.sleep(1)
                out = ser.read_all().decode(errors="ignore")
                for line in out.splitlines():
                    if line.startswith("+QGNSSLOC:"):
                        parts = line.split(":")[1].strip().split(",")
                        try:
                            lat = float(parts[1])
                            lon = float(parts[2])
                            return {"lat": lat, "lon": lon, "raw": out}
                        except Exception:
                            pass

                ser.write(b"AT+QGPSLOC?\r")
                time.sleep(1)
                out = ser.read_all().decode(errors="ignore")
                for line in out.splitlines():
                    if line.startswith("+QGPSLOC:"):
                        parts = line.split(":")[1].strip().split(",")
                        try:
                            lat = float(parts[1])
                            lon = float(parts[2])
                            return {"lat": lat, "lon": lon, "raw": out}
                        except Exception:
                            pass

                ser.write(b"AT+CGNSINF\r")
                time.sleep(1)
                out = ser.read_all().decode(errors="ignore")
                for line in out.splitlines():
                    if line.startswith("+CGNSINF:"):
                        fields = line.split(":")[1].strip().split(",")
                        if fields[1] == "1":
                            lat = float(fields[3])
                            lon = float(fields[4])
                            return {"lat": lat, "lon": lon, "raw": out}
                return None
            except Exception:
                return None
            finally:
                try:
                    ser.close()
                except Exception:
                    pass

    def make_call(self, number, timeout=30):
        """Make a call to the specified number"""
        with self.lock:
            ser = self._open()
            try:
                # Enable call progress notifications
                ser.write(b"AT+QINDCFG=\"call\",1\r")
                time.sleep(0.2)
                ser.read(256)
                
                # Make the call
                cmd = f'ATD{number};\r'.encode()
                ser.write(cmd)
                time.sleep(0.5)
                
                # Wait for call progress
                deadline = time.time() + timeout
                call_connected = False
                while time.time() < deadline:
                    chunk = ser.read(512)
                    if chunk:
                        response = chunk.decode(errors="ignore")
                        if "OK" in response:
                            call_connected = True
                            break
                        elif "ERROR" in response or "NO CARRIER" in response:
                            return False, "Call failed to connect"
                        elif "BUSY" in response:
                            return False, "Number busy"
                        elif "NO ANSWER" in response:
                            return False, "No answer"
                    time.sleep(0.1)
                
                if call_connected:
                    # Wait a bit more to see if call actually connects
                    time.sleep(2)
                    status = self.get_call_status()
                    if "progress" in status.lower():
                        return True, "Call connected"
                    else:
                        return False, "Call disconnected"
                else:
                    return False, "Call timeout"
            except Exception as e:
                return False, f"Call error: {str(e)}"
            finally:
                try:
                    ser.close()
                except Exception:
                    pass

    def hang_up_call(self):
        """Hang up the current call"""
        with self.lock:
            ser = self._open()
            try:
                ser.write(b"ATH\r")
                time.sleep(0.5)
                response = ser.read(512).decode(errors="ignore")
                return "OK" in response or "ERROR" not in response
            except Exception:
                return False
            finally:
                try:
                    ser.close()
                except Exception:
                    pass

    def get_call_status(self):
        """Get current call status"""
        with self.lock:
            ser = self._open()
            try:
                ser.write(b"AT+CPAS\r")
                time.sleep(0.2)
                response = ser.read(512).decode(errors="ignore")
                for line in response.splitlines():
                    if "+CPAS:" in line:
                        status = line.split(":")[1].strip()
                        status_map = {
                            "0": "Ready",
                            "1": "Unknown", 
                            "2": "Ringing",
                            "3": "Call in progress",
                            "4": "Incoming call"
                        }
                        return status_map.get(status, "Unknown")
                return "Unknown"
            except Exception:
                return "Error"
            finally:
                try:
                    ser.close()
                except Exception:
                    pass

# -----------------------------
# Auto-detect modem
# -----------------------------
def auto_detect_modem(baud=MODEM_BAUD, timeout=2):
    # Try AMA5 port first (EC200U-CNAA)
    try:
        ser = serial.Serial(MODEM_PORT, baudrate=baud, timeout=timeout)
        ser.write(b"AT\r")
        time.sleep(0.3)
        resp = ser.read(128)
        ser.close()
        if b"OK" in resp:
            print(f"[INFO] Found EC200U-CNAA modem on {MODEM_PORT}")
            return MODEM_PORT
    except Exception as e:
        print(f"[INFO] AMA5 port not available: {e}")
    
    # Fallback to USB ports
    ports = sorted(glob.glob("/dev/ttyUSB*"))
    for p in ports:
        try:
            ser = serial.Serial(p, baudrate=baud, timeout=timeout)
            ser.write(b"AT\r")
            time.sleep(0.3)
            resp = ser.read(128)
            ser.close()
            if b"OK" in resp:
                print(f"[INFO] Found modem on {p}")
                return p
        except Exception:
            pass
    return None

# -----------------------------
# GUI Signals
# -----------------------------
class AppSignals(QObject):
    ppm_update = pyqtSignal(int)
    modem_status = pyqtSignal(str)
    sms_result = pyqtSignal(bool, str)
    gnss_update = pyqtSignal(object)
    gsm_signal = pyqtSignal(object)
    call_status = pyqtSignal(str)
    call_timer = pyqtSignal(int)

# -----------------------------
# GUI App
# -----------------------------
class MinerMonitorApp(QWidget):
    def __init__(self, ze03_q, modem_ctrl, message_ids=None):
        super().__init__()
        self.ze03_q = ze03_q
        self.modem_ctrl = modem_ctrl
        self.signals = AppSignals()
        self.setWindowTitle(APP_TITLE)
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setStyleSheet("background-color: #111; color: #fff;")
        self._last_ppm = None
        self._last_frame_time = time.time()

        self.message_ids = message_ids or DEFAULT_MESSAGE_IDS.copy()

        self.title_font = QFont("Sans Serif", 12, QFont.Bold)
        self.big_font = QFont("Sans Serif", 24, QFont.Bold)
        self.med_font = QFont("Sans Serif", 10)
        self.small_font = QFont("Sans Serif", 8)

        # Top bar
        top_bar = QHBoxLayout()
        self.title_label = QLabel("MINER SAFETY")
        self.title_label.setFont(self.title_font)
        self.title_label.setAlignment(Qt.AlignCenter)
        close_btn = QPushButton("Close")
        close_btn.setFont(self.med_font)
        close_btn.setFixedHeight(34)
        close_btn.clicked.connect(self.close)
        top_bar.addWidget(self.title_label, 1)
        top_bar.addWidget(close_btn)

        self.ppm_label = QLabel("PPM: ---")
        self.ppm_label.setFont(self.big_font)
        self.ppm_label.setAlignment(Qt.AlignCenter)

        self.last_update_label = QLabel("Last update: --")
        self.last_update_label.setFont(self.small_font)
        self.last_update_label.setAlignment(Qt.AlignCenter)

        self.status_label = QLabel("Modem: -- | Signal: --")
        self.status_label.setFont(self.small_font)
        self.status_label.setAlignment(Qt.AlignCenter)

        self.signal_bar = QProgressBar()
        self.signal_bar.setRange(0, 31)
        self.signal_bar.setFormat("Signal: %v")

        # Buttons
        btn_row1 = QHBoxLayout()
        self.sos_button = QPushButton("SOS")
        self.sos_button.setFont(self.med_font)
        self.sos_button.setMinimumHeight(50)
        self.sos_button.setStyleSheet("background-color: #c0392b; color: white; border-radius: 6px;")
        self.sos_button.clicked.connect(self.on_sos_pressed)

        self.call_button = QPushButton("CALL")
        self.call_button.setFont(self.med_font)
        self.call_button.setMinimumHeight(50)
        self.call_button.setStyleSheet("background-color: #27ae60; color: white; border-radius: 6px;")
        self.call_button.clicked.connect(self.on_call_pressed)

        btn_row1.addWidget(self.sos_button)
        btn_row1.addWidget(self.call_button)

        btn_row2 = QHBoxLayout()
        self.send_button = QPushButton("SEND SMS")
        self.send_button.setFont(self.med_font)
        self.send_button.setMinimumHeight(50)
        self.send_button.setStyleSheet("background-color: #2e86de; color: white; border-radius: 6px;")
        self.send_button.clicked.connect(self.on_send_pressed)

        self.hangup_button = QPushButton("HANG UP")
        self.hangup_button.setFont(self.med_font)
        self.hangup_button.setMinimumHeight(50)
        self.hangup_button.setStyleSheet("background-color: #e74c3c; color: white; border-radius: 6px;")
        self.hangup_button.clicked.connect(self.on_hangup_pressed)
        self.hangup_button.setVisible(False)

        btn_row2.addWidget(self.send_button)
        btn_row2.addWidget(self.hangup_button)

        # Custom message controls
        custom_row = QHBoxLayout()
        self.id_dropdown = QComboBox()
        self.id_dropdown.setFont(self.med_font)
        self.id_dropdown.addItems(sorted(self.message_ids.keys()))
        self.phone_display = QLabel(self.message_ids.get(self.id_dropdown.currentText(), ""))
        self.phone_display.setFont(self.small_font)
        self.manage_ids_btn = QPushButton("Manage IDs")
        self.manage_ids_btn.setFont(self.small_font)
        self.manage_ids_btn.clicked.connect(self.manage_ids_dialog)
        self.id_dropdown.currentIndexChanged.connect(self._update_phone_display)

        custom_row.addWidget(self.id_dropdown)
        custom_row.addWidget(self.phone_display)
        custom_row.addWidget(self.manage_ids_btn)

        self.message_input = QLineEdit()
        self.message_input.setFont(self.small_font)
        self.message_input.setPlaceholderText("Custom message...")

        # Call status and timer
        call_status_row = QHBoxLayout()
        self.call_status_label = QLabel("Call Status: Ready")
        self.call_status_label.setFont(self.small_font)
        self.call_timer_label = QLabel("")
        self.call_timer_label.setFont(self.small_font)
        self.call_timer_label.setAlignment(Qt.AlignRight)
        call_status_row.addWidget(self.call_status_label)
        call_status_row.addWidget(self.call_timer_label)

        # GNSS row
        gnss_row = QHBoxLayout()
        self.loc_label = QLabel("Location: --")
        self.loc_label.setFont(self.small_font)
        self.loc_btn = QPushButton("Get Location")
        self.loc_btn.setFont(self.small_font)
        self.loc_btn.clicked.connect(self.on_get_location)
        gnss_row.addWidget(self.loc_label)
        gnss_row.addWidget(self.loc_btn)

        self.result_label = QLabel("")
        self.result_label.setFont(self.small_font)
        self.result_label.setAlignment(Qt.AlignCenter)

        v = QVBoxLayout()
        v.addLayout(top_bar)
        v.addWidget(self.ppm_label)
        v.addWidget(self.last_update_label)
        v.addWidget(self.status_label)
        v.addWidget(self.signal_bar)
        v.addLayout(btn_row1)
        v.addLayout(btn_row2)
        v.addLayout(call_status_row)
        v.addLayout(custom_row)
        v.addWidget(self.message_input)
        v.addLayout(gnss_row)
        v.addWidget(self.result_label)
        self.setLayout(v)

        # signals
        self.signals.ppm_update.connect(self.update_ppm)
        self.signals.modem_status.connect(self.update_modem_status)
        self.signals.sms_result.connect(self.on_sms_result)
        self.signals.gnss_update.connect(self.on_gnss_update)
        self.signals.gsm_signal.connect(self.on_gsm_signal)
        self.signals.call_status.connect(self.update_call_status)
        self.signals.call_timer.connect(self.update_call_timer)

        self.ze03_parser = ZE03Parser()
        self.reader_thread = threading.Thread(target=self.ze03_worker, daemon=True)
        self.reader_thread.start()

        self.timer = QTimer()
        self.timer.setInterval(5000)
        self.timer.timeout.connect(self.periodic_tasks)
        self.timer.start()

        # Call state variables
        self._busy = False
        self._call_in_progress = False
        self._call_start_time = None
        self._call_timer = QTimer()
        self._call_timer.setInterval(1000)  # Update every second
        self._call_timer.timeout.connect(self.update_call_timer_display)

    # slots
    def _update_phone_display(self):
        key = self.id_dropdown.currentText()
        self.phone_display.setText(self.message_ids.get(key, ""))

    def update_ppm(self, ppm):
        self._last_ppm = ppm
        self.last_update_label.setText(f"Last update: {datetime.now().strftime('%H:%M:%S')}")
        self.ppm_label.setText(f"PPM: {ppm}")
        if ppm < PPM_WARN:
            color = "#00cc66"
        elif ppm < PPM_DANGER:
            color = "#ffcc33"
        else:
            color = "#ff3333"
            threading.Thread(target=self._send_sos_thread, daemon=True).start()
        self.ppm_label.setStyleSheet(f"color: {color};")

    def update_modem_status(self, text):
        self.status_label.setText(text)

    def on_gnss_update(self, data):
        if data is None:
            self.loc_label.setText("Location: No fix")
        else:
            self.loc_label.setText(f"Location: {data.get('lat'):.6f}, {data.get('lon'):.6f}")

    def on_gsm_signal(self, val):
        if val is None:
            self.status_label.setText("Modem: Online | Signal: ?")
        else:
            self.signal_bar.setValue(val)
            self.status_label.setText(f"Modem: Online | Signal: {val}")

    def update_call_status(self, status):
        self.call_status_label.setText(f"Call Status: {status}")
        if status == "Call in progress":
            self._call_in_progress = True
            self._call_start_time = time.time()
            self.hangup_button.setVisible(True)
            self.call_button.setVisible(False)
            self._call_timer.start()
        elif status in ["Ready", "Call failed", "Call ended"]:
            self._call_in_progress = False
            self._call_start_time = None
            self.hangup_button.setVisible(False)
            self.call_button.setVisible(True)
            self._call_timer.stop()
            self.call_timer_label.setText("")

    def update_call_timer(self, seconds):
        self.call_timer_label.setText(f"Call Time: {seconds}s")

    def update_call_timer_display(self):
        if self._call_in_progress and self._call_start_time:
            elapsed = int(time.time() - self._call_start_time)
            self.call_timer_label.setText(f"Call Time: {elapsed}s")

    def ze03_worker(self):
        while True:
            try:
                data = self.ze03_q.get()
                if isinstance(data, bytes):
                    if data.startswith(b"__SERIAL_ERROR__:") or data.startswith(b"__SERIAL_EXCEPTION__:"):
                        self.signals.modem_status.emit("Sensor serial error")
                        continue
                    self.ze03_parser.feed(data)
                    frames = self.ze03_parser.extract_frames()
                    for ppm, raw in frames:
                        self.signals.ppm_update.emit(ppm)
            except Exception as e:
                print("ZE03 worker error:", e)
                traceback.print_exc()
                time.sleep(1)

    def periodic_tasks(self):
        threading.Thread(target=self.check_modem_and_signal, daemon=True).start()

    def check_modem_and_signal(self):
        try:
            alive = self.modem_ctrl.is_alive()
            if not alive:
                self.signals.modem_status.emit("Modem: Offline")
                return
            rssi = self.modem_ctrl.get_signal_quality()
            self.signals.gsm_signal.emit(rssi)
        except Exception as e:
            self.signals.modem_status.emit(f"Modem check error: {e}")

    def set_busy(self, busy, text=""):
        def _set():
            self._busy = busy
            self.sos_button.setDisabled(busy)
            self.send_button.setDisabled(busy)
            self.call_button.setDisabled(busy)
            self.manage_ids_btn.setDisabled(busy)
            self.loc_btn.setDisabled(busy)
            self.result_label.setText(text)
        QTimer.singleShot(0, _set)

    def on_sos_pressed(self):
        def confirmed():
            threading.Thread(target=self._send_sos_thread, daemon=True).start()
        self._confirm_and_run("Send SOS SMS?", confirmed)

    def on_send_pressed(self):
        key = self.id_dropdown.currentText()
        number = self.message_ids.get(key)
        if not number:
            QMessageBox.warning(self, "No number", "Selected ID has no phone number assigned.")
            return
        text = self.message_input.text().strip()
        if not text:
            QMessageBox.warning(self, "Empty message", "Please enter a message to send.")
            return
        def confirmed():
            threading.Thread(target=self._send_custom_thread, args=(number, text), daemon=True).start()
        self._confirm_and_run("Send custom SMS?", confirmed)

    def on_call_pressed(self):
        key = self.id_dropdown.currentText()
        number = self.message_ids.get(key)
        if not number:
            QMessageBox.warning(self, "No number", "Selected ID has no phone number assigned.")
            return
        def confirmed():
            threading.Thread(target=self._make_call_thread, args=(number,), daemon=True).start()
        self._confirm_and_run(f"Call {number}?", confirmed)

    def on_hangup_pressed(self):
        def confirmed():
            threading.Thread(target=self._hangup_call_thread, daemon=True).start()
        self._confirm_and_run("Hang up call?", confirmed)

    def _confirm_and_run(self, prompt, fn_if_yes):
        r = QMessageBox.question(self, "Confirm", prompt, QMessageBox.Yes | QMessageBox.No)
        if r == QMessageBox.Yes:
            fn_if_yes()

    def _send_sos_thread(self):
        self.set_busy(True, "Sending SOS...")
        key = self.id_dropdown.currentText()
        number = self.message_ids.get(key)
        if not number:
            self.set_busy(False, "")
            QMessageBox.warning(self, "No Recipient", "Selected ID has no phone number assigned for SOS.")
            return
        ok, raw = self.modem_ctrl.send_sms_textmode(number, SOS_SMS_TEXT, timeout=10)
        self.signals.sms_result.emit(ok, raw)
        self.set_busy(False, "")

    def _send_custom_thread(self, number, text):
        self.set_busy(True, "Sending message...")
        ok, raw = self.modem_ctrl.send_sms_textmode(number, text, timeout=10)
        self.signals.sms_result.emit(ok, raw)
        self.set_busy(False, "")

    def _make_call_thread(self, number):
        self.set_busy(True, "Initiating call...")
        self.signals.call_status.emit("Ringing")
        
        success, message = self.modem_ctrl.make_call(number, timeout=30)
        
        if success:
            self.signals.call_status.emit("Call in progress")
            self.set_busy(False, "")
        else:
            self.signals.call_status.emit("Call failed")
            self.set_busy(False, "")
            QMessageBox.warning(self, "Call Failed", f"Failed to make call: {message}")

    def _hangup_call_thread(self):
        self.set_busy(True, "Hanging up...")
        success = self.modem_ctrl.hang_up_call()
        if success:
            self.signals.call_status.emit("Call ended")
        else:
            self.signals.call_status.emit("Hangup failed")
        self.set_busy(False, "")

    def on_sms_result(self, ok, raw):
        if ok:
            QMessageBox.information(self, "SMS Sent", f"Message sent successfully.\n\n{(raw or '')[:200]}")
            self.result_label.setText("Last SMS: Sent")
        else:
            QMessageBox.warning(self, "SMS Failed", f"Failed to send message.\n\n{(raw or '')[:200]}")
            self.result_label.setText("Last SMS: Failed")

    def on_get_location(self):
        self.set_busy(True, "Acquiring location...")
        threading.Thread(target=self._gnss_thread, daemon=True).start()

    def _gnss_thread(self):
        self.modem_ctrl.start_gnss()
        time.sleep(1)
        loc = self.modem_ctrl.get_gnss_location(timeout=6)
        self.signals.gnss_update.emit(loc)
        self.set_busy(False, "")

    def manage_ids_dialog(self):
        d = QDialog(self)
        d.setWindowTitle("Manage Message IDs")
        layout = QFormLayout(d)

        editors = {}
        keys = sorted(self.message_ids.keys())
        new_id_input = QLineEdit()
        new_phone_input = QLineEdit()
        new_id_input.setPlaceholderText("New ID")
        new_phone_input.setPlaceholderText("Phone number (+91...)")
        layout.addRow(QLabel("New ID:"), new_id_input)
        layout.addRow(QLabel("Phone:"), new_phone_input)

        for k in keys:
            le = QLineEdit(self.message_ids.get(k, ""))
            layout.addRow(QLabel(k + ":"), le)
            editors[k] = le

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(buttons)
        buttons.accepted.connect(d.accept)
        buttons.rejected.connect(d.reject)

        if d.exec_() == QDialog.Accepted:
            nid = new_id_input.text().strip()
            nphone = new_phone_input.text().strip()
            if nid and nphone:
                self.message_ids[nid] = nphone
            for k, le in editors.items():
                v = le.text().strip()
                if v:
                    self.message_ids[k] = v
                else:
                    self.message_ids.pop(k, None)
            self.id_dropdown.clear()
            self.id_dropdown.addItems(sorted(self.message_ids.keys()))
            self._update_phone_display()

# -----------------------------
# Main
# -----------------------------
def main():
    ze03_queue = queue.Queue()
    ze03_reader = SerialReaderThread(ZE03_SERIAL, ZE03_BAUD, ze03_queue, name="ZE03Reader")
    ze03_reader.start()

    modem_port = auto_detect_modem(baud=MODEM_BAUD, timeout=2)
    if modem_port is None:
        print("ERROR: No modem found on AMA5 or USB ports")
        sys.exit(1)

    modem = ModemController(modem_port, MODEM_BAUD, timeout=2)

    app = QApplication(sys.argv)
    font = QFont()
    font.setPointSize(10)
    app.setFont(font)

    window = MinerMonitorApp(ze03_queue, modem, message_ids=DEFAULT_MESSAGE_IDS.copy())
    window.showFullScreen()
    try:
        sys.exit(app.exec_())
    finally:
        ze03_reader.stop()

if __name__ == "__main__":
    main()
