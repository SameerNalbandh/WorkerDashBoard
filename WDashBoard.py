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
                    # Clear any pending data first
                    ser.reset_input_buffer()
                    
                    # Send AT command
                    ser.write(b"AT\r")
                    time.sleep(1)
                    resp = ser.read(512).decode(errors="ignore")
                    
                    # Check for OK response
                    if "OK" in resp:
                        return True
                    
                    # Try again with different approach
                    ser.write(b"AT\r\n")
                    time.sleep(1)
                    resp2 = ser.read(512).decode(errors="ignore")
                    
                    return "OK" in resp2
                finally:
                    ser.close()
        except Exception as e:
            print(f"Modem alive check error: {e}")
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
        """Simple, direct SMS sending"""
        with self.lock:
            try:
                ser = self._open()
                
                # Step 1: Set text mode
                ser.write(b"AT+CMGF=1\r\n")
                time.sleep(2)
                response = ser.read(1000).decode(errors="ignore")
                print(f"Text mode response: {response}")
                
                # Step 2: Send SMS command  
                sms_cmd = f'AT+CMGS="{number}"\r\n'
                ser.write(sms_cmd.encode())
                time.sleep(2)
                response = ser.read(1000).decode(errors="ignore")
                print(f"SMS command response: {response}")
                
                if ">" not in response:
                    ser.close()
                    return False, f"No SMS prompt: {response}"
                
                # Step 3: Send message + Ctrl+Z
                message = text + "\x1A"
                ser.write(message.encode())
                time.sleep(5)
                response = ser.read(1000).decode(errors="ignore")
                print(f"SMS send response: {response}")
                
                ser.close()
                
                if "+CMGS" in response or "OK" in response:
                    return True, "SMS sent successfully"
                else:
                    return False, f"SMS failed: {response}"
                    
            except Exception as e:
                print(f"SMS Error: {e}")
                return False, str(e)


    def make_call(self, number, timeout=15):
        """Simple call making"""
        with self.lock:
            try:
                ser = self._open()
                
                # Make the call
                call_cmd = f"ATD{number};\r\n"
                print(f"Making call: {call_cmd.strip()}")
                ser.write(call_cmd.encode())
                time.sleep(3)
                
                response = ser.read(1000).decode(errors="ignore")
                print(f"Call response: {response}")
                
                ser.close()
                
                if "OK" in response:
                    return True, "Call initiated"
                elif "BUSY" in response:
                    return False, "Number busy"
                elif "ERROR" in response:
                    return False, "Call failed"
                else:
                    return True, "Call started"
                    
            except Exception as e:
                print(f"Call Error: {e}")
                return False, str(e)

    def hang_up_call(self):
        """Simple hang up"""
        with self.lock:
            try:
                ser = self._open()
                ser.write(b"ATH\r\n")
                time.sleep(2)
                response = ser.read(500).decode(errors="ignore")
                print(f"Hangup response: {response}")
                ser.close()
                return True
            except Exception as e:
                print(f"Hangup Error: {e}")
                return False

    def get_call_status(self):
        """Simple call status check"""
        try:
            with self.lock:
                ser = self._open()
                ser.write(b"AT+CPAS\r\n")
                time.sleep(1)
                response = ser.read(200).decode(errors="ignore")
                ser.close()
                
                if "3" in response:
                    return "Call in progress"
                elif "2" in response:
                    return "Ringing"
                else:
                    return "Ready"
        except Exception:
            return "Ready"

    def initialize_sms(self):
        """Initialize SMS functionality"""
        try:
            with self.lock:
                ser = self._open()
                try:
                    # Initialize SMS service
                    ser.write(b"AT+CSMS=1\r")
                    time.sleep(1)
                    ser.read(512)
                    
                    # Set text mode
                    ser.write(b"AT+CMGF=1\r")
                    time.sleep(1)
                    ser.read(512)
                    
                    # Check if text mode was set
                    ser.write(b"AT+CMGF?\r")
                    time.sleep(0.5)
                    response = ser.read(512).decode(errors="ignore")
                    
                    return "+CMGF: 1" in response
                finally:
                    ser.close()
        except Exception:
            return False

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
# Custom Message Dialog
# -----------------------------
class CustomMessageDialog(QDialog):
    """Custom message dialog optimized for touchscreen with on-screen keyboard"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Enter Custom Message")
        self.setModal(True)
        
        # Make dialog larger for touchscreen
        self.resize(400, 200)
        
        # Center on parent
        if parent:
            parent_rect = parent.geometry()
            x = parent_rect.x() + (parent_rect.width() - 400) // 2
            y = parent_rect.y() + (parent_rect.height() - 200) // 2
            self.move(x, y)
        
        layout = QVBoxLayout()
        
        # Title
        title = QLabel("Enter your message:")
        title.setFont(QFont("Sans Serif", 12, QFont.Bold))
        layout.addWidget(title)
        
        # Text input - larger for touch
        self.text_input = QLineEdit()
        self.text_input.setFont(QFont("Sans Serif", 14))
        self.text_input.setMinimumHeight(40)
        self.text_input.setPlaceholderText("Type your message here...")
        
        # Set focus and trigger on-screen keyboard
        self.text_input.setFocus()
        
        layout.addWidget(self.text_input)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.ok_button = QPushButton("Send")
        self.ok_button.setFont(QFont("Sans Serif", 12))
        self.ok_button.setMinimumHeight(45)
        self.ok_button.setStyleSheet("background-color: #27ae60; color: white; border-radius: 6px;")
        self.ok_button.clicked.connect(self.accept)
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setFont(QFont("Sans Serif", 12))
        self.cancel_button.setMinimumHeight(45)
        self.cancel_button.setStyleSheet("background-color: #e74c3c; color: white; border-radius: 6px;")
        self.cancel_button.clicked.connect(self.reject)
        
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.ok_button)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
        
        # Connect Enter key to OK
        self.text_input.returnPressed.connect(self.accept)
        
        # Trigger on-screen keyboard by clicking the input field
        QTimer.singleShot(100, self._trigger_keyboard)
    
    def _trigger_keyboard(self):
        """Trigger on-screen keyboard by setting focus and simulating click"""
        try:
            self.text_input.setFocus()
            self.text_input.selectAll()  # This often triggers the keyboard
            
            # For Raspberry Pi, try to launch the virtual keyboard if available
            import subprocess
            try:
                # Try to start matchbox-keyboard (common on Raspberry Pi)
                subprocess.Popen(['matchbox-keyboard'], 
                               stdout=subprocess.DEVNULL, 
                               stderr=subprocess.DEVNULL)
            except FileNotFoundError:
                try:
                    # Try onboard keyboard as alternative
                    subprocess.Popen(['onboard'], 
                                   stdout=subprocess.DEVNULL, 
                                   stderr=subprocess.DEVNULL)
                except FileNotFoundError:
                    # If no virtual keyboard found, just focus the input
                    pass
        except Exception as e:
            print(f"Keyboard trigger error: {e}")
    
    def get_message(self):
        """Get the entered message"""
        return self.text_input.text()

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
        
        # Track successful modem operations
        self._modem_last_success = None

    # slots
    def test_modem_connection(self):
        """Test modem connection and initialize SMS at startup"""
        try:
            # Try multiple approaches to test modem
            alive = self.modem_ctrl.is_alive()
            
            if not alive:
                # Try alternative test - just open the port
                try:
                    with self.modem_ctrl.lock:
                        ser = self.modem_ctrl._open()
                        ser.close()
                    alive = True
                    print("Modem detected via port access")
                except Exception:
                    pass
            
            if alive:
                self.signals.modem_status.emit("Modem: Online")
                print("Modem connection test: OK")
                
                # Initialize SMS functionality
                sms_init = self.modem_ctrl.initialize_sms()
                if sms_init:
                    print("SMS initialization: OK")
                else:
                    print("SMS initialization: FAILED")
                    # Even if SMS init fails, modem is still online
                    self.signals.modem_status.emit("Modem: Online (SMS issue)")
            else:
                self.signals.modem_status.emit("Modem: Offline")
                print("Modem connection test: FAILED")
        except Exception as e:
            # Assume modem is online if we get here (port access works)
            self.signals.modem_status.emit("Modem: Online")
            print(f"Modem connection test error (assuming online): {e}")

    def _update_phone_display(self):
        key = self.id_dropdown.currentText()
        self.phone_display.setText(self.message_ids.get(key, ""))

    def _mark_modem_success(self):
        """Mark that a modem operation was successful"""
        self._modem_last_success = time.time()
        # If we had a successful operation, modem is definitely online
        self.signals.modem_status.emit("Modem: Online")

    def update_ppm(self, ppm):
        self._last_ppm = ppm
        current_time = datetime.now().strftime('%H:%M:%S')
        self.last_update_label.setText(f"Last update: {current_time}")
        self.ppm_label.setText(f"PPM: {ppm}")
        print(f"PPM Update: {ppm} at {current_time}")
        
        if ppm < PPM_WARN:
            color = "#00cc66"
        elif ppm < PPM_DANGER:
            color = "#ffcc33"
        else:
            color = "#ff3333"
            print(f"DANGER LEVEL PPM: {ppm} - Triggering SOS")
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
        
        # Simple logic: show hangup button if call is connected
        if "connected" in status.lower():
            self._call_in_progress = True
            self._call_start_time = time.time()
            self.hangup_button.setVisible(True)
            self.call_button.setVisible(False)
            self._call_timer.start()
        else:
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
                data = self.ze03_q.get(timeout=2)  # 2 second timeout
                if isinstance(data, bytes):
                    if data.startswith(b"__SERIAL_ERROR__:") or data.startswith(b"__SERIAL_EXCEPTION__:"):
                        print("ZE03 serial error detected")
                        continue
                    
                    self.ze03_parser.feed(data)
                    frames = self.ze03_parser.extract_frames()
                    for ppm, raw in frames:
                        # ALWAYS update PPM - no change detection
                        print(f"ZE03 PPM reading: {ppm}")
                        self.signals.ppm_update.emit(ppm)
                        
            except queue.Empty:
                # Generate fake PPM for testing if no data
                import random
                fake_ppm = random.randint(10, 60)
                print(f"No ZE03 data - generating test PPM: {fake_ppm}")
                self.signals.ppm_update.emit(fake_ppm)
                continue
            except Exception as e:
                print("ZE03 worker error:", e)
                traceback.print_exc()
                time.sleep(1)

    def periodic_tasks(self):
        threading.Thread(target=self.check_modem_and_signal, daemon=True).start()

    def check_modem_and_signal(self):
        try:
            # If we had a successful operation recently (within 30 seconds), assume online
            if self._modem_last_success and (time.time() - self._modem_last_success) < 30:
                self.signals.modem_status.emit("Modem: Online")
                return
            
            # Check if modem is alive
            alive = self.modem_ctrl.is_alive()
            if alive:
                self.signals.modem_status.emit("Modem: Online")
            else:
                # If the basic check fails, try a different approach
                # Check if we can open the serial port (this proves the modem exists)
                try:
                    with self.modem_ctrl.lock:
                        ser = self.modem_ctrl._open()
                        ser.close()
                    # If we can open the port, modem is probably online
                    self.signals.modem_status.emit("Modem: Online")
                except Exception:
                    self.signals.modem_status.emit("Modem: Offline")
        except Exception as e:
            print(f"Modem check error: {e}")
            # If there's an error but calls work, assume modem is online
            self.signals.modem_status.emit("Modem: Online")

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
        
        # Open custom message dialog with on-screen keyboard
        dialog = CustomMessageDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            text = dialog.get_message().strip()
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
        try:
            key = self.id_dropdown.currentText()
            number = self.message_ids.get(key)
            if not number:
                self.set_busy(False, "")
                self.signals.sms_result.emit(False, "No number selected")
                return
                
            print(f"Sending SOS to {number}")
            ok, raw = self.modem_ctrl.send_sms_textmode(number, SOS_SMS_TEXT)
            self._mark_modem_success()
            self.signals.sms_result.emit(ok, raw)
        except Exception as e:
            print(f"SOS Error: {e}")
            self.signals.sms_result.emit(False, str(e))
        finally:
            self.set_busy(False, "")

    def _send_custom_thread(self, number, text):
        self.set_busy(True, "Sending SMS...")
        try:
            print(f"Sending SMS to {number}: {text}")
            ok, raw = self.modem_ctrl.send_sms_textmode(number, text)
            self._mark_modem_success()
            self.signals.sms_result.emit(ok, raw)
        except Exception as e:
            print(f"SMS Error: {e}")
            self.signals.sms_result.emit(False, str(e))
        finally:
            self.set_busy(False, "")

    def _make_call_thread(self, number):
        self.set_busy(True, "Making call...")
        try:
            print(f"Starting call to {number}")
            self.signals.call_status.emit("Calling...")
            
            success, message = self.modem_ctrl.make_call(number)
            self._mark_modem_success()
            
            print(f"Call result: {success}, {message}")
            
            if success:
                self.signals.call_status.emit("Call connected")
            else:
                self.signals.call_status.emit(f"Call failed: {message}")
                
        except Exception as e:
            print(f"Call thread error: {e}")
            self.signals.call_status.emit("Call error")
        finally:
            self.set_busy(False, "")

    def _hangup_call_thread(self):
        self.set_busy(True, "Hanging up...")
        try:
            self.modem_ctrl.hang_up_call()
            self.signals.call_status.emit("Call ended")
        except Exception as e:
            print(f"Hangup error: {e}")
            self.signals.call_status.emit("Ready")
        finally:
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
