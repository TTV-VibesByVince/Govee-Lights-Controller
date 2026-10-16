"""
Govee Light Controller - engine
-------------------------------
Config, colour table, LAN discovery, UDP control and the effects engine.
No UI code lives here.
"""

import colorsys
import copy
import json
import math
import os
import random
import socket
import threading
import time
from collections import deque

APP_NAME    = "Govee Light Controller"
APP_VERSION = "V1.4"

# ══════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════

CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "govee_config.json"
)

DEFAULT_CONFIG = {
    "port":                  8765,
    # Accept web requests from other devices on the home network (e.g. a NAS
    # or a second PC), not just this one. Off = localhost only, as before.
    "lan_access":            False,
    "default_color":         {"r": 255, "g": 255, "b": 255},
    "lights":                [],
    "excluded_ips":          [],
    # Models that never receive room commands, whatever their switch says.
    "excluded_skus":         [],
    # Curtain models (can show GIFs). A curtain whose switch is off is in
    # "GIF mode": room commands skip it and only GIF commands change it.
    "curtain_skus":          ["H70B6"],
    "effect_duration":       8,
    "strobe_interval":       0.15,
    "restore_after_effect":  True,
    # What a finished effect restores: "default" colour or the "previous" look
    "after_effect":          "default",
    "startup_apply_default": False,
    "theme":                 "dark",
    "auto_scan_on_startup":  False,
    "hide_offline":          False,
    "always_on_top":         False,
    "command_cooldown":      0,
    # Alerts wait for the one before them instead of cutting it off
    "queue_alerts":          True,
    # [{"name", "brightness", "lights": {ip: [r, g, b] or "off"}}]
    "scenes":                [],
    # [{"name", "effect", "color", "color2", "seconds", "speed"}]
    "alerts":                [],
    # Curtain GIFs: [{"name", "file", "source"}], files live in gifs/
    "gifs":                  [],
    "gif_default":           "",
    "gif_strict":            True,    # chat links: Giphy / Tenor / Imgur only
    "gif_cooldown":          10,      # seconds between chat links (0 = none)
    # A GIF from a web request stays up this long, then the next queued GIF
    # or the default GIF takes over (0 = stay until replaced)
    "gif_web_seconds":       8,
    "gif_queue":             False,   # web GIFs wait their turn instead of being refused
    "gif_queue_max":         5,
    "gif_remember":          True,    # keep the Govee password (encrypted)
}


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                data = json.load(f)
            if "curtain_skus" not in data:
                # Before V1.1 curtains were listed as excluded models. They
                # are now ordinary lights with a switch (off = GIF mode).
                curtains = DEFAULT_CONFIG["curtain_skus"]
                data["curtain_skus"] = list(curtains)
                data["excluded_skus"] = [
                    s for s in data.get("excluded_skus", [])
                    if s.upper() not in curtains]
            for k, v in DEFAULT_CONFIG.items():
                if k not in data:
                    data[k] = copy.deepcopy(v)
            return data
        except Exception:
            pass
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    save_config(cfg)
    return cfg


def save_config(cfg: dict):
    try:
        clean = dict(cfg)
        if "lights" in clean:
            clean["lights"] = [
                {k: v for k, v in l.items() if k != "_offline"}
                for l in clean["lights"]
            ]
        with open(CONFIG_FILE, "w") as f:
            json.dump(clean, f, indent=2)
    except Exception as e:
        print(f"Config save error: {e}")


def is_curtain(cfg: dict, light: dict) -> bool:
    """True for curtain lights (the models that can show GIFs)."""
    skus = {s.upper() for s in cfg.get("curtain_skus", [])}
    return str(light.get("sku", "")).upper() in skus


def in_gif_mode(cfg: dict, light: dict) -> bool:
    """A curtain whose switch is off: GIF commands only."""
    return is_curtain(cfg, light) and not light.get("enabled", True)


def is_excluded(cfg: dict, light: dict) -> bool:
    """True if room commands must not reach this light: an excluded address
    or model, or a curtain in GIF mode."""
    if light.get("ip") in cfg.get("excluded_ips", []):
        return True
    skus = {s.upper() for s in cfg.get("excluded_skus", [])}
    if str(light.get("sku", "")).upper() in skus:
        return True
    return in_gif_mode(cfg, light)


