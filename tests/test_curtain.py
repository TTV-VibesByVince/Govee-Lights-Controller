"""Curtain tests: curtain mode, Govee sign-in, GIF upload, library, chat
rules, show time, queue and profile pictures. Govee is replaced by a fake,
links are never fetched, and everything is written to a temp folder.
Run:  python tests/test_curtain.py"""
import base64, io, json, os, shutil, sys, tempfile, threading, time, urllib.request, urllib.error

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
import engine, server, curtain
from PIL import Image

fails = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (("  " + str(extra)) if extra and not cond else ""))
    if not cond: fails.append(name)

# ── fake Govee ────────────────────────────────────────────────
calls = []
G = {"need_code": True, "token_ok": {"TOK1"}, "next_token": 1, "reject_diy": False, "api_key": "k" * 36}
def fake(method, url, headers, body=None, timeout=30):
    path = url.split(".com", 1)[1]
    calls.append((method, path.split("?")[0], body, dict(headers)))
    if url.startswith(curtain.GOVEE_API):
        if headers.get("Govee-API-Key") != G["api_key"]: return 401, {"message": "bad key"}
        if path.endswith("/user/devices"):
            return 200, {"data": [{"sku": "H6076", "device": "AA"}, {"sku": "H70B6", "device": "CUR1", "deviceName": "Curtain Lights Pro"}]}
        return 200, {"code": 200, "msg": "success"}
    if path.endswith("/v2/login"):
        if G["need_code"] and "code" not in body: return 200, {"status": 454, "message": ""}
        if body.get("code") not in (None, "1234"): return 200, {"status": 454, "message": ""}
        if body["password"] != "pw": return 200, {"status": 400, "message": "wrong password"}
        tok = "TOK%d" % G["next_token"]; G["next_token"] += 1; G["token_ok"] = {tok}
        return 200, {"status": 200, "client": {"token": tok, "client": body["client"], "accountId": 9}}
    if path.endswith("/v1/verification"): return 200, {"status": 200, "message": "sent"}
    if headers.get("Authorization", "")[7:] not in G["token_ok"]: return 401, {"status": 401, "message": "please login"}
    if "devices/v1/list" in path: return 200, {"devices": [{"device": "CUR1", "bleSoftVersion": "1.01.27", "bleHardVersion": "3.08.01"}]}
    if "msg-channels" in path: return 200, {"message": "Success"}
    if "new-diys" in path:
        return (200, {"status": 400, "message": "nope"}) if G["reject_diy"] or body["effects"][0]["effectStr"] == G.get("reject_effect") else (200, {"data": {"diyIds": [555], "effectIds": [777]}})
    if method == "DELETE": return 200, {}
    return 404, {}
curtain._request = fake

def gif_bytes(frames=3, size=(64, 48), color=(200, 30, 30)):
    ims = [Image.new("RGB", size, tuple((c + i * 20) % 256 for c in color)) for i in range(frames)]
    b = io.BytesIO(); ims[0].save(b, "GIF", save_all=True, append_images=ims[1:], duration=80, loop=0); return b.getvalue()
fetched = []
curtain.fetch = lambda url, limit=0: (fetched.append(url), gif_bytes())[1]
curtain.resolve = lambda url: url if url.endswith(".gif") else ("https://evil.example/x.gif" if "redirect" in url else "https://media.giphy.com/media/abc12/giphy.gif" if "giphy" in url else url + ".gif")

tmp = tempfile.mkdtemp(prefix="govee_v11_")
shutil.copy(os.path.join(PROJ, "curtain_chunk1.txt"), tmp)
cfg = json.loads(json.dumps(engine.DEFAULT_CONFIG)); saved = []; cfg["gif_web_seconds"] = 0
C = curtain.Curtain(tmp, cfg, lambda: saved.append(1))
def wait(c=None, t=8):
    c = c or C; end = time.time() + t
    while time.time() < end and c.busy(): time.sleep(0.02)
    time.sleep(0.05)

