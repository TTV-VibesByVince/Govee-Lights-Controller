"""
Curtain GIF test  (throwaway - not part of the app)
---------------------------------------------------
Proves whether a GIF can be pushed to the Govee Curtain Lights (H70B6) from
Python, using the method from the "Govee GIF Player" by tailgunner357:
log in to Govee's cloud like the phone app, upload a 30x32 GIF as a temporary
DIY effect, switch the curtain to it, then delete the temporary effect.

    python tools/curtain_test.py                 sends a 6-colour test pattern
    python tools/curtain_test.py my.gif          sends a GIF file from this PC
    python tools/curtain_test.py "https://..."   sends a Giphy / Tenor / .gif link
    add  --dry  to any of these to convert only (nothing is sent)

Whatever is sent is also saved as tools/last_sent.gif (30x32) so you can see
what the curtain was given.

API key: save it in a file called  tools/api_key.txt  (just the key on one
line) and the script reads it from there. Without that file it asks for it.
It also asks for your Govee email and password, and for an emailed
verification code if Govee wants one. The password is never saved or printed. After a successful login a sign-in token (not the password)
is kept in tools/govee_token.json so later runs can skip the login.
Needs an internet connection. Standard library, plus Pillow for real GIFs.
"""

import base64
import getpass
import json
import os
import random
import ssl
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

GOVEE_APP = "https://app2.govee.com"            # the phone app's (private) API
GOVEE_API = "https://openapi.api.govee.com"     # the official developer API
SKU = "H70B6"
W, H = 30, 32                                   # the curtain is 30 x 32 LEDs
GOODS_TYPE = 329
EFFECT_CODE = [864]
DIY_CODE = 71
DIY_NAME = "LumiaGIF"                           # same name the original uses
PREFIX = bytes([0x50, 0x5D])
APP_VERSION = "7.3.15"
USER_AGENT = ("GoveeHome/7.3.15 (com.ihoment.GoVeeSensor; build:3; "
              "iOS 18.6.2) Alamofire/5.11.0")


# ══════════════════════════════════════════════════════════════
#  GIF writer  (ported from tailgunner357's engine.js so the bytes have the
#  exact layout the curtain is known to accept)
# ══════════════════════════════════════════════════════════════

def lzw_encode(indices, min_code_size: int) -> bytes:
    clear = 1 << min_code_size
    eoi = clear + 1
    out = bytearray()
    bits = n_bits = 0

    def emit(code, size):
        nonlocal bits, n_bits
        bits |= code << n_bits
        n_bits += size
        while n_bits >= 8:
            out.append(bits & 0xFF)
            bits >>= 8
            n_bits -= 8

    code_size = min_code_size + 1
    next_code = eoi + 1
    table = {}
    emit(clear, code_size)
    if indices:
        prev = indices[0]
        for cur in indices[1:]:
            key = (prev, cur)
            if key in table:
                prev = table[key]
                continue
            emit(prev, code_size)
            if next_code < 4096:
                table[key] = next_code
                next_code += 1
                # ">" (not ">=") keeps the encoder in step with GIF decoders
                if next_code > (1 << code_size) and code_size < 12:
                    code_size += 1
            else:
                emit(clear, code_size)
                table = {}
                code_size = min_code_size + 1
                next_code = eoi + 1
            prev = cur
        emit(prev, code_size)
    emit(eoi, code_size)
    if n_bits > 0:
        out.append(bits & 0xFF)
    return bytes(out)


def encode_gif(palette, frames, w, h, delays_ms) -> bytes:
    """palette: 256 (r, g, b); frames: lists of w*h palette indexes."""
    pal_bits = 8
    out = bytearray(b"GIF89a")
    out += w.to_bytes(2, "little") + h.to_bytes(2, "little")
    out += bytes([0x80 | ((pal_bits - 1) << 4) | (pal_bits - 1), 0, 0])
    for i in range(1 << pal_bits):
        out += bytes(palette[i] if i < len(palette) else (0, 0, 0))
    out += bytes([0x21, 0xFF, 0x0B]) + b"NETSCAPE2.0" + bytes([3, 1, 0, 0, 0])
    for frame, delay in zip(frames, delays_ms):
        d = max(2, round(delay / 10))
        out += bytes([0x21, 0xF9, 0x04, 0x04, d & 0xFF, (d >> 8) & 0xFF, 0, 0])
        out += bytes([0x2C]) + (0).to_bytes(2, "little") * 2
        out += w.to_bytes(2, "little") + h.to_bytes(2, "little") + bytes([0])
        out += bytes([pal_bits])
        data = lzw_encode(frame, pal_bits)
        for i in range(0, len(data), 255):
            block = data[i:i + 255]
            out += bytes([len(block)]) + block
        out += bytes([0])
    out += bytes([0x3B])
    return bytes(out)