def room_lights(cfg: dict) -> list[dict]:
    """The lights that room commands (colours, effects, on/off) go to."""
    return [
        l for l in cfg.get("lights", [])
        if l.get("enabled", True) and not is_excluded(cfg, l)
    ]


def slug(text) -> str:
    """Name as used in URLs: lowercase letters and digits only."""
    return "".join(ch for ch in str(text).lower() if ch.isalnum())


def find_lights(cfg: dict, token: str) -> list[dict]:
    """Lights matching a URL token: by name (slug) or by IP address."""
    key = slug(token)
    return [l for l in cfg.get("lights", [])
            if l.get("ip") == token or (key and slug(l.get("name", "")) == key)]


def find_named(items: list, token: str) -> dict | None:
    """A scene or alert by its name's slug."""
    key = slug(token)
    for item in items or []:
        if key and slug(item.get("name", "")) == key:
            return item
    return None


# ══════════════════════════════════════════════════════════════
#  COLORS
# ══════════════════════════════════════════════════════════════

COLORS: dict[str, tuple[int, int, int]] = {
    "red":        (255,   0,   0), "green":     (0,   255,   0),
    "blue":       (0,    80, 255), "white":     (255, 255, 255),
    "yellow":     (255, 220,   0), "orange":    (255, 100,   0),
    "purple":     (180,   0, 255), "pink":      (255,   0, 170),
    "cyan":       (0,   200, 255), "teal":      (0,   180, 150),
    "lime":       (120, 255,   0), "magenta":   (255,   0, 255),
    "warm":       (255, 147,  41), "cool":      (180, 200, 255),
    "sunset":     (255,  60,   0), "ocean":     (0,   100, 200),
    "rose":       (255, 100, 120), "lavender":  (150,  80, 255),
    "gold":       (255, 185,   0), "hotpink":   (255,   0, 100),
    "mint":       (100, 255, 180), "coral":     (255,  80,  60),
    "electric":   (0,   255, 255), "blood":     (180,   0,   0),
    "royalblue":  (65,  105, 225), "violet":    (238, 130, 238),
    "indigo":     (75,    0, 130), "amber":     (255, 191,   0),
    "crimson":    (220,  20,  60), "turquoise": (64,  224, 208),
    "hype":       (255,   0, 255), "chill":     (0,   120, 200),
    "gaming":     (0,   255,  80), "fire":      (255,  40,   0),
    "ice":        (100, 220, 255), "disco":     (200,   0, 255),
    "boss":       (220,   0,   0), "win":       (0,   255, 120),
    "lose":       (100,   0,   0), "spooky":    (255,  80,   0),
    "valentine":  (255,  20, 100), "xmas":      (0,   200,   0),
    "pride":      (255, 100,   0), "toxic":     (150, 255,   0),
    "midnight":   (0,     0,  80), "neon":      (0,   255, 128),
}

# Speed names -> seconds between strobe flashes
SPEED_NAMES = {"slow": 0.30, "normal": 0.15, "fast": 0.09, "max": 0.05}

# effect id -> (title, colours it takes, can run forever)
EFFECTS = {
    "flash":          ("Flash",          1, True),
    "strobe":         ("Strobe",         1, True),
    "pulse":          ("Pulse",          1, True),
    "rainbow":        ("Rainbow",        0, True),
    "rainbow-strobe": ("Rainbow Strobe", 0, True),
    "chase":          ("Chase",          1, True),
    "alternate":      ("Alternate",      2, True),
    "police":         ("Police",         0, True),
    "flicker":        ("Fire Flicker",   0, True),
    "breathe":        ("Breathe",        1, True),
    "fade":           ("Fade",           1, False),
    "lightning":      ("Lightning",      0, True),
    "sparkle":        ("Sparkle",        1, True),
    "countdown":      ("Countdown",      0, False),
}
EFFECT_TITLES = {k: v[0] for k, v in EFFECTS.items()}

# ══════════════════════════════════════════════════════════════
#  LAN DISCOVERY & CONTROL
# ══════════════════════════════════════════════════════════════