# ── 1. curtain mode (engine) ─────────────────────────────────
old = {"excluded_skus": ["H70B6"], "lights": [{"ip": "1", "sku": "H70B6", "name": "Curtain", "enabled": False}, {"ip": "2", "sku": "H6076", "name": "Lamp", "enabled": True}]}
p = os.path.join(tmp, "cfg.json"); json.dump(old, open(p, "w")); real = engine.CONFIG_FILE; engine.CONFIG_FILE = p
m = engine.load_config(); engine.CONFIG_FILE = real
check("old config migrates: H70B6 moves from excluded to curtain models", m["curtain_skus"] == ["H70B6"] and m["excluded_skus"] == [] and m["gif_strict"] is True)
cur, lamp = m["lights"]
check("curtain switched off = GIF mode, not in room", engine.in_gif_mode(m, cur) and engine.is_excluded(m, cur) and [l["ip"] for l in engine.room_lights(m)] == ["2"])
cur["enabled"] = True
check("curtain switched on = follows room commands", not engine.in_gif_mode(m, cur) and not engine.is_excluded(m, cur) and [l["ip"] for l in engine.room_lights(m)] == ["1", "2"])
lamp["enabled"] = False
check("an ordinary light switched off is just off (not GIF mode)", not engine.in_gif_mode(m, lamp) and not engine.is_curtain(m, lamp) and [l["ip"] for l in engine.room_lights(m)] == ["1"])
m["excluded_skus"] = ["H70B6"]
check("excluded_skus still hard-excludes", engine.is_excluded(m, cur))

# ── 2. sign in ───────────────────────────────────────────────
check("fresh: not ready", not C.ready() and not C.has_key())
C.set_api_key("  " + G["api_key"] + " ")
check("device list via API key", C.devices() == [{"id": "CUR1", "name": "Curtain Lights Pro"}])
r = C.sign_in("me@x.com", "pw")
check("first sign-in asks for a code and requests the email", r == "code" and C.waiting_for_code() and calls[-1][1].endswith("/v1/verification") and calls[-1][2] == {"type": 8, "email": "me@x.com"})
try: C.verify("0000"); bad = False
except curtain.CurtainError as e: bad = "code" in str(e)
check("wrong code is refused", bad and not C.signed_in())
C.sign_in("me@x.com", "pw"); r = C.verify(" 1234 ")
ids = {c[3].get("clientid") for c in calls if "/account/" in c[1]}
check("right code signs in; same client id throughout", r == "ok" and C.ready() and len(ids) == 1 and len(ids.pop()) == 32)
raw = open(C.account_file).read()
check("account file holds no readable secrets", "pw" not in json.loads(raw).get("password", "") and "TOK" not in raw and G["api_key"] not in raw and "dpapi:" in raw, raw[:200])
C2 = curtain.Curtain(tmp, cfg)
check("a new start reads the saved sign-in back", C2.ready() and C2.acct["token"] == C.acct["token"] and C2.acct["api_key"] == G["api_key"] and C2.acct["password"] == "pw")
G["need_code"] = False
try: C.sign_in("me@x.com", "wrong"); bad = False
except curtain.CurtainError as e: bad = "wrong password" in str(e)
check("wrong password gives Govee's message", bad)
G["need_code"] = False

