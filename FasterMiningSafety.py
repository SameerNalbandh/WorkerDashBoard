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
import json

import serial
from serial import SerialException

# Firebase imports
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    print("âš ï¸ Firebase Admin SDK not installed. PPM upload functionality will be disabled.")

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QMessageBox, QProgressBar, QLineEdit, QDialog, QFormLayout,
    QDialogButtonBox, QSizePolicy, QComboBox, QFrame, QSpacerItem
)
from PyQt5.QtGui import QFont

# -----------------------------
# CONFIG
# -----------------------------
ZE03_SERIAL = "/dev/ttyS0"
ZE03_BAUD = 9600

MODEM_BAUD = 115200
MODEM_SERIAL = "/dev/ttyAMA5"  # Fixed UART port for Quectel EC200U

SOS_SMS_TEXT = "SOS: Dangerous gas levels detected at latitude:16.4963,longitude:80.5006 and location:VIT AP UNIVERSITY!"
PPM_WARN = 100
PPM_DANGER = 1000

APP_TITLE = "Miner Safety Monitor"
WINDOW_WIDTH = 480
WINDOW_HEIGHT = 320

# Single alert destination (edit as fallback)
ALERT_PHONE = "+911234567890"

# Contact list for dropdown selection
CONTACTS = {
    "sameer": "+916352925852",
    "ramsha": "+918179489703",
    "surya": "+917974560541",
    "anupam": "+917905030839",
    "shanmukesh": "+919989278339",
    "kartika": "+919871390413"
}

# Firebase configuration
FIREBASE_SERVICE_ACCOUNT_INFO = {
  "type": "service_account",
  "project_id": "studio-5053909228-90740",
  "private_key_id": "ec48b6876af2046a47bc60a4b8e9ce67182e6827",
  "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQDIAD6oIwampQYk\n6WAKDgTH0AryPBgHxrBuSR17b3tSTLmZLeteiLGA1mVW6kOM5IOm1+twFYSl8H7h\nDVSdqNN2os/181TtzkrTirkOwfYcgUua0KOIttzZZwduzmYhHSwVrgmCkYNjEFDh\nwhx3KXeI35cG+fmYcOxm4p8H0KHa/hJYZ4eu1sZjg8Z5gTAvpD7TZWsnzmiWYQ9r\n5nCO7xGVXE7JmpvOz3s0uIzNyZfToGI0tAX9bwTKgRvE8vqU2tF314VdGqa9jyiF\nUA96i0Y0tO2Ryzv3IEmOCYl3EfOJ/ZBsLBAtunBIlQkwv+VjT2dVVMRiywJgfGQ+\nnoY2PktTAgMBAAECggEAIGZQatrjE3ECxKJdPBPBo4BTnaKtk+jp9lvNimG+J9Al\nIFMHi7TM6J29egM7toyNuqQaUHnel3vqhK6CVC4gNQUIIoRtGunYm691Q5ZEC/cd\ngTLRI0SDFOGzcGMVuWyT596IojMiMT9Ykvy9XB0xb6YlExdrifiqhg+qtVCPlT2v\n+JUBM9kUa6g0AIdn941rWqfFDVBEHld4cbMSRML4CYGVLRMVrsdUDIvRcJBBfEbO\nPbiLwTToEy04GuWa5Ghd2wytTw2gEVB50lsx79JWDXC4VX99sPo9+AjJGjiWJ2Ow\nftZ9Cole6iqOJkkjENRcuk5CeOH/Xkpkx2v1K+igyQKBgQDkTlfVydpQ/cOdAmmT\n4I3g1KsxBLDrpxEOJfSNLO9db8IpNmif/1FhlCILdNVsT7ZZeWfF9f4JewhoXJa4\nfRUZ8+sXtHmNcy3fLZ6j2xzajG5MNWJOyjvl1gs9aOememOEg+JG+dkAO9ulcMJB\nb/7KxQmaiHJIXhxBS1LwUOMxmQKBgQDgQu+Dg2laVl0gomaYfwGHLoDxR15x8/Ky\nvP0Y68LAc/YaoMjTgGDys1CI4rJVTkXJTXte73YggI/QZGzJ2MabUEcI+YyGFZKA\nS5mjZRqyR9fECrE6StqNiAwYIfHy4VVWFdRR79Y7Ak7omjo8LrXJcPex4pDSmOR3\nD0vgbF4PywKBgFBjVYIthPWnpM0QIGS1WL+lonGsGS+gr9yveKCNBet8gn1IbyaH\nG/yj0CkAhnWQy8BNg0CtETn9XESC9X8Ya+mrfUfngDVSLQC8a3N+n3ZEpEGpOmhL\nxTN0XpjM62QvDAOI/I/JQaNXcEucnIm2CZ0ULAGBsdvRZ1mGUDnWAWlhAoGAO003\n7LzpNPw1cBXBr32WN9ryOds3fEaX3O/gtaBSRXXklDIEKPl/qW4FU80ufyRNi+ez\nQe1sfTfBz8dehRmPmy5lOlhS8nnt3YMgQ3bO0mnxAmQZbWKx3E8nc5I2WpV/bV4k\nYO5c5gm8OAHgeF2ZsITw2tcgmK/ZaipfVB8T2HUCgYAlxGEsd0bsfXsI6a4UeTmA\nDqVvzVsC2G819NEskoE+fdLHK33LkxhKH3FW3UM5CQ/ZDtNNbsPnMPDYLJp4RcEH\nR+P2plSBQNICkVzZ6dm0JlGyFrK5p/DVUK+hNgIB4Wp4oGd6raIcrnjvo84gc2OZ\nLHFMj0vBsj/dDI5C2XqWWw==\n-----END PRIVATE KEY-----\n",
  "client_email": "firebase-adminsdk-fbsvc@studio-5053909228-90740.iam.gserviceaccount.com",
  "client_id": "109877301737436156902",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-fbsvc%40studio-5053909228-90740.iam.gserviceaccount.com",
  "universe_domain": "googleapis.com"
}

