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
    QMessageBox, QProgressBar, QComboBox, QLineEdit
)
from PyQt5.QtGui import QFont

# -----------------------------
# CONFIG
# -----------------------------
ZE03_SERIAL = "/dev/ttyS0"
ZE03_BAUD = 9600

MODEM_BAUD = 115200

SOS_SMS_TEXT = "SOS: Dangerous gas levels detected!"
PPM_WARN = 40
PPM_DANGER = 100

MODEM_PORT = "/dev/ttyAMA5"

# Global stylesheet for consistent dark theme and fewer white UI bars
APP_STYLESHEET = """
QWidget { background-color: #0f1115; color: #e5e7eb; }
QLabel { color: #e5e7eb; }
QPushButton { background-color: #2563eb; color: #ffffff; border: none; border-radius: 10px; padding: 10px 12px; }
QPushButton#sosButton { background-color: #dc2626; }
QPushButton#sosButton:pressed { background-color: #b91c1c; }
QPushButton:pressed { background-color: #1d4ed8; }
QPushButton:disabled { background-color: #374151; color: #9ca3af; }
QLineEdit, QComboBox { background-color: #111827; color: #e5e7eb; border: 1px solid #374151; border-radius: 8px; padding: 6px 8px; }
QProgressBar { background-color: #111827; border: 1px solid #374151; border-radius: 6px; text-align: center; color: #e5e7eb; }
QProgressBar::chunk { background-color: #10b981; border-radius: 6px; }
QMessageBox { background-color: #0f1115; }
"""

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