# ── 3. play a link ───────────────────────────────────────────
calls.clear()
check("play returns at once", C.play_source("https://giphy.com/gifs/cat-abc12") == "sending" and C.busy() and C.state["kind"] == "working")
try: C.play_source("https://giphy.com/gifs/other-zzzzz"); busy = False
except curtain.CurtainError as e: busy = e.status == 409
check("second play while busy is refused (409)", busy)
wait()
seq = [(m, p) for m, p, b, h in calls]
want = [("POST", "/device/rest/devices/v1/list"), ("POST", "/bff-app/v1/msg-channels"), ("POST", "/bff-app/v1/msg-channels"), ("POST", "/appsku/v1/diys/new-diys"), ("POST", "/router/api/v1/device/control"), ("DELETE", "/app/rest/v1/diy")]
check("upload sequence: firmware, chunk 1, GIF, register, play, delete", seq == want, seq)
first, second = calls[1][2]["msg"], calls[2][2]["msg"]
sent = base64.b64decode(second)
im = Image.open(io.BytesIO(sent[2:]))
check("chunk 1 is the fixed data; chunk 2 is a 30x32 GIF with the Govee prefix", first == open(os.path.join(tmp, "curtain_chunk1.txt")).read().strip() and sent[:2] == b"P]" and im.size == (30, 32) and im.n_frames == 3 and calls[2][2]["bleSoftVersion"] == "1.01.27")
check("play command carries the registered id", calls[4][2]["payload"]["capability"] == {"type": "devices.capabilities.dynamic_scene", "instance": "diyScene", "value": 555} and calls[4][2]["payload"]["device"] == "CUR1")
check("state says playing", C.state["kind"] == "playing" and "giphy" in C.state["name"], C.state)

# ── 4. library ───────────────────────────────────────────────
n = len(calls); C.save("Hype Cat"); wait()
g = C.find("hype-cat")
check("save reuses the GIF just played (no new download, nothing sent)", g and os.path.exists(C.path_of(g)) and len(calls) == n and len(fetched) == 1 and saved and cfg["gifs"][0]["source"].startswith("https://giphy"), (cfg["gifs"], len(fetched)))
C.save("Second", "https://tenor.com/view/x-1"); wait()
check("save from a link without playing", C.find("second") and len(fetched) == 2 and len(calls) == n)
calls.clear(); C.play_saved(g); wait()
check("play a saved GIF sends the stored file", base64.b64decode(calls[1][2]["msg"])[2:] == open(C.path_of(g), "rb").read() and C.state == {"kind": "playing", "text": "", "name": "Hype Cat", "since": C.state["since"]})
C.set_default(g); C.remove(C.find("second"))
check("default + remove", cfg["gif_default"] == "Hype Cat" and len(cfg["gifs"]) == 1 and not os.path.exists(os.path.join(tmp, "gifs", "second.gif")))

# ── 5. chat rules ────────────────────────────────────────────
def err(fn):
    try: fn(); return None
    except curtain.CurtainError as e: return e.status
cfg["gif_cooldown"] = 0
check("chat: other sites refused (403)", err(lambda: C.play_source("https://evil.example/a.gif", from_chat=True)) == 403)
check("chat: not a link refused (400), local files can't be read", err(lambda: C.play_source(r"C:\Windows\win.ini", from_chat=True)) == 400)
C.play_source("https://giphy.com/redirect-me", from_chat=True); wait()
check("chat: trusted page that leads elsewhere is refused", C.state["kind"] == "error" and "outside" in C.state["text"], C.state)
cfg["gif_cooldown"] = 30; C._last_link = 0
a = err(lambda: C.play_source("https://giphy.com/gifs/a-abc12", from_chat=True)); wait()
b = err(lambda: C.play_source("https://giphy.com/gifs/a-abc12", from_chat=True))
check("chat: cooldown (first plays, second 429)", a is None and b == 429, (a, b))
check("the app's own box ignores the chat rules", err(lambda: C.play_source("https://evil.example/a.gif")) is None); wait()
cfg["gif_strict"] = False; cfg["gif_cooldown"] = 0
check("strict off: any .gif link from chat", err(lambda: C.play_source("https://evil.example/a.gif", from_chat=True)) is None); wait()
cfg["gif_strict"] = True

