"""
Govee Light Controller - HTTP server
------------------------------------
The local web server MixItUp talks to. No UI code lives here.

RULE: never change the meaning of an existing URL. Add new ones only.
"""

import ipaddress
import json
import re
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, unquote, urlsplit

import engine as core
from curtain import CurtainError
from engine import APP_VERSION, COLORS, SPEED_NAMES, EffectsEngine

_EFFECT_NAMES         = {"strobe", "flash", "pulse"}
_RAINBOW_STROBE_NAMES = {"rainbow-strobe", "rainbowstrobe"}
_BRIGHTNESS           = {"dim": 12, "low": 20, "medium": 50,
                         "bright": 100, "max": 100, "half": 50}
# V1.0 effects that are written /effect/color or /color-effect
_COLOR_EFFECTS        = ("chase", "breathe", "sparkle", "flicker", "lightning",
                         "fade")
_NEW_EFFECTS          = set(_COLOR_EFFECTS) | {"alternate", "police", "countdown"}


def _parse_seconds(parts: list[str]) -> float | None:
    """Find an optional numeric seconds value in the URL, e.g. /rainbow-strobe/5"""
    for p in parts[1:]:
        try:
            v = float(p)
            return max(0.5, min(600.0, v))
        except ValueError:
            continue
    return None


def _color(token: str):
    """(rgb, name) for a colour name or 6-digit hex, else None."""
    t = token.lower().lstrip("#")
    if t in COLORS:
        return COLORS[t], t
    if len(t) == 6 and not t.isdigit():
        try:
            return (int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16)), "#" + t
        except ValueError:
            pass
    return None


def _options(query: str) -> dict:
    """Optional ?speed= &brightness= &seconds= on any URL."""
    q = {k.lower(): v[-1] for k, v in parse_qs(query).items()}
    out = {"interval": None, "brightness": None, "seconds": None}
    speed = q.get("speed", "").lower()
    if speed in SPEED_NAMES:
        out["interval"] = SPEED_NAMES[speed]
    elif speed:
        try:
            out["interval"] = max(0.03, min(2.0, float(speed)))
        except ValueError:
            pass
    try:
        out["brightness"] = max(1, min(100, int(float(q["brightness"]))))
    except (KeyError, ValueError):
        pass
    try:
        out["seconds"] = max(0.5, min(600.0, float(
            q.get("seconds", q.get("duration", "")))))
    except ValueError:
        pass
    return out