# -----------------------------
# Auto-detect modem
# -----------------------------
def auto_detect_modem(baud=MODEM_BAUD, timeout=2):
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
        self.setStyleSheet(APP_STYLESHEET)
        self._last_ppm = None
        self._last_frame_time = time.time()
        self._auto_sos_sent = False

        self.message_ids = message_ids or DEFAULT_MESSAGE_IDS.copy()

        self.title_font = QFont("Sans Serif", 14, QFont.Bold)
        self.big_font = QFont("Sans Serif", 28, QFont.Bold)
        self.med_font = QFont("Sans Serif", 12)
        self.small_font = QFont("Sans Serif", 10)

        # Top bar
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.setSpacing(8)
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
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(8)
        self.sos_button = QPushButton("SOS")
        self.sos_button.setObjectName("sosButton")
        self.sos_button.setFont(self.med_font)
        self.sos_button.setMinimumHeight(70)
        self.sos_button.clicked.connect(self.on_sos_pressed)

        self.send_button = QPushButton("Send Custom Message")
        self.send_button.setFont(self.med_font)
        self.send_button.setMinimumHeight(70)
        self.send_button.clicked.connect(self.on_send_pressed)

        btn_row.addWidget(self.sos_button)
        btn_row.addWidget(self.send_button)

        # Custom message controls
        custom_row = QHBoxLayout()
        custom_row.setContentsMargins(0, 0, 0, 0)
        custom_row.setSpacing(8)
        self.id_dropdown = QComboBox()
        self.id_dropdown.setFont(self.med_font)
        self.id_dropdown.addItems(sorted(self.message_ids.keys()))
        self.phone_display = QLabel(self.message_ids.get(self.id_dropdown.currentText(), ""))
        self.phone_display.setFont(self.small_font)
        self.id_dropdown.currentIndexChanged.connect(self._update_phone_display)

        custom_row.addWidget(self.id_dropdown)
        custom_row.addWidget(self.phone_display)

        self.message_input = QLineEdit()
        self.message_input.setFont(self.small_font)
        self.message_input.setPlaceholderText("Custom message...")

        # GNSS row
        gnss_row = QHBoxLayout()
        gnss_row.setContentsMargins(0, 0, 0, 0)
        gnss_row.setSpacing(8)
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
        v.setContentsMargins(12, 10, 12, 12)
        v.setSpacing(8)
        v.addLayout(top_bar)
        v.addWidget(self.ppm_label)
        v.addWidget(self.last_update_label)
        v.addWidget(self.status_label)
        v.addWidget(self.signal_bar)
        v.addLayout(btn_row)
        v.addLayout(custom_row)
        v.addWidget(self.message_input)
        v.addLayout(gnss_row)
        v.addWidget(self.result_label)
        self.setLayout(v)

        # loading overlay for actions
        self._create_loading_overlay()

        # signals
        self.signals.ppm_update.connect(self.update_ppm)
        self.signals.modem_status.connect(self.update_modem_status)
        self.signals.sms_result.connect(self.on_sms_result)
        self.signals.gnss_update.connect(self.on_gnss_update)
        self.signals.gsm_signal.connect(self.on_gsm_signal)

        self.ze03_parser = ZE03Parser()
        self.reader_thread = threading.Thread(target=self.ze03_worker, daemon=True)
        self.reader_thread.start()

        self.timer = QTimer()
        self.timer.setInterval(5000)
        self.timer.timeout.connect(self.periodic_tasks)
        self.timer.start()

        self._busy = False

        # Start GNSS once for live updates
        threading.Thread(target=self._ensure_gnss_started, daemon=True).start()

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
            # re-arm auto SOS when levels return to safe
            self._auto_sos_sent = False
        elif ppm < PPM_DANGER:
            color = "#ffcc33"
        else:
            color = "#ff3333"
            if not self._auto_sos_sent:
                self.result_label.setText("Auto SOS: high CO level")
                threading.Thread(target=self._send_sos_thread, daemon=True).start()
                self._auto_sos_sent = True
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

    def ze03_worker(self):
        while True:
            try:
                data = self.ze03_q.get()
                if isinstance(data, bytes):
                    if data.startswith(b"__SERIAL_ERROR__:") or data.startswith(b"__SERIAL_EXCEPTION__:"):
                        # Sensor serial error; do not override modem status label
                        try:
                            print(data.decode(errors="ignore"))
                        except Exception:
                            pass
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
        threading.Thread(target=self._poll_gnss_once, daemon=True).start()

    def _poll_gnss_once(self):
        try:
            loc = self.modem_ctrl.get_gnss_location(timeout=6)
        except Exception:
            loc = None
        self.signals.gnss_update.emit(loc)

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

    def _create_loading_overlay(self):
        self.overlay = QWidget(self)
        self.overlay.setStyleSheet("background-color: rgba(0, 0, 0, 160);")
        self.overlay.setVisible(False)
        self.overlay.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        layout = QVBoxLayout(self.overlay)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addStretch(1)
        self.overlay_label = QLabel("Please wait...")
        self.overlay_label.setAlignment(Qt.AlignCenter)
        self.overlay_label.setFont(self.med_font)
        layout.addWidget(self.overlay_label)
        self.overlay_progress = QProgressBar()
        self.overlay_progress.setRange(0, 0)
        layout.addWidget(self.overlay_progress)
        layout.addStretch(1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "overlay"):
            self.overlay.setGeometry(self.rect())

    def show_loading(self, text=""):
        def _show():
            self._busy = True
            self.sos_button.setDisabled(True)
            self.send_button.setDisabled(True)
            self.loc_btn.setDisabled(True)
            self.overlay_label.setStyleSheet("color: #e5e7eb;")
            self.overlay_label.setText(text or "Please wait...")
            self.overlay_progress.setRange(0, 0)
            self.overlay.setGeometry(self.rect())
            self.overlay.show()
        QTimer.singleShot(0, _show)

    def hide_loading(self):
        def _hide():
            self._busy = False
            self.overlay.hide()
            self.sos_button.setDisabled(False)
            self.send_button.setDisabled(False)
            self.loc_btn.setDisabled(False)
        QTimer.singleShot(0, _hide)

    def show_result_overlay(self, text, ok):
        def _show():
            color = "#10b981" if ok else "#ef4444"
            self.overlay_label.setStyleSheet(f"color: {color};")
            self.overlay_label.setText(text)
            self.overlay_progress.setRange(0, 1)
            self.overlay.setGeometry(self.rect())
            self.overlay.show()
            QTimer.singleShot(1300, self.hide_loading)
        QTimer.singleShot(0, _show)

    def set_busy(self, busy, text=""):
        if busy:
            self.show_loading(text or "Please wait...")
        else:
            self.hide_loading()

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

    def _send_custom_thread(self, number, text):
        self.set_busy(True, "Sending message...")
        ok, raw = self.modem_ctrl.send_sms_textmode(number, text, timeout=10)
        self.signals.sms_result.emit(ok, raw)

    def on_sms_result(self, ok, raw):
        if ok:
            self.result_label.setText("Last SMS: Sent")
            self.show_result_overlay("Message sent successfully", True)
        else:
            self.result_label.setText("Last SMS: Failed")
            self.show_result_overlay("Failed to send message", False)

    def on_get_location(self):
        self.set_busy(True, "Acquiring location...")
        threading.Thread(target=self._gnss_thread, daemon=True).start()

    def _gnss_thread(self):
        self.modem_ctrl.start_gnss()
        time.sleep(1)
        loc = self.modem_ctrl.get_gnss_location(timeout=6)
        self.signals.gnss_update.emit(loc)
        self.set_busy(False, "")

    def _ensure_gnss_started(self):
        try:
            self.modem_ctrl.start_gnss()
        except Exception:
            pass

# -----------------------------
# Main
# -----------------------------
def main():
    ze03_queue = queue.Queue()
    ze03_reader = SerialReaderThread(ZE03_SERIAL, ZE03_BAUD, ze03_queue, name="ZE03Reader")
    ze03_reader.start()

    modem_port = MODEM_PORT
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
