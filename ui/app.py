"""The main window: sidebar navigation + a scrolling page area.

The window owns the config, the effects engine and the HTTP server, and
offers the actions the pages call (apply a colour, run an effect, scan...).
"""

import os
import queue
import threading
import time
import tkinter as tk
from tkinter import colorchooser, messagebox, simpledialog

import engine as core
import server
from curtain import Curtain
from engine import APP_NAME, APP_VERSION, COLORS

from . import draw, theme
from .alerts import AlertsPage
from .colors import ColorsPage
from .dashboard import SPEEDS, DashboardPage
from .gifs import GifsPage
from .scenes import ScenesPage
from .settings import SettingsPage
from .stage import Scroller, Stage

SIDEBAR_W = 232
NAV = (
    ("dashboard", "Dashboard", "grid"),
    ("lights",    "Lights",    "bulb"),
    ("effects",   "Effects",   "sparkles"),
    ("scenes",    "Scenes",    "layers"),
    ("alerts",    "Alerts",    "zap"),
    ("gifs",      "GIFs",      "image"),
    ("settings",  "Settings",  "gear"),
)


def cmd_color(cmd: str, cfg: dict) -> str:
    """Dot colour for an activity entry."""
    c = cmd.lower().strip("/")
    if "rainbow" in c:
        return "#EC4899"
    first = c.split("/")[0]
    if first == "stop":
        return theme.MUTED
    if first == "off":
        return "#3A3A4E"
    if first in ("on", "status", "scan"):
        return theme.GREEN
    if first == "default":
        dc = cfg.get("default_color", {"r": 255, "g": 255, "b": 255})
        return draw.hexc(dc["r"], dc["g"], dc["b"])
    for token in c.replace("-", "/").split("/"):
        if token in COLORS:
            return draw.hexc(*COLORS[token])
    h = first.lstrip("#")
    if len(h) == 6:
        try:
            int(h, 16)
            return "#" + h.upper()
        except ValueError:
            pass
    return theme.AMBER if first in ("dim", "low", "medium", "half", "bright",
                                    "max", "brightness") else theme.MUTED


