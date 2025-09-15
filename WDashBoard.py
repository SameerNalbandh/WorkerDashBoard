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

APP_TITLE = "Worker Safety Monitor"
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
            with self.lock:
                ser = self._open()
                try:
                    ser.write(b"AT\r")
                    time.sleep(0.5)
                    resp = ser.read(256)
                    return b"OK" in resp
                finally:
                    ser.close()
        except Exception:
            return False

    def get_signal_quality(self):
        try:
            with self.lock:
                ser = self._open()
                try:
                    ser.write(b"AT+CSQ\r")
                    time.sleep(0.5)
                    resp = ser.read(256).decode(errors="ignore")
                    for line in resp.splitlines():
                        if "+CSQ" in line:
                            parts = line.split(":")[1].strip().split(",")
                            return int(parts[0])
                    return None
                finally:
                    ser.close()
        except Exception:
            return None

    def send_sms_textmode(self, number, text, timeout=20):
        with self.lock:
            ser = self._open()
            try:
                # Set text mode
                ser.write(b"AT+CMGF=1\r")
                time.sleep(1)
                response = ser.read(1024)
                if b"OK" not in response:
                    return False, f"Failed to set text mode: {response.decode(errors='ignore')}"

                # Send SMS command
                cmd = f'AT+CMGS="{number}"\r'.encode()
                ser.write(cmd)
                time.sleep(1)

                # Wait for '>' prompt
                deadline = time.time() + 15
                buf = bytearray()
                while time.time() < deadline:
                    chunk = ser.read(256)
                    if chunk:
                        buf.extend(chunk)
                        if b">" in buf:
                            break
                    time.sleep(0.2)

                if b">" not in buf:
                    return False, f"No prompt received: {buf.decode(errors='ignore')}"

                # Send message with Ctrl+Z
                ser.write(text.encode() + b"\x1A")
                time.sleep(2)

                # Wait for result
                resp = bytearray()
                deadline = time.time() + timeout
                while time.time() < deadline:
                    chunk = ser.read(512)
                    if chunk:
                        resp.extend(chunk)
                        if b"+CMGS" in resp or b"OK" in resp or b"ERROR" in resp or b"+CMS ERROR" in resp:
                            break
                    time.sleep(0.2)

                s = resp.decode(errors="ignore")
                if "ERROR" in s or "+CMS ERROR" in s:
                    return False, s
                if "+CMGS" in s or "OK" in s:
                    return True, s
                return False, f"No response received: {s}"
            except Exception as e:
                return False, str(e)
            finally:
                try:
                    ser.close()
                except Exception:
                    pass


    def make_call(self, number, timeout=15):
        """Make a call to the specified number"""
        with self.lock:
            ser = self._open()
            try:
                # Make the call
                cmd = f'ATD{number};\r'.encode()
                ser.write(cmd)
                time.sleep(1)
                
                # Quick response check
                response = ser.read(512).decode(errors="ignore")
                
                if "ERROR" in response:
                    return False, "Call failed"
                elif "BUSY" in response:
                    return False, "Number busy"
                elif "NO CARRIER" in response:
                    return False, "Call declined"
                elif "NO ANSWER" in response:
                    return False, "No answer"
                else:
                    return True, "Call initiated"
                    
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
        """Get current call status - simplified"""
        try:
            with self.lock:
                ser = self._open()
                try:
                    ser.write(b"AT+CPAS\r")
                    time.sleep(0.3)
                    response = ser.read(256).decode(errors="ignore")
                    if "+CPAS: 3" in response:
                        return "Call in progress"
                    elif "+CPAS: 2" in response:
                        return "Ringing"
                    else:
                        return "Ready"
                finally:
                    ser.close()
        except Exception:
            return "Ready"

# -----------------------------
# Get modem port (EC200U-CNAA on AMA5)
# -----------------------------
def get_modem_port():
    """Return the AMA5 port for EC200U-CNAA modem"""
    return MODEM_PORT