class LightRequestHandler(BaseHTTPRequestHandler):
    """
    URL patterns (everything from v8/v9 is unchanged):
      /red                      -> color (any name in engine.COLORS)
      /ff0080                   -> hex color
      /on  /off                 -> power
      /stop                     -> stop active effect + restore default
      /dim /low /medium /half /bright /max -> brightness
      /strobe/red               -> strobe red (timed)      (also /flash, /pulse)
      /strobe/red/forever       -> strobe red indefinitely
      /blue-pulse               -> pulse blue (timed)      (also -flash, -strobe)
      /blue-pulse/forever       -> pulse blue indefinitely
      /rainbow                  -> rainbow (timed)
      /rainbow/forever          -> rainbow indefinitely
      /rainbow-strobe           -> rainbow strobe (timed, uses effect duration)
      /rainbow-strobe/5         -> rainbow strobe for 5 seconds
      /rainbow-strobe/forever   -> rainbow strobe indefinitely
      /strobe/rainbow           -> same as /rainbow-strobe
      /default                  -> restore default color
      /status                   -> JSON status

    Added in V1.0:
      /chase/red                -> one lit light runs round the room
      /breathe/blue             -> slow swell            (/blue-breathe works too)
      /sparkle/purple           -> colour with white pops
      /flicker   /flicker/blue  -> fire flicker (or flicker in a colour)
      /lightning                -> random white bursts
      /police                   -> red / blue alternating
      /alternate/red/blue       -> any two colours alternating
        ... each takes /forever or a number of seconds: /chase/red/5
      /fade/blue   /fade/blue/3 -> glide to a colour over 2 (or N) seconds
      /countdown/10             -> green to red over 10 seconds, then flash
      /scene/<name>             -> recall a saved scene
      /alert/<name>             -> play an alert preset (alerts queue up)
      /queue/<any effect url>   -> wait for the running effect instead of
                                   cutting it off, e.g. /queue/strobe/red
      /light/<name>/<color|on|off> -> one light, by name or IP address
      ?speed=slow|normal|fast|max  ?brightness=1-100  ?seconds=N
                                -> options on any effect, e.g.
                                   /strobe/red?speed=fast&brightness=40

    Added in V1.1 (curtain lights, via the Govee cloud):
      /gif/<name>               -> play a saved GIF on the curtain
      /gif/default              -> play the default GIF
      /gif?url=<link>           -> play a Giphy / Tenor / Imgur link (for chat;
                                   has a cooldown, and other sites are refused
                                   unless that setting is turned off)

    Added in V1.2:
      /gif/avatar?url=<link>    -> show a Twitch / YouTube profile picture,
                                   e.g. /gif/avatar?url=$useravatar
      &seconds=N on any /gif URL -> how long this one stays before the next
                                   queued GIF or the default GIF takes over
                                   (default: the "show for" setting, 8 s)
      With "Queue web-request GIFs" on, a GIF that arrives while another is
      loading or showing waits its turn; the reply ends "(queued)".

    Added in V1.3:
      /color/ff0080             -> hex color (same as /ff0080; also takes a
                                   name, e.g. /color/red). Handy for tools
                                   that send a hex they worked out, like
                                   Vibe TV: http://<pc>:8765/color/{hex}
      Setting "Accept requests from my network" lets other devices on the
      home network (NAS, second PC) send any of these URLs. Off by default.
    """
    engine: EffectsEngine = None
    curtain               = None     # curtain.Curtain, when GIFs are available
    log_callback          = None

    def do_GET(self):
        if not _local_client(self.client_address[0]):
            self._ok("Only devices on the home network may send commands",
                     status=403)
            return
        url   = urlsplit(self.path)
        parts = [unquote(p) for p in url.path.strip("/").split("/") if p]
        opts  = _options(url.query)

        queue = bool(parts) and parts[0].lower() == "queue"
        if queue:
            parts = parts[1:]
        if not parts:
            self._ok(f"Govee Light Controller {APP_VERSION} running!")
            return

        cmd     = parts[0].lower()
        param   = parts[1].lower() if len(parts) > 1 else None
        forever = "forever" in [p.lower() for p in parts]
        fx = {"queue": queue, "interval": opts["interval"],
              "brightness": opts["brightness"]}      # passed to every effect

        # ── Status ──────────────────────────────────────────
        if cmd == "status":
            active = [l["name"] for l in self.engine.lights if l.get("enabled")]
            self._json({"status": "running", "version": APP_VERSION,
                        "lights": active})
            self._log("status")
            return

        # ── Stop ────────────────────────────────────────────
        if cmd == "stop":
            self.engine.stop()
            self._ok("Stopped")
            self._log("stop")
            return

        # ── Default ─────────────────────────────────────────
        if cmd == "default":
            self.engine.restore_default()
            self._ok("Default restored")
            self._log("default")
            return

        # ── Power ───────────────────────────────────────────
        if cmd == "on":
            self.engine.turn_on()
            self._ok("On")
            self._log("on")
            return
        if cmd == "off":
            self.engine.turn_off()
            self._ok("Off")
            self._log("off")
            return

        # ── Brightness ──────────────────────────────────────
        if cmd in _BRIGHTNESS:
            self.engine.brightness(_BRIGHTNESS[cmd])
            self._ok(f"Brightness {cmd}")
            self._log(cmd)
            return

        # ── Rainbow Strobe: /rainbow-strobe[/5][/forever] ───
        if cmd in _RAINBOW_STROBE_NAMES:
            secs = None if forever else (_parse_seconds(parts) or opts["seconds"])
            label = "rainbow-strobe" + (
                "/forever" if forever else (f"/{secs:g}s" if secs else ""))
            # The engine gets the real URL path (shown in the UI); the reply
            # keeps the v8 wording.
            path = "rainbow-strobe" + (
                "/forever" if forever else (f"/{secs:g}" if secs else ""))
            how = self.engine.rainbow_strobe(indefinite=forever, duration=secs,
                                             label=path, **fx)
            self._played(label, how)
            return

        # ── Rainbow ─────────────────────────────────────────
        if cmd == "rainbow":
            label = "rainbow/forever" if forever else "rainbow"
            how = self.engine.rainbow(indefinite=forever, label=label,
                                      duration=opts["seconds"], **fx)
            self._played(label, how)
            return

        # ── Effects: /strobe/red  or  /strobe/red/forever ───
        if cmd in _EFFECT_NAMES:
            color_name = param or "white"
            if color_name == "rainbow" and cmd == "strobe":
                label = "rainbow-strobe" + ("/forever" if forever else "")
                how = self.engine.rainbow_strobe(
                    indefinite=forever, label=label,
                    duration=opts["seconds"], **fx)
                self._played(label, how)
                return
            r, g, b = COLORS.get(color_name, (255, 255, 255))
            label = f"{cmd}/{color_name}" + ("/forever" if forever else "")
            how = getattr(self.engine, cmd)(r, g, b, indefinite=forever,
                                            label=label,
                                            duration=opts["seconds"], **fx)
            self._played(label, how)
            return

        # ── Combined: /blue-pulse  or  /blue-pulse/forever ──
        for eff in _EFFECT_NAMES:
            if cmd.endswith(f"-{eff}"):
                color_name = cmd[: -(len(eff) + 1)]
                r, g, b = COLORS.get(color_name, (255, 255, 255))
                label = f"{color_name}-{eff}" + ("/forever" if forever else "")
                how = getattr(self.engine, eff)(r, g, b, indefinite=forever,
                                                label=label,
                                                duration=opts["seconds"], **fx)
                self._played(label, how)
                return

        # ── V1.0 effects ────────────────────────────────────
        if cmd in _NEW_EFFECTS:
            self._new_effect(cmd, parts[1:], forever, opts, fx)
            return
        for eff in _COLOR_EFFECTS:               # /blue-breathe, /red-chase ...
            if cmd.endswith(f"-{eff}") and _color(cmd[: -(len(eff) + 1)]):
                self._new_effect(eff, [cmd[: -(len(eff) + 1)]] + parts[1:],
                                 forever, opts, fx)
                return

        # ── Scenes / alerts / single lights ─────────────────
        if cmd == "scene":
            scene = core.find_named(self.engine.cfg.get("scenes"), param or "")
            if not scene:
                self._ok(f"Unknown scene: {param}", status=404)
                return
            self.engine.apply_scene(scene)
            self._ok(f"Scene: {scene['name']}")
            self._log(f"scene/{param}")
            return

        if cmd == "alert":
            alert = core.find_named(self.engine.cfg.get("alerts"), param or "")
            if not alert:
                self._ok(f"Unknown alert: {param}", status=404)
                return
            how = self.engine.run_alert(alert)
            self._played(f"alert/{core.slug(alert['name'])}", how)
            return

        if cmd == "light":
            self._light(parts[1:])
            return

        if cmd == "gif":
            self._gif(parts[1:], url.query)
            return

        # ── V1.3: /color/<hex or name> ──────────────────────
        if cmd == "color":
            self._set_color(param, opts)
            return

        # ── Direct color ────────────────────────────────────
        if cmd in COLORS:
            r, g, b = COLORS[cmd]
            self.engine.set_color(r, g, b, label=cmd)
            if opts["brightness"]:
                self.engine.brightness(opts["brightness"])
            self._ok(f"Color: {cmd}")
            self._log(cmd)
            return

        # ── Hex color: /ff0080 ──────────────────────────────
        hex_c = cmd.lstrip("#")
        if len(hex_c) == 6:
            try:
                r = int(hex_c[0:2], 16)
                g = int(hex_c[2:4], 16)
                b = int(hex_c[4:6], 16)
                self.engine.set_color(r, g, b, label=f"#{hex_c}")
                if opts["brightness"]:
                    self.engine.brightness(opts["brightness"])
                self._ok(f"Color #{hex_c}")
                self._log(f"#{hex_c}")
                return
            except ValueError:
                pass

        self._ok(f"Unknown: {cmd}", status=404)

    # ── V1.0 helpers ────────────────────────────────────────

    def _new_effect(self, effect, rest, forever, opts, fx):
        """/effect[/color[/color2]][/seconds][/forever]"""
        colors, names, secs = [], [], opts["seconds"]
        for token in rest:
            if token.lower() == "forever":
                continue
            found = _color(token)
            if found:
                colors.append(found[0])
                names.append(found[1].lstrip("#"))
                continue
            try:
                secs = max(0.2 if effect == "fade" else 0.5,
                           min(600.0, float(token)))
            except ValueError:
                pass

        takes = core.EFFECTS[effect][1]
        if effect == "fade" and not colors:
            self._ok("Fade needs a color, e.g. /fade/blue/3", status=400)
            return
        if effect in ("flicker", "lightning"):     # colour is optional
            takes = 1 if colors else 0
        if effect == "alternate" and len(colors) < 2:
            colors, names = [(255, 0, 0), (0, 80, 255)], ["red", "blue"]
        if takes and not colors:
            colors, names = [(255, 255, 255)], ["white"]

        can_forever = forever and core.EFFECTS[effect][2]
        label = "/".join([effect] + names[:takes]) + (
            "/forever" if can_forever else (f"/{secs:g}" if secs else ""))
        how = self.engine.play(
            effect, rgb=colors[0] if takes else None,
            rgb2=colors[1] if takes >= 2 else None, indefinite=can_forever,
            duration=None if can_forever else secs, label=label,
            name=names[0] if names else None, **fx)
        self._played(label, how)

    def _set_color(self, token, opts):
        """/color/<hex | name>. Unlike effect URLs, an all-digit value such
        as 112233 is a hex here (there are no seconds to confuse it with)."""
        t = (token or "").strip().lower().lstrip("#")
        rgb = None
        if t in COLORS:
            rgb, label = COLORS[t], t
        elif re.fullmatch(r"[0-9a-f]{6}", t):
            rgb = (int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16))
            label = "#" + t
        if rgb is None:
            self._ok("Use /color/<6-digit hex or color name>, e.g. /color/ff0080",
                     status=400)
            return
        self.engine.set_color(*rgb, label=label)
        if opts["brightness"]:
            self.engine.brightness(opts["brightness"])
        self._ok(f"Color {label}" if label.startswith("#") else f"Color: {label}")
        self._log(f"color/{t}")

    def _light(self, rest):
        """/light/<name or ip>/<color | hex | on | off>"""
        if len(rest) < 2:
            self._ok("Use /light/<name>/<color|on|off>", status=400)
            return
        cfg = self.engine.cfg
        matches = core.find_lights(cfg, rest[0])
        if not matches:
            self._ok(f"Unknown light: {rest[0]}", status=404)
            return
        lights = [l for l in matches if not core.is_excluded(cfg, l)]
        if not lights:
            self._ok(f"Excluded light: {rest[0]}", status=403)
            return
        what = rest[1].lower()
        found = _color(what)
        if what in ("on", "off"):
            for l in lights:
                self.engine.light_power(l["ip"], what == "on")
        elif found:
            for l in lights:
                self.engine.light_color(l["ip"], *found[0])
        else:
            self._ok(f"Unknown: {what}", status=404)
            return
        self._ok(f"Light {lights[0].get('name', rest[0])}: {what}")
        self._log(f"light/{rest[0]}/{what}")

    def _gif(self, rest, query: str):
        """/gif/<name>  |  /gif/default  |  /gif?url=<link>"""
        curtain = self.curtain
        if curtain is None:
            self._ok("Curtain GIFs are not available", status=503)
            return
        # Everything after url= is the link, even if it contains & or ?.
        # seconds=N may come before it, or as the very last thing.
        before, _, link = query.partition("url=")
        if not _:
            before, link = query, ""
        seconds = None
        tail = re.search(r"&seconds=(\d+(?:\.\d+)?)$", link)
        if tail:
            seconds, link = float(tail.group(1)), link[:tail.start()]
        elif "seconds" in parse_qs(before):
            try:
                seconds = float(parse_qs(before)["seconds"][-1])
            except ValueError:
                pass
        link = unquote(link).strip()
        what = rest[0].lower() if rest else ""
        try:
            if what == "avatar":
                how = curtain.play_avatar(link, seconds)
                label = "Profile picture"
            elif link:
                how = curtain.play_source(link, from_chat=True, seconds=seconds)
                label = "GIF link"
            elif what == "default":
                how = curtain.play_default(web=True)
                label = "GIF: default"
            elif rest:
                gif = curtain.find(rest[0])
                if not gif:
                    self._ok(f"Unknown GIF: {rest[0]}", status=404)
                    return
                how = curtain.play_saved(gif, web=True, seconds=seconds)
                label = f"GIF: {gif['name']}"
            else:
                self._ok("Use /gif/<name>, /gif/default, /gif?url=<link> or "
                         "/gif/avatar?url=<picture link>", status=400)
                return
        except CurtainError as e:
            self._ok(str(e), status=e.status)
            return
        self._ok(f"{label} ({how})")
        self._log("gif")

    def _played(self, label: str, how: str):
        self._ok(label + (" (queued)" if how == "queued" else ""))
        self._log(label)

    def _ok(self, msg: str, status=200):
        body = msg.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: dict):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _log(self, cmd: str):
        # Report the path exactly as it was requested, e.g. rainbow-strobe/5
        if self.log_callback:
            self.log_callback(self.path.strip("/") or cmd)

    def log_message(self, format, *args):
        pass


def _local_client(ip: str) -> bool:
    """This PC or a device on the home network (never the open internet)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.is_loopback or addr.is_private or addr.is_link_local


def start_server(engine: EffectsEngine, port: int, log_callback=None,
                 curtain=None, lan: bool = False) -> HTTPServer:
    """Start serving on localhost:port in a background thread.

    With lan=True it listens on every network adapter instead, so other
    devices on the home network can send commands (requests from public
    addresses are still refused).

    Raises OSError if the port can't be opened - including when another copy
    of the app already has it.
    """
    class Handler(LightRequestHandler):
        pass

    class Server(HTTPServer):
        # The default (True) lets a second copy open the same port on Windows
        # and then never receive anything, while claiming to be live.
        allow_reuse_address = False

    Handler.engine       = engine
    Handler.curtain      = curtain
    Handler.log_callback = staticmethod(log_callback) if log_callback else None

    httpd = Server(("0.0.0.0" if lan else "localhost", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def stop_server(httpd: HTTPServer | None):
    if httpd:
        threading.Thread(target=httpd.shutdown, daemon=True).start()
