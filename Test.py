import serial, time, json, jwt, datetime, sys

# ========================
# USER CONFIG
# ========================
SERIAL_PORT = "/dev/ttyQUECTEL"   # AT port of EC200 over USB
BAUDRATE = 115200

APN = "airtelgprs.com"
CONTEXT_ID = 3
SSL_CTX_ID = 1
PROJECT_ID = "studio-5053909228-90740"

# Fill these from your Firebase service account JSON
SERVICE_ACCOUNT_INFO = {
    "client_email": "firebase-adminsdk-fbsvc@studio-5053909228-90740.iam.gserviceaccount.com",
    "private_key": """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG...snipped...
-----END PRIVATE KEY-----"""
}

DEVICE_ID = "SN-PI-001"
DEVICE_NAME = "Pi Sensor - Main Room"

# ========================
# SERIAL HELPERS
# ========================
ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=2)

def send_at(cmd, expect="OK", timeout=5, delay=0.2):
    """Send AT command and wait for response"""
    ser.flushInput()
    print(f"→ {cmd}")
    ser.write((cmd + "\r").encode())
    t_end = time.time() + timeout
    buffer = b""
    while time.time() < t_end:
        line = ser.readline()
        if line:
            line = line.decode(errors="ignore").strip()
            print(f"← {line}")
            buffer += line.encode() + b"\n"
            if expect in line:
                return True, buffer.decode()
        time.sleep(0.05)
    return False, buffer.decode()

def wait_connect(timeout=5):
    """Wait until modem replies CONNECT"""
    t_end = time.time() + timeout
    while time.time() < t_end:
        line = ser.readline()
        if line:
            line = line.decode(errors="ignore").strip()
            print(f"← {line}")
            if "CONNECT" in line:
                return True
    return False

# ========================
# FIREBASE AUTH (JWT)
# ========================
def make_jwt():
    now = int(time.time())
    payload = {
        "iss": SERVICE_ACCOUNT_INFO["client_email"],
        "scope": "https://www.googleapis.com/auth/datastore",
        "aud": "https://oauth2.googleapis.com/token",
        "iat": now,
        "exp": now + 3600,
    }
    token = jwt.encode(payload, SERVICE_ACCOUNT_INFO["private_key"], algorithm="RS256")
    return token if isinstance(token, str) else token.decode()

# ========================
# INIT MODEM
# ========================
def init_modem():
    print("📡 Initializing modem (reboot-proof init)...")
    send_at("AT")
    send_at("ATE0")
    send_at(f'AT+CGDCONT={CONTEXT_ID},"IP","{APN}"')
    send_at(f"AT+QIACT={CONTEXT_ID}", "OK", timeout=10)
    send_at("AT+QIACT?")
    send_at(f'AT+QHTTPCFG="contextid",{CONTEXT_ID}')
    send_at('AT+QHTTPCFG="responseheader",1')
    send_at(f'AT+QHTTPCFG="sslctxid",{SSL_CTX_ID}')
    send_at(f'AT+QSSLCFG="sslversion",{SSL_CTX_ID},4')
    send_at(f'AT+QSSLCFG="cacert",{SSL_CTX_ID},"UFS:cacert.pem"')

# ========================
# FIRESTORE POST
# ========================
def post_firestore(token, data):
    url = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)/documents/devices/{DEVICE_ID}"

    # Build Firestore payload
    payload = {
        "fields": {
            "id": {"stringValue": DEVICE_ID},
            "name": {"stringValue": DEVICE_NAME},
            "status": {"stringValue": data["status"]},
            "coLevel": {"doubleValue": data["coLevel"]},
            "timestamp": {"timestampValue": datetime.datetime.utcnow().isoformat("T") + "Z"},
        }
    }
    body = json.dumps(payload)
    body_bytes = body.encode("utf-8")
    body_len = len(body_bytes)

    # 1) Set URL
    send_at(f"AT+QHTTPURL={len(url)},80")
    if not wait_connect():
        print("❌ No CONNECT after URL")
        return
    ser.write(url.encode() + b"\x1A")   # Ctrl+Z

    # 2) POST data
    send_at(f"AT+QHTTPPOST={body_len},80,80")
    if not wait_connect():
        print("❌ No CONNECT after POST")
        return
    ser.write(body_bytes + b"\x1A")  # Ctrl+Z

    # 3) Read response
    ok, resp = send_at("AT+QHTTPREAD", "OK", timeout=10)
    print("🌍 Firestore response:")
    print(resp)

# ========================
# MAIN LOOP
# ========================
def main():
    init_modem()
    token = make_jwt()
    print("✅ Got OAuth2 token")

    while True:
        co_level = round(1 + 5 * time.time() % 10, 1)  # dummy CO
        status = "Normal" if co_level < 8 else "Warning" if co_level < 12 else "Critical"

        data = {"coLevel": co_level, "status": status}
        print(f"📟 CO: {co_level} ppm")

        post_firestore(token, data)
        time.sleep(15)

if __name__ == "__main__":
    main()