# -----------------------------
# GUI Signals
# -----------------------------
class AppSignals(QObject):
    ppm_update = pyqtSignal(int)
    modem_status = pyqtSignal(str)
    sms_result = pyqtSignal(bool, str)
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
        
        # Test modem connection asynchronously
        threading.Thread(target=self.test_modem_connection, daemon=True).start()

        self.title_font = QFont("Sans Serif", 12, QFont.Bold)
        self.big_font = QFont("Sans Serif", 24, QFont.Bold)
        self.med_font = QFont("Sans Serif", 10)
        self.small_font = QFont("Sans Serif", 8)

        # Top bar
        top_bar = QHBoxLayout()
        self.title_label = QLabel("WORKER SAFETY MONITOR")
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

        # Call status and timer
        call_status_row = QHBoxLayout()
        self.call_status_label = QLabel("Call Status: Ready")
        self.call_status_label.setFont(self.small_font)
        self.call_timer_label = QLabel("")
        self.call_timer_label.setFont(self.small_font)
        self.call_timer_label.setAlignment(Qt.AlignRight)
        call_status_row.addWidget(self.call_status_label)
        call_status_row.addWidget(self.call_timer_label)

        # Select number
        number_row = QHBoxLayout()
        self.id_dropdown = QComboBox()
        self.id_dropdown.setFont(self.med_font)
        self.id_dropdown.addItems(sorted(self.message_ids.keys()))
        self.phone_display = QLabel(self.message_ids.get(self.id_dropdown.currentText(), ""))
        self.phone_display.setFont(self.small_font)
        self.id_dropdown.currentIndexChanged.connect(self._update_phone_display)

        number_row.addWidget(QLabel("Select:"))
        number_row.addWidget(self.id_dropdown)
        number_row.addWidget(self.phone_display)

        # Custom message input
        self.message_input = QLineEdit()
        self.message_input.setFont(self.small_font)
        self.message_input.setPlaceholderText("Enter message...")

        self.result_label = QLabel("")
        self.result_label.setFont(self.small_font)
        self.result_label.setAlignment(Qt.AlignCenter)

        v = QVBoxLayout()
        v.addLayout(top_bar)
        v.addWidget(self.ppm_label)
        v.addWidget(self.last_update_label)
        v.addWidget(self.status_label)
        v.addLayout(btn_row1)
        v.addLayout(btn_row2)
        v.addLayout(call_status_row)
        v.addLayout(number_row)
        v.addWidget(self.message_input)
        v.addWidget(self.result_label)
        self.setLayout(v)

        # signals
        self.signals.ppm_update.connect(self.update_ppm)
        self.signals.modem_status.connect(self.update_modem_status)
        self.signals.sms_result.connect(self.on_sms_result)
        self.signals.gsm_signal.connect(self.on_gsm_signal)
        self.signals.call_status.connect(self.update_call_status)
        self.signals.call_timer.connect(self.update_call_timer)

        self.ze03_parser = ZE03Parser()
        self.reader_thread = threading.Thread(target=self.ze03_worker, daemon=True)
        self.reader_thread.start()

        self.timer = QTimer()
        self.timer.setInterval(10000)  # Reduced frequency - every 10 seconds
        self.timer.timeout.connect(self.periodic_tasks)
        self.timer.start()

        # Call state variables
        self._busy = False
        self._call_in_progress = False
        self._call_start_time = None
        self._call_timer = QTimer()
        self._call_timer.setInterval(1000)  # Update every second
        self._call_timer.timeout.connect(self.update_call_timer_display)
        
        # Simple call monitoring (only when call is active)
        self._call_monitor = QTimer()
        self._call_monitor.setInterval(5000)  # Check every 5 seconds
        self._call_monitor.timeout.connect(self.check_call_ended)

    # slots
    def test_modem_connection(self):
        """Test modem connection at startup"""
        try:
            alive = self.modem_ctrl.is_alive()
            if alive:
                self.signals.modem_status.emit("Modem: Online")
                print("Modem connection test: OK")
            else:
                self.signals.modem_status.emit("Modem: Offline")
                print("Modem connection test: FAILED")
        except Exception as e:
            self.signals.modem_status.emit("Modem: Error")
            print(f"Modem connection test error: {e}")

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

    def on_gsm_signal(self, val):
        if val is None:
            self.status_label.setText("Modem: Online | Signal: ?")
        else:
            self.status_label.setText(f"Modem: Online | Signal: {val}")

    def update_call_status(self, status):
        self.call_status_label.setText(f"Call Status: {status}")
        if status in ["Call in progress", "Call connected"]:
            self._call_in_progress = True
            self._call_start_time = time.time()
            self.hangup_button.setVisible(True)
            self.call_button.setVisible(False)
            self._call_timer.start()
            self._call_monitor.start()  # Start monitoring for call end
        elif status in ["Ready", "Call failed", "Call ended", "Call declined", "No answer", "Number busy"]:
            self._call_in_progress = False
            self._call_start_time = None
            self.hangup_button.setVisible(False)
            self.call_button.setVisible(True)
            self._call_timer.stop()
            self._call_monitor.stop()  # Stop monitoring
            self.call_timer_label.setText("")

    def update_call_timer(self, seconds):
        self.call_timer_label.setText(f"Call Time: {seconds}s")

    def update_call_timer_display(self):
        if self._call_in_progress and self._call_start_time:
            elapsed = int(time.time() - self._call_start_time)
            self.call_timer_label.setText(f"Call Time: {elapsed}s")

    def check_call_ended(self):
        """Check if call has ended - only runs when call is active"""
        if self._call_in_progress:
            try:
                status = self.modem_ctrl.get_call_status()
                if status == "Ready":
                    self.signals.call_status.emit("Call ended")
            except Exception:
                pass


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
            # Simple alive check only
            alive = self.modem_ctrl.is_alive()
            if alive:
                self.signals.modem_status.emit("Modem: Online")
            else:
                self.signals.modem_status.emit("Modem: Offline")
        except Exception as e:
            print(f"Modem check error: {e}")
            self.signals.modem_status.emit("Modem: Error")

    def set_busy(self, busy, text=""):
        self._busy = busy
        self.sos_button.setDisabled(busy)
        self.send_button.setDisabled(busy)
        self.call_button.setDisabled(busy)
        self.result_label.setText(text)

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
        
        success, message = self.modem_ctrl.make_call(number, timeout=15)
        
        if success:
            self.signals.call_status.emit("Call connected")
            self.set_busy(False, "")
        else:
            # Handle different failure cases
            if "busy" in message.lower():
                self.signals.call_status.emit("Number busy")
            elif "no answer" in message.lower():
                self.signals.call_status.emit("No answer")
            elif "declined" in message.lower():
                self.signals.call_status.emit("Call declined")
            else:
                self.signals.call_status.emit("Call failed")
            self.set_busy(False, "")
            # Don't show message box for declined/no answer as these are normal

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



# -----------------------------
# Main
# -----------------------------
def main():
    ze03_queue = queue.Queue()
    ze03_reader = SerialReaderThread(ZE03_SERIAL, ZE03_BAUD, ze03_queue, name="ZE03Reader")
    ze03_reader.start()

    # Use AMA5 port directly for EC200U-CNAA
    modem_port = get_modem_port()
    print(f"[INFO] Using EC200U-CNAA modem on {modem_port}")

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