# Device configuration for Firebase
DEVICE_ID = "SN-PI-001"
DEVICE_NAME = "Miner Safety Monitor - Main Room"
LOCATION_NAME = "Main Room"
LOCATION_LAT = 16.4963
LOCATION_LNG = 80.5006

# Upload interval in seconds (upload every 30 seconds)
UPLOAD_INTERVAL = 30

# -----------------------------
# Utilities
# -----------------------------
def current_ts():
    return datetime.utcnow().isoformat() + "Z"

def read_co_sensor():
    """Read CO sensor value from the ZE03 sensor."""
    # This function should be called from the context where we have access to the current PPM reading
    # For now, we'll return the last known PPM value from the GUI
    # In a real implementation, this might read directly from the serial port
    # or access the last reading from a shared variable
    return 50  # Placeholder - in practice, this would get the current PPM from the sensor

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
        self._initialized = False

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

    def wait_for_registration(self, max_wait_seconds=30):
        deadline = time.time() + max_wait_seconds
        while time.time() < deadline:
            try:
                # Try LTE, PS and CS registration queries
                for cmd in ("AT+CEREG?", "AT+CGREG?", "AT+CREG?"):
                    resp = self.send_at(cmd, wait_for=b"OK", timeout=2)
                    s = resp.decode(errors="ignore")
                    for line in s.splitlines():
                        if ":" in line and ("CEREG" in line or "CGREG" in line or "CREG" in line):
                            try:
                                status = int(line.split(":")[1].strip().split(",")[1])
                                if status in (1, 5):
                                    return True
                            except Exception:
                                pass
            except Exception:
                pass
            time.sleep(1.0)
        return False

    def initialize_for_sms(self):
        try:
            steps = [
                ("AT", 2),
                ("ATE0", 2),
                ("AT+CMEE=2", 2),
                ("AT+CFUN=1", 5),
                ("AT+CPIN?", 2),
            ]
            for cmd, to in steps:
                _ = self.send_at(cmd, wait_for=b"OK", timeout=to)

            if not self.wait_for_registration(max_wait_seconds=45):
                return False, "Not registered to network"

            _ = self.send_at("AT+CSCS=\"GSM\"", wait_for=b"OK", timeout=2)
            _ = self.send_at("AT+CMGF=1", wait_for=b"OK", timeout=2)
            _ = self.send_at("AT+CSMS=1", wait_for=b"OK", timeout=2)
            # Optional: ensure SMS storage
            _ = self.send_at("AT+CPMS=\"ME\",\"ME\",\"ME\"", wait_for=b"OK", timeout=2)
        self._initialized = True
        return True, "Ready"
    except Exception as e:
        return False, str(e)
    
    def pre_initialize_for_fast_sms(self):
        """Pre-initialize modem for ultra-fast SMS sending."""
        try:
            # Pre-configure modem for maximum speed
            steps = [
                ("ATE0", 1),  # Echo off
                ("AT+CMEE=1", 1),  # Minimal error reporting
                ("AT+CMGF=1", 1),  # Text mode
                ("AT+CSCS=\"GSM\"", 1),  # Character set
                ("AT+CSMS=1", 1),  # SMS service
                ("AT+CPMS=\"ME\",\"ME\",\"ME\"", 1),  # Memory settings
            ]
            for cmd, to in steps:
                _ = self.send_at(cmd, wait_for=b"OK", timeout=to)
            return True, "Pre-initialized for fast SMS"
        except Exception as e:
            return False, str(e)

    def send_sms_textmode_fast(self, number, text, timeout=3):
        """Lightning-fast SMS sending with optimized timing and reduced delays."""
        with self.lock:
            ser = self._open()
            try:
                # Ultra-fast sequence - skip initialization if pre-configured
                if not hasattr(self, '_fast_mode_configured'):
                    # Quick setup only if not pre-configured
                    ser.write(b"ATE0\r")
                    time.sleep(0.02)
                    ser.read(64)
                    
                    ser.write(b"AT+CMGF=1\r")
                    time.sleep(0.02)
                    ser.read(64)
                    
                    ser.write(b"AT+CSCS=\"GSM\"\r")
                    time.sleep(0.02)
                    ser.read(64)
                    self._fast_mode_configured = True

                cmd = f'AT+CMGS="{number}"\r'.encode()
                ser.write(cmd)

                # Ultra-fast prompt detection
                deadline = time.time() + 2  # Reduced from 3
                buf = bytearray()
                while time.time() < deadline:
                    chunk = ser.read(64)  # Even smaller chunks
                    if chunk:
                        buf.extend(chunk)
                        if b">" in buf:
                            break
                    else:
                        time.sleep(0.01)  # Reduced from 0.02

                ser.write(text.encode() + b"\x1A")

                # Ultra-fast result detection
                resp = bytearray()
                deadline = time.time() + timeout
                while time.time() < deadline:
                    chunk = ser.read(128)  # Smaller chunks
                    if chunk:
                        resp.extend(chunk)
                        if b"+CMGS" in resp or b"OK" in resp or b"ERROR" in resp or b"+CMS ERROR" in resp:
                            break
                    else:
                        time.sleep(0.01)  # Reduced from 0.02

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

    def send_sms_textmode(self, number, text, timeout=10):
        """Original SMS method for backward compatibility."""
        with self.lock:
            ser = self._open()
            try:
                ser.write(b"ATE0\r")
                time.sleep(0.1)
                _ = ser.read(256)
                ser.write(b"AT+CMGF=1\r")
                time.sleep(0.2)
                _ = ser.read(512)
                ser.write(b"AT+CSCS=\"GSM\"\r")
                time.sleep(0.2)
                _ = ser.read(256)

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

    def send_sms_to_all_contacts_parallel(self, contacts_dict, text, timeout=5):
        """Send SMS to all contacts in parallel for maximum speed."""
        import concurrent.futures
        from threading import Lock
        
        results = {}
        results_lock = Lock()
        
        def send_to_contact(contact_name, phone_number):
            """Send SMS to a single contact."""
            try:
                success, response = self.send_sms_textmode_fast(phone_number, text, timeout)
                with results_lock:
                    results[contact_name] = {
                        'phone': phone_number,
                        'success': success,
                        'response': response[:100] if response else "No response"
                    }
                return contact_name, success, response
            except Exception as e:
                with results_lock:
                    results[contact_name] = {
                        'phone': phone_number,
                        'success': False,
                        'response': f"Exception: {str(e)[:100]}"
                    }
                return contact_name, False, str(e)
        
        # Send to all contacts in parallel using ThreadPoolExecutor
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(contacts_dict)) as executor:
            # Submit all SMS sending tasks
            future_to_contact = {
                executor.submit(send_to_contact, name, phone): name 
                for name, phone in contacts_dict.items()
            }
            
            # Collect results as they complete
            completed_count = 0
            total_count = len(contacts_dict)
            
            for future in concurrent.futures.as_completed(future_to_contact):
                contact_name = future_to_contact[future]
                try:
                    name, success, response = future.result()
                    completed_count += 1
                except Exception as e:
                    with results_lock:
                        results[contact_name] = {
                            'phone': contacts_dict[contact_name],
                            'success': False,
                            'response': f"Future exception: {str(e)[:100]}"
                        }
        
        # Calculate summary statistics
        successful = sum(1 for r in results.values() if r['success'])
        failed = len(results) - successful
        
        return {
            'total': total_count,
            'successful': successful,
            'failed': failed,
            'results': results
        }

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
# Loading Dialog
# -----------------------------
class LoadingDialog(QDialog):
    def __init__(self, parent, message="Processing..."):
        super().__init__(parent)
        self.setWindowTitle("Processing")
        self.setModal(True)
        self.setFixedSize(300, 150)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        
        # Worker safety color scheme
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                border: 2px solid #ff6b35;
                border-radius: 10px;
            }
        """)
        
        layout = QVBoxLayout()
        layout.setSpacing(20)
        
        # Loading spinner (animated progress bar)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.progress_bar.setFixedHeight(20)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #ff6b35;
                border-radius: 10px;
                background-color: #2a2a2a;
            }
            QProgressBar::chunk {
                background-color: #ff6b35;
                border-radius: 8px;
            }
        """)
        
        # Message label
        self.message_label = QLabel(message)
        self.message_label.setAlignment(Qt.AlignCenter)
        self.message_label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-size: 14px;
                font-weight: bold;
            }
        """)
        
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.message_label)
        self.setLayout(layout)
        
        # Center the dialog
        self.center_dialog()
    
    def center_dialog(self):
        if self.parent():
            parent_geometry = self.parent().geometry()
            x = parent_geometry.x() + (parent_geometry.width() - self.width()) // 2
            y = parent_geometry.y() + (parent_geometry.height() - self.height()) // 2
            self.move(x, y)
    
    def update_message(self, message):
        self.message_label.setText(message)

# -----------------------------
# Firebase Uploader
# -----------------------------
class FirebaseUploader:
    def __init__(self):
        self.db = None
        self.initialized = False
        self.last_upload_time = 0
        self.upload_count = 0
        self.failed_uploads = 0
        
        if FIREBASE_AVAILABLE:
            self._initialize_firebase()
    
    def _initialize_firebase(self):
        """Initialize Firebase connection."""
        try:
            cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT_INFO)
            firebase_admin.initialize_app(cred)
            self.db = firestore.client()
            self.initialized = True
            print("âœ… Firebase initialized successfully")
        except Exception as e:
            print(f"âŒ Firebase initialization failed: {e}")
            self.initialized = False
    
    def determine_status(self, co_level):
        """Determines status based on CO level."""
        if co_level > PPM_DANGER:
            return "Critical"
        elif co_level > PPM_WARN:
            return "Warning"
        else:
            return "Normal"
    
    def send_data_to_firestore(self, co_level=None):
        """Packages sensor data and adds it to a historical list in Firestore."""
        if not self.initialized or not self.db:
            return False, "Firebase not initialized"
        
        # Use provided co_level or read from sensor
        if co_level is None:
            co_level = read_co_sensor()
        
        status = self.determine_status(co_level)

        try:
            device_ref = self.db.collection("devices").document(DEVICE_ID)

            # Create a new reading object for the history
            new_reading = {
                "coLevel": co_level,
                "timestamp": firestore.SERVER_TIMESTAMP
            }

            # Prepare the main update payload
            update_payload = {
                "name": DEVICE_NAME,
                "location": { "name": LOCATION_NAME, "lat": LOCATION_LAT, "lng": LOCATION_LNG },
                "status": status,
                "coLevel": co_level, # This is the latest reading
                "timestamp": firestore.SERVER_TIMESTAMP, # This is the last updated time
                # Add the new reading to an array named 'historicalData'
                "historicalData": firestore.ArrayUnion([new_reading])
            }
            
            # Use .set() with merge=True to create or update the document
            device_ref.set(update_payload, merge=True)
            
            self.upload_count += 1
            self.last_upload_time = time.time()
            return True, f"✅ Success! Data saved to Firestore. PPM: {co_level}, Status: {status}"
            
        except Exception as e:
            self.failed_uploads += 1
            return False, f"❌ Firestore Error. Could not save data. Details: {e}"
    
    def upload_ppm_data(self, ppm_value):
        """Upload PPM data to Firebase - wrapper for backward compatibility."""
        return self.send_data_to_firestore(ppm_value)
    
    def get_stats(self):
        """Get upload statistics."""
        return {
            "initialized": self.initialized,
            "upload_count": self.upload_count,
            "failed_uploads": self.failed_uploads,
            "last_upload": self.last_upload_time
        }

# -----------------------------
# GUI Signals
# -----------------------------
class AppSignals(QObject):
    ppm_update = pyqtSignal(int)
    modem_status = pyqtSignal(str)
    sms_result = pyqtSignal(bool, str)
    gsm_signal = pyqtSignal(object)
    firebase_status = pyqtSignal(str)

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
        
        # Worker safety color scheme - dark background with safety orange/yellow accents
        self.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
            }
        """)
        
        self._last_ppm = None
        self._last_frame_time = time.time()
        self._above_threshold = False
        self.loading_dialog = None
        
        # Initialize Firebase uploader
        self.firebase_uploader = FirebaseUploader()
        self._last_upload_time = 0

        # Contacts and selected destination
        self.contacts = CONTACTS.copy()
        self.alert_phone = ALERT_PHONE

        self.title_font = QFont("Sans Serif", 16, QFont.Bold)
        self.big_font = QFont("Sans Serif", 36, QFont.Bold)
        self.med_font = QFont("Sans Serif", 13)
        self.small_font = QFont("Sans Serif", 11)

        # Top bar with safety styling
        top_bar = QHBoxLayout()
        top_bar.setSpacing(10)
        
        self.title_label = QLabel("âš ï¸ MINER SAFETY MONITOR âš ï¸")
        self.title_label.setFont(self.title_font)
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet("""
            QLabel {
                color: #ff6b35;
                font-weight: bold;
                padding: 10px;
                background-color: #2a2a2a;
                border: 2px solid #ff6b35;
                border-radius: 8px;
            }
        """)
        
        close_btn = QPushButton("âœ•")
        close_btn.setFont(self.med_font)
        close_btn.setFixedSize(40, 40)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff4444;
                color: white;
                border: 2px solid #cc0000;
                border-radius: 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #cc0000;
            }
        """)
        close_btn.clicked.connect(self.close)
        
        top_bar.addWidget(self.title_label, 1)
        top_bar.addWidget(close_btn)

        # PPM Display with safety styling
        self.ppm_label = QLabel("PPM: ---")
        self.ppm_label.setFont(self.big_font)
        self.ppm_label.setAlignment(Qt.AlignCenter)
        self.ppm_label.setStyleSheet("""
            QLabel {
                background-color: #2a2a2a;
                border: 3px solid #ff6b35;
                border-radius: 15px;
                padding: 20px;
                margin: 10px;
            }
        """)

        self.last_update_label = QLabel("Last update: --")
        self.last_update_label.setFont(self.small_font)
        self.last_update_label.setAlignment(Qt.AlignCenter)
        self.last_update_label.setStyleSheet("""
            QLabel {
                color: #cccccc;
                background-color: #333333;
                border-radius: 5px;
                padding: 5px;
            }
        """)

        self.status_label = QLabel("Modem: -- | Signal: --")
        self.status_label.setFont(self.small_font)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("""
            QLabel {
                color: #cccccc;
                background-color: #333333;
                border-radius: 5px;
                padding: 5px;
            }
        """)

        # Firebase status label
        self.firebase_status_label = QLabel("ðŸ“¡ Firebase: --")
        self.firebase_status_label.setFont(self.small_font)
        self.firebase_status_label.setAlignment(Qt.AlignCenter)
        self.firebase_status_label.setStyleSheet("""
            QLabel {
                color: #cccccc;
                background-color: #333333;
                border-radius: 5px;
                padding: 5px;
            }
        """)

        # Signal strength bar with safety colors
        self.signal_bar = QProgressBar()
        self.signal_bar.setRange(0, 31)
        self.signal_bar.setFormat("Signal: %v")
        self.signal_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #ff6b35;
                border-radius: 8px;
                background-color: #2a2a2a;
                text-align: center;
                color: white;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #ff6b35;
                border-radius: 6px;
            }
        """)

        # Busy/loading bar (indeterminate) - hidden as we'll use modal dialog
        self.busy_bar = QProgressBar()
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setVisible(False)
        self.busy_bar.setFixedHeight(10)

        # Buttons with enhanced safety styling
        btn_row = QHBoxLayout()
        btn_row.setSpacing(15)
        
        self.sos_button = QPushButton("ðŸš¨ SOS ðŸš¨")
        self.sos_button.setFont(self.med_font)
        self.sos_button.setMinimumHeight(80)
        self.sos_button.setStyleSheet("""
            QPushButton {
                background-color: #ff4444;
                color: white;
                border: 3px solid #cc0000;
                border-radius: 15px;
                font-weight: bold;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #cc0000;
                border-color: #aa0000;
            }
            QPushButton:pressed {
                background-color: #aa0000;
            }
            QPushButton:disabled {
                background-color: #666666;
                border-color: #444444;
                color: #aaaaaa;
            }
        """)
        self.sos_button.clicked.connect(self.on_sos_pressed)

        self.send_button = QPushButton("ðŸ“± SMS ðŸ“±")
        self.send_button.setFont(self.med_font)
        self.send_button.setMinimumHeight(80)
        self.send_button.setStyleSheet("""
            QPushButton {
                background-color: #ff6b35;
                color: white;
                border: 3px solid #e55a2b;
                border-radius: 15px;
                font-weight: bold;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #e55a2b;
                border-color: #cc4a1b;
            }
            QPushButton:pressed {
                background-color: #cc4a1b;
            }
            QPushButton:disabled {
                background-color: #666666;
                border-color: #444444;
                color: #aaaaaa;
            }
        """)
        self.send_button.clicked.connect(self.on_send_pressed)

        btn_row.addWidget(self.sos_button)
        btn_row.addWidget(self.send_button)

        # Contact selection row with safety styling
        contact_row = QHBoxLayout()
        contact_row.setSpacing(10)
        
        contact_label = QLabel("ðŸ“ž Contact:")
        contact_label.setFont(self.med_font)
        contact_label.setStyleSheet("color: #ff6b35; font-weight: bold;")
        
        self.contact_dropdown = QComboBox()
        self.contact_dropdown.setFont(self.med_font)
        self.contact_dropdown.addItems(sorted(self.contacts.keys()))
        self.contact_dropdown.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                color: white;
                border: 2px solid #ff6b35;
                border-radius: 8px;
                padding: 5px;
                font-weight: bold;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid #ff6b35;
                margin-right: 5px;
            }
            QComboBox QAbstractItemView {
                background-color: #2a2a2a;
                color: white;
                border: 2px solid #ff6b35;
                selection-background-color: #ff6b35;
            }
        """)
        
        self.contact_label = QLabel(self.contacts.get(self.contact_dropdown.currentText(), self.alert_phone))
        self.contact_label.setFont(self.small_font)
        self.contact_label.setAlignment(Qt.AlignLeft)
        self.contact_label.setStyleSheet("""
            QLabel {
                color: #cccccc;
                background-color: #333333;
                border-radius: 5px;
                padding: 5px;
                border: 1px solid #555555;
            }
        """)
        
        self.contact_dropdown.currentIndexChanged.connect(self._on_contact_changed)
        contact_row.addWidget(contact_label)
        contact_row.addWidget(self.contact_dropdown)
        contact_row.addWidget(self.contact_label)

        self.result_label = QLabel("")
        self.result_label.setFont(self.small_font)
        self.result_label.setAlignment(Qt.AlignCenter)
        self.result_label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                background-color: #2a2a2a;
                border-radius: 8px;
                padding: 8px;
                border: 2px solid #ff6b35;
                font-weight: bold;
            }
        """)

        v = QVBoxLayout()
        v.addLayout(top_bar)
        v.addWidget(self.ppm_label)
        v.addWidget(self.last_update_label)
        v.addWidget(self.status_label)
        v.addWidget(self.firebase_status_label)
        v.addWidget(self.signal_bar)
        v.addWidget(self.busy_bar)
        v.addLayout(btn_row)
        v.addLayout(contact_row)
        v.addWidget(self.result_label)
        self.setLayout(v)

        # signals
        self.signals.ppm_update.connect(self.update_ppm)
        self.signals.modem_status.connect(self.update_modem_status)
        self.signals.sms_result.connect(self.on_sms_result)
        self.signals.gsm_signal.connect(self.on_gsm_signal)
        self.signals.firebase_status.connect(self.update_firebase_status)

        self.ze03_parser = ZE03Parser()
        self.reader_thread = threading.Thread(target=self.ze03_worker, daemon=True)
        self.reader_thread.start()

        # Initialize modem in background
        threading.Thread(target=self.modem_init_worker, daemon=True).start()

        # Initialize Firebase status
        if self.firebase_uploader.initialized:
            self.signals.firebase_status.emit("ðŸ“¡ Firebase: âœ… Connected")
        else:
            self.signals.firebase_status.emit("ðŸ“¡ Firebase: âŒ Not Available")

        self.timer = QTimer()
        self.timer.setInterval(5000)
        self.timer.timeout.connect(self.periodic_tasks)
        self.timer.start()

        self._busy = False

    # slots
    def _on_contact_changed(self):
        name = self.contact_dropdown.currentText()
        self.alert_phone = self.contacts.get(name, ALERT_PHONE)
        self.contact_label.setText(self.alert_phone)
    def modem_init_worker(self):
        self.signals.modem_status.emit("Modem: Initializing...")
        ok, msg = self.modem_ctrl.initialize_for_sms()
        if ok:
            # Pre-initialize for ultra-fast SMS
            fast_ok, fast_msg = self.modem_ctrl.pre_initialize_for_fast_sms()
            rssi = self.modem_ctrl.get_signal_quality()
            self.signals.gsm_signal.emit(rssi)
            if fast_ok:
                self.signals.modem_status.emit("Modem: Online (Fast SMS Ready)")
            else:
                self.signals.modem_status.emit(f"Modem: Online (Fast SMS: {fast_msg})")
        else:
            self.signals.modem_status.emit(f"Modem: Init failed - {msg}")
    # Enhanced on-screen keyboard dialog for SMS text with safety styling
    def open_sms_keyboard(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("ðŸ“± Type SMS Message")
        dialog.setFixedSize(500, 400)
        dialog.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                color: white;
            }
        """)
        
        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)

        # Title
        title_label = QLabel("ðŸ“± Type Your Message")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("""
            QLabel {
                color: #ff6b35;
                font-size: 18px;
                font-weight: bold;
                padding: 10px;
                background-color: #2a2a2a;
                border: 2px solid #ff6b35;
                border-radius: 8px;
            }
        """)
        layout.addWidget(title_label)

        # Input field
        input_line = QLineEdit()
        input_line.setFont(self.med_font)
        input_line.setPlaceholderText("Type your message here...")
        input_line.setReadOnly(True)
        input_line.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a;
                color: white;
                border: 2px solid #ff6b35;
                border-radius: 8px;
                padding: 10px;
                font-size: 14px;
            }
        """)
        layout.addWidget(input_line)

        def append_text(t):
            input_line.setText(input_line.text() + t)

        def backspace():
            txt = input_line.text()
            if txt:
                input_line.setText(txt[:-1])

        # Keyboard grid
        grid_rows = [
            list("1234567890"),
            list("qwertyuiop"),
            list("asdfghjkl"),
            list("zxcvbnm"),
        ]
        for row in grid_rows:
            h = QHBoxLayout()
            h.setSpacing(5)
            for ch in row:
                b = QPushButton(ch.upper())
                b.setMinimumHeight(40)
                b.setMinimumWidth(40)
                b.setStyleSheet("""
                    QPushButton {
                        background-color: #ff6b35;
                        color: white;
                        border: 2px solid #e55a2b;
                        border-radius: 8px;
                        font-weight: bold;
                        font-size: 14px;
                    }
                    QPushButton:hover {
                        background-color: #e55a2b;
                    }
                    QPushButton:pressed {
                        background-color: #cc4a1b;
                    }
                """)
                b.clicked.connect(lambda _, c=ch: append_text(c))
                h.addWidget(b)
            layout.addLayout(h)

        # Control buttons
        controls = QHBoxLayout()
        controls.setSpacing(10)
        for label, fn in [("SPACE", lambda: append_text(" ")), ("BACK", backspace), ("CLEAR", lambda: input_line.setText(""))]:
            b = QPushButton(label)
            b.setMinimumHeight(40)
            b.setStyleSheet("""
                QPushButton {
                    background-color: #2a2a2a;
                    color: white;
                    border: 2px solid #ff6b35;
                    border-radius: 8px;
                    font-weight: bold;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #ff6b35;
                }
            """)
            b.clicked.connect(fn)
            controls.addWidget(b)
        layout.addLayout(controls)

        # Dialog buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.setStyleSheet("""
            QPushButton {
                background-color: #ff6b35;
                color: white;
                border: 2px solid #e55a2b;
                border-radius: 8px;
                padding: 8px 16px;
                font-weight: bold;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #e55a2b;
            }
            QPushButton#qt_msgboxbuttonbox_button {
                background-color: #666666;
                border-color: #444444;
            }
            QPushButton#qt_msgboxbuttonbox_button:hover {
                background-color: #888888;
            }
        """)
        layout.addWidget(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        if dialog.exec_() == QDialog.Accepted:
            return input_line.text().strip()
        return None

    def update_ppm(self, ppm):
        self._last_ppm = ppm
        self.last_update_label.setText(f"Last update: {datetime.now().strftime('%H:%M:%S')}")
        self.ppm_label.setText(f"PPM: {ppm}")
        
        # Worker safety color scheme
        if ppm < PPM_WARN:
            color = "#00ff00"  # Green - Safe
            border_color = "#00cc00"
            bg_color = "#1a3d1a"
        elif ppm < PPM_DANGER:
            color = "#ffaa00"  # Orange - Warning
            border_color = "#ff8800"
            bg_color = "#3d2a1a"
        else:
            color = "#ff0000"  # Red - Danger
            border_color = "#cc0000"
            bg_color = "#3d1a1a"
            if not self._above_threshold:
                self._above_threshold = True
                self.result_label.setText("âš ï¸ AUTO SOS TRIGGERED - HIGH PPM DETECTED! âš ï¸")
                threading.Thread(target=self._send_sos_all_contacts_thread, daemon=True).start()
        
        if ppm < PPM_DANGER:
            self._above_threshold = False
            
        # Update PPM label styling with safety colors
        self.ppm_label.setStyleSheet(f"""
            QLabel {{
                color: {color};
                background-color: {bg_color};
                border: 3px solid {border_color};
                border-radius: 15px;
                padding: 20px;
                margin: 10px;
                font-weight: bold;
            }}
        """)
        
        # Upload to Firebase if enough time has passed
        current_time = time.time()
        if current_time - self._last_upload_time >= UPLOAD_INTERVAL:
            threading.Thread(target=self._upload_to_firebase, args=(ppm,), daemon=True).start()
            self._last_upload_time = current_time

    def update_modem_status(self, text):
        self.status_label.setText(text)

    def on_gsm_signal(self, val):
        if val is None:
            self.status_label.setText("Modem: Online | Signal: ?")
        else:
            self.signal_bar.setValue(val)
            self.status_label.setText(f"Modem: Online | Signal: {val}")

    def update_firebase_status(self, text):
        self.firebase_status_label.setText(text)

    def _upload_to_firebase(self, ppm_value):
        """Upload PPM data to Firebase in a separate thread."""
        if not self.firebase_uploader.initialized:
            self.signals.firebase_status.emit("ðŸ“¡ Firebase: Not Available")
            return
        
        try:
            # Use the new send_data_to_firestore method with the current PPM value
            success, message = self.firebase_uploader.send_data_to_firestore(ppm_value)
            if success:
                stats = self.firebase_uploader.get_stats()
                self.signals.firebase_status.emit(f"ðŸ“¡ Firebase: âœ… Uploaded ({stats['upload_count']})")
            else:
                self.signals.firebase_status.emit(f"ðŸ“¡ Firebase: âŒ Failed - {message[:30]}...")
        except Exception as e:
            self.signals.firebase_status.emit(f"ðŸ“¡ Firebase: âŒ Error - {str(e)[:30]}...")

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
            self.busy_bar.setVisible(busy)
            self.result_label.setText(text)
        QTimer.singleShot(0, _set)

    def on_sos_pressed(self):
        # Show confirmation dialog for SOS
        reply = QMessageBox.question(
            self, 
            "SOS Confirmation", 
            "ðŸš¨ EMERGENCY SOS ALERT ðŸš¨\n\nAre you sure you want to send an SOS message?\n\nThis will send an emergency alert to ALL contacts simultaneously!",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            threading.Thread(target=self._send_sos_all_contacts_thread, daemon=True).start()

    def on_send_pressed(self):
        # Show confirmation dialog for SMS
        reply = QMessageBox.question(
            self, 
            "SMS Confirmation", 
            "ðŸ“± Send SMS Message ðŸ“±\n\nAre you sure you want to send a custom SMS message?\n\nThis will send a message to the selected contact.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            number = self.alert_phone
            text = self.open_sms_keyboard()
            if not text:
                return
            threading.Thread(target=self._send_custom_thread, args=(number, text), daemon=True).start()

    def _send_sos_thread(self):
        # Show loading dialog
        self.loading_dialog = LoadingDialog(self, "ðŸš¨ Sending SOS Alert...")
        self.loading_dialog.show()
        
        # Disable buttons
        self.sos_button.setDisabled(True)
        self.send_button.setDisabled(True)
        
        try:
            number = self.alert_phone
            if not self.modem_ctrl.is_alive():
                self.signals.sms_result.emit(False, "Modem not responding to AT")
                return
            
            # Update loading message
            self.loading_dialog.update_message("ðŸš¨ Connecting to network...")
            
            ok, raw = self.modem_ctrl.send_sms_textmode(number, SOS_SMS_TEXT, timeout=20)
            self.signals.sms_result.emit(ok, raw)
        finally:
            # Close loading dialog and re-enable buttons
            if self.loading_dialog:
                self.loading_dialog.close()
                self.loading_dialog = None
            self.sos_button.setDisabled(False)
            self.send_button.setDisabled(False)

    def _send_sos_all_contacts_thread(self):
        """New lightning-fast SOS method that sends to ALL contacts in parallel."""
        # Show loading dialog with updated message for all contacts
        self.loading_dialog = LoadingDialog(self, "🚨 Sending SOS Alert to ALL Contacts...")
        self.loading_dialog.show()
        
        # Disable buttons
        self.sos_button.setDisabled(True)
        self.send_button.setDisabled(True)
        
        try:
            if not self.modem_ctrl.is_alive():
                self.signals.sms_result.emit(False, "Modem not responding to AT")
                return
            
            # Update loading message
            self.loading_dialog.update_message("🚨 Sending to ALL contacts in parallel...")
            
            # Send SOS to ALL contacts simultaneously using parallel processing
            sos_results = self.modem_ctrl.send_sms_to_all_contacts_parallel(
                self.contacts, 
                SOS_SMS_TEXT, 
                timeout=5  # Reduced timeout for speed
            )
            
            # Create summary message
            total = sos_results['total']
            successful = sos_results['successful']
            failed = sos_results['failed']
            
            if successful == total:
                summary = f"🚨 SOS sent to ALL {total} contacts successfully!"
                self.signals.sms_result.emit(True, summary)
            elif successful > 0:
                summary = f"🚨 SOS sent to {successful}/{total} contacts. {failed} failed."
                self.signals.sms_result.emit(True, summary)
            else:
                summary = f"🚨 SOS failed to send to ALL {total} contacts!"
                self.signals.sms_result.emit(False, summary)
            
            # Store detailed results for debugging
            print(f"SOS Results: {sos_results}")
            
        finally:
            # Close loading dialog and re-enable buttons
            if self.loading_dialog:
                self.loading_dialog.close()
                self.loading_dialog = None
            self.sos_button.setDisabled(False)
            self.send_button.setDisabled(False)

    def _send_custom_thread(self, number, text):
        # Show loading dialog
        self.loading_dialog = LoadingDialog(self, "ðŸ“± Sending SMS Message...")
        self.loading_dialog.show()
        
        # Disable buttons
        self.sos_button.setDisabled(True)
        self.send_button.setDisabled(True)
        
        try:
            if not self.modem_ctrl.is_alive():
                self.signals.sms_result.emit(False, "Modem not responding to AT")
                return
            
            # Update loading message
            self.loading_dialog.update_message("ðŸ“± Connecting to network...")
            
            ok, raw = self.modem_ctrl.send_sms_textmode(number, text, timeout=20)
            self.signals.sms_result.emit(ok, raw)
        finally:
            # Close loading dialog and re-enable buttons
            if self.loading_dialog:
                self.loading_dialog.close()
                self.loading_dialog = None
            self.sos_button.setDisabled(False)
            self.send_button.setDisabled(False)

    def on_sms_result(self, ok, raw):
        if ok:
            # Success message with safety styling
            msg = QMessageBox(self)
            msg.setWindowTitle("âœ… SMS Sent Successfully")
            msg.setText("ðŸ“± Message sent successfully!")
            msg.setInformativeText(f"Response: {(raw or '')[:200]}")
            msg.setIcon(QMessageBox.Information)
            msg.setStyleSheet("""
                QMessageBox {
                    background-color: #1a1a1a;
                    color: white;
                }
                QMessageBox QLabel {
                    color: white;
                }
                QPushButton {
                    background-color: #ff6b35;
                    color: white;
                    border: 2px solid #e55a2b;
                    border-radius: 8px;
                    padding: 8px 16px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #e55a2b;
                }
            """)
            msg.exec_()
            self.result_label.setText("âœ… Last SMS: Sent Successfully")
            self.result_label.setStyleSheet("""
                QLabel {
                    color: #00ff00;
                    background-color: #1a3d1a;
                    border-radius: 8px;
                    padding: 8px;
                    border: 2px solid #00cc00;
                    font-weight: bold;
                }
            """)
        else:
            # Error message with safety styling
            msg = QMessageBox(self)
            msg.setWindowTitle("âŒ SMS Failed")
            msg.setText("ðŸ“± Failed to send message!")
            msg.setInformativeText(f"Error: {(raw or '')[:200]}")
            msg.setIcon(QMessageBox.Warning)
            msg.setStyleSheet("""
                QMessageBox {
                    background-color: #1a1a1a;
                    color: white;
                }
                QMessageBox QLabel {
                    color: white;
                }
                QPushButton {
                    background-color: #ff4444;
                    color: white;
                    border: 2px solid #cc0000;
                    border-radius: 8px;
                    padding: 8px 16px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #cc0000;
                }
            """)
            msg.exec_()
            self.result_label.setText("âŒ Last SMS: Failed")
            self.result_label.setStyleSheet("""
                QLabel {
                    color: #ff0000;
                    background-color: #3d1a1a;
                    border-radius: 8px;
                    padding: 8px;
                    border: 2px solid #cc0000;
                    font-weight: bold;
                }
            """)

    # Removed manage IDs and location handlers

# -----------------------------
# Main
# -----------------------------
def main():
    ze03_queue = queue.Queue()
    ze03_reader = SerialReaderThread(ZE03_SERIAL, ZE03_BAUD, ze03_queue, name="ZE03Reader")
    ze03_reader.start()

    modem_port = MODEM_SERIAL
    modem = ModemController(modem_port, MODEM_BAUD, timeout=2)

    app = QApplication(sys.argv)
    font = QFont()
    font.setPointSize(10)
    app.setFont(font)

    window = MinerMonitorApp(ze03_queue, modem)
    window.showFullScreen()
    try:
        sys.exit(app.exec_())
    finally:
        ze03_reader.stop()

if __name__ == "__main__":
    main()
