import os, time, json, struct, asyncio, requests
from bleak import BleakScanner

TARGET_MAC = "A4C1384DC981".upper()  # Twój MAC bez :
UUID_181A  = "0000181a-0000-1000-8000-00805f9b34fb"
PUBLISH_EVERY_SEC = 30

GIST_ID = os.environ.get("GIST_ID")
GHTOKEN = os.environ.get("GITHUB_TOKEN")

def mac_be(b): return "".join(f"{x:02X}" for x in b)
def mac_le(b): return "".join(f"{x:02X}" for x in b[::-1])

def parse_len13_be(b: bytes):
    # [MAC(6 BE)][temp*10 i16 BE][hum u8][bat u8][mV u16 BE][cnt u8]
    mac = mac_be(b[0:6])
    t   = struct.unpack(">h", b[6:8])[0] / 10.0
    h   = float(b[8])
    bat = int(b[9])
    mv  = struct.unpack(">H", b[10:12])[0]
    cnt = b[12]
    return mac, t, h, bat, mv, cnt

def parse_len16_le(b: bytes):
    mac = mac_le(b[5:11]); t = struct.unpack("<h", b[11:13])[0] / 10.0
    h = float(b[13]); bat = int(b[14]); mv = int(b[15]) * 10; cnt = None
    return mac, t, h, bat, mv, cnt

def parse_len19_le(b: bytes):
    mac = mac_le(b[5:11]); t = struct.unpack("<h", b[11:13])[0] / 100.0
    h = struct.unpack("<H", b[13:15])[0] / 100.0
    bat = int(b[15]); mv = struct.unpack("<H", b[16:18])[0]; cnt = b[18]
    return mac, t, h, bat, mv, cnt

def parse_any(b: bytes):
    n = len(b)
    if n == 13: return parse_len13_be(b)
    if n == 16: return parse_len16_le(b)
    if n == 19: return parse_len19_le(b)
    return None

state = {"last": None, "ts": 0}

def adv_cb(dev, adv):
    raw = (adv.service_data or {}).get(UUID_181A)
    if not raw: return
    rec = parse_any(bytes(raw))
    if not rec: return
    mac, t, h, bat, mv, cnt = rec
    ok = (mac == TARGET_MAC) or (len(raw)==13 and mac_le(raw[0:6])==TARGET_MAC)
    if not ok: return
    state["last"] = {
        "temp_c": round(t, 2),
        "hum_pct": round(h, 2),
        "battery_pct": bat,
        "battery_mV": mv,
        "counter": cnt,
        "rssi": adv.rssi,
        "mac": TARGET_MAC,
        "source": "BLE_ADV_0x181A",
    }
    state["ts"] = int(time.time())

def publish_to_gist(doc: dict):
    if not (GIST_ID and GHTOKEN):
        print("Brak GIST_ID/GITHUB_TOKEN")
        return False
    url = f"https://api.github.com/gists/{GIST_ID}"
    body = {"files": {"room.json": {"content": json.dumps(doc, ensure_ascii=False)}}}
    r = requests.patch(url, headers={"Authorization": f"token {GHTOKEN}",
                                     "Accept": "application/vnd.github+json"},
                       json=body, timeout=15)
    print("PUBLISH", r.status_code)
    return 200 <= r.status_code < 300

async def main():
    s = BleakScanner(detection_callback=adv_cb)
    await s.start()
    try:
        next_pub = 0
        while True:
            await asyncio.sleep(1)
            if state["last"] and time.time() >= next_pub:
                doc = {"device":"ATC-BEDROOM","timestamp":state["ts"],"reading":state["last"]}
                publish_to_gist(doc)
                next_pub = time.time() + PUBLISH_EVERY_SEC
    finally:
        await s.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
