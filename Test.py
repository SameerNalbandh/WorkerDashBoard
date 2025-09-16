import serial
import time
import json
import jwt
import requests
import datetime

# --- CONFIG ---
DEVICE_ID = "SN-PI-001"
PROJECT_ID = "studio-5053909228-90740"
APN = "airtelgprs.com"
PDP_CONTEXT = 3
SEND_INTERVAL = 15
TOKEN_REFRESH_INTERVAL = 55 * 60

# --- PRIVATE KEY (PEM block) ---
PRIVATE_KEY_PEM = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEA...
... your full private key here ...
-----END PRIVATE KEY-----"""

# --- SERVICE ACCOUNT INFO ---
SERVICE_ACCOUNT_INFO = {
  "type": "service_account",
  "project_id": PROJECT_ID,
  "private_key_id": "90f1efbb3e10ab661699642a5bd176c308861ebd",
  "private_key": PRIVATE_KEY_PEM,
  "client_email": "firebase-adminsdk-fbsvc@studio-5053909228-90740.iam.gserviceaccount.com",
  "token_uri": "https://oauth2.googleapis.com/token"
}

# --- SERIAL PORTS ---
ser_sensor = serial.Serial("/dev/ttyS0", baudrate=9600, timeout=1)      # Winsen ZE03
ser_modem = serial.Serial("/dev/ttyAMA5", baudrate=115200, timeout=2)   # Quectel

# --- AT Helpers ---
def send_at(cmd, delay=1):
    ser_modem.write((cmd + "\r\n").encode())
    time.sleep(delay)
    resp = ser_modem.read_all().decode(errors="ignore")
    print(f"→ {cmd}\n← {resp}")
    return resp

def init_modem():
    print("📡 Initializing modem (reboot-proof init)...")
    send_at("AT")
    send_at("ATE0")
    send_at(f'AT+CGDCONT={PDP_CONTEXT},"IP","{APN}"')
    send_at(f'AT+QIACT={PDP_CONTEXT}', 3)
    send_at("AT+QIACT?")

    # HTTP config (must set every boot)
    send_at(f'AT+QHTTPCFG="contextid",{PDP_CONTEXT}')
    send_at('AT+QHTTPCFG="responseheader",1')
    send_at('AT+QHTTPCFG="sslctxid",1')

    # SSL config (already persistent, but reapply defensively)
    send_at('AT+QSSLCFG="sslversion",1,4')
    send_at('AT+QSSLCFG="cacert",1,"UFS:cacert.pem"')

    # Self-test Google GET
    print("🌐 Testing HTTPS connectivity...")
    url = "https://www.google.com"
    send_at(f'AT+QHTTPURL={len(url)},80')
    time.sleep(0.5)
    ser_modem.write(url.encode())
    send_at("AT+QHTTPGET=80", 5)
    resp = send_at("AT+QHTTPREAD", 3)
    print("🔎 HTTPS Test Response:", resp[:200])  # print first 200 chars

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
    private_key = SERVICE_ACCOUNT_INFO["private_key"].strip()

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
    req = bytearray([0xFF,0x01,0x86,0,0,0,0,0,0x79])
    ser_sensor.write(req)
    resp = ser_sensor.read(9)
    if len(resp)==9 and resp[0]==0xFF and resp[1]==0x86:
        co = (resp[2]<<8)|resp[3]
        print(f"📟 CO: {co} ppm")
        return co
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

    # Important: end headers with \r\n\r\n
    headers = f"Authorization: Bearer {token}\r\nContent-Type: application/json\r\n\r\n"
    payload = headers + data
    length = len(payload.encode("utf-8"))

    # Send URL
    send_at(f'AT+QHTTPURL={len(url)},80')
    time.sleep(0.5)
    ser_modem.write(url.encode())

    # Send body
    send_at(f'AT+QHTTPPOST={length},80,80')
    time.sleep(0.5)
    ser_modem.write(payload.encode("utf-8"))

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