# ── 6. return to default ─────────────────────────────────────
cfg["gif_web_seconds"] = 0.6; cfg["gif_cooldown"] = 0; calls.clear()
C.play_source("https://giphy.com/gifs/cat-abc12", from_chat=True); wait(); time.sleep(0.9); wait()
plays = [c for c in calls if c[1].endswith("/device/control")]
check("after N seconds the default GIF comes back", len(plays) == 2 and C.state.get("name") == "Hype Cat", (len(plays), C.state))
time.sleep(0.9)
check("the default itself does not loop back again", len([c for c in calls if c[1].endswith("/device/control")]) == 2)
cfg["gif_web_seconds"] = 0

# ── 7. problems ──────────────────────────────────────────────
G["token_ok"] = set(); calls.clear()                  # sign-in expired
C.play_saved(g); wait()
check("expired sign-in renews itself with the kept password", C.state["kind"] == "playing" and any(c[1].endswith("/v2/login") for c in calls), C.state)
G["token_ok"] = set(); C.acct.pop("password")
C.play_saved(g); wait()
check("without a kept password it asks to sign in again", C.state["kind"] == "error" and "Sign in again" in C.state["text"] and not C.signed_in(), C.state)
check("not signed in: play refused (503)", err(lambda: C.play_saved(g)) == 503)
G["need_code"] = False; C.sign_in("me@x.com", "pw")
G["reject_diy"] = True; C.play_saved(g); wait()
check("Govee rejecting the GIF is reported, app keeps working", C.state["kind"] == "error" and "did not accept" in C.state["text"] and not C.busy(), C.state); G["reject_diy"] = False
curtain.fetch = lambda url, limit=0: b"<html>not a gif</html>"
C.play_source("https://giphy.com/gifs/cat-abc12"); wait()
check("a link that is not an image is reported", C.state["kind"] == "error" and "not a GIF" in C.state["text"], C.state)
curtain.fetch = lambda url, limit=0: gif_bytes(frames=130, size=(40, 40))
C.play_source("https://giphy.com/gifs/long-abc12"); wait()
check("long GIFs are capped at 100 frames", C.last["info"] == "100 frames (first 100 of 130)" and C.state["kind"] == "playing", C.last["info"])

# ── 8. MixItUp URLs ──────────────────────────────────────────
curtain.fetch = lambda url, limit=0: gif_bytes()
e = engine.EffectsEngine(); e.cfg = cfg; e.lights = []
logged = []
s = server.start_server(e, 8795, logged.append, curtain=C)
def get(path):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8795" + path, timeout=5) as r: return r.status, r.read().decode()
    except urllib.error.HTTPError as ex: return ex.code, ex.read().decode()
cfg["gif_cooldown"] = 0
r1 = get("/gif/hype-cat"); r1b = get("/gif/hypecat"); wait()
r2 = get("/gif/default"); wait()
r3 = get("/gif/nope"); r4 = get("/gif")
r5 = get("/gif?url=https://giphy.com/gifs/cat-abc12?x=1&y=2"); wait()
r6 = get("/gif?url=https://evil.example/a.gif")
r7 = get("/gif?url=https%3A%2F%2Ftenor.com%2Fview%2Fa-1"); wait()
check("/gif/<name>, busy reply, /gif/default", r1 == (200, "GIF: Hype Cat (sending)") and r1b[0] == 409 and r2 == (200, "GIF: default (sending)"), (r1, r1b, r2))
check("/gif unknown name 404, bare /gif 400", r3 == (404, "Unknown GIF: nope") and r4[0] == 400, (r3, r4))
check("/gif?url= keeps the whole link, refuses other sites, accepts encoded links", r5 == (200, "GIF link (sending)") and C.last and r6[0] == 403 and r7 == (200, "GIF link (sending)"), (r5, r6, r7))
s2 = server.start_server(e, 8796, None)
try:
    with urllib.request.urlopen("http://127.0.0.1:8796/gif/x", timeout=5) as r: nocur = r.status