MULTICAST_GRP  = "239.255.255.250"
DISCOVERY_PORT = 4001
LISTEN_PORT    = 4002
COMMAND_PORT   = 4003
DISCOVERY_MSG  = json.dumps(
    {"msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}}
).encode()


def discover_lights(timeout=3.0) -> list[dict]:
    found = {}
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        rx.bind(("", LISTEN_PORT))
    except OSError:
        rx.bind(("", 0))
    rx.settimeout(0.3)
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    tx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    try:
        tx.sendto(DISCOVERY_MSG, (MULTICAST_GRP, DISCOVERY_PORT))
        tx.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        tx.sendto(DISCOVERY_MSG, ("255.255.255.255", DISCOVERY_PORT))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, addr = rx.recvfrom(1024)
                msg = json.loads(data.decode())
                if msg.get("msg", {}).get("cmd") == "scan":
                    dd = msg["msg"]["data"]
                    ip = dd.get("ip") or addr[0]
                    if ip not in found:
                        found[ip] = {"ip": ip, "sku": dd.get("sku", "Unknown"),
                                     "id": dd.get("device", "")}
            except Exception:
                pass
    finally:
        rx.close()
        tx.close()
    return list(found.values())


# Shared UDP socket - avoids creating a new socket for every command
_udp_lock   = threading.Lock()
_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def send_udp(ip: str, payload: dict):
    """Send a single command to one light. Thread-safe."""
    try:
        msg = json.dumps({"msg": payload}).encode()
        with _udp_lock:
            _udp_socket.sendto(msg, (ip, COMMAND_PORT))
    except Exception:
        pass


def send_all(lights: list[dict], payload: dict, wait=False):
    """
    Fire a command to all enabled lights in parallel.
    wait=False (default) - fire and forget, returns immediately.
    wait=True  - blocks until all sends complete (use for one-shot commands).
    """
    active = [l for l in lights if l.get("enabled", True)]
    threads = [
        threading.Thread(target=send_udp, args=(l["ip"], payload), daemon=True)
        for l in active
    ]
    for t in threads:
        t.start()
    if wait:
        for t in threads:
            t.join(timeout=0.5)


def close_socket():
    try:
        _udp_socket.close()
    except Exception:
        pass


def color_payload(r: int, g: int, b: int) -> dict:
    return {"cmd": "colorwc",
            "data": {"color": {"r": r, "g": g, "b": b}, "colorTemInKelvin": 0}}


def _scaled(rgb, k) -> dict:
    return color_payload(int(rgb[0] * k), int(rgb[1] * k), int(rgb[2] * k))


# ══════════════════════════════════════════════════════════════
#  EFFECTS ENGINE
# ══════════════════════════════════════════════════════════════

class EffectsEngine:
    """Runs light effects in a background thread, non-blocking.

    Besides sending commands it keeps a small picture of what the room is
    doing (`now`, `light_colors`, `power`) so a UI can show it. `rev` goes up
    whenever that picture changes.

    Effects normally replace whatever is running. Started with queue=True
    they instead wait for the running (timed) effect to finish, and the room
    is only restored after the last one.
    """

    def __init__(self):
        self._lock   = threading.RLock()
        self._stop   = threading.Event()          # belongs to the current run
        self._thread: threading.Thread | None = None
        self._active = False                      # an effect run is in progress
        self._active_forever = False
        self._queue: deque = deque()              # (loop, options, brightness, forever)
        self._bright_before = None                # brightness to put back
        self.lights: list[dict] = []
        self.cfg:    dict       = {}

        self.now: dict = {"kind": "idle"}
        self.light_colors: dict[str, tuple[int, int, int]] = {}
        self.power: dict[str, bool] = {}
        self.brightness_value = 100
        self.rev = 0

        # The last steady (non-effect) look, for "return to previous"
        self.steady_colors: dict[str, tuple[int, int, int]] = {}
        self.steady_off = False
        self._steady_now: dict = {"kind": "idle"}

        self._loops = {
            "flash": self._flash_loop, "strobe": self._strobe_loop,
            "pulse": self._pulse_loop, "rainbow": self._rainbow_loop,
            "rainbow-strobe": self._rainbow_strobe_loop,
            "chase": self._chase_loop, "alternate": self._alternate_loop,
            "police": self._alternate_loop, "flicker": self._flicker_loop,
            "breathe": self._breathe_loop, "fade": self._fade_loop,
            "lightning": self._lightning_loop, "sparkle": self._sparkle_loop,
            "countdown": self._countdown_loop,
        }

    # ── State the UI reads ──────────────────────────────────

    def _set_now(self, kind: str, **info):
        self.now = {"kind": kind, **info}
        if kind != "effect":
            self._steady_now = self.now
        self.rev += 1

    def queue_length(self) -> int:
        return len(self._queue)

    def _note(self, ips, payload: dict):
        cmd = payload.get("cmd")
        if cmd == "colorwc":
            c = payload["data"]["color"]
            rgb = (c["r"], c["g"], c["b"])
            for ip in ips:
                self.light_colors[ip] = rgb
        elif cmd == "turn":
            on = bool(payload["data"]["value"])
            for ip in ips:
                self.power[ip] = on
            self.rev += 1

    def _room(self) -> list[dict]:
        return [l for l in self.lights if l.get("enabled", True)]

    def _send(self, payload: dict, wait=False):
        """Room command: goes to every light in self.lights."""
        self._note([l["ip"] for l in self._room()], payload)
        send_all(self.lights, payload, wait=wait)

    def _send_one(self, ip: str, payload: dict):
        self._note([ip], payload)
        send_udp(ip, payload)

    def _steady_all(self, rgb):
        for l in self._room():
            self.steady_colors[l["ip"]] = tuple(rgb)
        self.steady_off = False

    # ── Internal ────────────────────────────────────────────

    def _cancel(self, clear_queue=True) -> threading.Event:
        """Stop the running effect (if any) without blocking.

        Each run owns its stop event. Cancelling sets that event for good
        and hands out a fresh one, so a running loop can never miss it.
        """
        with self._lock:
            self._stop.set()
            self._stop = threading.Event()
            self._active = False
            if clear_queue and self._queue:
                self._queue.clear()
                self.rev += 1
            before, self._bright_before = self._bright_before, None
            stop = self._stop
        if before is not None:
            self._send({"cmd": "brightness", "data": {"value": before}})
        return stop

    def _run(self, fn, opts, brightness=None, forever=False, clear_queue=True):
        """Cancel any running effect, then start a new run."""
        stop = self._cancel(clear_queue)
        old = self._thread
        if old and old.is_alive() and old is not threading.current_thread():
            old.join(timeout=0.3)
        with self._lock:
            if stop.is_set():          # something newer got in first
                return
            self._active = True
            self._active_forever = forever
            self._thread = threading.Thread(
                target=self._worker, args=(stop, fn, opts, brightness),
                daemon=True)
            self._thread.start()

    def _start(self, fn, opts, brightness, forever, queue) -> str:
        if queue:
            with self._lock:
                if self._active and not self._active_forever:
                    self._queue.append((fn, opts, brightness, forever))
                    self.rev += 1
                    return "queued"
        self._run(fn, opts, brightness, forever, clear_queue=not queue)
        return "playing"

    def _worker(self, stop, fn, opts, brightness):
        """Play one effect, then anything queued behind it, then restore."""
        while True:
            self._item_brightness(stop, brightness)
            result = fn(stop, opts)
            with self._lock:
                if stop.is_set():
                    return
                nxt = self._queue.popleft() if self._queue else None
                if nxt:
                    self._active_forever = nxt[3]
                    self.rev += 1
            if nxt:
                fn, opts, brightness, _ = nxt
                continue
            self._item_brightness(stop, None)
            if result != "keep":
                self._finish(stop)
            with self._lock:
                if stop.is_set():
                    return
                if not self._queue:
                    self._active = False
                    return
                fn, opts, brightness, self._active_forever = self._queue.popleft()
                self.rev += 1

    def _item_brightness(self, stop, value):
        """Apply an effect's own brightness, or put the old one back."""
        with self._lock:
            if stop.is_set():
                return
            if value is None:
                target, self._bright_before = self._bright_before, None
            else:
                if self._bright_before is None:
                    self._bright_before = self.brightness_value
                target = max(1, min(100, int(value)))
        if target is not None:
            self._send({"cmd": "brightness", "data": {"value": target}})

    def _default_rgb(self) -> dict:
        return self.cfg.get("default_color", {"r": 255, "g": 255, "b": 255})

    def _apply_default(self):
        dc = self._default_rgb()
        self._send({"cmd": "turn", "data": {"value": 1}}, wait=True)
        time.sleep(0.1)
        self._send({"cmd": "colorwc",
                    "data": {"color": dc, "colorTemInKelvin": 0}}, wait=True)
        self._steady_all((dc["r"], dc["g"], dc["b"]))

    def _restore_previous(self, stop) -> bool:
        """Put back the look from before the effect. False if it isn't known."""
        if self.steady_off:
            self._send({"cmd": "turn", "data": {"value": 0}}, wait=True)
            if not stop.is_set():
                self._set_now("off")
            return True
        room = self._room()
        if not any(l["ip"] in self.steady_colors for l in room):
            return False
        dc = self._default_rgb()
        default = (dc["r"], dc["g"], dc["b"])
        look = dict(self._steady_now)
        self._send({"cmd": "turn", "data": {"value": 1}}, wait=True)
        time.sleep(0.1)
        for l in room:
            self._send_one(l["ip"], color_payload(
                *self.steady_colors.get(l["ip"], default)))
        if not stop.is_set():
            kind = look.pop("kind", "on")
            self._set_now(kind if kind in ("color", "scene", "custom") else "on",
                          **look)
        return True

    def _finish(self, stop: threading.Event):
        """End of a timed effect: restore the room unless it was cancelled."""
        if stop.is_set():
            return
        if not self.cfg.get("restore_after_effect", True):
            self._set_now("idle")
            return
        if (self.cfg.get("after_effect") == "previous"
                and self._restore_previous(stop)):
            return
        self._apply_default()
        if not stop.is_set():
            dc = self._default_rgb()
            self._set_now("color", rgb=(dc["r"], dc["g"], dc["b"]),
                          label="default")

    @staticmethod
    def _black() -> dict:
        """Use black color instead of 'turn off' for effects.
        More reliable across all light models including H6062."""
        return color_payload(0, 0, 0)

    def _begin(self, stop, o: dict) -> float:
        """Record the effect for the UI and return its end time."""
        start = time.time()
        if o["indefinite"]:
            end = start + 86400
        else:
            secs = o["duration"] if o["duration"] else \
                self.cfg.get("effect_duration", 8)
            end = start + secs
        if not stop.is_set():
            self._set_now("effect", effect=o["effect"],
                          title=EFFECT_TITLES[o["effect"]],
                          start=start, end=end, forever=bool(o["indefinite"]),
                          label=o["label"] or o["effect"], rgb=o["rgb"])
        return end

    def _iv(self, o: dict) -> float:
        """Seconds between flashes: the effect's own speed, else the setting."""
        return o["interval"] or self.cfg.get("strobe_interval", 0.15)

    @staticmethod
    def _factor(o: dict) -> float:
        """Time stretch for fixed-rate effects (1.0 unless a speed was given)."""
        return o["interval"] / 0.15 if o["interval"] else 1.0

    # ── Public controls ─────────────────────────────────────

    def set_color(self, r: int, g: int, b: int, label: str | None = None):
        self._cancel()
        self._send(color_payload(r, g, b))
        self._steady_all((r, g, b))
        self._set_now("color", rgb=(r, g, b), label=label)

    def turn_on(self):
        self._cancel()
        self._send({"cmd": "turn", "data": {"value": 1}})
        self.steady_off = False
        self._set_now("on")

    def turn_off(self):
        self._cancel()
        self._send({"cmd": "turn", "data": {"value": 0}})
        self.steady_off = True
        self._set_now("off")

    def stop(self):
        """Stop current effect (and anything queued) and restore default."""
        self._cancel()
        self._set_now("idle")
        threading.Thread(target=self.restore_default, daemon=True).start()

    def restore_default(self):
        """Turn the room on and set the default colour."""
        self._apply_default()
        if self.now.get("kind") != "effect":
            dc = self._default_rgb()
            self._set_now("color", rgb=(dc["r"], dc["g"], dc["b"]),
                          label="default")

    def brightness(self, value: int):
        self.brightness_value = max(1, min(100, value))
        with self._lock:
            self._bright_before = None
        self._send({"cmd": "brightness",
                    "data": {"value": self.brightness_value}})

    def light_power(self, ip: str, on: bool):
        """Switch one light directly (not a room command)."""
        self._send_one(ip, {"cmd": "turn", "data": {"value": 1 if on else 0}})

    def light_color(self, ip: str, r: int, g: int, b: int):
        """Colour one light directly (not a room command)."""
        self._send_one(ip, color_payload(r, g, b))
        self.steady_colors[ip] = (r, g, b)
        if self.now.get("kind") != "effect":
            self.steady_off = False
            self._set_now("custom")
        else:
            self.rev += 1

    # ── Scenes ──────────────────────────────────────────────

    def capture_scene(self, name: str) -> dict | None:
        """The room's current steady look as a scene. None if nothing is known."""
        lights = {}
        for l in self._room():
            ip = l["ip"]
            if self.steady_off or self.power.get(ip) is False:
                lights[ip] = "off"
            elif ip in self.steady_colors:
                lights[ip] = list(self.steady_colors[ip])
        if not any(v != "off" for v in lights.values()) and not self.steady_off:
            return None
        return {"name": name, "brightness": self.brightness_value,
                "lights": lights}

    def apply_scene(self, scene: dict):
        """Set each light to its saved colour. Only room lights are touched."""
        self._cancel()
        saved = scene.get("lights", {})
        room = [l for l in self._room() if l["ip"] in saved]
        on = [l for l in room if saved[l["ip"]] != "off"]
        for l in room:
            self._send_one(l["ip"], {"cmd": "turn", "data": {
                "value": 0 if saved[l["ip"]] == "off" else 1}})
        if on:
            time.sleep(0.1)
        for l in on:
            rgb = tuple(int(v) for v in saved[l["ip"]])
            self._send_one(l["ip"], color_payload(*rgb))
            self.steady_colors[l["ip"]] = rgb
        if scene.get("brightness"):
            self.brightness(int(scene["brightness"]))
        self.steady_off = bool(room) and not on
        self._set_now("scene", name=scene.get("name", "Scene"))

    # ── Starting effects ────────────────────────────────────

    def play(self, effect: str, rgb=None, rgb2=None, indefinite=False,
             duration: float | None = None, interval: float | None = None,
             label: str | None = None, queue=False, brightness=None,
             name: str | None = None) -> str:
        """Start an effect by id. Returns "playing" or "queued".

        rgb / rgb2 - colours, for the effects that take them
        duration   - seconds (default: the effect-duration setting)
        interval   - speed override, seconds between flashes
        brightness - brightness just for this effect (put back afterwards)
        name       - colour name, shown by the UI after a fade
        """
        if effect == "police":
            rgb, rgb2 = (255, 0, 0), (0, 40, 255)
        forever = bool(indefinite) and EFFECTS[effect][2]
        opts = {"effect": effect, "rgb": tuple(rgb) if rgb else None,
                "rgb2": tuple(rgb2) if rgb2 else None, "indefinite": forever,
                "duration": duration, "interval": interval, "label": label,
                "name": name}
        return self._start(self._loops[effect], opts, brightness, forever, queue)

    def run_alert(self, alert: dict, label: str | None = None) -> str:
        """Play an alert preset (queued, unless that setting is off)."""
        effect = alert.get("effect")
        if effect not in EFFECTS:
            effect = "strobe"
        takes = EFFECTS[effect][1]
        color = alert.get("color") or "red"
        return self.play(
            effect,
            rgb=COLORS.get(color, (255, 255, 255)) if takes >= 1 else None,
            rgb2=COLORS.get(alert.get("color2") or "blue", (0, 80, 255))
            if takes >= 2 else None,
            duration=alert.get("seconds") or None,
            interval=SPEED_NAMES.get(alert.get("speed")),
            label=label or "alert/" + slug(alert.get("name", "")),
            queue=bool(self.cfg.get("queue_alerts", True)), name=color)

    # The original five keep their own methods
    def flash(self, r, g, b, indefinite=False, label=None, **kw):
        return self.play("flash", (r, g, b), indefinite=indefinite,
                         label=label, **kw)

    def strobe(self, r, g, b, indefinite=False, label=None, **kw):
        return self.play("strobe", (r, g, b), indefinite=indefinite,
                         label=label, **kw)

    def pulse(self, r, g, b, indefinite=False, label=None, **kw):
        return self.play("pulse", (r, g, b), indefinite=indefinite,
                         label=label, **kw)

    def rainbow(self, indefinite=False, label=None, **kw):
        return self.play("rainbow", indefinite=indefinite, label=label, **kw)

    def rainbow_strobe(self, indefinite=False, duration: float | None = None,
                       label=None, **kw):
        return self.play("rainbow-strobe", indefinite=indefinite,
                         duration=duration, label=label, **kw)

    # ══════════════════════════════════════════════════════════
    #  EFFECT LOOPS  (each runs until its time is up or `stop` is set)
    # ══════════════════════════════════════════════════════════

    def _flash_loop(self, stop, o):
        end_time = self._begin(stop, o)
        color_on = color_payload(*o["rgb"])
        gap = 0.3 * self._factor(o)
        while time.time() < end_time and not stop.is_set():
            self._send(color_on)
            if stop.wait(gap):
                break
            self._send(self._black())
            stop.wait(gap)

    def _strobe_loop(self, stop, o):
        end_time = self._begin(stop, o)
        color_on = color_payload(*o["rgb"])
        while time.time() < end_time and not stop.is_set():
            interval = self._iv(o)
            self._send(color_on)
            if stop.wait(interval):
                break
            self._send(self._black())
            stop.wait(interval)

    def _rainbow_strobe_loop(self, stop, o):
        """
        Strobes through the rainbow. Every light is offset around the
        color wheel so the room shows several colors at once, and the
        whole wheel advances on every flash.
        """
        end_time = self._begin(stop, o)
        hue      = 0.0
        hue_step = 0.11
        while time.time() < end_time and not stop.is_set():
            interval = self._iv(o)
            active   = self._room()
            count    = max(len(active), 1)
            for i, light in enumerate(active):
                h = (hue + i / count) % 1.0
                r, g, b = [int(c * 255) for c in colorsys.hsv_to_rgb(h, 1.0, 1.0)]
                self._send_one(light["ip"], color_payload(r, g, b))
            if stop.wait(interval):
                break
            self._send(self._black())
            stop.wait(interval)
            hue = (hue + hue_step) % 1.0

    def _pulse_loop(self, stop, o):
        end_time = self._begin(stop, o)
        steps    = 18
        pause    = 0.04 * self._factor(o)
        while time.time() < end_time and not stop.is_set():
            for i in list(range(steps)) + list(range(steps, -1, -1)):
                if stop.is_set():
                    return
                self._send(_scaled(o["rgb"], i / steps))
                time.sleep(pause)

    def _rainbow_loop(self, stop, o):
        end_time = self._begin(stop, o)
        hue = 0.0
        pause = 0.05 * self._factor(o)
        while time.time() < end_time and not stop.is_set():
            r, g, b = [int(c * 255) for c in colorsys.hsv_to_rgb(hue, 1.0, 1.0)]
            self._send(color_payload(r, g, b))
            hue = (hue + 0.02) % 1.0
            stop.wait(pause)

    # ── New in V1.0 ─────────────────────────────────────────

    def _chase_loop(self, stop, o):
        """One lit light runs around the room."""
        end_time = self._begin(stop, o)
        color_on = color_payload(*o["rgb"])
        self._send(self._black())
        i, prev = 0, None
        while time.time() < end_time and not stop.is_set():
            active = self._room()
            if not active:
                stop.wait(0.2)
                continue
            if len(active) == 1:                 # nothing to chase: blink
                self._send_one(active[0]["ip"],
                               color_on if i % 2 == 0 else self._black())
            else:
                cur = active[i % len(active)]["ip"]
                if prev and prev != cur:
                    self._send_one(prev, self._black())
                self._send_one(cur, color_on)
                prev = cur
            i += 1
            stop.wait(max(0.08, self._iv(o) * 1.6))

    def _alternate_loop(self, stop, o):
        """Two colours on alternate lights, swapping (police lights)."""
        end_time = self._begin(stop, o)
        a = color_payload(*(o["rgb"] or (255, 0, 0)))
        b = color_payload(*(o["rgb2"] or (0, 40, 255)))
        flip = False
        while time.time() < end_time and not stop.is_set():
            for i, light in enumerate(self._room()):
                self._send_one(light["ip"], a if (i % 2 == 0) != flip else b)
            flip = not flip
            stop.wait(max(0.12, self._iv(o) * 2.5))

    def _flicker_loop(self, stop, o):
        """Fire / candle: each light wanders through warm, uneven brightness."""
        end_time = self._begin(stop, o)
        base = o["rgb"]
        f = self._factor(o)
        while time.time() < end_time and not stop.is_set():
            for light in self._room():
                if random.random() < 0.7:
                    k = random.uniform(0.35, 1.0)
                    if base:
                        payload = _scaled(base, k)
                    else:
                        payload = color_payload(
                            int(255 * k), int(random.uniform(40, 130) * k), 0)
                    self._send_one(light["ip"], payload)
            stop.wait(random.uniform(0.05, 0.14) * f)

    def _breathe_loop(self, stop, o):
        """Slow, smooth swell that never goes fully dark."""
        end_time = self._begin(stop, o)
        period = 4.0 * self._factor(o)
        t0 = time.time()
        while time.time() < end_time and not stop.is_set():
            phase = ((time.time() - t0) % period) / period
            k = 0.12 + 0.88 * (0.5 - 0.5 * math.cos(2 * math.pi * phase))
            self._send(_scaled(o["rgb"], k))
            stop.wait(0.06)

    def _fade_loop(self, stop, o):
        """Glide from what each light shows now to a colour, and stay there."""
        secs = max(0.2, min(600.0, o["duration"] or 2.0))
        o["duration"] = secs
        self._begin(stop, o)
        target = o["rgb"]
        dc = self._default_rgb()
        default = (dc["r"], dc["g"], dc["b"])
        active = self._room()
        was_off = self.steady_off
        src = {l["ip"]: (0, 0, 0) if was_off or self.power.get(l["ip"]) is False
               else self.light_colors.get(l["ip"], default) for l in active}
        if was_off or any(self.power.get(l["ip"]) is False for l in active):
            self._send(self._black())
            self._send({"cmd": "turn", "data": {"value": 1}}, wait=True)
        start = time.time()
        while not stop.is_set():
            t = min(1.0, (time.time() - start) / secs)
            for l in active:
                s = src[l["ip"]]
                self._send_one(l["ip"], color_payload(
                    *(int(s[i] + (target[i] - s[i]) * t) for i in range(3))))
            if t >= 1.0:
                break
            stop.wait(0.05)
        if stop.is_set():
            return None
        self._steady_all(target)
        self._set_now("color", rgb=target, label=o.get("name"))
        return "keep"

    def _lightning_loop(self, stop, o):
        """Mostly dark, with random bursts of flashes."""
        end_time = self._begin(stop, o)
        flash = color_payload(*(o["rgb"] or (210, 225, 255)))
        f = self._factor(o)
        self._send(self._black())
        while time.time() < end_time and not stop.is_set():
            gap = min(random.uniform(0.3, 2.2) * f,
                      max(0.05, end_time - time.time()))
            if stop.wait(gap) or time.time() >= end_time:
                break
            active = self._room()
            if not active:
                continue
            for _ in range(random.randint(1, 3)):
                hit = active if random.random() < 0.6 else \
                    random.sample(active, max(1, len(active) // 2))
                for light in hit:
                    self._send_one(light["ip"], flash)
                if stop.wait(random.uniform(0.04, 0.09)):
                    break
                self._send(self._black())
                if stop.wait(random.uniform(0.04, 0.12)):
                    break

    def _sparkle_loop(self, stop, o):
        """A base colour with random lights briefly popping white."""
        end_time = self._begin(stop, o)
        base = color_payload(*o["rgb"])
        white = color_payload(255, 255, 255)
        self._send(base)
        while time.time() < end_time and not stop.is_set():
            active = self._room()
            if not active:
                stop.wait(0.2)
                continue
            ip = random.choice(active)["ip"]
            self._send_one(ip, white)
            if stop.wait(max(0.06, self._iv(o) * 0.8)):
                break
            self._send_one(ip, base)
            stop.wait(random.uniform(0.5, 1.5) * self._iv(o))

    def _countdown_loop(self, stop, o):
        """Green to yellow to red over the time, then three red flashes."""
        secs = o["duration"] if o["duration"] else \
            self.cfg.get("effect_duration", 8)
        o["duration"] = secs + 1.2
        self._begin(stop, o)
        start = time.time()
        while not stop.is_set():
            t = (time.time() - start) / secs
            if t >= 1.0:
                break
            r, g, b = [int(c * 255) for c in
                       colorsys.hsv_to_rgb((1.0 - t) / 3.0, 1.0, 1.0)]
            self._send(color_payload(r, g, b))
            stop.wait(0.1)
        for _ in range(3):
            if stop.is_set():
                break
            self._send(color_payload(255, 0, 0))
            if stop.wait(0.2):
                break
            self._send(self._black())
            stop.wait(0.2)
