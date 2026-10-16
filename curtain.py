"""
Govee Light Controller - curtain GIFs
-------------------------------------
Plays GIFs on Govee Curtain Lights (H70B6). No UI code lives here.

The LAN protocol used for the room lights can only set one colour per
device, so pictures go through Govee's cloud instead, the way the Govee Home
phone app does it: sign in, upload a 30x32 GIF as a temporary "DIY" effect,
switch the curtain to it, delete the temporary effect. The curtain then loops
the GIF on its own. This needs an internet connection, a Govee account and a
free Govee developer API key.

The upload uses the phone app's private API, which Govee does not document
and may change. The method (and the fixed first chunk in
curtain_chunk1.txt) comes from the "Govee GIF Player" by a friend of the
author, used with permission.
"""

import base64
import io
import json
import os
import random
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from urllib.parse import unquote, urlsplit

from PIL import Image, ImageSequence

GOVEE_APP = "https://app2.govee.com"            # the phone app's (private) API
GOVEE_API = "https://openapi.api.govee.com"     # the official developer API
SKU = "H70B6"
W, H = 30, 32                                   # the curtain is 30 x 32 LEDs
GOODS_TYPE = 329
EFFECT_CODE = [864]
DIY_CODE = 71
DIY_NAME = "LumiaGIF"       # name of the temporary effect (as in the original)
PREFIX = bytes([0x50, 0x5D])
APP_VERSION = "7.3.15"
USER_AGENT = ("GoveeHome/7.3.15 (com.ihoment.GoVeeSensor; build:3; "
              "iOS 18.6.2) Alamofire/5.11.0")
BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
MAX_FRAMES = 100
MAX_DOWNLOAD = 10 * 1024 * 1024
TRUSTED_SITES = ("giphy.com", "tenor.com", "imgur.com")
# Where Twitch and YouTube serve profile pictures from
AVATAR_SITES = ("jtvnw.net", "ggpht.com", "googleusercontent.com")
IMAGE_ENDINGS = (".gif", ".png", ".jpg", ".jpeg", ".webp")


class CurtainError(Exception):
    """A problem worth showing to the user. `status` is the HTTP reply code
    the MixItUp server should answer with."""

    def __init__(self, message: str, status: int = 500):
        super().__init__(message)
        self.status = status


# ══════════════════════════════════════════════════════════════
#  GIF writer - produces the exact layout the curtain accepts
#  (global 256-colour table, full frames, no interlacing)
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


def encode_gif(palette, frames, delays_ms) -> bytes:
    """palette: up to 256 (r, g, b); frames: sequences of W*H palette indexes."""
    out = bytearray(b"GIF89a")
    out += W.to_bytes(2, "little") + H.to_bytes(2, "little")
    out += bytes([0xF7, 0, 0])                    # global table, 256 colours
    for i in range(256):
        out += bytes(palette[i] if i < len(palette) else (0, 0, 0))
    out += bytes([0x21, 0xFF, 0x0B]) + b"NETSCAPE2.0" + bytes([3, 1, 0, 0, 0])
    for frame, delay in zip(frames, delays_ms):
        d = max(2, round(delay / 10))
        out += bytes([0x21, 0xF9, 0x04, 0x04, d & 0xFF, (d >> 8) & 0xFF, 0, 0])
        out += bytes([0x2C, 0, 0, 0, 0])
        out += W.to_bytes(2, "little") + H.to_bytes(2, "little") + bytes([0])
        out += bytes([8])
        data = lzw_encode(frame, 8)
        for i in range(0, len(data), 255):
            block = data[i:i + 255]
            out += bytes([len(block)]) + block
        out += bytes([0])
    out += bytes([0x3B])
    return bytes(out)