def test_pattern() -> bytes:
    """Six solid colours, half a second each."""
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255),
              (255, 255, 0), (0, 255, 255), (255, 0, 255)]
    palette = colors + [(0, 0, 0)] * (256 - len(colors))
    frames = [[i] * (W * H) for i in range(len(colors))]
    return encode_gif(palette, frames, W, H, [500] * len(colors))


# ══════════════════════════════════════════════════════════════
#  Real GIFs: fetch, crop to the curtain's shape, shrink, 256 colours
# ══════════════════════════════════════════════════════════════

MAX_FRAMES = 100
MAX_DOWNLOAD = 10 * 1024 * 1024
BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}


def fetch(url: str, limit: int) -> bytes:
    req = urllib.request.Request(url, headers=BROWSER)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"file is larger than {limit // 1024 // 1024} MB")
    return data


def resolve(url: str) -> str:
    """Turn a Giphy / Tenor / Imgur page link into the GIF file's address."""
    import re
    from urllib.parse import urlsplit
    u = urlsplit(url)
    host, path = u.netloc.lower(), u.path
    if path.lower().endswith(".gif"):
        return url
    if host.endswith("giphy.com"):
        # .../gifs/some-title-<id>  or  /media/<id>/giphy.webp
        m = re.search(r"/media/(?:v1\.[^/]+/)?([A-Za-z0-9]+)/", path)
        gid = m.group(1) if m else path.rstrip("/").split("/")[-1].split("-")[-1]
        return f"https://media.giphy.com/media/{gid}/giphy.gif"
    # Tenor, Imgur and anything else: look for the GIF named in the page
    page = fetch(url, 2 * 1024 * 1024).decode("utf-8", "replace")
    for pattern in (r'https://[^"\'\\ ]+?\.gif', ):
        found = re.findall(pattern, page)
        tenor = [f for f in found if "tenor.com" in f and "AAAAC" in f]
        if tenor or found:
            return (tenor or found)[0]
    raise ValueError("could not find a GIF on that page")


def convert(data: bytes):
    """Any image/GIF bytes -> (30x32 curtain GIF bytes, info text)."""
    import io
    from PIL import Image, ImageSequence
    src = Image.open(io.BytesIO(data))
    sw, sh = src.size
    # centre-crop to the curtain's 30:32 shape
    if sw / sh > W / H:
        cw, ch = int(sh * W / H), sh
    else:
        cw, ch = sw, int(sw * H / W)
    box = ((sw - cw) // 2, (sh - ch) // 2, (sw - cw) // 2 + cw, (sh - ch) // 2 + ch)

    small, delays = [], []
    total = getattr(src, "n_frames", 1)
    for i, frame in enumerate(ImageSequence.Iterator(src)):
        if i >= MAX_FRAMES:
            break
        rgba = frame.convert("RGBA")                  # fully drawn frame
        flat = Image.new("RGB", rgba.size, (0, 0, 0))  # transparent -> off
        flat.paste(rgba, mask=rgba.getchannel("A"))
        small.append(flat.crop(box).resize((W, H), Image.BOX))
        delays.append(frame.info.get("duration") or 100)

    # one shared 256-colour palette for every frame
    sheet = Image.new("RGB", (W, H * len(small)))
    for i, im in enumerate(small):
        sheet.paste(im, (0, i * H))
    pal_img = sheet.quantize(colors=256, method=Image.MEDIANCUT,
                             dither=Image.Dither.NONE)
    flat_pal = pal_img.getpalette()[:768]
    palette = [tuple(flat_pal[i:i + 3]) for i in range(0, len(flat_pal), 3)]
    indexed = pal_img.tobytes()
    frames = [list(indexed[i * W * H:(i + 1) * W * H]) for i in range(len(small))]
    info = (f"{sw}x{sh}, {total} frame(s) -> {W}x{H}, {len(frames)} frame(s)"
            + (f" (capped at {MAX_FRAMES})" if total > MAX_FRAMES else ""))
    return encode_gif(palette, frames, W, H, delays), info


def load_source(arg: str):
    """(curtain GIF bytes, description) for a file path or a link."""
    if arg.lower().startswith(("http://", "https://")):
        direct = resolve(arg)
        print(f"Downloading {direct[:90]}")
        data = fetch(direct, MAX_DOWNLOAD)
        print(f"    {len(data) / 1024:.0f} KB")
    else:
        with open(arg, "rb") as f:
            data = f.read()
    gif, info = convert(data)
    return gif, info


# ══════════════════════════════════════════════════════════════
#  Web requests
# ══════════════════════════════════════════════════════════════

_ctx = ssl.create_default_context()


def request(method, url, headers, body=None, timeout=30):
    """Returns (http_status, parsed JSON or text)."""
    data = None
    if body is not None:
        data = json.dumps(body, separators=(",", ":")).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ctx) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    try:
        return status, json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return status, raw.decode("utf-8", "replace")[:300]


