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
    print("⚠️ Firebase Admin SDK not installed. PPM upload functionality will be disabled.")

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

SOS_SMS_TEXT = "SOS: Dangerous gas levels detected!"
PPM_WARN = 40
PPM_DANGER = 100

APP_TITLE = "Miner Safety Monitor"
WINDOW_WIDTH = 480
WINDOW_HEIGHT = 320

# Single alert destination (edit as fallback)
ALERT_PHONE = "+911234567890"

# Contact list for dropdown selection
CONTACTS = {
    "sameer": "+919825186687",
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
  "private_key_id": "90f1efbb3e10ab661699642a5bd176c308861ebd",
  "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCw+OI3gAxqXs9Q\nLJpvAprY1iS7dHr6v/G0AEzRlcWNyKJuF2gho8ZRGN+BYmJZRvm3DRzqyXOoS6X/\nIuZMS/xTXzVNKPtGHdS/KE5sdlE+zvBsqqsrQXbbvyglA4N+zTsOrpDgDx0Q7+A+\nWAcwdYBufSQsNLsJ+CCCM/1k+FPTpVvo4EfsB0yhD0pROpom9w3k28qqbgC8eS/x\np6LPaJmoIyzvo8d0XdY89ViSgVt94uu5dLTl0z8ULzB4YxBoFYLfpaHlBNzNGpnz\nRWk7UXAjEbuqeRlbGrbvIQj1AAPB7he+77ibOefXJIC1+IR7lnqOaU99uqHaHa5G\n3fcmcIV/AgMBAAECggEAFygh9bAwL7UDPJLxjEgTef8fZFX8B5aZKnwFkUEfTgus\nUWqHqiszdoYiLNxyUQtL/qtdFs3Qb/uiF236I46n0EL7hwKvSn/5yB+ej2u1+tl6\nNUXpyumwg1WSi7FXgf6Z1TR7aY4guAgjWBUNr8YYTZzbYFtwBABvRIpIBG/IDD/1\neDkxNgkRgErmNcAog3GxpFa+EbbYyldd/W1pyeNfBrfMhw8BMwuW+gtN5yRIgczd\nkqdOA/Et7OkG1iMLCCezv3nJx0s9TNj78vCINXajeDP3j1AXD7VeNdG9r/x3Sww0\n5eHdVf2IWKHdQljsbatf+hDJ8IN1R43RGRHFDI+MtQKBgQDrWGjs1IdOGdIHehDI\nZEhaHVcu23coxzMaspsQn+1nNmbnzJh/qBJK+uY95R0BW3N8JhCbvwe+DpzwZUTX\n/4Cu1rzO00B4Zfe/oTrbfj/nCfe3lp1rafLdr6oMRQJ1pDoi7hKRTu6/H8uZxCwx\noh15o2XfePSo/R5SUKZq6q753QKBgQDAgPuehZKbLvBJUGIg0l0c45UxxhIZSN72\nbgKMkG/1y9mygXdtpkTyJ9NAZcU0O/pX3089whyShw7RPhB/gt/Zt2Vr0nbkcAYQ\n8BiFK8fvrQmaqPtTrJJZjF3C8is4mmlmvsfFyglDuk+yJOKdfiy54sQmcCuzXcc7\nZWgRyJjdCwKBgEOWN0PUYSsvxR56krlJ+3FNvczqIBVo56dCJcAnfaFHgVQOcLkw\nhlhcJ6Uc2DCcl9TOhbSEru+I+M8c9iFl8gnEB6MKDhjFh9nTrrh8UFPEjAyAR6Mi\nYSoDGb2+T8+DI2MGpfRvC6d9tRXqvZpfaUGWiFoePX0OfBe9q51G2otNAoGAIVj2\nvcJT4FAkTf7/0MHAYZXHLaUrU3f9L+FkzabjzkevAa5N2w/Xl79waBJ5NBBD0N8d\nYgxzWKrO1U6UGxK35oZPqnr+H5qMYnjFNqSb8RgftswZJaiafarEP1YmSJrvMV5R\nSyExs6rdzXV4UGIgK19uLV53I45WSiLKAXKnkHsCgYEAt1eKl1q18F2knTe7Jape\nwK9VVLm1FPOe4bJNaBGyLjBDL7WECjOZAcQgRsFFyqa6fQ/FzEJsvihVmtwWDR6t\n08ftHRqkeVLhcoN4m+h7cXtRMMaqVOFk96pepeqC04Lmem90I5j+LRKblCEe5cN6\nPLxOHmFS4JHItXVr2PPu6TY=\n-----END PRIVATE KEY-----\n",
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
LOCATION_LAT = 40.7160
LOCATION_LNG = -74.0040

# Upload interval in seconds (upload every 0.1 seconds for real-time updates)
UPLOAD_INTERVAL = 0.1

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

    def wait_for_registration(self, max_wait_seconds=15):
        deadline = time.time() + max_wait_seconds
        while time.time() < deadline:
            try:
                # Try LTE, PS and CS registration queries with faster checks
                for cmd in ("AT+CEREG?", "AT+CGREG?", "AT+CREG?"):
                    resp = self.send_at(cmd, wait_for=b"OK", timeout=1)  # Reduced timeout
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
            time.sleep(0.5)  # Reduced from 1.0
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

            if not self.wait_for_registration(max_wait_seconds=20):
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

    def send_sms_textmode(self, number, text, timeout=2):
        with self.lock:
            ser = self._open()
            try:
                # Lightning-fast SMS sending with minimal delays
                ser.write(b"ATE0\r")
                time.sleep(0.01)  # Ultra-reduced
                _ = ser.read(64)
                ser.write(b"AT+CMGF=1\r")
                time.sleep(0.02)   # Ultra-reduced
                _ = ser.read(128)
                ser.write(b"AT+CSCS=\"GSM\"\r")
                time.sleep(0.02)   # Ultra-reduced
                _ = ser.read(64)

                cmd = f'AT+CMGS="{number}"\r'.encode()
                ser.write(cmd)

                # wait for '>' prompt with ultra-minimal timeout
                deadline = time.time() + 1  # Ultra-reduced
                buf = bytearray()
                while time.time() < deadline:
                    chunk = ser.read(64)
                    if chunk:
                        buf.extend(chunk)
                        if b">" in buf:
                            break
                    else:
                        time.sleep(0.005)  # Ultra-reduced

                ser.write(text.encode() + b"\x1A")

                # wait for result with ultra-minimal timeout
                resp = bytearray()
                deadline = time.time() + timeout
                while time.time() < deadline:
                    chunk = ser.read(128)
                    if chunk:
                        resp.extend(chunk)
                        if b"+CMGS" in resp or b"OK" in resp or b"ERROR" in resp or b"+CMS ERROR" in resp:
                            break
                    else:
                        time.sleep(0.005)  # Ultra-reduced

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

    def send_sms_to_all_contacts(self, text, timeout=2):
        """Send SMS to all contacts in parallel for maximum speed."""
        import concurrent.futures
        
        all_contacts = list(CONTACTS.values()) + [ALERT_PHONE]
        # Remove duplicates while preserving order
        unique_contacts = list(dict.fromkeys(all_contacts))
        
        results = []
        
        def send_to_contact(phone_number):
            try:
                return self.send_sms_textmode(phone_number, text, timeout)
            except Exception as e:
                return False, str(e)
        
        # Use ThreadPoolExecutor for parallel SMS sending
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(unique_contacts), 5)) as executor:
            future_to_phone = {executor.submit(send_to_contact, phone): phone for phone in unique_contacts}
            
            for future in concurrent.futures.as_completed(future_to_phone):
                phone = future_to_phone[future]
                try:
                    success, response = future.result()
                    results.append((phone, success, response))
                except Exception as e:
                    results.append((phone, False, str(e)))
        
        return results

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
            
            # Initialize device document with static data once
            device_ref = self.db.collection("devices").document(DEVICE_ID)
            device_ref.set({
                "id": DEVICE_ID,
                "name": DEVICE_NAME,
                "location": {
                    "name": LOCATION_NAME,
                    "lat": LOCATION_LAT,
                    "lng": LOCATION_LNG,
                },
                "battery": 100,
                "deviceType": "Miner Safety Monitor",
                "sensorType": "ZE03-CO"
            }, merge=True)
            
            print("✅ Firebase initialized successfully")
        except Exception as e:
            print(f"❌ Firebase initialization failed: {e}")
            self.initialized = False
    
    def determine_status(self, co_level):
        """Determines status based on CO level."""
        if co_level > PPM_DANGER:
            return "Critical"
        elif co_level > PPM_WARN:
            return "Warning"
        else:
            return "Normal"
    
    def upload_ppm_data(self, ppm_value):
        """Upload PPM data to Firebase with ultra-optimized payload for real-time updates."""
        if not self.initialized or not self.db:
            return False, "Firebase not initialized"
        
        try:
            status = self.determine_status(ppm_value)
            
            # Ultra-optimized payload - minimal data for maximum speed
            payload = {
                "coLevel": ppm_value,
                "status": status,
                "timestamp": firestore.SERVER_TIMESTAMP
            }
            
            # Use update with minimal data for fastest operations
            device_ref = self.db.collection("devices").document(DEVICE_ID)
            device_ref.update(payload)
            
            self.upload_count += 1
            self.last_upload_time = time.time()
            return True, f"Real-time upload: PPM {ppm_value}, Status: {status}"
            
        except Exception as e:
            self.failed_uploads += 1
            return False, f"Upload failed: {str(e)}"
    
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
    bulk_sms_result = pyqtSignal(list)  # For bulk SMS results
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
        
        self.title_label = QLabel("⚠️ MINER SAFETY MONITOR ⚠️")
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
        
        close_btn = QPushButton("✕")
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
        self.firebase_status_label = QLabel("📡 Firebase: --")
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

        # Single emergency button with enhanced safety styling
        btn_row = QHBoxLayout()
        btn_row.setSpacing(15)
        
        self.emergency_button = QPushButton("🚨 EMERGENCY ALERT 🚨")
        self.emergency_button.setFont(self.med_font)
        self.emergency_button.setMinimumHeight(80)
        self.emergency_button.setStyleSheet("""
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
        self.emergency_button.clicked.connect(self.on_emergency_pressed)

        btn_row.addWidget(self.emergency_button)

        # Emergency contact display (simplified)
        contact_row = QHBoxLayout()
        contact_row.setSpacing(10)
        
        contact_label = QLabel("📞 Emergency Contact:")
        contact_label.setFont(self.med_font)
        contact_label.setStyleSheet("color: #ff6b35; font-weight: bold;")
        
        self.contact_label = QLabel(self.alert_phone)
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
        
        contact_row.addWidget(contact_label)
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
        self.signals.bulk_sms_result.connect(self.on_bulk_sms_result)
        self.signals.gsm_signal.connect(self.on_gsm_signal)
        self.signals.firebase_status.connect(self.update_firebase_status)

        self.ze03_parser = ZE03Parser()
        self.reader_thread = threading.Thread(target=self.ze03_worker, daemon=True)
        self.reader_thread.start()

        # Initialize modem in background
        threading.Thread(target=self.modem_init_worker, daemon=True).start()

        # Initialize Firebase status
        if self.firebase_uploader.initialized:
            self.signals.firebase_status.emit("📡 Firebase: ✅ Connected")
        else:
            self.signals.firebase_status.emit("📡 Firebase: ❌ Not Available")

        self.timer = QTimer()
        self.timer.setInterval(5000)
        self.timer.timeout.connect(self.periodic_tasks)
        self.timer.start()

        self._busy = False

    # slots
    def modem_init_worker(self):
        self.signals.modem_status.emit("Modem: Initializing...")
        ok, msg = self.modem_ctrl.initialize_for_sms()
        if ok:
            rssi = self.modem_ctrl.get_signal_quality()
            self.signals.gsm_signal.emit(rssi)
            self.signals.modem_status.emit("Modem: Online")
        else:
            self.signals.modem_status.emit(f"Modem: Init failed - {msg}")

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
                self.result_label.setText("⚠️ AUTO SOS TRIGGERED - HIGH PPM DETECTED! ⚠️")
                threading.Thread(target=self._send_emergency_thread, daemon=True).start()
        
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
            self.signals.firebase_status.emit("📡 Firebase: Not Available")
            return
        
        try:
            success, message = self.firebase_uploader.upload_ppm_data(ppm_value)
            if success:
                stats = self.firebase_uploader.get_stats()
                self.signals.firebase_status.emit(f"📡 Firebase: ✅ Uploaded ({stats['upload_count']})")
            else:
                self.signals.firebase_status.emit(f"📡 Firebase: ❌ Failed - {message[:30]}...")
        except Exception as e:
            self.signals.firebase_status.emit(f"📡 Firebase: ❌ Error - {str(e)[:30]}...")

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
            self.emergency_button.setDisabled(busy)
            self.busy_bar.setVisible(busy)
            self.result_label.setText(text)
        QTimer.singleShot(0, _set)

    def on_emergency_pressed(self):
        # Direct emergency alert - no confirmation needed for speed
        threading.Thread(target=self._send_emergency_thread, daemon=True).start()

    def _send_emergency_thread(self):
        # Show loading dialog
        self.loading_dialog = LoadingDialog(self, "🚨 Sending Emergency Alert to ALL Contacts...")
        self.loading_dialog.show()
        
        # Disable button
        self.emergency_button.setDisabled(True)
        
        try:
            if not self.modem_ctrl.is_alive():
                self.signals.sms_result.emit(False, "Modem not responding to AT")
                return
            
            # Update loading message
            self.loading_dialog.update_message("🚨 Sending to all contacts in parallel...")
            
            # Send to all contacts in parallel for maximum speed
            results = self.modem_ctrl.send_sms_to_all_contacts(SOS_SMS_TEXT, timeout=2)
            
            # Emit bulk results for detailed feedback
            self.signals.bulk_sms_result.emit(results)
            
            # Count successful sends
            successful = sum(1 for _, success, _ in results if success)
            total = len(results)
            
            if successful > 0:
                self.signals.sms_result.emit(True, f"🚨 EMERGENCY SENT to {successful}/{total} contacts! 🚨")
            else:
                self.signals.sms_result.emit(False, f"❌ Failed to send to all {total} contacts")
                
        finally:
            # Close loading dialog and re-enable button
            if self.loading_dialog:
                self.loading_dialog.close()
                self.loading_dialog = None
            self.emergency_button.setDisabled(False)

    def on_sms_result(self, ok, raw):
        if ok:
            # Success message with safety styling
            msg = QMessageBox(self)
            msg.setWindowTitle("✅ SMS Sent Successfully")
            msg.setText("📱 Message sent successfully!")
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
            self.result_label.setText("✅ Last SMS: Sent Successfully")
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
            msg.setWindowTitle("❌ SMS Failed")
            msg.setText("📱 Failed to send message!")
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
            self.result_label.setText("❌ Last SMS: Failed")
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

    def on_bulk_sms_result(self, results):
        """Handle bulk SMS results for detailed feedback."""
        successful_contacts = []
        failed_contacts = []
        
        for phone, success, response in results:
            if success:
                successful_contacts.append(phone)
            else:
                failed_contacts.append((phone, response))
        
        # Log detailed results
        print(f"🚨 BULK SMS RESULTS:")
        print(f"✅ Successful: {len(successful_contacts)} contacts")
        for phone in successful_contacts:
            print(f"   ✅ {phone}")
        
        if failed_contacts:
            print(f"❌ Failed: {len(failed_contacts)} contacts")
            for phone, error in failed_contacts:
                print(f"   ❌ {phone}: {error}")

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