def convert(data: bytes) -> tuple[bytes, str]:
    """Any GIF / image bytes -> (30x32 curtain GIF, short description).

    Centre-crops to the curtain's shape, shrinks, and reduces every frame to
    one shared 256-colour palette. Transparent areas become black (LEDs off).
    """
    try:
        src = Image.open(io.BytesIO(data))
        src.load()
    except Exception:
        raise CurtainError("That is not a GIF or picture the app can read", 415)
    sw, sh = src.size
    if sw / sh > W / H:
        cw, ch = max(1, int(sh * W / H)), sh
    else:
        cw, ch = sw, max(1, int(sw * H / W))
    left, top = (sw - cw) // 2, (sh - ch) // 2
    box = (left, top, left + cw, top + ch)

    small, delays = [], []
    total = getattr(src, "n_frames", 1)
    for i, frame in enumerate(ImageSequence.Iterator(src)):
        if i >= MAX_FRAMES:
            break
        rgba = frame.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (0, 0, 0))
        flat.paste(rgba, mask=rgba.getchannel("A"))
        small.append(flat.crop(box).resize((W, H), Image.BOX))
        delays.append(frame.info.get("duration") or 100)
    still = len(small) == 1
    if still:                 # a still picture: send it as two equal frames
        small.append(small[0])
        delays = [500, 500]

    sheet = Image.new("RGB", (W, H * len(small)))
    for i, im in enumerate(small):
        sheet.paste(im, (0, i * H))
    pal_img = sheet.quantize(colors=256, method=Image.MEDIANCUT,
                             dither=Image.Dither.NONE)
    flat_pal = pal_img.getpalette()[:768]
    palette = [tuple(flat_pal[i:i + 3]) for i in range(0, len(flat_pal), 3)]
    indexed = pal_img.tobytes()
    frames = [indexed[i * W * H:(i + 1) * W * H] for i in range(len(small))]
    info = "still picture" if still else f"{len(frames)} frames"
    if total > MAX_FRAMES:
        info += f" (first {MAX_FRAMES} of {total})"
    return encode_gif(palette, frames, delays), info


# ══════════════════════════════════════════════════════════════
#  Links
# ══════════════════════════════════════════════════════════════

def is_link(text: str) -> bool:
    return text.strip().lower().startswith(("http://", "https://"))


def is_trusted(url: str) -> bool:
    """True for Giphy / Tenor / Imgur addresses (moderated GIF libraries)."""
    return _host_in(url, TRUSTED_SITES)


def is_avatar_link(url: str) -> bool:
    """True for Twitch / YouTube profile-picture addresses."""
    return _host_in(url, AVATAR_SITES)


def _host_in(url: str, sites) -> bool:
    host = urlsplit(url).netloc.lower().split(":")[0]
    return any(host == s or host.endswith("." + s) for s in sites)


def fetch(url: str, limit: int = MAX_DOWNLOAD) -> bytes:
    req = urllib.request.Request(url, headers=BROWSER)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read(limit + 1)
    except urllib.error.HTTPError as e:
        raise CurtainError(f"The link answered with error {e.code}", 502)
    except (urllib.error.URLError, OSError) as e:
        raise CurtainError(f"Could not open the link ({getattr(e, 'reason', e)})",
                           502)
    if len(data) > limit:
        raise CurtainError(
            f"That file is larger than {limit // 1024 // 1024} MB", 413)
    return data


def resolve(url: str) -> str:
    """Turn a Giphy / Tenor / Imgur page link into the GIF file's address."""
    u = urlsplit(url)
    host, path = u.netloc.lower(), u.path
    if path.lower().endswith(IMAGE_ENDINGS):
        return url
    if host.endswith("giphy.com") or host == "gph.is":
        m = re.search(r"/media/(?:v1\.[^/]+/)?([A-Za-z0-9]+)/", path)
        gid = m.group(1) if m else path.rstrip("/").split("/")[-1].split("-")[-1]
        if host != "gph.is" and len(gid) >= 5:
            return f"https://media.giphy.com/media/{gid}/giphy.gif"
    if host.endswith("imgur.com"):
        gid = path.rstrip("/").split("/")[-1].split(".")[0]
        if gid and "/a/" not in path and "/gallery/" not in path:
            return f"https://i.imgur.com/{gid}.gif"
    # Tenor and anything else: find the GIF named in the page itself
    page = fetch(url, 2 * 1024 * 1024).decode("utf-8", "replace")
    page = page.replace("\\u002F", "/").replace("\\/", "/")
    found = re.findall(r'https://[^"\'\\<> ]+?\.gif', page)
    for prefer in ("tenor.com", "giphy.com", "imgur.com"):
        hits = [f for f in found if prefer in urlsplit(f).netloc]
        if hits:
            return hits[0]
    if found:
        return found[0]
    raise CurtainError("Could not find a GIF on that page", 404)


