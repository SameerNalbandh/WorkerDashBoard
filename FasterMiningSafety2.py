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
- Loud speaker alarm when PPM > 300 (siren sound)
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
import concurrent.futures

import serial
from serial import SerialException

# Sound alarm imports
import numpy as np
import pygame

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
    QMessageBox, QProgressBar, QDialog, QDialogButtonBox, QSizePolicy, QFrame, QSpacerItem
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

# Contact list for SOS emergency broadcasting
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

def load_firebase_config():
    """Tries to load Firebase configuration from the hardcoded dict first."""
    if FIREBASE_SERVICE_ACCOUNT_INFO and isinstance(FIREBASE_SERVICE_ACCOUNT_INFO, dict):
        print("📁 Using hardcoded Firebase configuration.")
        return FIREBASE_SERVICE_ACCOUNT_INFO
    
    print("⚠️ Hardcoded Firebase config is invalid or missing.")
    return None

# Device configuration for Firebase
DEVICE_ID = "SN-PI-001"
DEVICE_NAME = "Miner Safety Monitor - Main Room"
LOCATION_NAME = "Main Room"
LOCATION_LAT = 16.4963
LOCATION_LNG = 80.5006

# Upload interval in seconds
UPLOAD_INTERVAL = 30

# Sound alarm threshold
PPM_ALARM_THRESHOLD = 300


# -----------------------------
# Firebase Uploader (REVISED CLASS)
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
        """Initializes the Firebase connection with robust error handling."""
        try:
            print("🔄 Attempting to initialize Firebase...")
            
            # Use the flexible config loader
            firebase_config = load_firebase_config()
            if not firebase_config:
                print("❌ No valid Firebase configuration found. Cannot proceed.")
                self.initialized = False
                return

            # Avoid re-initializing if an app already exists
            if not firebase_admin._apps:
                print(f"🔑 Using project: {firebase_config.get('project_id')}")
                cred = credentials.Certificate(firebase_config)
                firebase_admin.initialize_app(cred)
                print("🚀 Firebase app initialized successfully.")
            else:
                print("⚠️ Firebase app already initialized. Using existing instance.")

            self.db = firestore.client()
            self.initialized = True
            print("✅ Firebase is ready.")
            
        except Exception as e:
            print("❌ Firebase initialization FAILED. See details below.")
            print(f"🔍 Error Type: {type(e).__name__}")
            print(f"🔍 Error Details: {e}")
            print("📋 Full Traceback:")
            traceback.print_exc()
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
        """Uploads PPM data to Firebase with historical tracking."""
        if not self.initialized or not self.db:
            return False, "Firebase not initialized"
        
        try:
            status = self.determine_status(ppm_value)
            
            new_reading = {
                "coLevel": ppm_value,
                "timestamp": firestore.SERVER_TIMESTAMP
            }
            
            update_payload = {
                "id": DEVICE_ID,
                "name": DEVICE_NAME,
                "location": {
                    "name": LOCATION_NAME,
                    "lat": LOCATION_LAT,
                    "lng": LOCATION_LNG,
                },
                "status": status,
                "coLevel": ppm_value,
                "timestamp": firestore.SERVER_TIMESTAMP,
                "lastUpdate": datetime.utcnow().isoformat() + "Z",
                "historicalData": firestore.ArrayUnion([new_reading])
            }
            
            device_ref = self.db.collection("devices").document(DEVICE_ID)
            device_ref.set(update_payload, merge=True)
            
            self.upload_count += 1
            self.last_upload_time = time.time()
            return True, f"Success! PPM: {ppm_value}, Status: {status}"
            
        except Exception as e:
            self.failed_uploads += 1
            error_msg = f"❌ Upload Error: {str(e)}"
            print(error_msg)
            return False, error_msg

    def test_connection(self):
        """Actively tests the Firebase connection by writing and deleting a test doc."""
        if not self.initialized or not self.db:
            return False, "Not initialized"
        
        try:
            print("🧪 Testing Firebase write/delete permissions...")
            test_doc_ref = self.db.collection("connection_tests").document(DEVICE_ID)
            test_doc_ref.set({"timestamp": firestore.SERVER_TIMESTAMP, "status": "testing"})
            time.sleep(0.5) # Give firestore a moment
            test_doc_ref.delete()
            print("✅ Firebase connection test successful.")
            return True, "Connection OK"
        except Exception as e:
            print(f"❌ Firebase connection test FAILED: {e}")
            return False, f"Test failed: {e}"

# (Keep all your existing code between here...)

