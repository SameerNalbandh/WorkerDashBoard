import serial
import time
import json
import jwt
import requests
import datetime

# --- CONFIGURATION ---
DEVICE_ID = "SN-PI-001"
SEND_INTERVAL = 10  # seconds
TOKEN_REFRESH_INTERVAL = 55 * 60  # refresh every 55 minutes
APN = "airtelgprs.com"  # Airtel APN

# --- SERVICE ACCOUNT FILE ---
SERVICE_ACCOUNT_FILE = "service-account.json"

with open(SERVICE_ACCOUNT_FILE, "r") as f:
    SERVICE_ACCOUNT = json.load(f)

PROJECT_ID = SERVICE_ACCOUNT["project_id"]

# --- SERIAL PORTS ---
ser_sensor = serial.Serial("/dev/ttyS0", baudrate=9600, timeout=1)      # Winsen ZE03 sensor
ser_modem = serial.Serial("/dev/ttyAMA5", baudrate=115200, timeout=2)   # EC200Y modem

# --- AT COMMAND HELPERS ---
def send_at(cmd, delay=1):
    """Send AT command and return response."""
    ser_modem.write((cmd + "\r\n").encode())
    time.sleep(delay)
    resp = ser_modem.read_all().decode(errors="ignore")
    print(f"→ {cmd}\n← {resp}")
    return resp

def init_modem():
    print("📡 Initializing modem...")
    send_at("AT")
    send_at("ATE0")  # echo off
    send_at(f'AT+CGDCONT=1,"IP","{APN}"')
    send_at("AT+QIACT=1")   # activate PDP
    send_at('AT+QHTTPCFG="contextid",1')
    send_at('AT+QHTTPCFG="responseheader",1')

# --- FIREBASE AUTH ---
def make_token():
    """Generate OAuth2 access token for Firestore."""
    iat = int(time.time())
    exp = iat + 3600
    payload = {
        "iss": SERVICE_ACCOUNT["client_email"],
        "scope": "https://www.googleapis.com/auth/datastore",
        "aud": "https://oauth2.googleapis.com/token",
        "iat": iat,
        "exp": exp
    }
    headers = {"kid": SERVICE_ACCOUNT["private_key_id"]}

    # Fix private key format
    raw_key = SERVICE_ACCOUNT["private_key"]
    private_key = raw_key.replace("\\n", "\n").strip()

    # Save for debug (optional)
    with open("debug_key.pem", "w") as f:
        f.write(private_key)

    signed_jwt = jwt.encode(payload, private_key, algorithm="RS256", headers=headers)

    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": signed_jwt
    })
    if resp.status_code == 200:
        token = resp.json()["access_token"]
        print("✅ Got OAuth2 token")
        return token
    else:
        print("❌ Token error:", resp.text)
        return None

# --- SENSOR ---
def read_co_sensor():
    """Read CO ppm from Winsen ZE03 sensor."""
    request_cmd = bytearray([0xFF, 0x01, 0x86, 0, 0, 0, 0, 0, 0x79])
    ser_sensor.write(request_cmd)
    response = ser_sensor.read(9)
    if len(response) == 9 and response[0] == 0xFF and response[1] == 0x86:
        co_ppm = (response[2] << 8) | response[3]
        print(f"📟 CO Sensor: {co_ppm} PPM")
        return co_ppm
    else:
        print("⚠️ Invalid sensor response")
        return None

# --- FIRESTORE POST ---
def post_to_firestore(co_level, token):
    """Post CO data to Firestore using modem AT commands."""
    url = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)/documents/devices/{DEVICE_ID}"
    
    body = {
        "fields": {
            "id": {"stringValue": DEVICE_ID},
            "coLevel": {"integerValue": co_level},
            "timestamp": {"timestampValue": datetime.datetime.utcnow().isoformat("T") + "Z"}
        }
    }
    data = json.dumps(body)
    headers = f"Authorization: Bearer {token}\r\nContent-Type: application/json\r\n"

    # 1. Send URL
    send_at(f'AT+QHTTPURL={len(url)},80')
    time.sleep(0.5)
    ser_modem.write(url.encode())

    # 2. Send POST body (headers + JSON)
    post_payload = headers + "\r\n" + data
    send_at(f'AT+QHTTPPOST={len(post_payload)},60,60')
    time.sleep(0.5)
    ser_modem.write(post_payload.encode())

    # 3. Read response
    resp = send_at("AT+QHTTPREAD", 3)
    print("🌍 Firestore response:", resp)

# --- MAIN LOOP ---
if __name__ == "__main__":
    init_modem()
    token = make_token()
    if not token:
        exit()

    token_time = time.time()

    while True:
        # Refresh token if expired
        if time.time() - token_time > TOKEN_REFRESH_INTERVAL:
            token = make_token()
            token_time = time.time()

        co = read_co_sensor()
        if co is not None:
            post_to_firestore(co, token)
        print(f"⏳ Waiting {SEND_INTERVAL}s...\n")
        time.sleep(SEND_INTERVAL)
