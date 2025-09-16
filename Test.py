import firebase_admin
from firebase_admin import credentials, firestore
import time, serial

# --- STEP 1: Service Account JSON ---
# Paste your service account dictionary here:
SERVICE_ACCOUNT_INFO = {
    # "type": "service_account",
    # "project_id": "xxxxx",
    # "private_key_id": "xxxxx",
    # "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEv....\n-----END PRIVATE KEY-----\n",
    # "client_email": "xxxxx@xxxxx.iam.gserviceaccount.com",
    # "client_id": "xxxxx",
    # "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    # "token_uri": "https://oauth2.googleapis.com/token",
    # "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    # "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/xxxxx",
    # "universe_domain": "googleapis.com"
}

cred = credentials.Certificate(SERVICE_ACCOUNT_INFO)
firebase_admin.initialize_app(cred)
db = firestore.client()

# --- STEP 2: Serial (ZE03 sensor on Pi UART S0) ---
ser = serial.Serial("/dev/ttyS0", baudrate=9600, timeout=1)

DEVICE_ID = "SN-PI-001"
DEVICE_NAME = "Pi Sensor - Main Room"

# --- STEP 3: ZE03 decode ---
def read_ze03():
    """Read an 8-byte frame from ZE03 and extract PPM value"""
    data = ser.read(8)
    if len(data) == 8 and data[0] == 0xFF and data[1] == 0x17:
        high = data[2]
        low = data[3]
        value = (high << 8) | low
        return value
    return None

def determine_status(ppm):
    if ppm > 12:
        return "Critical"
    elif ppm > 8:
        return "Warning"
    return "Normal"

# --- STEP 4: Main loop ---
while True:
    ppm = read_ze03()
    if ppm is not None:
        status = determine_status(ppm)
        payload = {
            "id": DEVICE_ID,
            "name": DEVICE_NAME,
            "coLevel": ppm,
            "status": status,
            "timestamp": firestore.SERVER_TIMESTAMP,
            "battery": 100,
        }

        print(f"📟 ZE03: {ppm} ppm → {status}")
        try:
            db.collection("devices").document(DEVICE_ID).set(payload, merge=True)
            print("✅ Sent to Firestore\n")
        except Exception as e:
            print(f"❌ Firestore error: {e}\n")

    time.sleep(5)