# -----------------------------
# GUI App (WITH SMALL MODIFICATION)
# -----------------------------
class MinerMonitorApp(QWidget):
    def __init__(self, ze03_q, modem_ctrl, message_ids=None):
        super().__init__()
        # ... (all your existing __init__ code here) ...
        # ... from self.ze03_q = ze03_q down to the modem_init_worker thread ...

        # Initialize Firebase status
        if self.firebase_uploader.initialized:
            self.signals.firebase_status.emit("📡 Firebase: ✅ Initialized")
            # Test connection after initialization
            threading.Thread(target=self._test_firebase_connection, daemon=True).start()
        else:
            self.signals.firebase_status.emit("📡 Firebase: ❌ Init Failed")

        # ... (the rest of your __init__ code) ...

    # ADD THIS NEW HELPER METHOD TO YOUR MinerMonitorApp CLASS
    def _test_firebase_connection(self):
        """Tests the Firebase connection in a background thread."""
        success, message = self.firebase_uploader.test_connection()
        if success:
            self.signals.firebase_status.emit("📡 Firebase: ✅ Connection OK")
        else:
            self.signals.firebase_status.emit(f"📡 Firebase: ⚠️ Test Failed")


    # REPLACE YOUR EXISTING _upload_to_firebase METHOD WITH THIS ONE
    def _upload_to_firebase(self, ppm_value):
        """Uploads PPM data to Firebase in a separate thread with retry logic."""
        if not self.firebase_uploader.initialized:
            self.signals.firebase_status.emit("📡 Firebase: Not Available")
            return
        
        max_retries = 3
        for attempt in range(max_retries):
            success, message = self.firebase_uploader.upload_ppm_data(ppm_value)
            if success:
                stats = self.firebase_uploader.get_stats()
                self.signals.firebase_status.emit(f"📡 Firebase: ✅ Uploaded ({stats['upload_count']})")
                return  # Success, so we exit the function
            else:
                # If failed, emit status and prepare for retry
                self.signals.firebase_status.emit(f"📡 Firebase: Retry {attempt + 1}/{max_retries}")
                if attempt < max_retries - 1:
                    print(f"Upload failed. Retrying in 5 seconds... ({message})")
                    time.sleep(5)
                else:
                    print(f"Upload failed after {max_retries} attempts.")
                    self.signals.firebase_status.emit(f"📡 Firebase: ❌ Upload Failed")

    # (The rest of your MinerMonitorApp class and the main() function remain the same)
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
        if self._sos_in_progress:
            return
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
            self.busy_bar.setVisible(busy)
            self.result_label.setText(text)
        QTimer.singleShot(0, _set)

    def on_sos_pressed(self):
        # Show confirmation dialog for SOS
        reply = QMessageBox.question(
            self, 
            "SOS Confirmation", 
            "🚨 EMERGENCY SOS ALERT 🚨\n\nAre you sure you want to send an SOS message?\n\nThis will send an emergency alert to the selected contact.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            threading.Thread(target=self._send_sos_thread, daemon=True).start()


    def _send_sos_thread(self):
        # BULK SOS - single connection, accurate status, fast throughput
        self._sos_in_progress = True
        self.sos_button.setDisabled(True)
        self.signals.modem_status.emit("Modem: Sending SOS...")
        self.result_label.setText("🚨 Sending SOS to all contacts...")
        
        try:
            if not self.modem_ctrl.is_alive():
                self.signals.sms_result.emit(False, "Modem not responding to AT")
                return

            # Unique ordered list of numbers (contacts + fallback)
            all_numbers = list(dict.fromkeys(list(self.contacts.values()) + [self.alert_phone]))
            
            success_count, total_count, errors = self.modem_ctrl.send_bulk_sms_textmode(
                all_numbers, SOS_SMS_TEXT, per_number_timeout=3
            )

            # Update progress
            self.result_label.setText(f"🚨 SOS progress: {success_count}/{total_count} sent")

            if success_count == total_count:
                self.signals.sms_result.emit(True, f"SOS sent to all {total_count} contacts")
            elif success_count > 0:
                self.signals.sms_result.emit(True, f"SOS sent to {success_count}/{total_count}; failures: {len(errors)}")
            else:
                self.signals.sms_result.emit(False, "SOS failed for all contacts")
        except Exception as e:
            self.signals.sms_result.emit(False, f"SOS error: {str(e)[:100]}")
        finally:
            self.sos_button.setDisabled(False)
            # Restore modem status
            try:
                rssi = self.modem_ctrl.get_signal_quality()
                if rssi is None:
                    self.signals.modem_status.emit("Modem: Online | Signal: ?")
                else:
                    self.signals.gsm_signal.emit(rssi)
            except Exception:
                self.signals.modem_status.emit("Modem: Online")
            self._sos_in_progress = False

    def closeEvent(self, event):
        """Handle application close event"""
        # Stop any playing alarm
        if SOUND_AVAILABLE:
            try:
                pygame.mixer.stop()
                pygame.mixer.quit()
            except Exception:
                pass
        event.accept()

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
        # Cleanup sound system
        if SOUND_AVAILABLE:
            try:
                pygame.mixer.quit()
            except Exception:
                pass

if __name__ == "__main__":
    main()