except urllib.error.HTTPError as ex: nocur = ex.code
check("server without a curtain answers 503", nocur == 503)
check("old URLs untouched by /gif", get("/status")[0] == 200 and get("/nope")[0] == 404)

# ══════════════ V1.2 ══════════════
def controls(): return [c for c in calls if c[1].endswith("/device/control")]
def sent_gifs():   # the GIF bytes of each upload, in order (skipping chunk 1)
    chunk1 = open(os.path.join(tmp, "curtain_chunk1.txt")).read().strip()
    return [c[2]["msg"] for c in calls if "msg-channels" in c[1] and c[2]["msg"] != chunk1]
def idle(t=12):
    end = time.time() + t
    while time.time() < end and (C.busy() or C._timer or C.queue_length()): time.sleep(0.03)
    time.sleep(0.1)
# three recognisable saved GIFs
for nm, col in (("Red", (250, 0, 0)), ("Green", (0, 250, 0)), ("Blue", (0, 0, 250))):
    curtain.fetch = lambda url, limit=0, col=col: gif_bytes(color=col)
    C.save(nm, "https://giphy.com/gifs/%s-abc12" % nm.lower()); wait()
def b64_of(name): return base64.b64encode(b"P]" + open(C.path_of(C.find(name)), "rb").read()).decode()
RED, GREEN, BLUE, HYPE = b64_of("Red"), b64_of("Green"), b64_of("Blue"), b64_of("Hype Cat")
check("V1.2 defaults: show time 8s, queue off", engine.DEFAULT_CONFIG["gif_web_seconds"] == 8 and engine.DEFAULT_CONFIG["gif_queue"] is False and "gif_return_seconds" not in engine.DEFAULT_CONFIG)

# show time: web request returns to default, the app's own play stays
cfg["gif_web_seconds"] = 0.6; cfg["gif_queue"] = False; calls.clear()
C.play_saved(C.find("red"), web=True); idle()
check("web request: GIF, then default after the show time", sent_gifs() == [RED, HYPE] and C.state.get("name") == "Hype Cat", [g[:12] for g in sent_gifs()])
calls.clear(); C.play_saved(C.find("red")); wait(); time.sleep(1.2)
check("played from the app: stays (no return)", sent_gifs() == [RED] and C.state.get("name") == "Red" and C._timer is None)
calls.clear(); r = get("/gif/green?seconds=1.5"); wait(); t0 = time.time(); time.sleep(0.9); mid = len(controls()); idle()
check("?seconds= overrides the show time for one request", r == (200, "GIF: Green (sending)") and mid == 1 and sent_gifs() == [GREEN, HYPE] and time.time() - t0 > 1.3, (r, mid, time.time() - t0))
cfg["gif_web_seconds"] = 0; calls.clear(); C.play_saved(C.find("blue"), web=True); wait(); time.sleep(0.8)
check("show time 0 = stay", sent_gifs() == [BLUE] and C._timer is None)

