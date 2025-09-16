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
TOKEN_REFRESH_INTERVAL = 55 * 60  # refresh every 55 minutes

# --- SERVICE ACCOUNT INFO (paste yours here) ---
SERVICE_ACCOUNT_INFO = {
  # paste your JSON here
}

PROJECT_ID = SERVICE_ACCOUNT_INFO["project_id"]

# --- SERIAL PORTS ---
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
    print("📡 Initializing modem (Airtel, PDP context 3)...")
    send_at("AT")
    send_at("ATE0")
    send_at(f'AT+CGDCONT=3,"IP","{APN}"')   # PDP context 3
    send_at("AT+QIACT=3", 3)                # activate PDP context 3
    send_at("AT+QIACT?")
    send_at('AT+QHTTPCFG="contextid",3')    # use context 3 for HTTP
    send_at('AT+QHTTPCFG="responseheader",1')

# --- Firebase Auth ---
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

    headers = {"kid": SERVICE_ACCOUNT_INFO["private_key_id"]}

    # Fix newlines in private key
    raw_key = SERVICE_ACCOUNT_INFO["private_key"]
    private_key = raw_key.replace("\\n", "\n").strip()

    # Debug check
    print(private_key.splitlines()[0])
    print(private_key.splitlines()[-1])

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

# --- Sensor ---
def read_co_sensor():
    req = bytearray([0xFF, 0x01, 0x86, 0, 0, 0, 0, 0, 0x79])
    ser_sensor.write(req)
    resp = ser_sensor.read(9)
    if len(resp) == 9 and resp[0] == 0xFF and resp[1] == 0x86:
        co_ppm = (resp[2] << 8) | resp[3]
        print(f"📟 CO: {co_ppm} ppm")
        return co_ppm
    print("⚠️ Sensor error")
    return None

# --- Firestore Post ---
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
    if not token:
        exit()

    token_time = time.time()

    while True:
        if time.time() - token_time > TOKEN_REFRESH_INTERVAL:
            token = make_token()
            token_time = time.time()

        co = read_co_sensor()
        if co is not None and token:
            post_firestore(co, token)
        time.sleep(SEND_INTERVAL)
