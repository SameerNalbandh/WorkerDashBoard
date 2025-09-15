 #!/usr/bin/env python3
"""
MinerDashboard_refactored_beautiful_ui.py

Refactored dashboard:
- ZE03-CO on UART reader (robust 9-byte frame parsing)
- Quectel EC200U modem fixed to /dev/ttyAMA5 for SMS & Calls
- SOS, Custom SMS, Call (accept detection -> call dialog + timer + hangup; decline -> immediate declined state)
- Virtual touchscreen keyboard for custom message input
- Removed any signal-strength / GPS UI/code
- Polished UI/UX with card layout, rounded buttons and clearer fonts

Notes:
- AT port fixed at /dev/ttyAMA5 as requested.
- Keep an eye on permissions for serial ports (run as root or add user to dialout).
"""

import os
os.environ["QT_QPA_PLATFORM"] = "xcb"

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
    QMessageBox, QComboBox, QLineEdit, QDialog, QGridLayout, QFrame, QSizePolicy
)
from PyQt5.QtGui import QFont

# -----------------------------
# CONFIG
# -----------------------------
ZE03_SERIAL = "/dev/ttyS0"  # sensor port; change if needed
ZE03_BAUD = 9600

MODEM_SERIAL = "/dev/ttyAMA5"  # fixed per your note
MODEM_BAUD = 115200

APP_TITLE = "Miner Safety Monitor"
WINDOW_WIDTH = 800
WINDOW_HEIGHT = 480

SOS_SMS_TEXT = "SOS: Dangerous gas levels detected!"
PPM_WARN = 40
PPM_DANGER = 50

SMS_MIN_INTERVAL = 8  # seconds between SMS sends
CALL_TIMEOUT = 35     # seconds to wait for CONNECT

DEFAULT_MESSAGE_IDS = {
    "sameer": "+919825186687",
    "ramsha": "+918179489703",
    "surya":  "+917974560541",
    "anupam": "+917905030839",
    "shanmukesh": "+919989278339",
    "kartika": "+919871390413"
}

# -----------------------------
# Signals
# -----------------------------
class AppSignals(QObject):
    ppm_update = pyqtSignal(int)
    modem_status = pyqtSignal(str)
    sms_result = pyqtSignal(bool, str)
    call_state = pyqtSignal(str, str)  # state, raw

# -----------------------------
# Serial Reader
# -----------------------------
class SerialReaderThread(threading.Thread):
    def __init__(self, device, baud, out_q, reconnect_delay=2):
        super().__init__(daemon=True)
        self.device = device
        self.baud = baud
        self.out_q = out_q
        self.reconnect_delay = reconnect_delay
        self._stop = threading.Event()
    def stop(self):
        self._stop.set()
    def run(self):
        ser = None
        while not self._stop.is_set():
            try:
                if ser is None:
                    ser = serial.Serial(self.device, self.baud, timeout=1)
                    try: ser.reset_input_buffer()
                    except Exception: pass
                b = ser.read(256)
                if b:
                    try: self.out_q.put(b, timeout=0.5)
                    except Exception: pass
            except SerialException as e:
                try:
                    self.out_q.put(b"__ZE03_SERIAL_ERROR__:" + str(e).encode(), timeout=0.5)
                except Exception:
                    pass
                try:
                    if ser: ser.close()
                except Exception:
                    pass
                ser = None
                time.sleep(self.reconnect_delay)
            except Exception as e:
                try:
                    self.out_q.put(b"__ZE03_EXCEPTION__:" + str(e).encode(), timeout=0.5)
                except Exception:
                    pass
                time.sleep(self.reconnect_delay)
        try:
            if ser: ser.close()
        except Exception:
            pass

