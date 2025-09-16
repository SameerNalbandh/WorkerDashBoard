import firebase_admin
from firebase_admin import credentials, firestore
import serial
import time
import json

# --- STEP 1: SERVICE ACCOUNT KEY (UNCHANGED) ---
SERVICE_ACCOUNT_INFO = {
  "type": "service_account",
  "project_id": "studio-5053909228-90740",
  "private_key_id": "90f1efbb3e10ab661699642a5bd176c308861ebd",
  "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCw+OI3gAxqXs9Q\nLJpvAprY1iS7dHr6v/G0AEzRlcWNyKJuF2gho8ZRGN+BYmJZRvm3DRzqyXOoS6X/\nIuZMS/xTXzVNKPtGHdS/KE5sdlE+zvBsqqsrQXbbvyglA4N+zTsOrpDgDx0Q7+A+\nWAcwdYBufSQsNLsJ+CCCM/1k+FPTpVvo4EfsB0yhD0pROpom9w3k28qqbgC8eS/x\np6LPaJmoIyzvo8d0XdY89ViSgVt94uu5dLTl0z8ULzB4YxBoFYLfpaHlBNzNGpnz\nRWk7UXAjEbuqeRlbGrbvIQj1AAPB7he+77ibOefXJIC1+IR7lnqOaU99uqHaHa5G\n3fcmcIV/AgMBAAECggEAFygh9bAwL7UDPJLxjEgTef8fZFX8B5aZKnwFkUEfTgus\nUWqHqiszdoYiLNxyUQtL/qtdFs3Qb/uiF236I46n0EL7hwKvSn/5yB+ej2u1+tl6\nNUXpyumwg1WSi7FXgf6Z1TR7aY4guAgjWBUNr8YYTZzbYFtwBABvRIpIBG/IDD/1\neDkxNgkRgErmNcAog3GxpFa+EbbYyldd/W1pyeNfBrfMhw8BMwuW+gtN5yRIgczd\nkqdOA/Et7OkG1iMLCCezv3nJx0s9TNj78vCINXajeDP3j1AXD7VeNdG9r/x3Sww0\n5eHdVf2IWKHdQljsbatf+hDJ8IN1R43RGRHFDI+MtQKBgQDrWGjs1IdOGdIHehDI\nZEhaHVcu23coxzMaspsQn+1nNmbnzJh/qBJK+uY95R0BW3N8JhCbvwe+DpzwZUTX\n/4Cu1rzO00B4Zfe/oTrbfj/nCfe3lp1rafLdr6oMRQJ1pDoi7hKRTu6/H8uZxCwx\noh15o2XfePSo/R5SUKZq6q753QKBgQDAgPuehZKbLvBJUGIg0l0c45UxxhIZSN72\nbgKMkG/1y9mygXdtpkTyJ9NAZcU0O/pX3089whyShw7RPhB/gt/Zt2Vr0nbkcAYQ\n8BiFK8fvrQmaqPtTrJJZjF3C8is4mmlmvsfFyglDuk+yJOKdfiy54sQmcCuzXcc7\nZWgRyJjdCwKBgEOWN0PUYSsvxR56krlJ+3FNvczqIBVo56dCJcAnfaFHgVQOcLkw\nhlhcJ6Uc2DCcl9TOhbSEru+I+M8c9iFl8gnEB6MKDhjFh9nTrrh8UFPEjAyAR6Mi\nYSoDGb2+T8+DI2MGpfRvC6d9tRXqvZpfaUGWiFoePX0OfBe9q51G2otNAoGAIVj2\nvcJT4FAkTf7/0MHAYZXHLaUrU3f9L+FkzabjzkevAa5N2w/Xl79waBJ5NBBD0N8d\nYgxzWKrO1U6UGxK35oZPqnr+H5qMYnjFNqSb8RgftswZJaiafarEP1YmSJrvMV5R\nSyExs6rdzXV4UGIgK19uLV53I45WSiLKAXKnkHsCgYEAt1eKl1q18F2knTe7Jape\nwK9VVLm1FPOe4bJNaBGyLjBDL7WECjOZAcQgRsFFyqa6fQ/FzEJsvihVmtwWDR6t\n08ftHRqkeVLhcoN4m+h7cXtRMMaqVOFk96pepeqC04Lmem90I5j+LRKblCEe5cN6\nPLxOHmFS4JHItXVr2PPu6TY=\n-----END PRIVATE KEY-----\n",
  "client_email": "firebase-adminsdk-fbsvc@studio-5053909228-90740.iam.gserviceaccount.com",
  "client_id": "109877301737436156902",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-fbsvc%40studio-5053909228-90740.iam.gserviceaccount.com",
  "universe_domain": "googleapis.com"
}

# --- STEP 2: SENSOR DETAILS & CONFIGURATION ---
DEVICE_ID = "SN-PI-001"
DEVICE_NAME = "Pi Sensor - Main Room"
LOCATION_NAME = "Main Room"
LOCATION_LAT = 40.7160
LOCATION_LNG = -74.0040

SEND_INTERVAL = 1   # seconds

# --- STEP 3: INITIALIZE FIREBASE ADMIN ---
try:
    cred = credentials.Certificate(SERVICE_ACCOUNT_INFO)
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("✅ Successfully connected to Firestore.")
except Exception as e:
    print(f"❌ Error connecting to Firestore: {e}")
    exit()

# --- STEP 4: UART CONFIGURATION FOR ZE03 ---
UART_PORT = "/dev/ttyAMA0"   # S0 port on Pi
BAUD_RATE = 9600
ser = serial.Serial(UART_PORT, BAUD_RATE, timeout=1)

def read_co_sensor():
    """
    Reads CO concentration (ppm) from Winsen ZE03 via UART.
    Returns float ppm or None if invalid.
    """
    try:
        if ser.in_waiting >= 9:
            frame = ser.read(9)
            if frame[0] == 0xFF and frame[1] == 0x86:
                high = frame[2]
                low = frame[3]
                ppm = (high << 8) | low
                print(f"📟 Read ZE03 sensor value: {ppm} PPM")
                return ppm
    except Exception as e:
        print(f"⚠️ UART read error: {e}")
    return None

def determine_status(co_level):
    if co_level is None:
        return "Error"
    if co_level > 12:
        return "Critical"
    elif co_level > 8:
        return "Warning"
    else:
        return "Normal"

def send_data_to_firestore():
    co_level = read_co_sensor()
    status = determine_status(co_level)

    payload = {
        "id": DEVICE_ID,
        "name": DEVICE_NAME,
        "location": {
            "name": LOCATION_NAME,
            "lat": LOCATION_LAT,
            "lng": LOCATION_LNG,
        },
        "status": status,
        "coLevel": co_level,
        "timestamp": firestore.SERVER_TIMESTAMP,
        "battery": 100,
    }

    print(f"🚀 Sending data to Firestore...")

    try:
        device_ref = db.collection("devices").document(DEVICE_ID)
        device_ref.set(payload, merge=True)
        print("✅ Success! Data saved to Firestore.\n")
    except Exception as e:
        print(f"❌ Firestore Error: {e}\n")

# --- STEP 5: MAIN LOOP ---
if __name__ == "__main__":
    print(f"🔋 Starting sensor {DEVICE_ID}. Press Ctrl+C to stop.")
    while True:
        send_data_to_firestore()
        print(f"--- ⏳ Waiting for {SEND_INTERVAL} seconds... ---\n")
        time.sleep(SEND_INTERVAL)
