import serial
import time
import json
import jwt
import requests
import datetime

# --- CONFIG ---
DEVICE_ID = "SN-PI-001"
APN = "airtelgprs.com"   # Airtel APN
SEND_INTERVAL = 15       # seconds

# --- Service account info (embedded) ---
SERVICE_ACCOUNT_INFO = {
  "type": "service_account",
  "project_id": "studio-5053909228-90740",
  "private_key_id": "e92d42f35f7a606c3713e4af63f4e41ad3296ec5",
  "private_key": """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBK...
... (your full base64 body) ...
-----END PRIVATE KEY-----""",
  "client_email": "firebase-adminsdk-fbsvc@studio-5053909228-90740.iam.gserviceaccount.com",
  "token_uri": "https://oauth2.googleapis.com/token"
}

PROJECT_ID = SERVICE_ACCOUNT_INFO["project_id"]

# --- Serial ports ---
ser_sensor = serial.Serial("/dev/ttyS0", baudrate=9600, timeout=1)      # ZE03 sensor
ser_modem = serial.Serial("/dev/ttyAMA5", baudrate=115200, timeout=2)   # Quectel modem

# --- AT Helpers ---
def send_at(cmd, delay=1):
    ser_modem.write((cmd + "\r\n").encode())
    time.sleep(delay)
    resp = ser_modem.read_all().decode(errors="ignore")
    print(f"→ {cmd}\n← {resp}")
    return resp

def init_modem():
    print("📡 Initializing modem...")
    send_at("AT")
    send_at("ATE0")
    send_at(f'AT+CGDCONT=1,"IP","{APN}"')
    send_at("AT+QIACT=1")
    send_at('AT+QHTTPCFG="contextid",1')
    send_at('AT+QHTTPCFG="responseheader",1')

# --- Auth token ---
def make_token():
    iat = int(time.time())
    exp = iat + 3600
    payload = {
        "iss": SERVICE_ACCOUNT_INFO["client_email"],
        "scope": "https://www.googleapis.com/auth/datastore",
        "aud": "https://oauth2.googleapis.com/token",
        "iat": iat,
        "exp": exp
    }

    private_key = SERVICE_ACCOUNT_INFO["private_key"]

    signed_jwt = jwt.encode(payload, private_key, algorithm="RS256")

    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": signed_jwt
    })
    token = resp.json().get("access_token")
    if token:
        print("✅ Got OAuth2 token")
    else:
        print("❌ Token error:", resp.text)
    return token

# --- Sensor ---
def read_co_sensor():
    req = bytearray([0xFF,0x01,0x86,0,0,0,0,0,0x79])
    ser_sensor.write(req)
    resp = ser_sensor.read(9)
    if len(resp)==9 and resp[0]==0xFF and resp[1]==0x86:
        co = (resp[2]<<8)|resp[3]
        print(f"📟 CO: {co} ppm")
        return co
    print("⚠️ Sensor error")
    return None

# --- Post to Firestore ---
def post_firestore(co_level, token):
    url = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)/documents/devices/{DEVICE_ID}"
    body = {
        "fields": {
            "id": {"stringValue": DEVICE_ID},
            "coLevel": {"integerValue": co_level},
            "timestamp": {"timestampValue": datetime.datetime.utcnow().isoformat("T")+"Z"}
        }
    }
    data = json.dumps(body)
    headers = f"Authorization: Bearer {token}\r\nContent-Type: application/json\r\n"

    # Send URL
    send_at(f'AT+QHTTPURL={len(url)},80')
    time.sleep(0.5)
    ser_modem.write(url.encode())

    # Send body
    payload = headers + "\r\n" + data
    send_at(f'AT+QHTTPPOST={len(payload)},60,60')
    time.sleep(0.5)
    ser_modem.write(payload.encode())

    # Read response
    resp = send_at("AT+QHTTPREAD", 3)
    print("🌍 Firestore response:", resp)

# --- MAIN ---
if __name__ == "__main__":
    init_modem()
    token = make_token()
    while True:
        co = read_co_sensor()
        if co is not None and token:
            post_firestore(co, token)
        time.sleep(SEND_INTERVAL)