# queue
cfg["gif_web_seconds"] = 0.8; cfg["gif_queue"] = True; calls.clear()
r1 = get("/gif/red"); r2 = get("/gif/green"); r3 = get("/gif/blue")
q = C.queue_length(); idle(20)
times = [c for c in calls if c[1].endswith("/device/control")]
check("queue: first sends, the rest wait", (r1, r2, r3) == ((200, "GIF: Red (sending)"), (200, "GIF: Green (queued)"), (200, "GIF: Blue (queued)")) and q == 2, (r1, r2, r3, q))
check("queue: plays in order, then the default", sent_gifs() == [RED, GREEN, BLUE, HYPE] and C.state.get("name") == "Hype Cat" and C.queue_length() == 0, [g[:10] for g in sent_gifs()])
cfg["gif_queue_max"] = 2; calls.clear()
rs = [get("/gif/red"), get("/gif/green"), get("/gif/blue"), get("/gif/red")]
check("queue: full queue refuses (429)", [r[0] for r in rs] == [200, 200, 200, 429], rs); idle(20); cfg["gif_queue_max"] = 5
calls.clear(); get("/gif/red"); get("/gif/green"); get("/gif/blue"); wait(); C.play_saved(C.find("Hype Cat")); idle()
check("queue: a play from the app clears what is waiting", C.queue_length() == 0 and sent_gifs()[-1] == HYPE and GREEN not in sent_gifs(), [g[:10] for g in sent_gifs()])
calls.clear(); G["reject_effect"] = GREEN                 # Govee will refuse the 2nd one
get("/gif/red"); get("/gif/green"); get("/gif/blue"); idle(20); G["reject_effect"] = None
names = {RED: "red", GREEN: "green", BLUE: "blue", HYPE: "default"}
played = [names[c[2]["effects"][0]["effectStr"]] for c in calls if c[1].endswith("new-diys")]
check("queue: a refused GIF is skipped, the rest still play", played == ["red", "green", "blue", "default"] and len(controls()) == 3 and C.state.get("name") == "Hype Cat", (played, len(controls()), C.state))
cfg["gif_queue"] = False; calls.clear()
ra = get("/gif/red"); rb = get("/gif/green"); idle()
check("queue off: second one is refused while loading (409)", ra[0] == 200 and rb[0] == 409)

# avatars
def png(color=(10, 200, 120)):
    b = io.BytesIO(); Image.new("RGB", (300, 300), color).save(b, "PNG"); return b.getvalue()
asked = []
curtain.fetch = lambda url, limit=0: (asked.append(url), png())[1]
curtain.resolve = lambda url: (_ for _ in ()).throw(AssertionError("avatar links must not be resolved"))
cfg["gif_web_seconds"] = 0.6; cfg["gif_cooldown"] = 60; C._last_link = time.time(); calls.clear()
av = "https://static-cdn.jtvnw.net/jtv_user_pictures/abc-profile_image-300x300.png"
r = get("/gif/avatar?url=" + av); wait()
pic = Image.open(io.BytesIO(base64.b64decode(sent_gifs()[0])[2:]))
check("avatar: Twitch picture plays (no cooldown, fetched directly)", r == (200, "Profile picture (sending)") and asked == [av] and C.state.get("name") in ("a profile picture", "Hype Cat"), (r, asked))
check("avatar: still picture becomes a two-frame 30x32 GIF", pic.size == (30, 32) and pic.n_frames == 2 and pic.convert("RGB").getpixel((5, 5))[1] > 150, (pic.size, pic.n_frames))
idle(); check("avatar: default GIF returns afterwards", sent_gifs()[-1] == HYPE)
r1 = get("/gif/avatar?url=https://evil.example/me.png"); r2 = get("/gif/avatar?url=https://giphy.com/gifs/x-abc12"); r3 = get("/gif/avatar")
check("avatar: other sites refused (403)", (r1[0], r2[0], r3[0]) == (403, 403, 403), (r1, r2, r3))
calls.clear(); r = get("/gif/avatar?url=" + av + "&seconds=1.4"); wait(); t0 = time.time(); time.sleep(0.9); n = len(controls()); idle()
check("avatar: &seconds= at the end is not part of the link", r[0] == 200 and asked[-1] == av and n == 1 and len(controls()) == 2, (asked[-1], n))
r = get("/gif/avatar?url=https%3A%2F%2Fyt3.ggpht.com%2Fabc%3Ds88"); idle()
check("avatar: YouTube picture, encoded link", r[0] == 200 and asked[-1] == "https://yt3.ggpht.com/abc=s88", (r, asked[-1]))
cfg["gif_cooldown"] = 0
check("old /gif replies unchanged", get("/gif/nope") == (404, "Unknown GIF: nope") and get("/gif")[0] == 400); idle()

C.close(); shutil.rmtree(tmp, ignore_errors=True)
print("\nFAILED:", fails if fails else "none")
sys.exit(1 if fails else 0)
