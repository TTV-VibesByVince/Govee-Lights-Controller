"""Engine + MixItUp server tests (effects, queue, scenes, options).
Nothing goes on the network: send_udp is replaced by a recorder and the
lights are made-up addresses.  Run:  python tests/test_server.py"""
import json, os, sys, threading, time, urllib.request, urllib.error

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
import engine, server

sent = []                      # (time, ip, cmd, value)
def rec(ip, payload):
    d = payload["data"]
    sent.append((time.time(), ip, payload["cmd"], d.get("color") and (d["color"]["r"], d["color"]["g"], d["color"]["b"]) or d.get("value")))
engine.send_udp = rec
engine.save_config = lambda cfg: None

fails = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (("  " + str(extra)) if extra and not cond else ""))
    if not cond: fails.append(name)

def get(port, path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as ex:
        return ex.code, ex.read().decode()

# ── 1. every URL from the original v8 still answers exactly the same ──
CFG = {"effect_duration": 0.6, "strobe_interval": 0.05, "restore_after_effect": True,
       "default_color": {"r": 1, "g": 2, "b": 3}}
golden = json.load(open(os.path.join(PROJ, "tests", "v8_replies.json"), encoding="utf-8"))["replies"]
e0 = engine.EffectsEngine(); e0.cfg = dict(CFG); e0.lights = []
s0 = server.start_server(e0, 8792, None)
bad = []
for u, (st, body) in golden.items():
    got = get(8792, u)
    if got != (st, body.replace("{VERSION}", engine.APP_VERSION)): bad.append((u, got, (st, body)))
    time.sleep(0.02)
check(f"{len(golden)} original URLs answer exactly like v8", not bad, bad)
e0.stop()

# ── 2. new URLs ─────────────────────────────────────────────────
LIGHTS = [{"ip": "10.9.9.1", "name": "Floor Lamp", "sku": "H6076", "enabled": True},
          {"ip": "10.9.9.2", "name": "TV", "sku": "H6042", "enabled": True},
          {"ip": "10.9.9.3", "name": "Wall", "sku": "H6062", "enabled": True},
          {"ip": "10.9.9.4", "name": "Wall", "sku": "H6062", "enabled": True},
          {"ip": "10.9.9.5", "name": "Curtain", "sku": "H70B6", "enabled": False}]
cfg = dict(engine.DEFAULT_CONFIG); cfg.update(CFG); cfg["lights"] = LIGHTS
cfg["effect_duration"] = 0.5
cfg["alerts"] = [{"name": "Raid", "effect": "chase", "color": "red", "color2": "blue", "seconds": 0.5, "speed": "max"},
                 {"name": "sub", "effect": "alternate", "color": "gold", "color2": "purple", "seconds": 0.5, "speed": None}]
cfg["scenes"] = []
e = engine.EffectsEngine(); e.cfg = cfg; e.lights = engine.room_lights(cfg)
logged = []
s = server.start_server(e, 8793, logged.append)
P = 8793
check("room lights exclude H70B6", [l["ip"] for l in e.lights] == ["10.9.9.1", "10.9.9.2", "10.9.9.3", "10.9.9.4"])

expect = {
 "/chase/red": (200, "chase/red"), "/chase/red/2": (200, "chase/red/2"), "/red-chase/forever": (200, "chase/red/forever"),
 "/breathe/blue": (200, "breathe/blue"), "/blue-breathe": (200, "breathe/blue"), "/sparkle/purple": (200, "sparkle/purple"),
 "/flicker": (200, "flicker"), "/flicker/blue/3": (200, "flicker/blue/3"), "/lightning": (200, "lightning"),
 "/police": (200, "police"), "/police/forever": (200, "police/forever"), "/alternate/red/blue": (200, "alternate/red/blue"),
 "/alternate": (200, "alternate/red/blue"), "/fade/blue/1": (200, "fade/blue/1"), "/fade": (400, "Fade needs a color, e.g. /fade/blue/3"),
 "/fade/blue/forever": (200, "fade/blue"), "/countdown/1": (200, "countdown/1"), "/chase/ff0080": (200, "chase/ff0080"),
 "/scene/nope": (404, "Unknown scene: nope"), "/alert/nope": (404, "Unknown alert: nope"),
 "/light/nobody/red": (404, "Unknown light: nobody"), "/light/curtain/red": (403, "Excluded light: curtain"),
 "/light/tv/red": (200, "Light TV: red"), "/light/floor-lamp/off": (200, "Light Floor Lamp: off"),
 "/light/Floor%20Lamp/on": (200, "Light Floor Lamp: on"), "/light/10.9.9.3/00ff00": (200, "Light Wall: 00ff00"),
 "/light/tv": (400, "Use /light/<name>/<color|on|off>"), "/strobe/red?speed=fast&brightness=40&seconds=1": (200, "strobe/red"),
 "/red?brightness=30": (200, "Color: red"), "/queue": (200, f"Govee Light Controller {engine.APP_VERSION} running!"),
}
wrong = []
for u, want in expect.items():
    got = get(P, u)
    if got != want: wrong.append((u, got, want))
    time.sleep(0.03)
check("new URL replies", not wrong, wrong)
e.stop(); time.sleep(0.4)
check("curtain never sent anything", not [x for x in sent if x[1] == "10.9.9.5"])

def wait_idle(t=6):
    end = time.time() + t
    while time.time() < end and (e._active or e.now.get("kind") == "effect"): time.sleep(0.02)
    time.sleep(0.25)

# ── 3. each new effect actually sends and ends ──────────────────
for fx, kw in (("chase", {"rgb": (255, 0, 0)}), ("alternate", {"rgb": (255, 0, 0), "rgb2": (0, 0, 255)}), ("police", {}),
               ("flicker", {}), ("breathe", {"rgb": (0, 0, 255)}), ("lightning", {}), ("sparkle", {"rgb": (9, 9, 9)}),
               ("countdown", {}), ("fade", {"rgb": (10, 20, 30), "name": "x"})):
    sent.clear(); e.set_color(200, 200, 200); t0 = time.time()
    e.play(fx, duration=0.5, **kw); time.sleep(0.15)
    running = e.now.get("kind") == "effect" and e.now.get("effect") == fx
    wait_idle()
    n = len([x for x in sent if x[2] == "colorwc"])
    end_ok = e.now.get("kind") == "color" and (e.now.get("rgb") == (10, 20, 30) if fx == "fade" else e.now.get("label") == "default")
    check(f"effect {fx}: runs, sends ({n}), ends in {time.time()-t0:.1f}s", running and n > 3 and end_ok and not e._thread.is_alive(), e.now)
# chase lights one at a time
sent.clear(); e.play("chase", rgb=(255, 0, 0), duration=0.6, interval=0.05); wait_idle()
on = [x[1] for x in sent if x[3] == (255, 0, 0)]
check("chase visits every light in turn", set(on) == {"10.9.9.1", "10.9.9.2", "10.9.9.3", "10.9.9.4"} and all(a != b for a, b in zip(on, on[1:])), on[:8])
# fade ends exactly on target, stays (no default restore)
sent.clear(); e.set_color(0, 0, 0); e.play("fade", rgb=(100, 50, 250), duration=0.4, name="lavender"); wait_idle(); time.sleep(0.3)
last = {ip: v for _, ip, c, v in sent if c == "colorwc"}
check("fade lands on the target and stays there", set(last.values()) == {(100, 50, 250)} and e.now == {"kind": "color", "rgb": (100, 50, 250), "label": "lavender"}, (last, e.now))

# ── 4. queue ────────────────────────────────────────────────────
sent.clear(); e.set_color(5, 5, 5)
r1 = e.play("strobe", rgb=(255, 0, 0), duration=0.6, queue=True, label="one")
time.sleep(0.05)
r2 = e.play("strobe", rgb=(0, 255, 0), duration=0.6, queue=True, label="two")
r3 = e.play("strobe", rgb=(0, 0, 255), duration=0.6, queue=True, label="three")
check("queue: first plays, next two wait", (r1, r2, r3) == ("playing", "queued", "queued") and e.queue_length() == 2)
order, seen_default_mid = [], False
end = time.time() + 6
while time.time() < end and (e._active or e.now.get("kind") == "effect"):
    lab = e.now.get("label")
    if e.now.get("kind") == "effect" and (not order or order[-1] != lab): order.append(lab)
    time.sleep(0.01)
time.sleep(0.3)
colors = [v for _, ip, c, v in sent if c == "colorwc" and ip == "10.9.9.1" and v not in ((0, 0, 0), (5, 5, 5))]
dedup = [c for i, c in enumerate(colors) if i == 0 or colors[i - 1] != c]
check("queue: plays in order, restores once at the end", order == ["one", "two", "three"] and dedup == [(255, 0, 0), (0, 255, 0), (0, 0, 255), (1, 2, 3)], (order, dedup))
# a normal command cuts in and empties the queue (old behaviour kept)
e.play("strobe", rgb=(255, 0, 0), duration=2, queue=True); time.sleep(0.05); e.play("strobe", rgb=(0, 255, 0), duration=2, queue=True)
e.set_color(9, 9, 9); time.sleep(0.5)
check("plain command interrupts and clears the queue", e.queue_length() == 0 and not e._thread.is_alive() and e.now.get("rgb") == (9, 9, 9))
# non-queued effect replaces immediately, as before
e.play("strobe", rgb=(255, 0, 0), duration=2, label="a"); time.sleep(0.1); e.play("rainbow", duration=0.3, label="b"); time.sleep(0.1)
check("non-queued effect replaces the running one", e.now.get("label") == "b"); wait_idle()
# queue behind a forever effect starts straight away
e.play("rainbow", indefinite=True, label="f"); time.sleep(0.1); r = e.play("strobe", rgb=(1, 1, 1), duration=0.3, queue=True, label="q"); time.sleep(0.1)
check("queued effect takes over from a forever effect", r == "playing" and e.now.get("label") == "q"); wait_idle()
# /stop clears the queue
e.play("strobe", rgb=(255, 0, 0), duration=2, queue=True); time.sleep(0.05); e.play("strobe", rgb=(0, 255, 0), duration=2, queue=True)
get(P, "/stop"); time.sleep(0.6)
check("/stop ends the effect and the queue", e.queue_length() == 0 and e.now.get("label") == "default" and not e._thread.is_alive(), e.now)
# alerts queue via URL; /queue/ prefix
a1 = get(P, "/alert/raid"); time.sleep(0.05); a2 = get(P, "/alert/SUB"); a3 = get(P, "/queue/strobe/red?seconds=0.5")
check("/alert and /queue replies", (a1, a2, a3) == ((200, "alert/raid"), (200, "alert/sub (queued)"), (200, "strobe/red (queued)")), (a1, a2, a3))
check("alert uses its preset", e.now.get("effect") == "chase" and e.now.get("label") == "alert/raid", e.now); wait_idle()
cfg["queue_alerts"] = False
get(P, "/alert/raid"); time.sleep(0.05); a2 = get(P, "/alert/sub"); time.sleep(0.1)
check("queue_alerts off: alert cuts in", a2 == (200, "alert/sub") and e.now.get("label") == "alert/sub"); wait_idle(); cfg["queue_alerts"] = True

# ── 5. return to previous look ──────────────────────────────────
cfg["after_effect"] = "previous"
e.set_color(11, 22, 33, label="x"); get(P, "/light/tv/red"); time.sleep(0.1); sent.clear()
e.play("strobe", rgb=(255, 255, 255), duration=0.4); wait_idle(); time.sleep(0.2)
last = {ip: v for _, ip, c, v in sent if c == "colorwc"}
check("previous look: per-light colours come back", last == {"10.9.9.1": (11, 22, 33), "10.9.9.2": (255, 0, 0), "10.9.9.3": (11, 22, 33), "10.9.9.4": (11, 22, 33)} and e.now.get("kind") == "custom", (last, e.now))
e.turn_off(); sent.clear(); e.play("strobe", rgb=(255, 255, 255), duration=0.4); wait_idle(); time.sleep(0.2)
check("previous look: room that was off goes back off", sent[-1][2:] == ("turn", 0) and e.now.get("kind") == "off", (sent[-3:], e.now))
e.set_color(11, 22, 33); e.play("strobe", rgb=(255, 255, 255), indefinite=True); time.sleep(0.2); sent.clear(); e.stop(); time.sleep(0.6)
last = {ip: v for _, ip, c, v in sent if c == "colorwc"}
check("/stop still restores the default colour", set(last.values()) == {(1, 2, 3)}, last)
cfg["after_effect"] = "default"
e.set_color(11, 22, 33); sent.clear(); e.play("strobe", rgb=(255, 255, 255), duration=0.4); wait_idle(); time.sleep(0.2)
last = {ip: v for _, ip, c, v in sent if c == "colorwc"}
check("default mode unchanged: restores default colour", set(last.values()) == {(1, 2, 3)}, last)

# ── 6. per-URL options ──────────────────────────────────────────
e.brightness(80); sent.clear()
get(P, "/strobe/red?speed=max&brightness=25&seconds=0.6"); time.sleep(0.5)
ons = [t for t, ip, c, v in sent if ip == "10.9.9.1" and v == (255, 0, 0)]
gaps = [b - a for a, b in zip(ons, ons[1:])]
wait_idle()
br = [v for _, ip, c, v in sent if c == "brightness" and ip == "10.9.9.1"]
check("?speed=max strobes at ~0.10s per cycle", gaps and 0.07 < sum(gaps) / len(gaps) < 0.16, gaps)
check("?brightness applies for the effect and is put back", br == [25, 80] and e.brightness_value == 80, br)
check("setting unchanged by ?speed", cfg["strobe_interval"] == 0.05)
sent.clear(); get(P, "/strobe/red?brightness=25&seconds=5"); time.sleep(0.2); get(P, "/blue"); time.sleep(0.2)
br = [v for _, ip, c, v in sent if c == "brightness" and ip == "10.9.9.1"]
check("brightness is put back when the effect is interrupted", br == [25, 80], br)
sent.clear(); get(P, "/rainbow?seconds=0.5"); t0 = time.time(); wait_idle()
check("?seconds on an old effect", 0.4 < time.time() - t0 < 1.6, time.time() - t0)

# ── 7. scenes ───────────────────────────────────────────────────
e.set_color(0, 0, 255); get(P, "/light/tv/00ff00"); get(P, "/light/wall/red"); e.light_power("10.9.9.1", False); e.brightness(60); time.sleep(0.1)
scene = e.capture_scene("Chill Mode")
check("capture scene", scene == {"name": "Chill Mode", "brightness": 60, "lights": {"10.9.9.1": "off", "10.9.9.2": [0, 255, 0], "10.9.9.3": [255, 0, 0], "10.9.9.4": [255, 0, 0]}}, scene)
cfg["scenes"].append(scene)
e.light_power("10.9.9.1", True); e.set_color(7, 7, 7); e.brightness(100); sent.clear()
r = get(P, "/scene/chill-mode"); time.sleep(0.3)
last = {ip: v for _, ip, c, v in sent if c == "colorwc"}
turns = {ip: v for _, ip, c, v in sent if c == "turn"}
check("apply scene by URL", r == (200, "Scene: Chill Mode") and last == {"10.9.9.2": (0, 255, 0), "10.9.9.3": (255, 0, 0), "10.9.9.4": (255, 0, 0)} and turns == {"10.9.9.1": 0, "10.9.9.2": 1, "10.9.9.3": 1, "10.9.9.4": 1} and e.brightness_value == 60 and e.now == {"kind": "scene", "name": "Chill Mode"}, (r, last, turns, e.now))
fresh = engine.EffectsEngine(); fresh.cfg = cfg; fresh.lights = e.lights
check("capture with nothing known returns None", fresh.capture_scene("x") is None)
check("curtain never sent anything (whole run)", not [x for x in sent if x[1] == "10.9.9.5"])
check("log callback gets the requested path", "strobe/red?speed=max&brightness=25&seconds=0.6" in logged and "alert/raid" in logged, logged[-6:])

print("\nFAILED:", fails if fails else "none")
sys.exit(1 if fails else 0)