def app_headers(client_id, token=None):
    h = {"Content-Type": "application/json", "appversion": APP_VERSION,
         "clienttype": "1", "clientid": client_id,
         "timestamp": str(int(time.time() * 1000)), "timezone": "America/New_York",
         "country": "US", "user-agent": USER_AGENT, "accept": "*/*"}
    if token:
        h["Authorization"] = "Bearer " + token
    else:
        h["sysversion"] = "18.6.2"
    return h


def api_headers(api_key):
    return {"Govee-API-Key": api_key, "Content-Type": "application/json"}


def msg_id():
    return str(int(time.time() * 1000)) + f"{random.randrange(10**6):06d}"


def short(data, n=160):
    if isinstance(data, dict):
        data = data.get("message") or json.dumps(data)
    return str(data)[:n]


def clean(text: str) -> str:
    """Drop invisible characters (a bad paste) and surrounding spaces/quotes."""
    return "".join(ch for ch in text if ch > " " or ch == " ").strip().strip("\"'")


def looks_like_key(key: str) -> bool:
    return (len(key) == 36 and key.count("-") == 4
            and all(ch in "0123456789abcdefABCDEF-" for ch in key))


KEY_FILE = os.path.join(HERE, "api_key.txt")


def read_key_file() -> str:
    """The API key from tools/api_key.txt, if that file holds one."""
    try:
        with open(KEY_FILE, encoding="utf-8-sig") as f:
            for line in f:
                if looks_like_key(clean(line)):
                    return clean(line)
    except OSError:
        pass
    return ""


def step(n, text):
    print(f"\n[{n}] {text}")


def fail(text):
    print("\n  STOPPED: " + text)
    sys.exit(1)


# ══════════════════════════════════════════════════════════════
#  Login  (email + password, plus an emailed code if Govee asks for one)
# ══════════════════════════════════════════════════════════════

TOKEN_FILE = os.path.join(HERE, "govee_token.json")


def load_saved_login():
    """A login saved by an earlier run, if it has not expired."""
    try:
        with open(TOKEN_FILE) as f:
            d = json.load(f)
        if d["token"] and d["expires"] > time.time() + 300:
            return d
    except (OSError, ValueError, KeyError):
        pass
    return None


def saved_client_id():
    """Reuse the same 'phone id' every run so Govee recognises this PC."""
    try:
        with open(TOKEN_FILE) as f:
            cid = json.load(f).get("clientId", "")
        if len(cid) == 32:
            return cid
    except (OSError, ValueError):
        pass
    return "".join(random.choice("0123456789abcdef") for _ in range(32))


def login():
    """Returns (token, client_id, account_id). Stops the script on failure."""
    saved = load_saved_login()
    if saved:
        print("    Using the login saved by an earlier run "
              "(tools/govee_token.json).")
        return saved["token"], saved["clientId"], saved.get("accountId")

    email = clean(input("    Govee account email: "))
    password = getpass.getpass("    Govee account password (hidden): ")
    password = "".join(ch for ch in password if ch >= " ")
    print(f"    Password received: {len(password)} characters")
    if not (email and password):
        fail("email and password are needed.")

    client_id = saved_client_id()
    url = GOVEE_APP + "/account/rest/account/v2/login"
    body = {"email": email, "client": client_id, "password": password}

    def attempt():
        status, data = request("POST", url, app_headers(client_id), body)
        inner = data.get("status") if isinstance(data, dict) else None
        client = data.get("client") if isinstance(data, dict) else None
        return status, inner, client, data

    status, inner, client, data = attempt()
    if 454 in (status, inner):
        # New device: Govee emails a code, which goes in a second login.
        print("    Govee wants a verification code. Asking it to email one...")
        vs, vd = request(
            "POST", GOVEE_APP + "/account/rest/account/v1/verification",
            app_headers(client_id), {"type": 8, "email": email})
        print(f"    Code request: HTTP {vs} - {short(vd)}")
        print("    Check the inbox of your Govee account email (and spam).")
        code = clean(input("    Verification code from the email: "))
        if not code:
            fail("no code entered.")
        body["code"] = code
        status, inner, client, data = attempt()
        if 454 in (status, inner):
            fail("Govee did not accept that code (still status 454).\n"
                 "  Run again for a fresh code; codes expire quickly.")
    body.clear()
    if not (status == 200 and inner == 200 and client and client.get("token")):
        fail(f"login failed (HTTP {status}, status {inner}): {short(data)}")

    client_id = client.get("client") or client_id
    saved = {"token": client["token"], "clientId": client_id,
             "accountId": client.get("accountId"),
             "expires": time.time() + (client.get("tokenExpireCycle") or 57600)}
    try:
        with open(TOKEN_FILE, "w") as f:
            json.dump(saved, f)
        print("    Logged in. Login saved to tools/govee_token.json so the next"
              "\n    runs skip the email, password and code (delete the file to"
              " sign out).")
    except OSError:
        print("    Logged in.")
    return saved["token"], client_id, saved["accountId"]


