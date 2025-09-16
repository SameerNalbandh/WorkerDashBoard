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

# --- SERVICE ACCOUNT INFO (embedded) ---
SERVICE_ACCOUNT_INFO = {
  "type": "service_account",
  "project_id": "studio-5053909228-90740",
  "private_key_id": "e92d42f35f7a606c3713e4af63f4e41ad3296ec5",
  "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCeriXe/JVc6Zsa\nEyhGuk9MDFz8Ct16++1GXvi7OrBug9Xyw5OaZq0TGXZrCT3V5IYBfBpBYAGxrXXp\nc0j6o1bj56t3dw4943/qqMQsvE4Hneo/odPuA+IHER43xTUKxKpRv6tqc/7dAV/V\nuXC6mCVhjB0cqezlmeSjX3oUgjf5CbzPhFrrY0/s7gSRs/MhV5foZ0OcIPbsxsBg\nKIGCKRClKpxBfqp+2EvoHpNDP0f1EAqmRNEBVsz/gQRdLiUb6qN1rgkGaI1oGRwS\nByvwAZtGhdjCRmoQ0IX7p0YSVimZ32X83r/l2RTA6H2MHwxTDr6gPwL4K4DxhFwo\nQEpfiJ+pAgMBAAECggEAAg49fVsGUFLSaI8Q+YGWX2TVm4pEfkBfPYcjb8F94aCh\nl+iCtABag6HTz+UpwOiZ99D0wh4NR5D4sxKEQoL1MDSjGwQW0iRtVsvi5rV1yVF5\nZGOjTDUOq4rEOnK6ki4kCrUR8moYRiKrbChf1nr8GPxosCNfZ0YMGTW2bieVtAsw\nByDD5O+kvOk6uK7qBbKhkSr+fPS55wQ3Jcq9ew39HFww20OJ5ILhg3dLlKJdQRR2\nOnTwqOZpvmWProc/HcVyhnW5saODG/RR43Rc8MOnSh8vn9qN+/2qnt/LUbAex2gG\nmFmLlM1+1AVPU3w4fCrC3sXmtj72cWXKlnPZFoaJBQKBgQDKmI9AZ9gOw/E1GMQR\nIPLS1Jc07zYn1YxNf9YK7Z8JzkG7c/Cbnab+EgYoXGAc6rSydKDrGZZW08dAfMtx\nNpO37Ihjca63NzC4R52ERalzjoUDP+P95n7asmZHCHPWd/KAZA0XKXsg7hoC9VV5\nOGBTYbZXIPTLYi2Z59lS5gA4gwKBgQDIghniN7KNR8DqovWzYZdY42YFpQNGkx9C\n7jn0+9KlVvgw34cTYziIh8FC0cf73h4KbGNV0lI1ZiF33RcgI+NYHWzDBW+8a5O0\n+HicxZrG/rg9075wOOXWiyoFhuMWquEi/v7o22bO4Yo6bLWuumsqjjUAOZxrRkw1\nqhu48fUXYwKBgH1uLKqkYDjsCSdleOZd7tim9CK6w12wMdg9gEhty5wnjby/0ESY\nO65rfFJ6tqrQiSU/Xe2Qfuqs3VzIprAmKRijIeHnnVMjoU9GT3h4JKw9nY5gfQhS\nL1G5R+dMjWNICeSBjTU84lWF9KbGO6/8Pm8BPQH+jnBpDXCPAZb4fUR/AoGARc+W\nd37w+eO7tXYbmeMmsNor0VdMtqvOvJz5LOToyIxpSYrqGsP3EQJDNaKYwIbrarGm\nPGFIIjN2/6bIwHX+V9WW4qfn6XCDMwU36U2bwCE7wLsSmTwWOgamENqQAnpofKjP\n0/9f4jQAzqq+7yEU4vI0XemxHmCRdDXQBSqpLQUCgYEAtSDd4BI5Rn+DxSlYr6L+\nyIK3dZ9geTHu2Gsg0nV6Z/HX3AI5pJt4iFt9yM4+y5WQRs6GfZRlJrOhLNQx8Pim\nXXddIDd6brLPh5WnNk1fg5QvJahC/pRApXnC2u1onyZJZ1bE4YOR6E5/YZKNDHOm\n1rF3jBKzdP627hmp0j1j0xI=\n-----END PRIVATE KEY-----\n",
  "client_email": "firebase-adminsdk-fbsvc@studio-5053909228-90740.iam.gserviceaccount.com",
  "client_id": "109877301737436156902",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-fbsvc%4Studio-5053909228-90740.iam.gserviceaccount.com",
  "universe_domain": "googleapis.com"
}

PROJECT_ID = SERVICE_ACCOUNT_INFO["project_id"]

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
        "iss": SERVICE_ACCOUNT_INFO["client_email"],
        "scope": "https://www.googleapis.com/auth/datastore",
        "aud": "https://oauth2.googleapis.com/token",
        "iat": iat,
        "exp": exp
    }
    headers = {"kid": SERVICE_ACCOUNT_INFO["private_key_id"]}

    # 🔑 Fix private key newlines
    raw_key = SERVICE_ACCOUNT_INFO["private_key"]
    private_key = raw_key.replace("\\n", "\n").strip()

    print(private_key.splitlines()[0])   # Debug
    print(private_key.splitlines()[-1])  # Debug

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
        if time.time() - token_time > TOKEN_REFRESH_INTERVAL:
            token = make_token()
            token_time = time.time()

        co = read_co_sensor()
        if co is not None:
            post_to_firestore(co, token)
        print(f"⏳ Waiting {SEND_INTERVAL}s...\n")
        time.sleep(SEND_INTERVAL)