# ══════════════════════════════════════════════════════════════
#  Keeping secrets: encrypted for this Windows user where possible
# ══════════════════════════════════════════════════════════════

def _dpapi(data: bytes, encrypt: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = Blob()
    crypt32 = ctypes.windll.crypt32
    fn = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    if not fn(ctypes.byref(blob_in), None, None, None, None, 0,
              ctypes.byref(blob_out)):
        raise OSError("Windows data protection failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        free = ctypes.windll.kernel32.LocalFree
        free.argtypes = [ctypes.c_void_p]
        free(ctypes.cast(blob_out.pbData, ctypes.c_void_p))


def seal(text: str) -> str:
    """Encrypt for the current Windows user. Elsewhere: stored as it is."""
    if text and sys.platform == "win32":
        try:
            return "dpapi:" + base64.b64encode(
                _dpapi(text.encode(), True)).decode()
        except Exception:
            pass
    return text or ""


def unseal(text: str) -> str:
    if text and text.startswith("dpapi:"):
        try:
            return _dpapi(base64.b64decode(text[6:]), False).decode()
        except Exception:
            return ""          # another PC / another Windows user
    return text or ""


# ══════════════════════════════════════════════════════════════
#  Web requests
# ══════════════════════════════════════════════════════════════

_ctx = ssl.create_default_context()


def _request(method, url, headers, body=None, timeout=30):
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
    except (urllib.error.URLError, OSError) as e:
        raise CurtainError(
            f"Could not reach Govee ({getattr(e, 'reason', e)}). "
            "Is the internet connection up?", 502)
    try:
        return status, json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return status, raw.decode("utf-8", "replace")[:300]


def _short(data, n=140) -> str:
    if isinstance(data, dict):
        data = data.get("message") or data.get("msg") or json.dumps(data)
    return str(data)[:n]


def _msg_id() -> str:
    return str(int(time.time() * 1000)) + f"{random.randrange(10**6):06d}"


# ══════════════════════════════════════════════════════════════
#  The curtain
# ══════════════════════════════════════════════════════════════

class Curtain:
    """Govee account + GIF library + sending.

    Everything slow runs on a background thread; `state` and `rev` let a UI
    show progress (rev goes up whenever state changes).

    state["kind"]:  idle | working | playing | error
    """

    def __init__(self, folder: str, cfg: dict, save_cfg=None):
        self.folder = folder
        self.cfg = cfg                       # the app's config (live)
        self.save_cfg = save_cfg or (lambda: None)
        self.account_file = os.path.join(folder, "govee_account.json")
        self.gif_dir = os.path.join(folder, "gifs")
        self.state: dict = {"kind": "idle", "text": ""}
        self.rev = 0
        self.last: dict | None = None        # last GIF converted: gif, source
        self._lock = threading.Lock()
        self._busy = False
        self._pending = None                 # sign-in waiting for a code
        self._devices: list | None = None
        self._fw: dict = {}
        self._timer: threading.Timer | None = None   # show time running
        self._queue: deque = deque()                 # web GIFs waiting: (job, text)
        self._last_link = 0.0
        self._chunk1: str | None = None
        self.acct: dict = self._load_account()

    # ── account storage ─────────────────────────────────────

    def _load_account(self) -> dict:
        try:
            with open(self.account_file) as f:
                raw = json.load(f)
            return {k: unseal(v) if k in ("api_key", "token", "password")
                    else v for k, v in raw.items()}
        except (OSError, ValueError):
            return self._import_test_login()

    def _import_test_login(self) -> dict:
        """Carry over the key and sign-in made with tools/curtain_test.py."""
        acct = {}
        tools = os.path.join(self.folder, "tools")
        try:
            with open(os.path.join(tools, "api_key.txt"),
                      encoding="utf-8-sig") as f:
                acct["api_key"] = f.read().strip()
            with open(os.path.join(tools, "govee_token.json")) as f:
                t = json.load(f)
            acct.update(token=t["token"], clientId=t["clientId"],
                        accountId=t.get("accountId"))
        except (OSError, ValueError, KeyError):
            return acct if acct.get("api_key") else {}
        self.acct = acct
        self._save_account()
        return acct

    def _save_account(self):
        raw = {k: seal(v) if k in ("api_key", "token", "password") else v
               for k, v in self.acct.items() if v not in (None, "")}
        try:
            with open(self.account_file, "w") as f:
                json.dump(raw, f, indent=2)
        except OSError as e:
            print(f"Account save error: {e}")

    # ── what the UI asks ────────────────────────────────────

    def has_key(self) -> bool:
        return bool(self.acct.get("api_key"))

    def signed_in(self) -> bool:
        return bool(self.acct.get("token"))

    def ready(self) -> bool:
        return self.has_key() and self.signed_in()

    def waiting_for_code(self) -> bool:
        return self._pending is not None

    def busy(self) -> bool:
        return self._busy

    def gifs(self) -> list[dict]:
        return self.cfg.setdefault("gifs", [])

    def find(self, token: str) -> dict | None:
        key = _slug(token)
        for g in self.gifs():
            if key and _slug(g.get("name", "")) == key:
                return g
        return None

    def default(self) -> dict | None:
        return self.find(self.cfg.get("gif_default") or "")

    def path_of(self, gif: dict) -> str:
        return os.path.join(self.gif_dir, gif["file"])

    def _set(self, kind: str, text: str = "", **info):
        self.state = {"kind": kind, "text": text, **info}
        self.rev += 1

    # ── signing in ──────────────────────────────────────────

    def set_api_key(self, key: str):
        key = "".join(ch for ch in key if ch > " ").strip("\"'")
        if key != self.acct.get("api_key"):
            self.acct["api_key"] = key
            self._devices = None
            self._save_account()

    def _app_headers(self, token=None) -> dict:
        h = {"Content-Type": "application/json", "appversion": APP_VERSION,
             "clienttype": "1", "clientid": self.acct.get("clientId", ""),
             "timestamp": str(int(time.time() * 1000)),
             "timezone": "America/New_York", "country": "US",
             "user-agent": USER_AGENT, "accept": "*/*"}
        if token:
            h["Authorization"] = "Bearer " + token
        else:
            h["sysversion"] = "18.6.2"
        return h

    def _login(self, email, password, code=None):
        """One sign-in attempt. Returns "ok" or "code" (a code was emailed)."""
        if len(self.acct.get("clientId") or "") != 32:
            # The same "phone id" every time, so Govee recognises this PC
            self.acct["clientId"] = "".join(
                random.choice("0123456789abcdef") for _ in range(32))
            self._save_account()
        body = {"email": email, "client": self.acct["clientId"],
                "password": password}
        if code:
            body["code"] = code
        status, data = _request(
            "POST", GOVEE_APP + "/account/rest/account/v2/login",
            self._app_headers(), body)
        inner = data.get("status") if isinstance(data, dict) else None
        client = data.get("client") if isinstance(data, dict) else None
        if 454 in (status, inner):
            if code:
                raise CurtainError("Govee did not accept that code. Sign in "
                                   "again to get a new one.", 401)
            vs, vd = _request(
                "POST", GOVEE_APP + "/account/rest/account/v1/verification",
                self._app_headers(), {"type": 8, "email": email})
            if vs != 200:
                raise CurtainError(
                    f"Govee would not send a code: {_short(vd)}", 401)
            return "code"
        if not (status == 200 and inner == 200 and client
                and client.get("token")):
            raise CurtainError(
                f"Sign-in failed: {_short(data) or inner or status}", 401)
        self.acct.update(
            token=client["token"], email=email,
            clientId=client.get("client") or self.acct["clientId"],
            accountId=client.get("accountId"))
        if self.cfg.get("gif_remember", True):
            self.acct["password"] = password
        else:
            self.acct.pop("password", None)
        self._save_account()
        return "ok"

    def sign_in(self, email: str, password: str) -> str:
        """Returns "ok", or "code" when Govee emailed a verification code -
        then call verify(code)."""
        email = email.strip()
        if not (email and password):
            raise CurtainError("Enter the Govee email and password", 400)
        self._pending = None
        result = self._login(email, password)
        if result == "code":
            self._pending = (email, password)
        self.rev += 1
        return result

    def verify(self, code: str) -> str:
        if not self._pending:
            raise CurtainError("Sign in first", 400)
        code = "".join(ch for ch in code if ch.isalnum())
        if not code:
            raise CurtainError("Enter the code from the email", 400)
        email, password = self._pending
        try:
            return self._login(email, password, code)
        finally:
            self._pending = None
            self.rev += 1

    def sign_out(self):
        for k in ("token", "password", "accountId", "email"):
            self.acct.pop(k, None)
        self._pending = None
        self._save_account()
        self._set("idle")

    def _relogin(self) -> bool:
        """Renew an expired sign-in with the remembered password."""
        email, password = self.acct.get("email"), self.acct.get("password")
        if not (email and password):
            return False
        try:
            return self._login(email, password) == "ok"
        except CurtainError:
            return False

    # ── Govee requests ──────────────────────────────────────

    def _app(self, method, path, body=None, extra=None):
        """Phone-app API call; renews the sign-in once if it has expired."""
        for attempt in (0, 1):
            headers = self._app_headers(self.acct.get("token"))
            headers.update(extra or {})
            status, data = _request(method, GOVEE_APP + path, headers, body)
            inner = data.get("status") if isinstance(data, dict) else None
            if 401 not in (status, inner):
                return status, data
            if attempt == 0 and self._relogin():
                continue
            self.acct.pop("token", None)
            self._save_account()
            raise CurtainError("The Govee sign-in has expired. Sign in again "
                               "in Settings.", 401)

    def _api(self, method, path, body=None):
        status, data = _request(
            method, GOVEE_API + path,
            {"Govee-API-Key": self.acct.get("api_key", ""),
             "Content-Type": "application/json"}, body, timeout=15)
        if status == 401:
            raise CurtainError("Govee did not accept the API key. Check it "
                               "in Settings.", 401)
        if status == 429:
            raise CurtainError("Govee says too many requests. Wait a minute.",
                               429)
        return status, data

    def devices(self, refresh=False) -> list[dict]:
        """Curtain Lights on the account: [{"id", "name"}]."""
        if self._devices is None or refresh:
            status, data = self._api("GET", "/router/api/v1/user/devices")
            found = data.get("data") if isinstance(data, dict) else None
            if status != 200 or not isinstance(found, list):
                raise CurtainError(
                    f"Could not list Govee devices: {_short(data)}", 502)
            self._devices = [
                {"id": d["device"], "name": d.get("deviceName") or d["device"]}
                for d in found if d.get("sku") == SKU]
        return self._devices

    def _firmware(self, dev_id: str) -> dict:
        if dev_id not in self._fw:
            fw = {"bleSoftVersion": "0.0.0", "bleHardVersion": "0.0.0",
                  "wifiSoftVersion": "0.0.0", "wifiHardVersion": "0.0.0"}
            _, data = self._app("POST", "/device/rest/devices/v1/list",
                                {"device": dev_id})
            listed = []
            if isinstance(data, dict):
                listed = (data.get("devices")
                          or (data.get("data") or {}).get("devices") or [])
            match = next((d for d in listed if d.get("device") == dev_id),
                         listed[0] if listed else None)
            if match:
                fw = {"bleSoftVersion": match.get("bleSoftVersion")
                      or match.get("versionSoft") or "0.0.0",
                      "bleHardVersion": match.get("bleHardVersion")
                      or match.get("versionHard") or "0.0.0",
                      "wifiSoftVersion": match.get("wifiSoftVersion") or "0.0.0",
                      "wifiHardVersion": match.get("wifiHardVersion") or "0.0.0"}
            self._fw[dev_id] = fw
        return self._fw[dev_id]

    def _first_chunk(self) -> str:
        if self._chunk1 is None:
            try:
                with open(os.path.join(self.folder, "curtain_chunk1.txt")) as f:
                    self._chunk1 = f.read().strip()
            except OSError:
                self._chunk1 = ""
        return self._chunk1

    def _push(self, gif: bytes):
        """Upload a curtain GIF and make every curtain on the account play it."""
        if not self.has_key():
            raise CurtainError("Add your Govee API key in Settings", 503)
        if not self.signed_in():
            raise CurtainError("Sign in to Govee in Settings", 503)
        devices = self.devices()
        if not devices:
            raise CurtainError("No Curtain Lights (H70B6) on this Govee "
                               "account", 404)
        effect = base64.b64encode(PREFIX + gif).decode()
        staged = []
        for dev in devices:
            fw = self._firmware(dev["id"])
            common = {"sku": SKU, "device": dev["id"], **fw}
            if self._first_chunk():
                self._app("POST", "/bff-app/v1/msg-channels?msgId=" + _msg_id(),
                          {"msg": self._first_chunk(), **common})
                time.sleep(0.5)
            status, data = self._app(
                "POST", "/bff-app/v1/msg-channels?msgId=" + _msg_id(),
                {"msg": effect, **common})
            if status != 200:
                raise CurtainError(f"Upload failed: {_short(data)}", 502)
            status, data = self._app(
                "POST", "/appsku/v1/diys/new-diys",
                {"goodsType": GOODS_TYPE, "sku": SKU, "effects": [{
                    "gifId": 2, "origin": 0, "diyName": DIY_NAME,
                    "effectCode": EFFECT_CODE, "effectType": 0, "diyFrom": 0,
                    "diyCode": DIY_CODE, "groupId": -1, "effectStr": effect,
                    "whiteNoiseId": 0, "device": dev["id"], "diyId": DIY_CODE,
                    "voiceType": 0, "diyModeType": 0, "coverUrl": "",
                    "createTime": int(time.time() * 1000), "sku": SKU,
                    "on": False, "effectId": 0}]})
            rd = (data.get("data") or data) if isinstance(data, dict) else {}
            diy_id = (rd.get("diyIds") or [None])[0]
            if not diy_id:
                raise CurtainError(
                    f"Govee did not accept the GIF: {_short(data)}", 502)
            staged.append((dev, diy_id, (rd.get("effectIds") or [None])[0]))

        for dev, diy_id, _ in staged:
            status, data = self._api(
                "POST", "/router/api/v1/device/control",
                {"requestId": "trig_" + str(int(time.time() * 1000)),
                 "payload": {"sku": SKU, "device": dev["id"], "capability": {
                     "type": "devices.capabilities.dynamic_scene",
                     "instance": "diyScene", "value": diy_id}}})
            code = data.get("code") if isinstance(data, dict) else None
            if status != 200 or code not in (200, None):
                raise CurtainError(
                    f"{dev['name']} would not play it: {_short(data)}", 502)

        for _, _, effect_id in staged:            # tidy the temporary effect
            if effect_id:
                extra = {"content-length": "0"}
                if self.acct.get("accountId"):
                    extra["accountid"] = str(self.acct["accountId"])
                try:
                    self._app("DELETE",
                              f"/app/rest/v1/diy?effectId={effect_id}",
                              extra=extra)
                except CurtainError:
                    pass

    # ── background work ─────────────────────────────────────

    def _start(self, job, text: str):
        with self._lock:
            if self._busy:
                raise CurtainError("The curtain is still loading the last GIF",
                                   409)
            self._busy = True
        self._set("working", text)
        threading.Thread(target=self._run, args=(job,), daemon=True).start()

    def _run(self, job):
        try:
            job()
        except CurtainError as e:
            self._set("error", str(e))
        except Exception as e:                      # never kill the thread
            self._set("error", f"Something went wrong: {e}")
        finally:
            self._busy = False
            self.rev += 1
            if self.state.get("kind") == "error" and self._queue:
                self._arm(0.5)                      # skip it, play the next

    def _load(self, source: str, trusted_only=False, direct_link=False) -> bytes:
        """Curtain GIF for a link or a file path (remembered in self.last).
        direct_link: the link is the picture itself, don't go looking for one."""
        source = source.strip().strip('"')
        if is_link(source):
            direct = source if direct_link else resolve(source)
            if trusted_only and not is_trusted(direct):
                raise CurtainError("That link leads outside Giphy / Tenor / "
                                   "Imgur", 403)
            data = fetch(direct)
        else:
            try:
                with open(source, "rb") as f:
                    data = f.read(MAX_DOWNLOAD + 1)
            except OSError:
                raise CurtainError("That is not a link or a file on this PC",
                                   404)
        gif, info = convert(data)
        self.last = {"gif": gif, "source": source, "info": info}
        return gif

    # ── show time, queue, return to default ─────────────────
    #
    # A GIF from a web request (MixItUp) gets a "show time": it stays up for
    # that many seconds, then the next queued GIF plays, or - if nothing is
    # waiting - the default GIF comes back. A GIF played from the app itself
    # has no show time: it stays until something replaces it.

    def queue_length(self) -> int:
        return len(self._queue)

    def _show_seconds(self, seconds) -> float:
        if seconds is None:
            seconds = self.cfg.get("gif_web_seconds", 8)
        try:
            return max(0.0, min(3600.0, float(seconds)))
        except (TypeError, ValueError):
            return 0.0

    def _played(self, name: str, is_default: bool, show=None):
        """show: seconds this GIF is owed on the curtain (None = no limit)."""
        self._set("playing", name=name, since=time.time())
        self._cancel_timer()
        if show and not is_default:
            self._arm(show)
        elif self._queue:
            self._arm(0.3)

    def _arm(self, seconds: float):
        self._cancel_timer()
        self._timer = threading.Timer(seconds, self._next)
        self._timer.daemon = True
        self._timer.start()

    def _cancel_timer(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def _next(self):
        """Show time is up: play what is waiting, else go back to the default."""
        self._timer = None
        if self._busy:                              # e.g. a Save is running
            self._arm(1.5)
            return
        try:
            if self._queue:
                job, text = self._queue.popleft()
                self.rev += 1
                self._start(job, text)
            else:
                gif = self.default()
                if gif and self.state.get("name") != gif["name"]:
                    self._start(self._saved_job(gif, None),
                                f"Back to {gif['name']}…")
        except CurtainError:
            self._arm(1.5)

    def _begin(self, job, text: str, web: bool) -> str:
        """Start a play now, or queue it. Returns "sending" or "queued"."""
        if not web:
            self._queue.clear()                     # the app takes over
        elif self.cfg.get("gif_queue") and (self._busy or self._timer):
            if len(self._queue) >= int(self.cfg.get("gif_queue_max", 5)):
                raise CurtainError("The GIF queue is full, try again soon", 429)
            self._queue.append((job, text))
            self.rev += 1
            return "queued"
        self._start(job, text)                      # refuses if still loading
        self._cancel_timer()
        return "sending"

    # ── playing ─────────────────────────────────────────────

    def check_link(self, url: str):
        """Rules for links that come from chat. Raises CurtainError."""
        if not is_link(url):
            raise CurtainError("That is not a link", 400)
        if self.cfg.get("gif_strict", True) and not is_trusted(url):
            raise CurtainError("Only Giphy, Tenor and Imgur links are allowed",
                               403)
        wait = float(self.cfg.get("gif_cooldown") or 0) - \
            (time.time() - self._last_link)
        if wait > 0:
            raise CurtainError(f"GIF cooldown: wait {wait:.0f}s", 429)

    def play_source(self, source: str, from_chat=False, seconds=None) -> str:
        """Play a link or a local file. Returns at once ("sending" or
        "queued"); the work continues in the background.

        from_chat - a web request: applies the trusted-site rule and the
                    cooldown, and gives the GIF a show time (`seconds`, or the
                    setting) after which the default GIF returns.
        """
        source = (source or "").strip()
        if not source:
            raise CurtainError("Paste a GIF link first", 400)
        if from_chat:
            self.check_link(source)
        if not self.ready():
            raise CurtainError("Connect your Govee account in Settings", 503)
        show = self._show_seconds(seconds) if from_chat else None

        def job():
            gif = self._load(source, trusted_only=from_chat
                             and self.cfg.get("gif_strict", True))
            self._push(gif)
            self._played(_label(source), False, show)

        how = self._begin(job, "Sending GIF to the curtain…", web=from_chat)
        if from_chat:
            self._last_link = time.time()
        return how

    def play_avatar(self, url: str, seconds=None) -> str:
        """Web request: show a profile picture (Twitch / YouTube image links
        only). Still pictures work; no cooldown, MixItUp decides how often."""
        url = (url or "").strip()
        if not is_link(url) or not is_avatar_link(url):
            raise CurtainError("Only Twitch and YouTube profile picture links "
                               "are accepted here", 403)
        if not self.ready():
            raise CurtainError("Connect your Govee account in Settings", 503)
        show = self._show_seconds(seconds)

        def job():
            self._push(self._load(url, direct_link=True))
            self._played("a profile picture", False, show)

        return self._begin(job, "Sending a profile picture…", web=True)

    def _saved_job(self, gif: dict, show):
        is_default = _slug(gif["name"]) == _slug(self.cfg.get("gif_default") or "")

        def job():
            try:
                with open(self.path_of(gif), "rb") as f:
                    data = f.read()
            except OSError:
                raise CurtainError(f"The file for {gif['name']} is missing", 404)
            self._push(data)
            self._played(gif["name"], is_default, show)
        return job

    def play_saved(self, gif: dict, web=False, seconds=None) -> str:
        """Play a library GIF. web=True: a web request (show time applies)."""
        if not self.ready():
            raise CurtainError("Connect your Govee account in Settings", 503)
        show = self._show_seconds(seconds) if web else None
        return self._begin(self._saved_job(gif, show),
                           f"Sending {gif['name']} to the curtain…", web)

    def play_default(self, web=False) -> str:
        gif = self.default()
        if not gif:
            raise CurtainError("No default GIF is set", 404)
        return self.play_saved(gif, web=web)

    # ── library ─────────────────────────────────────────────

    def save(self, name: str, source: str = "") -> str:
        """Add a GIF to the library, from a link / file, or (no source) the
        one that was just played. Work continues in the background."""
        name = name.strip()
        if not _slug(name):
            raise CurtainError("Give the GIF a name", 400)
        source = (source or "").strip()
        reuse = self.last if (self.last and (not source or
                                             self.last["source"] == source)) \
            else None
        if not reuse and not source:
            raise CurtainError("Paste a GIF link first", 400)

        def job():
            gif = reuse["gif"] if reuse else self._load(source)
            os.makedirs(self.gif_dir, exist_ok=True)
            fname = _slug(name) + ".gif"
            with open(os.path.join(self.gif_dir, fname), "wb") as f:
                f.write(gif)
            items = [g for g in self.gifs() if _slug(g["name"]) != _slug(name)]
            items.append({"name": name, "file": fname,
                          "source": (reuse or self.last)["source"]})
            self.cfg["gifs"] = items
            self.save_cfg()
            self._set("idle", f"Saved {name}")

        self._start(job, f"Saving {name}…")
        return "saving"

    def remove(self, gif: dict):
        self.cfg["gifs"] = [g for g in self.gifs() if g is not gif]
        if _slug(self.cfg.get("gif_default") or "") == _slug(gif["name"]):
            self.cfg["gif_default"] = ""
        try:
            os.remove(self.path_of(gif))
        except OSError:
            pass
        self.save_cfg()
        self.rev += 1

    def set_default(self, gif: dict | None):
        self.cfg["gif_default"] = gif["name"] if gif else ""
        self.save_cfg()
        self.rev += 1

    def close(self):
        self._queue.clear()
        self._cancel_timer()


def _slug(text) -> str:
    return "".join(ch for ch in str(text).lower() if ch.isalnum())


def _label(source: str) -> str:
    """Short name for a link or path, for the status line."""
    if is_link(source):
        u = urlsplit(source)
        tail = unquote(u.path.rstrip("/").split("/")[-1]) or u.netloc
        host = u.netloc.lower().replace("www.", "").replace("media.", "")
        return f"{host.split('.')[0]}: {tail[:28]}"
    return os.path.basename(source)[:40]