# -----------------------------
# ModemController
# -----------------------------
class ModemController:
    def __init__(self, dev=MODEM_SERIAL, baud=MODEM_BAUD, timeout=2):
        self.dev = dev
        self.baud = baud
        self.timeout = timeout
        self.lock = threading.Lock()
        self._last_sms_ts = 0

    def _open(self):
        return serial.Serial(self.dev, self.baud, timeout=1)

    def is_alive(self):
        try:
            with self.lock:
                ser = self._open()
                try:
                    ser.write(b"AT\r"); ser.flush()
                    deadline = time.time() + 1.5
                    out = bytearray()
                    while time.time() < deadline:
                        chunk = ser.read(256)
                        if chunk:
                            out.extend(chunk)
                            if b"OK" in out: break
                        else:
                            time.sleep(0.02)
                    return b"OK" in out
                finally:
                    try: ser.close()
                    except Exception: pass
        except Exception:
            return False

    def send_sms_textmode(self, number, text, timeout=12):
        now = time.time()
        if now - self._last_sms_ts < SMS_MIN_INTERVAL:
            return False, f"Rate limit: wait {int(SMS_MIN_INTERVAL - (now - self._last_sms_ts))}s"
        with self.lock:
            try:
                ser = self._open()
            except Exception as e:
                return False, f"open_failed:{e}"
            try:
                ser.write(b"AT+CMGF=1\r"); ser.flush()
                time.sleep(0.08)
                _ = ser.read(ser.in_waiting or 1)
                ser.write(f'AT+CMGS="{number}"\r'.encode()); ser.flush()
                deadline = time.time() + 6
                buf = bytearray()
                saw = False
                while time.time() < deadline:
                    chunk = ser.read(512)
                    if chunk:
                        buf.extend(chunk)
                        if b'>' in buf:
                            saw = True; break
                        s = buf.decode(errors="ignore").upper()
                        if "ERROR" in s:
                            return False, s
                    else:
                        time.sleep(0.05)
                if not saw:
                    return False, buf.decode(errors="ignore")
                ser.write(text.encode() + b"\x1A"); ser.flush()
                resp = bytearray()
                deadline = time.time() + timeout
                while time.time() < deadline:
                    chunk = ser.read(512)
                    if chunk:
                        resp.extend(chunk)
                        s = resp.decode(errors="ignore").upper()
                        if "+CMGS" in s or "OK" in s or "ERROR" in s:
                            break
                    else:
                        time.sleep(0.05)
                s = resp.decode(errors="ignore")
                if "ERROR" in s and "+CMGS" not in s:
                    return False, s
                if "+CMGS" in s or "OK" in s:
                    self._last_sms_ts = time.time()
                    return True, s
                return False, s
            except Exception as e:
                return False, str(e)
            finally:
                try: ser.close()
                except Exception: pass

    def make_call_blocking(self, number, state_callback):
        """
        Improved call handling for EC200U:
        - DIALING -> immediately after ATD
        - FAILED  -> declined (NO CARRIER before CONNECT)
        - ACTIVE  -> call accepted
        - HANGUP  -> after connect, call ended
        - IDLE    -> cleanup
        """
        try:
            ser = serial.Serial(self.dev, self.baud, timeout=1)
        except Exception as e:
            state_callback("FAILED", f"open_failed:{e}")
            return

        try:
            ser.reset_input_buffer()
        except Exception:
            pass

        ser.write((f"ATD{number};\r").encode())
        ser.flush()
        state_callback("DIALING", "")
        start = time.time()
        connected = False

        while time.time() - start < CALL_TIMEOUT:
            line = ser.readline()
            if not line:
                time.sleep(0.1)
                continue
            s = line.decode(errors="ignore").strip().upper()
            if not s:
                continue
            # connected tokens
            if "CONNECT" in s or "VOICE" in s:
                connected = True
                state_callback("ACTIVE", s)
                break
            # declined/failure tokens before connect
            if any(tok in s for tok in ("NO CARRIER", "BUSY", "NO DIALTONE", "+CME ERROR", "ERROR")):
                if not connected:
                    state_callback("FAILED", s)
                    try: ser.close()
                    except Exception: pass
                    return

        if not connected:
            state_callback("FAILED", "TIMEOUT")
            try: ser.close()
            except Exception: pass
            return

        # connected: wait for hangup
        while True:
            line = ser.readline()
            if not line:
                time.sleep(0.2)
                continue
            s = line.decode(errors="ignore").strip().upper()
            if not s:
                continue
            if any(tok in s for tok in ("NO CARRIER", "BUSY", "+CME ERROR", "ERROR", "CLOSED")):
                state_callback("HANGUP", s)
                break

        state_callback("IDLE", "")
        try: ser.close()
        except Exception: pass

    def hangup(self):
        with self.lock:
            try:
                ser = serial.Serial(self.dev, self.baud, timeout=1)
            except Exception:
                return False
            try:
                ser.write(b"ATH\r"); ser.flush()
                time.sleep(0.1)
                ser.close()
                return True
            except Exception:
                try: ser.close()
                except Exception: pass
                return False