class GoveeApp(tk.Tk):
    def __init__(self):
        super().__init__()
        theme.init(self)
        s = theme.SCALE

        self.cfg = core.load_config()
        self.engine = core.EffectsEngine()
        self.sync_lights()
        self.curtain = Curtain(os.path.dirname(core.CONFIG_FILE), self.cfg,
                               lambda: core.save_config(self.cfg))

        self.httpd = None
        self.server_error = None
        self.running_port = self.cfg.get("port", 8765)
        self.running_lan = bool(self.cfg.get("lan_access", False))
        self.log: list[dict] = []
        self.events: queue.Queue = queue.Queue()   # from worker threads
        self.page = "dashboard"
        self.nav = "dashboard"
        self.effect_color = "red"
        self.forever = False
        self.scanning = False
        self.copied = None

        self.title(f"{APP_NAME} {APP_VERSION}")
        self.configure(bg=theme.BG)
        w = min(int(1280 * s), self.winfo_screenwidth() - 80)
        h = min(int(900 * s), self.winfo_screenheight() - 120)
        self.geometry(f"{w}x{h}")
        self.minsize(min(int(960 * s), w), min(int(600 * s), h))
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        if self.cfg.get("always_on_top"):
            self.attributes("-topmost", True)

        self.sidebar = Stage(self, bg=theme.SIDEBAR)
        self.sidebar.configure(width=draw.dev(SIDEBAR_W))
        self.sidebar.pack(side="left", fill="y")
        self.main = Stage(self, bg=theme.BG)
        self.scroller = Scroller(self, self.main)
        self.scroller.pack(side="right", fill="y")
        self.main.pack(side="left", fill="both", expand=True)
        self.main.configure(yscrollincrement=draw.dev(24))

        self.pages = {
            "dashboard": DashboardPage(self),
            "colors":    ColorsPage(self),
            "scenes":    ScenesPage(self),
            "alerts":    AlertsPage(self),
            "gifs":      GifsPage(self),
            "settings":  SettingsPage(self),
        }
        self._content_h = 0.0
        self._render_job = None
        self._pending_anchor = None
        self._scenes_rev = -1
        self._curtain_rev = self.curtain.rev

        self.sidebar.bind("<Configure>", lambda e: self.render_sidebar(), add="+")
        self.main.bind("<Configure>", lambda e: self.refresh(), add="+")
        self.bind_all("<MouseWheel>", self._on_wheel)

        self.start_server()

        # Saved lights show immediately; scan if asked to (or the list is empty)
        if not self.cfg.get("lights") or self.cfg.get("auto_scan_on_startup"):
            self.after(800, self.scan)
        if self.cfg.get("startup_apply_default"):
            self.after(1200, self.apply_default)
        self.after(200, self._tick)

    # ══════════════════════════════════════════════════════════
    #  RENDERING
    # ══════════════════════════════════════════════════════════

    def refresh(self):
        """Redraw the current page soon (several calls become one redraw)."""
        if self._render_job is None:
            self._render_job = self.after(15, self.render)

    def render(self):
        if self._render_job is not None:
            self.after_cancel(self._render_job)
            self._render_job = None
        st = self.main
        w, view_h = st.size()
        if w < 50:
            return
        st.begin()
        self._content_h = self.pages[self.page].render(st, w)
        s = theme.SCALE
        st.configure(scrollregion=(0, 0, int(w * s),
                                   int(max(self._content_h, view_h) * s)))
        if self._pending_anchor is not None:
            total = max(self._content_h, view_h)
            st.yview_moveto(max(0.0, self._pending_anchor) / total)
            self._pending_anchor = None
        st.end()

    def render_sidebar(self):
        sb = self.sidebar
        _, h = sb.size()
        if h < 50:
            return
        sb.begin()
        sb.create_rectangle(draw.dev(SIDEBAR_W) - max(1, round(theme.SCALE)), 0,
                            draw.dev(SIDEBAR_W), h * theme.SCALE,
                            fill=theme.LINE, outline="")
        # Brand
        sb.img(24 - draw.LOGO_PAD, 24 - draw.LOGO_PAD, draw.logo)
        sb.txt(74, 34, "Govee Control", 15, "bold")
        sb.txt(74, 53, f"Light controller · {APP_VERSION}", 12, fill=theme.MUTED)

        # Navigation
        y = 90
        for key, label, icon in NAV:
            active = key == self.nav
            if active:
                sb.img(16, y, draw.rrect, 200, 40, 10, theme.NAV_ACTIVE)
            else:
                hov = sb.img(16, y, draw.rrect, 200, 40, 10, theme.NAV_HOVER,
                             state="hidden")
            fg = theme.TEXT if active else theme.DIM
            ic = sb.img(28, y + 11, draw.icon, icon, 18,
                        theme.ACCENT_SOFT if active else theme.DIM)
            tx = sb.txt(58, y + 20, label, 14, "semi" if active else "reg", fg)
            if not active:
                def enter(hov=hov, ic=ic, tx=tx, icon=icon):
                    sb.itemconfigure(hov, state="normal")
                    sb.itemconfigure(tx, fill=theme.TEXT)
                    sb.set_img(ic, draw.icon, icon, 18, theme.TEXT)

                def leave(hov=hov, ic=ic, tx=tx, icon=icon):
                    sb.itemconfigure(hov, state="hidden")
                    sb.itemconfigure(tx, fill=theme.DIM)
                    sb.set_img(ic, draw.icon, icon, 18, theme.DIM)

                sb.zone(16, y, 200, 40, click=lambda k=key: self.go(k),
                        enter=enter, leave=leave)
            y += 44

        # Server status
        cy = h - 24 - 72
        sb.img(16, cy, draw.rrect, 200, 72, 14, theme.CARD, theme.LINE)
        live = self.httpd is not None
        sb.img(34, cy + 24, draw.status_dot, theme.GREEN if live else theme.RED,
               anchor="center")
        sb.txt(46, cy + 23, "Server live" if live else "Server offline",
               13, "semi")
        host = (self.lan_ip() or "network") if self.running_lan else "localhost"
        sb.txt(30, cy + 50, f"{host}:{self.running_port}", 12, "mono",
               theme.MUTED)
        sb.end()

    def go(self, key: str, pick: dict | None = None):
        """Navigate. 'lights' and 'effects' are sections of the dashboard.

        The colours page can be opened as a picker: pass pick=dict(title, sub,
        current, choose, back) - see pick_color().
        """
        if key in ("lights", "effects"):
            self.page, self.nav = "dashboard", key
            self.render()        # so the section positions are known
            self._pending_anchor = self.pages["dashboard"].anchors.get(key, 0) - 20
        else:
            self.page = key
            self._pending_anchor = 0
            if key == "colors":
                self.pages["colors"].pick = pick
                if pick is None:
                    self.nav = "dashboard"
            else:
                self.nav = key
            if key == "settings":
                self.pages["settings"].load()
        self.render_sidebar()
        self.render()

    def pick_color(self, title: str, sub: str, current, choose, back: str):
        """Open the colours page to choose a colour name.

        choose(name) is called with the pick, then the app returns to `back`.
        """
        self.go("colors", pick={"title": title, "sub": sub, "current": current,
                                "choose": choose, "back": back})

    def _on_wheel(self, e):
        try:
            if e.widget.winfo_toplevel() is not self:
                return
        except Exception:
            return
        if self.scroller.needed():
            self.main.yview_scroll(int(-e.delta / 120) * 3, "units")
            self.main.refresh_hover()

    def _tick(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "log":
                    self.log_add(*data)
                elif kind == "scan":
                    self._on_scan_done(data)
                elif kind == "ui":
                    data()
        except queue.Empty:
            pass
        if self.curtain.rev != self._curtain_rev:    # GIF progress / sign-in
            self._curtain_rev = self.curtain.rev
            if self.page in ("gifs", "dashboard", "settings"):
                self.refresh()
        if self.page == "dashboard":
            self.pages["dashboard"].tick()
        elif self.page == "scenes" and self.engine.rev != self._scenes_rev:
            self._scenes_rev = self.engine.rev      # highlight the active scene
            self.refresh()
        elif self.page == "gifs":
            self.pages["gifs"].tick()
        self.after(200, self._tick)

    def background(self, work, done=None):
        """Run work() off the UI thread, then done(result, error) on it."""
        def run():
            try:
                result, error = work(), None
            except Exception as e:
                result, error = None, e
            if done:
                self.events.put(("ui", lambda: done(result, error)))
        threading.Thread(target=run, daemon=True).start()

    # ══════════════════════════════════════════════════════════
    #  SERVER / LOG
    # ══════════════════════════════════════════════════════════

    def base_url(self) -> str:
        return f"http://localhost:{self.running_port}"

    def lan_ip(self) -> str:
        """This PC's address on the home network (cached), or ''."""
        if not hasattr(self, "_lan_ip"):
            self._lan_ip = ""
            try:
                import socket
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    # No packet is sent; this only picks the outgoing adapter.
                    s.connect(("10.255.255.255", 1))
                    self._lan_ip = s.getsockname()[0]
                finally:
                    s.close()
            except OSError:
                pass
        return self._lan_ip

    def start_server(self):
        try:
            self.httpd = server.start_server(
                self.engine, self.running_port,
                lambda cmd: self.events.put(("log", ("/" + cmd, "MixItUp"))),
                curtain=self.curtain, lan=self.running_lan)
            self.server_error = None
        except OSError as e:
            self.httpd = None
            self.server_error = str(e)
            self.log_add("server", f"port {self.running_port} is busy", theme.RED)

    def log_add(self, cmd: str, src: str, color: str | None = None):
        self.log.insert(0, {"t": time.strftime("%H:%M:%S"), "cmd": cmd,
                            "src": src, "c": color or cmd_color(cmd, self.cfg)})
        del self.log[100:]
        if self.page == "dashboard":
            self.refresh()

    def copy(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)

    def copy_url(self, key, path: str):
        """Copy a full MixItUp URL and flash a tick on its button."""
        self.copy(self.base_url() + path)
        self.copied = key
        self.refresh()

        def clear():
            if self.copied == key:
                self.copied = None
                self.refresh()
        self.after(1500, clear)

    # ══════════════════════════════════════════════════════════
    #  LIGHTS
    # ══════════════════════════════════════════════════════════

    def sync_lights(self):
        """Tell the engine which lights get room commands."""
        self.engine.lights = core.room_lights(self.cfg)
        self.engine.cfg = self.cfg

    def save(self):
        core.save_config(self.cfg)
        self.sync_lights()

    def is_excluded(self, light: dict) -> bool:
        return core.is_excluded(self.cfg, light)

    def visible_lights(self) -> list[dict]:
        lights = self.cfg.get("lights", [])
        if self.cfg.get("hide_offline"):
            lights = [l for l in lights if not l.get("_offline")]
        return lights

    def toggle_light(self, light: dict):
        light["enabled"] = not light.get("enabled", True)
        self.save()
        self.refresh()

    def select_all(self, enabled: bool):
        for l in self.visible_lights():
            # Curtains keep their own mode; All / None is for the room lights
            if not self.is_excluded(l) and not core.is_curtain(self.cfg, l):
                l["enabled"] = enabled
        self.save()
        self.refresh()

    def remove_light(self, light: dict):
        self.cfg["lights"] = [l for l in self.cfg["lights"] if l is not light]
        self.save()
        self.log_add("removed", f"{light.get('name', light['ip'])}", theme.MUTED)

    def clear_offline(self):
        before = len(self.cfg["lights"])
        self.cfg["lights"] = [l for l in self.cfg["lights"]
                              if not l.get("_offline")]
        removed = before - len(self.cfg["lights"])
        self.save()
        self.log_add("clear offline",
                     f"Removed {removed} light(s)" if removed
                     else "No offline lights", theme.MUTED)

    def rename_light(self, light: dict):
        new = simpledialog.askstring(
            "Rename", f"Name for {light['ip']}:",
            initialvalue=light.get("name", light["sku"]), parent=self)
        if new and new.strip():
            light["name"] = new.strip()
            self.save()
        self.refresh()

    def light_power(self, light: dict):
        """Switch one light on/off directly."""
        on = not self.engine.power.get(light["ip"], True)
        self.engine.light_power(light["ip"], on)
        self.refresh()

    def scan(self):
        if self.scanning:
            return
        self.scanning = True
        self.refresh()
        threading.Thread(
            target=lambda: self.events.put(
                ("scan", core.discover_lights(timeout=3.0))),
            daemon=True).start()

    def _on_scan_done(self, found: list[dict]):
        self.scanning = False
        excluded_ips = self.cfg.get("excluded_ips", [])
        existing = {l["ip"]: l for l in self.cfg.get("lights", [])}
        merged = []
        for dev in found:
            ip = dev["ip"]
            if ip in excluded_ips:
                continue
            if ip in existing:
                existing[ip]["_offline"] = False
                merged.append(existing[ip])
            else:
                merged.append({"ip": ip, "name": dev["sku"],
                               "sku": dev["sku"],
                               # a newly found curtain starts in GIF mode
                               "enabled": not core.is_curtain(self.cfg, dev)})
        found_ips = {d["ip"] for d in found}
        for l in existing.values():
            if l["ip"] not in found_ips and l["ip"] not in excluded_ips:
                l["_offline"] = True
                merged.append(l)
        self.cfg["lights"] = merged
        self.save()
        n = len([l for l in merged if not l.get("_offline")])
        self.log_add("scan", f"Found {n} light{'' if n == 1 else 's'}")

    # ══════════════════════════════════════════════════════════
    #  ROOM COMMANDS
    # ══════════════════════════════════════════════════════════

    def apply_color(self, name: str):
        self.engine.set_color(*COLORS[name], label=name)
        self.log_add("/" + name, "Dashboard")

    def all_on(self):
        self.engine.turn_on()
        self.log_add("/on", "Dashboard")

    def all_off(self):
        self.engine.turn_off()
        self.log_add("/off", "Dashboard")

    def stop(self):
        self.engine.stop()
        self.log_add("/stop", "Dashboard")

    def effect_path(self, fx: str) -> str:
        """The MixItUp URL path for an effect with the current options."""
        c = self.effect_color
        path = {"flash": f"/flash/{c}", "strobe": f"/strobe/{c}",
                "pulse": f"/{c}-pulse", "rainbow": "/rainbow",
                "rainbow-strobe": "/rainbow-strobe",
                "chase": f"/chase/{c}", "police": "/police",
                "flicker": "/flicker", "breathe": f"/breathe/{c}",
                "fade": f"/fade/{c}", "lightning": "/lightning",
                "sparkle": f"/sparkle/{c}", "countdown": "/countdown"}[fx]
        can_forever = self.forever and core.EFFECTS[fx][2]
        return path + ("/forever" if can_forever else "")

    def run_effect(self, fx: str):
        path = self.effect_path(fx)
        takes_color = core.EFFECTS[fx][1] >= 1
        self.engine.play(
            fx, rgb=COLORS.get(self.effect_color, (255, 255, 255))
            if takes_color else None,
            indefinite=self.forever, label=path.lstrip("/"),
            name=self.effect_color)
        self.log_add(path, "Dashboard")

    # ── one light ───────────────────────────────────────────

    def pick_light_color(self, light: dict):
        name = light.get("name", light["sku"])

        def choose(color):
            self.engine.light_color(light["ip"], *COLORS[color])
            self.log_add(f"/light/{core.slug(name)}/{color}", "Dashboard")

        self.pick_color(f"Color for {name}", "Only this light changes",
                        None, choose, "lights")

    # ── scenes ──────────────────────────────────────────────

    def save_scene(self):
        name = simpledialog.askstring(
            "Save scene", "Name for this scene:", parent=self)
        if not name or not core.slug(name):
            self.refresh()
            return
        scene = self.engine.capture_scene(name.strip())
        if scene is None:
            messagebox.showinfo(
                "Nothing to save yet",
                "Set the room (or single lights) to a color first, "
                "then save the scene.", parent=self)
            return
        scenes = [s for s in self.cfg.get("scenes", [])
                  if core.slug(s.get("name", "")) != core.slug(name)]
        scenes.append(scene)
        self.cfg["scenes"] = scenes
        self.save()
        self.refresh()

    def apply_scene(self, scene: dict):
        threading.Thread(target=self.engine.apply_scene, args=(scene,),
                         daemon=True).start()
        self.log_add("/scene/" + core.slug(scene["name"]), "Dashboard",
                     theme.ACCENT_SOFT)

    def delete_scene(self, scene: dict):
        self.cfg["scenes"] = [s for s in self.cfg.get("scenes", [])
                              if s is not scene]
        self.save()
        self.refresh()

    # ── alerts ──────────────────────────────────────────────

    def new_alert(self):
        name = simpledialog.askstring(
            "New alert", "Name (used in the URL, e.g. raid):", parent=self)
        if not name or not core.slug(name):
            self.refresh()
            return
        if core.find_named(self.cfg.get("alerts"), name):
            messagebox.showinfo("Already exists",
                                f"There is already an alert called {name}.",
                                parent=self)
            return
        self.cfg.setdefault("alerts", []).append(
            {"name": name.strip(), "effect": "strobe", "color": "red",
             "color2": "blue", "seconds": None, "speed": None})
        self.save()
        self.refresh()

    def delete_alert(self, alert: dict):
        self.cfg["alerts"] = [a for a in self.cfg.get("alerts", [])
                              if a is not alert]
        self.save()
        self.refresh()

    def test_alert(self, alert: dict):
        path = "/alert/" + core.slug(alert["name"])
        self.engine.run_alert(alert, label=path.lstrip("/"))
        self.log_add(path, "Dashboard")

    def set_brightness(self, value: int):
        self.engine.brightness(value)
        self.log_add(f"brightness {value}%", "Dashboard", theme.AMBER)

    def speed_index(self) -> int:
        cur = self.cfg.get("strobe_interval", 0.15)
        return min(range(len(SPEEDS)), key=lambda i: abs(SPEEDS[i][1] - cur))

    def set_speed(self, index: int):
        self.cfg["strobe_interval"] = SPEEDS[index][1]
        self.save()
        self.refresh()

    def toggle_forever(self):
        self.forever = not self.forever
        self.refresh()

    # ── default colour ──────────────────────────────────────

    def default_hex(self) -> str:
        dc = self.cfg.get("default_color", {"r": 255, "g": 255, "b": 255})
        return draw.hexc(dc["r"], dc["g"], dc["b"])

    def set_default(self, r: int, g: int, b: int):
        self.cfg["default_color"] = {"r": r, "g": g, "b": b}
        self.save()
        self.refresh()

    def pick_default(self):
        result = colorchooser.askcolor(color=self.default_hex(),
                                       title="Pick Default Color", parent=self)
        if result and result[0]:
            self.set_default(*(int(x) for x in result[0]))
        self.refresh()

    def use_current_as_default(self) -> bool:
        """Make the colour the room is showing the default. False if unknown."""
        now = self.engine.now
        if now.get("kind") == "color" and now.get("rgb"):
            self.set_default(*now["rgb"])
            return True
        return False

    def apply_default(self):
        threading.Thread(target=self.engine.restore_default, daemon=True).start()

    # ══════════════════════════════════════════════════════════

    def on_close(self):
        server.stop_server(self.httpd)
        self.curtain.close()
        core.close_socket()
        self.destroy()