# ══════════════════════════════════════════════════════════════

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        try:
            gif, info = load_source(args[0])
        except Exception as e:
            fail(f"could not prepare that GIF: {e}")
        what = "your GIF"
        print(f"Converted: {info}, {len(gif) / 1024:.1f} KB")
    else:
        gif, what = test_pattern(), "the test pattern"
    with open(os.path.join(HERE, "last_sent.gif"), "wb") as f:
        f.write(gif)
    if "--dry" in sys.argv:
        print(f"Wrote tools/last_sent.gif ({len(gif)} bytes). Nothing was sent.")
        return

    started = time.time()
    effect = base64.b64encode(PREFIX + gif).decode()
    # The fixed first chunk ships with the app (curtain_chunk1.txt next to
    # the main program); tools/chunk1.txt is an optional local copy.
    for name in (os.path.join(HERE, "..", "curtain_chunk1.txt"),
                 os.path.join(HERE, "chunk1.txt")):
        if os.path.exists(name):
            with open(name) as f:
                chunk1 = f.read().strip()
            break
    else:
        fail("curtain_chunk1.txt is missing")

    print(__doc__.split("It asks")[0].strip())
    print("\nYour API key and password are never saved or shown. After a successful login a\nsign-in token (not the password) is kept in tools/govee_token.json.\n")
    print("TIP: in a hidden prompt, paste with RIGHT-CLICK. Ctrl+V often types"
          "\n     one invisible character instead of pasting.\n")
    api_key = read_key_file()
    if api_key:
        print("Using the API key saved in tools/api_key.txt")
    else:
        api_key = clean(getpass.getpass("Govee developer API key (hidden): "))
        if not looks_like_key(api_key):
            print(f"    That came through as {len(api_key)} character(s); a Govee"
                  " key is 36 (letters, digits and 4 dashes).")
            print("    Paste it again - this time it will be visible.")
            api_key = clean(input("Govee developer API key: "))
    if not looks_like_key(api_key):
        fail(f"that is not a Govee API key ({len(api_key)} characters, expected"
             " 36).\n  The clipboard probably holds something else. Easiest fix:"
             " save the key in\n  tools/api_key.txt (see the top of this file)"
             " and run again.")
    print("    Key looks right: 36 characters")

    if not api_key:
        fail("the API key is needed.")

    # ── 1. find the curtain (official API) ──────────────────
    step(1, "Looking for Curtain Lights (H70B6) on your account...")
    status, data = request("GET", GOVEE_API + "/router/api/v1/user/devices",
                           api_headers(api_key), timeout=15)
    devices = data.get("data", []) if isinstance(data, dict) else []
    if status != 200 or not isinstance(devices, list):
        fail(f"device list failed (HTTP {status}): {short(data)}\n"
             f"  Govee did not accept the key it was sent ({len(api_key)} "
             "characters).\n"
             "  If the count is 36, the key itself is being refused: request a"
             " new one in the\n  Govee Home app (Profile > Settings > Apply for"
             " API Key) and use the one emailed to you.")
    curtains = [d for d in devices if d.get("sku") == SKU]
    print(f"    {len(devices)} Govee devices on the account, "
          f"{len(curtains)} of them H70B6.")
    if not curtains:
        fail("no H70B6 found on this account.")
    dev = curtains[0]
    dev_id, dev_name = dev["device"], dev.get("deviceName") or dev["device"]
    print(f"    Using: {dev_name}")

    # ── 2. log in like the phone app ────────────────────────
    step(2, "Logging in to Govee...")
    token, client_id, account_id = login()

    # ── 3. firmware versions (the upload wants them) ────────
    step(3, "Reading the curtain's firmware versions...")
    fw = {"bleSoftVersion": "0.0.0", "bleHardVersion": "0.0.0",
          "wifiSoftVersion": "0.0.0", "wifiHardVersion": "0.0.0"}
    status, data = request("POST", GOVEE_APP + "/device/rest/devices/v1/list",
                           app_headers(client_id, token), {"device": dev_id})
    listed = []
    if isinstance(data, dict):
        listed = data.get("devices") or (data.get("data") or {}).get("devices") or []
    match = next((d for d in listed if d.get("device") == dev_id),
                 listed[0] if listed else None)
    if match:
        fw = {"bleSoftVersion": match.get("bleSoftVersion") or match.get("versionSoft") or "0.0.0",
              "bleHardVersion": match.get("bleHardVersion") or match.get("versionHard") or "0.0.0",
              "wifiSoftVersion": match.get("wifiSoftVersion") or "0.0.0",
              "wifiHardVersion": match.get("wifiHardVersion") or "0.0.0"}
    print(f"    HTTP {status}: {fw}")

    def push(msg):
        body = {"msg": msg, "sku": SKU, "device": dev_id, **fw}
        return request("POST", GOVEE_APP + "/bff-app/v1/msg-channels?msgId=" + msg_id(),
                       app_headers(client_id, token), body)

    # ── 4. upload ───────────────────────────────────────────
    upload_started = time.time()
    step(4, f"Uploading (fixed first chunk, then {what})...")
    status, data = push(chunk1)
    print(f"    chunk 1: HTTP {status} - {short(data)}")
    time.sleep(0.5)
    status, data = push(effect)
    print(f"    {what} ({len(effect)} chars): HTTP {status} - {short(data)}")

    # ── 5. register it as a temporary DIY effect ────────────
    step(5, "Registering it as a temporary DIY effect...")
    status, data = request(
        "POST", GOVEE_APP + "/appsku/v1/diys/new-diys",
        app_headers(client_id, token),
        {"goodsType": GOODS_TYPE, "sku": SKU, "effects": [{
            "gifId": 2, "origin": 0, "diyName": DIY_NAME,
            "effectCode": EFFECT_CODE, "effectType": 0, "diyFrom": 0,
            "diyCode": DIY_CODE, "groupId": -1, "effectStr": effect,
            "whiteNoiseId": 0, "device": dev_id, "diyId": DIY_CODE,
            "voiceType": 0, "diyModeType": 0, "coverUrl": "",
            "createTime": int(time.time() * 1000), "sku": SKU, "on": False,
            "effectId": 0}]})
    rd = (data.get("data") or data) if isinstance(data, dict) else {}
    diy_id = (rd.get("diyIds") or [None])[0]
    effect_id = (rd.get("effectIds") or [None])[0]
    print(f"    HTTP {status}: diyId={diy_id} effectId={effect_id}")
    if not diy_id:
        fail(f"Govee did not accept the DIY: {short(data, 300)}")

    # ── 6. switch the curtain to it (official API) ──────────
    step(6, "Telling the curtain to play it...")
    status, data = request(
        "POST", GOVEE_API + "/router/api/v1/device/control", api_headers(api_key),
        {"requestId": "trig_" + str(int(time.time() * 1000)),
         "payload": {"sku": SKU, "device": dev_id, "capability": {
             "type": "devices.capabilities.dynamic_scene",
             "instance": "diyScene", "value": diy_id}}}, timeout=15)
    print(f"    HTTP {status}: {short(data, 200)}")
    playing_after = time.time() - upload_started

    # ── 7. tidy up the temporary effect ─────────────────────
    step(7, "Deleting the temporary effect from your account...")
    if effect_id:
        h = app_headers(client_id, token)
        h["content-length"] = "0"
        if account_id:
            h["accountid"] = str(account_id)
        status, data = request(
            "DELETE", GOVEE_APP + f"/app/rest/v1/diy?effectId={effect_id}", h)
        print(f"    HTTP {status}")

    print(f"\nDone. Upload to playing took {playing_after:.1f}s "
          f"({time.time() - started:.1f}s for the whole run).")
    if args:
        print("LOOK AT THE CURTAIN: it should be playing your GIF. Compare it with"
              "\ntools/last_sent.gif, which is exactly what was sent.")
    else:
        print("LOOK AT THE CURTAIN: it should be cycling red, green, blue,"
              "\nyellow, cyan, magenta, half a second each.")
    print("Tell Claude what you see, and paste the lines above "
          "(they contain no password, key or token).")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
    except urllib.error.URLError as e:
        print(f"\n  STOPPED: could not reach Govee ({e.reason}). "
              "Check the internet connection.")