# -----------------------------
# Virtual Keyboard
# -----------------------------
class VirtualKeyboard(QWidget):
    def __init__(self, target_lineedit, parent=None):
        super().__init__(parent, flags=Qt.Window | Qt.WindowStaysOnTopHint)
        self.target = target_lineedit
        self.shift = False
        self.setWindowTitle("Keyboard")
        self.setStyleSheet("background:#121212;color:#fff;border-radius:8px;")
        self.setFixedHeight(260)
        grid = QGridLayout()
        rows = ["qwertyuiop", "asdfghjkl", "zxcvbnm"]
        r = 0
        for row in rows:
            c = 0
            for ch in row:
                btn = QPushButton(ch.upper() if self.shift else ch)
                btn.setFixedSize(48,48)
                btn.setStyleSheet("background:#1f1f1f;color:#fff;border-radius:10px;")
                btn.clicked.connect(lambda _, x=ch: self._press(x))
                grid.addWidget(btn, r, c)
                c += 1
            r += 1
        # numbers
        numrow = "1234567890"
        c = 0
        for ch in numrow:
            btn = QPushButton(ch)
            btn.setFixedSize(44,44)
            btn.setStyleSheet("background:#1f1f1f;color:#fff;border-radius:10px;")
            btn.clicked.connect(lambda _, x=ch: self._press(x))
            grid.addWidget(btn, r, c)
            c += 1
        r += 1
        self.shift_btn = QPushButton("Shift"); self.shift_btn.setFixedSize(90,48); self.shift_btn.clicked.connect(self._toggle_shift)
        self.space_btn = QPushButton("Space"); self.space_btn.setFixedSize(300,48); self.space_btn.clicked.connect(lambda: self._press(" "))
        self.back_btn = QPushButton("⌫"); self.back_btn.setFixedSize(90,48); self.back_btn.clicked.connect(self._back)
        self.enter_btn = QPushButton("Enter"); self.enter_btn.setFixedSize(90,48); self.enter_btn.clicked.connect(self._enter)
        grid.addWidget(self.shift_btn, r, 0, 1, 2)
        grid.addWidget(self.space_btn, r, 2, 1, 6)
        grid.addWidget(self.back_btn, r, 8, 1, 1)
        grid.addWidget(self.enter_btn, r, 9, 1, 1)
        self.setLayout(grid)
    def _press(self, ch):
        c = ch.upper() if self.shift else ch
        cur = self.target.text(); self.target.setText(cur + c)
    def _back(self):
        cur = self.target.text(); self.target.setText(cur[:-1])
    def _enter(self):
        self.hide(); self.target.clearFocus()
    def _toggle_shift(self):
        self.shift = not self.shift

# -----------------------------
# Loading & Call Dialogs
# -----------------------------
class LoadingDialog(QDialog):
    def __init__(self, title, msg, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setStyleSheet("background:#0f0f0f;color:#fff;")
        self.resize(420,140)
        v = QVBoxLayout()
        self.msg = QLabel(msg); self.msg.setAlignment(Qt.AlignCenter); self.msg.setWordWrap(True)
        self.ind = QLabel("⟳ Working..."); self.ind.setAlignment(Qt.AlignCenter)
        v.addWidget(self.msg); v.addWidget(self.ind)
        self.close_btn = QPushButton("Close"); self.close_btn.clicked.connect(self.accept); self.close_btn.setVisible(False)
        h = QHBoxLayout(); h.addStretch(); h.addWidget(self.close_btn); v.addLayout(h)
        self.setLayout(v)
    def set_message(self, m): self.msg.setText(m)
    def set_done(self, ok, extra=""):
        self.close_btn.setVisible(True)
        self.msg.setText(("Success: " if ok else "Failed: ") + (extra or ""))

class CallDialog(QDialog):
    def __init__(self, number, hangup_cb, close_cb, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"In call: {number}")
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setStyleSheet("background:#0f0f0f;color:#fff;")
        self.resize(420,220)
        v = QVBoxLayout()
        title = QLabel(f"In call: {number}"); title.setFont(QFont("Sans",14,QFont.Bold)); title.setAlignment(Qt.AlignCenter)
        self.timer_lbl = QLabel("00:00"); self.timer_lbl.setFont(QFont("Sans",36,QFont.Bold)); self.timer_lbl.setAlignment(Qt.AlignCenter)
        v.addWidget(title); v.addWidget(self.timer_lbl)
        h = QHBoxLayout()
        self.hang = QPushButton("Hang Up"); self.hang.setMinimumHeight(52); self.hang.clicked.connect(hangup_cb)
        self.hang.setStyleSheet("background:#c0392b;color:#fff;border-radius:10px;font-weight:bold;")
        self.close = QPushButton("Close App"); self.close.setMinimumHeight(52); self.close.clicked.connect(close_cb)
        h.addWidget(self.hang); h.addWidget(self.close)
        v.addLayout(h)
        self.setLayout(v)
        self._start = None
        self._timer = QTimer(); self._timer.timeout.connect(self._tick); self._timer.setInterval(1000)
    def start_timer(self): self._start = time.time(); self._timer.start()
    def stop_timer(self): self._timer.stop(); self._start = None; self.timer_lbl.setText("00:00")
    def _tick(self):
        if not self._start: return
        elapsed = int(time.time() - self._start)
        m, s = divmod(elapsed, 60)
        self.timer_lbl.setText(f"{m:02d}:{s:02d}")

# -----------------------------
# Main GUI App
# -----------------------------
class MinerMonitorApp(QWidget):
    def __init__(self, ze03_q, modem_ctrl, message_ids=None):
        super().__init__()
        self.ze03_q = ze03_q
        self.modem_ctrl = modem_ctrl
        self.signals = AppSignals()
        self.setWindowTitle(APP_TITLE)
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setStyleSheet("background-color: #0b0b0b; color: #fff;")

        self.message_ids = message_ids or DEFAULT_MESSAGE_IDS.copy()

        # fonts
        self.title_font = QFont("Sans Serif", 18, QFont.Bold)
        self.big_font = QFont("Sans Serif", 48, QFont.Bold)
        self.med_font = QFont("Sans Serif", 14)
        self.small_font = QFont("Sans Serif", 11)

        # top bar
        top = QHBoxLayout()
        title = QLabel("MINER SAFETY"); title.setFont(self.title_font); title.setAlignment(Qt.AlignLeft)
        title.setStyleSheet("color:#f5f5f5;padding:8px;")
        top.addWidget(title)
        top.addStretch()
        close_btn = QPushButton("⨉"); close_btn.setFixedSize(44,44); close_btn.clicked.connect(self._confirm_close)
        close_btn.setStyleSheet("background:#1f1f1f;color:#fff;border-radius:8px;font-weight:bold;")
        top.addWidget(close_btn)

        # main cards
        # left: PPM card
        ppm_card = QFrame(); ppm_card.setStyleSheet("background:#121212;border-radius:12px;padding:12px;")
        ppm_layout = QVBoxLayout()
        self.ppm_label = QLabel("---"); self.ppm_label.setFont(self.big_font); self.ppm_label.setAlignment(Qt.AlignCenter)
        self.ppm_label.setStyleSheet("color:#9ae6b4;")
        self.last_update_label = QLabel("Last: --"); self.last_update_label.setFont(self.small_font); self.last_update_label.setAlignment(Qt.AlignCenter)
        ppm_layout.addWidget(QLabel("CO (PPM)")); ppm_layout.addWidget(self.ppm_label); ppm_layout.addWidget(self.last_update_label)
        ppm_card.setLayout(ppm_layout)

        # right: actions card
        actions_card = QFrame(); actions_card.setStyleSheet("background:#121212;border-radius:12px;padding:12px;")
        actions_layout = QVBoxLayout()
        # big buttons row
        row = QHBoxLayout()
        self.sos_button = QPushButton("SOS"); self.sos_button.setFixedHeight(80); self.sos_button.setFont(self.med_font)
        self.sos_button.setStyleSheet("background:#e53e3e;color:#fff;border-radius:12px;font-weight:bold;")
        self.sos_button.clicked.connect(self.on_sos_pressed)
        self.send_button = QPushButton("Send Message"); self.send_button.setFixedHeight(80); self.send_button.setFont(self.med_font)
        self.send_button.setStyleSheet("background:#2b6cb0;color:#fff;border-radius:12px;font-weight:bold;")
        self.send_button.clicked.connect(self.on_send_pressed)
        self.call_button = QPushButton("Call"); self.call_button.setFixedHeight(80); self.call_button.setFont(self.med_font)
        self.call_button.setStyleSheet("background:#2f855a;color:#fff;border-radius:12px;font-weight:bold;")
        self.call_button.clicked.connect(self.on_call_pressed)
        row.addWidget(self.sos_button); row.addWidget(self.send_button); row.addWidget(self.call_button)

        actions_layout.addLayout(row)
        # id + phone
        id_row = QHBoxLayout()
        self.id_dropdown = QComboBox(); self.id_dropdown.setFont(self.med_font); self.id_dropdown.addItems(sorted(self.message_ids.keys()))
        self.phone_display = QLabel(self.message_ids.get(self.id_dropdown.currentText(), "")); self.phone_display.setFont(self.small_font)
        self.id_dropdown.currentIndexChanged.connect(self._update_phone_display)
        id_row.addWidget(self.id_dropdown); id_row.addWidget(self.phone_display)
        actions_layout.addLayout(id_row)

        # message input
        self.message_input = QLineEdit(); self.message_input.setPlaceholderText("Custom message..."); self.message_input.setFont(self.small_font)
        self.message_input.setFixedHeight(44)
        self.message_input.setStyleSheet("background:#0b0b0b;border:1px solid #222;color:#fff;padding:8px;border-radius:8px;")
        self.keyboard = VirtualKeyboard(self.message_input, parent=self)
        self.message_input.mousePressEvent = self._show_keyboard
        actions_layout.addWidget(self.message_input)

        # result / status
        self.result_label = QLabel(""); self.result_label.setFont(self.small_font); self.result_label.setAlignment(Qt.AlignCenter)
        actions_layout.addWidget(self.result_label)

        actions_card.setLayout(actions_layout)

        # assemble main layout
        main_h = QHBoxLayout()
        main_h.addWidget(ppm_card, 2)
        main_h.addWidget(actions_card, 3)

        root = QVBoxLayout()
        root.addLayout(top)
        root.addLayout(main_h)
        self.setLayout(root)

        # signals
        self.signals.ppm_update.connect(self.update_ppm)
        self.signals.modem_status.connect(self.update_modem_status)
        self.signals.sms_result.connect(self.on_sms_result)
        self.signals.call_state.connect(self.on_call_state)

        # worker
        self.ze03_q = ze03_q
        self.ze03_parser_buf = bytearray()
        self._ze_thread = threading.Thread(target=self.ze03_worker, daemon=True)
        self._ze_thread.start()

        self.call_dialog = None
        self._current_call_number = None

        # periodic modem check
        self.timer = QTimer(); self.timer.setInterval(5000); self.timer.timeout.connect(self._check_modem_status); self.timer.start()
        self._op_lock = threading.Lock()

    # ---------------- ZE03 worker (robust parsing) ----------------
    def ze03_worker(self):
        buf = bytearray()
        while True:
            try:
                data = self.ze03_q.get()
                if isinstance(data, bytes):
                    # ignore error messages from reader; but print for debug
                    if data.startswith(b"__ZE03_SERIAL_ERROR__") or data.startswith(b"__ZE03_EXCEPTION__"):
                        try:
                            print("SerialReader:", data.decode(errors='ignore'))
                        except Exception:
                            pass
                        time.sleep(0.1)
                        continue

                    buf.extend(data)
                    while len(buf) >= 9:
                        if buf[0] != 0xFF:
                            buf.pop(0); continue
                        frame = buf[:9]
                        # remove only consumed bytes when frame is used; if invalid, advance by 1
                        checksum = (~sum(frame[1:8]) + 1) & 0xFF
                        if frame[1] == 0x86 and checksum == frame[8]:
                            ppm = (frame[2] << 8) | frame[3]
                            QTimer.singleShot(0, lambda p=ppm: self.signals.ppm_update.emit(p))
                            del buf[:9]
                        else:
                            # bad frame header or checksum -> advance
                            del buf[0]
                else:
                    time.sleep(0.01)
            except Exception as e:
                print("ZE03 worker error:", e)
                traceback.print_exc()
                time.sleep(1)

    def update_ppm(self, ppm):
        self.ppm_label.setText(str(ppm))
        self.last_update_label.setText(f"Last: {datetime.now().strftime('%H:%M:%S')}")
        if ppm < PPM_WARN:
            self.ppm_label.setStyleSheet("color:#9ae6b4;")
        elif ppm < PPM_DANGER:
            self.ppm_label.setStyleSheet("color:#f6e05e;")
        else:
            self.ppm_label.setStyleSheet("color:#feb2b2;")
            threading.Thread(target=self._auto_sos, daemon=True).start()

    # ---------------- Modem status ----------------
    def _check_modem_status(self):
        try:
            alive = self.modem_ctrl.is_alive()
        except Exception:
            alive = False
        self.signals.modem_status.emit("Modem: Online" if alive else "Modem: Offline")

    def update_modem_status(self, text):
        self.result_label.setText(text)

    # ---------------- SMS ----------------
    def on_sos_pressed(self):
        number = self.message_ids.get(self.id_dropdown.currentText())
        if not number:
            QMessageBox.warning(self, "No number", "Selected ID has no phone number.")
            return
        if QMessageBox.question(self, "Confirm", f"Send SOS to {number}?", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        threading.Thread(target=lambda: self._send_sms_bg(number, SOS_SMS_TEXT), daemon=True).start()

    def on_send_pressed(self):
        number = self.message_ids.get(self.id_dropdown.currentText())
        text = self.message_input.text().strip()
        if not number:
            QMessageBox.warning(self, "No number", "Selected ID has no phone number.")
            return
        if not text:
            QMessageBox.warning(self, "Empty message", "Please enter message.")
            return
        if QMessageBox.question(self, "Confirm", f"Send message to {number}?", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        threading.Thread(target=lambda: self._send_sms_bg(number, text), daemon=True).start()

    def _send_sms_bg(self, number, text):
        with self._op_lock:
            QTimer.singleShot(0, lambda: self.signals.modem_status.emit("Sending SMS..."))
            ok, raw = self.modem_ctrl.send_sms_textmode(number, text, timeout=12)
            self.signals.sms_result.emit(ok, (raw or ""))
            QTimer.singleShot(0, lambda: self.signals.modem_status.emit("Modem: Online" if ok else "Modem: Offline"))

    def _auto_sos(self):
        number = self.message_ids.get(self.id_dropdown.currentText())
        if not number: return
        ok, raw = self.modem_ctrl.send_sms_textmode(number, SOS_SMS_TEXT, timeout=12)
        QTimer.singleShot(0, lambda: self.result_label.setText("Auto SOS: Sent" if ok else "Auto SOS: Failed"))

    def on_sms_result(self, ok, raw):
        if ok:
            QMessageBox.information(self, "SMS Sent", "Message sent successfully.")
            self.result_label.setText("Last SMS: Sent")
        else:
            QMessageBox.warning(self, "SMS Failed", f"Failed to send message.\n\n{(raw or '')[:300]}")
            self.result_label.setText("Last SMS: Failed")

    # ---------------- Calls ----------------
    def on_call_pressed(self):
        number = self.message_ids.get(self.id_dropdown.currentText())
        if not number:
            QMessageBox.warning(self, "No number", "Selected ID has no phone number.")
            return
        if QMessageBox.question(self, "Confirm", f"Call {number}?", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        # store current dialed number to avoid race if user changes dropdown
        self._current_call_number = number
        # show dialing loading
        self.loading = LoadingDialog("Dialing", f"Dialing {number}...", parent=self)
        self.loading.show()
        # run blocking make_call in background thread, with state callback mapping to signals
        def state_cb(state, raw):
            self.signals.call_state.emit(state, raw)
        threading.Thread(target=lambda: self.modem_ctrl.make_call_blocking(number, state_cb), daemon=True).start()

    def on_call_state(self, state, raw):
        st = state.upper()
        if st == "DIALING":
            if hasattr(self, "loading") and self.loading:
                self.loading.set_message("Ringing...")
            self.result_label.setText("Call: Dialing...")
        elif st == "ACTIVE":
            if hasattr(self, "loading") and self.loading:
                try: self.loading.accept()
                except Exception: pass
            number = getattr(self, "_current_call_number", "") or self.message_ids.get(self.id_dropdown.currentText(), "")
            if self.call_dialog is None:
                self.call_dialog = CallDialog(number, hangup_cb=self._call_hangup, close_cb=self._confirm_close, parent=self)
            self.call_dialog.show(); self.call_dialog.start_timer()
            self.result_label.setText("Call: Connected")
            self.sos_button.setDisabled(True); self.send_button.setDisabled(True); self.call_button.setDisabled(True)
        elif st == "FAILED":
            if hasattr(self, "loading") and self.loading:
                self.loading.set_done(False, raw or "Call failed/declined")
                QTimer.singleShot(800, lambda: getattr(self, "loading", None).accept() if getattr(self, "loading", None) else None)
            else:
                QMessageBox.warning(self, "Call Failed", f"Call failed/declined: {raw}")
            self.result_label.setText("Call: Failed/Declined")
            self.sos_button.setDisabled(False); self.send_button.setDisabled(False); self.call_button.setDisabled(False)
            self._current_call_number = None
        elif st == "HANGUP":
            self._destroy_call_dialog()
            self.result_label.setText("Call: Ended")
            self.sos_button.setDisabled(False); self.send_button.setDisabled(False); self.call_button.setDisabled(False)
            self._current_call_number = None
        elif st == "IDLE":
            self._destroy_call_dialog()
            self.sos_button.setDisabled(False); self.send_button.setDisabled(False); self.call_button.setDisabled(False)
            self._current_call_number = None

    def _call_hangup(self):
        try:
            threading.Thread(target=lambda: self.modem_ctrl.hangup(), daemon=True).start()
        except Exception:
            pass
        QTimer.singleShot(600, self._destroy_call_dialog)

    def _destroy_call_dialog(self):
        if self.call_dialog:
            try:
                self.call_dialog.stop_timer()
                self.call_dialog.close()
            except Exception:
                pass
            self.call_dialog = None
            self.sos_button.setDisabled(False); self.send_button.setDisabled(False); self.call_button.setDisabled(False)

    # ---------------- misc ----------------
    def _update_phone_display(self): self.phone_display.setText(self.message_ids.get(self.id_dropdown.currentText(), ""))
    def _show_keyboard(self, ev):
        self.keyboard.move(self.x() + 20, self.y() + self.height() - self.keyboard.height() - 20)
        self.keyboard.show()
        return QLineEdit.mousePressEvent(self.message_input, ev)
    def _confirm_close(self):
        r = QMessageBox.question(self, "Exit", "Exit application?", QMessageBox.Yes | QMessageBox.No)
        if r == QMessageBox.Yes:
            try: QApplication.quit()
            except Exception: os._exit(0)

# -----------------------------
# Main
# -----------------------------
def main():
    ze03_q = queue.Queue()
    reader = SerialReaderThread(ZE03_SERIAL, ZE03_BAUD, ze03_q); reader.start()
    modem = ModemController(MODEM_SERIAL, MODEM_BAUD)

    app = QApplication(sys.argv)
    font = QFont(); font.setPointSize(10); app.setFont(font)

    window = MinerMonitorApp(ze03_q, modem, message_ids=DEFAULT_MESSAGE_IDS.copy())
    window.showFullScreen()
    try:
        sys.exit(app.exec_())
    finally:
        try: reader.stop()
        except Exception: pass

if __name__ == "__main__":
    main()
