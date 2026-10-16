"""Settings page (scrolls with the mouse wheel or the scrollbar).

Switches and number boxes are held as pending values until Save is clicked;
the default-colour buttons act straight away.
"""

import tkinter as tk
from tkinter import messagebox

from . import draw, theme
from .theme import fit, measure

ROW_H = 56

# (path, what it does) - the MixItUp cheat sheet
URLS = (
    ("/red", "Any color name, e.g. /blue /hotpink /gaming"),
    ("/ff0080", "Any hex color"),
    ("/color/ff0080", "Hex or color name, for tools that send {hex}"),
    ("/on", "Room on"),
    ("/off", "Room off"),
    ("/stop", "Stop the effect and restore the default color"),
    ("/default", "Restore the default color"),
    ("/dim", "Brightness: /dim /low /medium /half /bright /max"),
    ("/strobe/red", "Strobe (also /flash/red and /pulse/red)"),
    ("/strobe/red/forever", "Add /forever to run until /stop"),
    ("/blue-pulse", "Color first works too: -pulse -flash -strobe"),
    ("/rainbow", "Rainbow fade"),
    ("/rainbow/forever", "Rainbow until /stop"),
    ("/rainbow-strobe", "Rainbow strobe for the effect duration"),
    ("/rainbow-strobe/5", "Rainbow strobe for 5 seconds"),
    ("/rainbow-strobe/forever", "Rainbow strobe until /stop"),
    ("/status", "JSON status"),
    ("/chase/red", "One lit light runs round the room"),
    ("/police", "Red / blue alternating"),
    ("/alternate/red/blue", "Any two colors alternating"),
    ("/flicker", "Fire flicker (or /flicker/blue for a color)"),
    ("/breathe/blue", "Slow swell that never goes dark"),
    ("/lightning", "Random white bursts"),
    ("/sparkle/purple", "Color with white pops"),
    ("/chase/red/5", "New effects take seconds or /forever"),
    ("/fade/blue/3", "Glide to a color over 3 seconds and stay"),
    ("/countdown/10", "Green to red over 10 seconds, then flash"),
    ("/scene/name", "Recall a saved scene"),
    ("/alert/name", "Play an alert preset"),
    ("/queue/strobe/red", "Wait for the running effect instead of cutting in"),
    ("/light/name/red", "One light by name or IP (color, on, off)"),
    ("/strobe/red?speed=fast", "Options: speed, brightness=1-100, seconds=N"),
    ("/gif/name", "Curtain: play a saved GIF"),
    ("/gif/default", "Curtain: play the default GIF"),
    ("/gif?url=LINK", "Curtain: play a Giphy / Tenor / Imgur link from chat"),
    ("/gif/avatar?url=LINK", "Curtain: a profile picture, e.g. url=$useravatar"),
    ("/gif/name?seconds=15", "Curtain: show time for this one request"),
)


class SettingsPage:
    def __init__(self, app):
        self.app = app
        self.flags: dict = {}
        self.vars: dict = {}
        self.note = ("", theme.MUTED)
        # Govee account form (acts straight away, not part of Save settings)
        self.account = {k: tk.StringVar(master=app)
                        for k in ("key", "email", "password", "code")}
        self.account_note = ("", theme.MUTED)
        self.account_busy = False
        self._checked_devices = False
        self.load()

    def load(self):
        """(Re)read pending values from the saved config."""
        cfg = self.app.cfg
        self.flags = {k: bool(cfg.get(k, d)) for k, d in (
            ("auto_scan_on_startup", False), ("startup_apply_default", False),
            ("always_on_top", False), ("hide_offline", False),
            ("restore_after_effect", True), ("queue_alerts", True),
            ("gif_strict", True), ("gif_remember", True),
            ("gif_queue", False), ("lan_access", False))}
        # Shown as a switch; stored as after_effect = "previous" / "default"
        self.flags["return_previous"] = cfg.get("after_effect") == "previous"
        for key, default in (("port", 8765), ("command_cooldown", 0),
                             ("effect_duration", 8), ("gif_cooldown", 10),
                             ("gif_web_seconds", 8)):
            text = f"{cfg.get(key, default):g}"
            if key in self.vars:
                self.vars[key].set(text)
            else:
                self.vars[key] = tk.StringVar(master=self.app, value=text)
        self.note = ("", theme.MUTED)

    # ══════════════════════════════════════════════════════════

    def render(self, st, width) -> float:
        a = self.app
        x = 32
        w = max(560, min(width - 64, 820))
        y = 28

        st.txt(x, y + 18, "Settings", 28, "bold")
        text, color = self.note
        st.txt(x, y + 51, text or "Changes apply when you click Save settings",
               14, fill=color if text else theme.MUTED)
        bx = x + w
        bx -= st.button(bx, y + 8, 44, self.save, "Save settings", "check",
                        fg="#FFFFFF", fill=theme.ACCENT, hover="#8B4DF5",
                        line=None, align_right=True) + 10
        st.button(bx, y + 8, 44, self.revert, "Revert", align_right=True)
        y += 62 + 22

        curtains = ", ".join(a.cfg.get("curtain_skus", [])) or "none"
        y = self._section(st, x, y, w, "Startup", (
            ("flag", "auto_scan_on_startup", "Scan for lights when the app opens", ""),
            ("flag", "startup_apply_default", "Apply the default color on launch", ""),
        ))
        y = self._section(st, x, y, w, "Window", (
            ("flag", "always_on_top", "Always on top", ""),
        ))
        y = self._section(st, x, y, w, "Lights", (
            ("flag", "hide_offline", "Hide offline lights", ""),
            ("info", curtains, "Curtain models (can show GIFs)",
             "Switch a curtain off on the Dashboard to keep it in GIF mode"),
        ))
        y = self._section(st, x, y, w, "Server", (
            ("entry", "port", "Port", "Restart the app to apply"),
            ("flag", "lan_access", "Accept requests from my network",
             "For a NAS or another PC. Home addresses only. Restart to apply"),
            ("entry", "command_cooldown", "Command cooldown (seconds)",
             "0 = no limit"),
        ))
        y = self._section(st, x, y, w, "Effects", (
            ("entry", "effect_duration", "Effect duration (seconds)",
             "How long timed effects run"),
            ("flag", "restore_after_effect",
             "Restore the room when a timed effect ends", ""),
            ("flag", "return_previous",
             "Return to the previous look instead of the default color",
             "/stop always restores the default color"),
            ("flag", "queue_alerts", "Play alerts one after another",
             "Off: a new alert cuts off the one that is playing"),
        ))
        y = self._default_color(st, x, y, w)
        y = self._account(st, x, y, w)
        y = self._section(st, x, y, w, "Curtain GIFs", (
            ("flag", "gif_strict", "Chat links: Giphy, Tenor and Imgur only",
             "Off: /gif?url= accepts a .gif link from any site"),
            ("entry", "gif_cooldown", "Seconds between chat links",
             "Stops chat flooding the curtain (0 = no limit)"),
            ("entry", "gif_web_seconds",
             "Show a web-request GIF for (seconds)",
             "Then the default GIF comes back. 0 = stay. GIFs played in the "
             "app always stay"),
            ("flag", "gif_queue", "Queue web-request GIFs",
             "Each waits its turn and gets its show time. Off: refused while "
             "one is loading"),
            ("flag", "gif_remember", "Stay signed in to Govee",
             "Keeps your password encrypted for this Windows user, to renew "
             "the sign-in"),
        ))
        y = self._urls(st, x, y, w)
        return y + 18

    # ── building blocks ─────────────────────────────────────

    def _card(self, st, x, y, w, title, body_h) -> float:
        """Draw a titled card; returns the y where its rows start."""
        st.img(x, y, draw.rrect, w, 20 + 24 + 8 + body_h + 10, 18,
               theme.CARD, theme.LINE)
        st.txt(x + 20, y + 32, title, 17, "bold")
        return y + 52

    def _section(self, st, x, y, w, title, rows) -> float:
        ry = self._card(st, x, y, w, title, len(rows) * ROW_H)
        ix, iw = x + 20, w - 40
        for i, (kind, key, label, hint) in enumerate(rows):
            if i:
                st.hline(ix, ry, iw)
            mid = ry + ROW_H / 2
            if hint:
                st.txt(ix, mid - 9, label, 14)
                st.txt(ix, mid + 10, hint, 12, fill=theme.MUTED)
            else:
                st.txt(ix, mid, label, 14)
            if kind == "flag":
                st.switch(ix + iw - 44, mid - 13, self.flags[key],
                          lambda k=key: self._flip(k))
            elif kind == "entry":
                self._entry(st, ix + iw - 96, mid - 18, self.vars[key])
            else:
                pw = measure(key, 12, "mono") + 24
                st.img(ix + iw - pw, mid - 14, draw.rrect, pw, 28, 14, theme.PILL)
                st.txt(ix + iw - pw / 2, mid, key, 12, "mono", anchor="center")
            ry += ROW_H
        return ry + 10 + 18

    def _entry(self, st, x, y, var):
        st.img(x, y, draw.rrect, 96, 36, 10, theme.BG, theme.GHOST_LINE)
        e = tk.Entry(st, textvariable=var, justify="center", relief="flat", bd=0,
                     bg=theme.BG, fg=theme.TEXT, insertbackground=theme.TEXT,
                     selectbackground=theme.ACCENT, selectforeground="#FFFFFF",
                     highlightthickness=0, font=theme.font(13, "mono"))
        e.bind("<Return>", lambda _e: self.save())
        st.widget(x + 10, y + 7, 76, 22, e)

    def _default_color(self, st, x, y, w) -> float:
        a = self.app
        ry = self._card(st, x, y, w, "Default color", ROW_H)
        ix, iw = x + 20, w - 40
        mid = ry + ROW_H / 2
        hexv = a.default_hex()
        pw = 6 + 20 + 8 + measure(hexv, 12, "mono") + 12
        st.img(ix, mid - 16, draw.rrect, pw, 32, 16, theme.PILL)
        st.img(ix + 6, mid - 10, draw.circle, 20, hexv)
        st.txt(ix + 34, mid, hexv, 12, "mono")
        if iw - pw > 520:
            st.txt(ix + pw + 12, mid, "Lights return to this after effects", 12,
                   fill=theme.MUTED)
        bx = ix + iw
        for text, cmd in (("Apply now", self._apply_default),
                          ("Use current", self._use_current),
                          ("Pick…", a.pick_default)):
            bx -= st.button(bx, mid - 18, 36, cmd, text, pad=14, r=10, size=13,
                            align_right=True) + 8
        return ry + ROW_H + 10 + 18

    # ── Govee account (for curtain GIFs) ────────────────────

    def _field(self, st, x, y, w, var, hidden=False, on_enter=None):
        st.img(x, y, draw.rrect, w, 36, 10, theme.BG, theme.GHOST_LINE)
        e = tk.Entry(st, textvariable=var, relief="flat", bd=0,
                     show="•" if hidden else "",
                     bg=theme.BG, fg=theme.TEXT, insertbackground=theme.TEXT,
                     selectbackground=theme.ACCENT, selectforeground="#FFFFFF",
                     highlightthickness=0, font=theme.font(13, "mono"))
        if on_enter:
            e.bind("<Return>", lambda _e: on_enter())
        st.widget(x + 12, y + 7, w - 24, 22, e)

    def _account(self, st, x, y, w) -> float:
        a = self.app
        c = a.curtain
        ix, iw = x + 20, w - 40
        fw = min(340, iw - 190)                    # width of the text boxes
        fx = ix + iw - fw
        if c.ready():
            rows = ("status", "curtains")
        elif c.waiting_for_code():
            rows = ("code",)
        else:
            rows = ("key", "email", "password", "connect")
        ry = self._card(st, x, y, w, "Govee account (for curtain GIFs)",
                        len(rows) * ROW_H + 26)
        text, color = self.account_note
        if not text:
            text = ("GIFs reach the curtain through Govee's cloud. The API key "
                    "is free: Govee Home app > Profile > Settings > Apply for "
                    "API Key.")
            color = theme.MUTED
        st.txt(ix, ry + 8, fit(text, 12, "reg", iw), 12, fill=color)
        ry += 26

        for i, row in enumerate(rows):
            if i:
                st.hline(ix, ry, iw)
            mid = ry + ROW_H / 2
            if row == "status":
                st.img(ix + 5, mid, draw.status_dot, theme.GREEN, anchor="center")
                who = c.acct.get("email") or "your Govee account"
                st.txt(ix + 18, mid, fit(f"Connected as {who}", 14, "reg",
                                         iw - 140), 14)
                st.button(ix + iw, mid - 18, 36, self._sign_out, "Sign out",
                          pad=14, r=10, size=13, align_right=True)
            elif row == "curtains":
                st.txt(ix, mid, "Curtain lights on the account", 14)
                devices = c._devices
                if devices is None:
                    names = "Checking…"
                    if not self._checked_devices:
                        self._checked_devices = True
                        a.background(lambda: c.devices(),
                                     lambda r, e: self._devices_done(e))
                else:
                    names = ", ".join(d["name"] for d in devices) or "none found"
                st.txt(ix + iw, mid, fit(names, 13, "reg", iw - 240), 13,
                       fill=theme.MUTED, anchor="e")
            elif row == "key":
                st.txt(ix, mid - 9, "Govee API key", 14)
                st.txt(ix, mid + 10, "Saved - leave blank to keep it"
                       if c.has_key() else "36 characters, with dashes", 12,
                       fill=theme.MUTED)
                self._field(st, fx, mid - 18, fw, self.account["key"],
                            hidden=True)
            elif row == "email":
                st.txt(ix, mid, "Govee account email", 14)
                self._field(st, fx, mid - 18, fw, self.account["email"])
            elif row == "password":
                st.txt(ix, mid - 9, "Govee account password", 14)
                st.txt(ix, mid + 10, "Sent to Govee only", 12, fill=theme.MUTED)
                self._field(st, fx, mid - 18, fw, self.account["password"],
                            hidden=True, on_enter=self._connect)
            elif row == "connect":
                st.txt(ix, mid, "Govee may email you a code the first time", 12,
                       fill=theme.MUTED)
                st.button(ix + iw, mid - 18, 36, self._connect,
                          "Connecting…" if self.account_busy else "Connect",
                          pad=18, r=10, size=13, fg="#FFFFFF",
                          fill=theme.ACCENT, hover="#8B4DF5", line=None,
                          align_right=True)
            elif row == "code":
                st.txt(ix, mid - 9, "Code from Govee's email", 14)
                st.txt(ix, mid + 10, "Check the inbox (and spam) of your Govee "
                       "account", 12, fill=theme.MUTED)
                bx = ix + iw
                bx -= st.button(bx, mid - 18, 36, self._cancel_code, "Cancel",
                                pad=14, r=10, size=13, align_right=True) + 8
                bx -= st.button(bx, mid - 18, 36, self._verify,
                                "Checking…" if self.account_busy else "Verify",
                                pad=18, r=10, size=13, fg="#FFFFFF",
                                fill=theme.ACCENT, hover="#8B4DF5", line=None,
                                align_right=True) + 10
                self._field(st, bx - 120, mid - 18, 120, self.account["code"],
                            on_enter=self._verify)
            ry += ROW_H
        return ry + 10 + 18

    def _account_result(self, result, error, ok_text):
        self.account_busy = False
        self.account["password"].set("")
        self.account["code"].set("")
        if error:
            self.account_note = (str(error), theme.RED)
        elif result == "code":
            self.account_note = ("Govee emailed you a code. Enter it below.",
                                 theme.AMBER)
        else:
            self.account["key"].set("")
            self._checked_devices = False
            self.account_note = (ok_text, theme.GREEN)
        self.app.refresh()

    def _connect(self):
        a = self.app
        c = a.curtain
        if self.account_busy:
            return
        key = self.account["key"].get().strip()
        email = self.account["email"].get().strip()
        password = self.account["password"].get()
        if not (key or c.has_key()):
            self.account_note = ("Enter your Govee API key", theme.AMBER)
        elif not (email and password):
            self.account_note = ("Enter your Govee email and password",
                                 theme.AMBER)
        else:
            self.account_busy = True
            self.account_note = ("Connecting to Govee…", theme.MUTED)

            def work():
                if key:
                    c.set_api_key(key)
                c.devices(refresh=True)            # proves the key works
                return c.sign_in(email, password)
            a.background(work, lambda r, e: self._account_result(
                r, e, "Connected to Govee"))
        a.refresh()

    def _verify(self):
        a = self.app
        if self.account_busy:
            return
        code = self.account["code"].get().strip()
        self.account_busy = True
        self.account_note = ("Checking the code…", theme.MUTED)
        a.background(lambda: a.curtain.verify(code),
                     lambda r, e: self._account_result(r, e, "Connected to Govee"))
        a.refresh()

    def _cancel_code(self):
        self.app.curtain._pending = None
        self.account_note = ("", theme.MUTED)
        self.app.refresh()

    def _sign_out(self):
        self.app.curtain.sign_out()
        self._checked_devices = False
        self.account_note = ("Signed out. The API key is still saved.",
                             theme.MUTED)
        self.app.refresh()

    def _devices_done(self, error):
        if error:
            self.account_note = (str(error), theme.RED)
        self.app.refresh()

    def _urls(self, st, x, y, w) -> float:
        a = self.app
        row_h = 40
        ry = self._card(st, x, y, w, "MixItUp URLs", len(URLS) * row_h)
        ix, iw = x + 20, w - 40
        base = a.base_url()
        col2 = ix + max(measure(base + p, 12, "mono") for p, _ in URLS) + 24
        for i, (path, what) in enumerate(URLS):
            if i:
                st.hline(ix, ry, iw)
            mid = ry + row_h / 2
            st.txt(ix, mid, base + path, 12, "mono")
            room = ix + iw - 42 - col2
            if room > 60:
                st.txt(col2, mid, fit(what, 12, "reg", room), 12,
                       fill=theme.MUTED)
            key = "url:" + path
            copied = a.copied == key
            st.button(ix + iw - 30, mid - 15, 30,
                      lambda k=key, p=path: a.copy_url(k, p),
                      icon="check" if copied else "copy", w=30, r=8,
                      icon_size=15, fg=theme.GREEN if copied else theme.DIM,
                      fill=None, line=None)
            ry += row_h
        return ry + 10 + 18

    # ── actions ─────────────────────────────────────────────

    def _flip(self, key):
        self.flags[key] = not self.flags[key]
        self.note = ("Unsaved changes", theme.AMBER)
        self.app.refresh()

    def _apply_default(self):
        self.app.apply_default()
        self.note = (f"Default color {self.app.default_hex()} applied", theme.GREEN)
        self.app.refresh()

    def _use_current(self):
        if self.app.use_current_as_default():
            self.note = (f"Default color set to {self.app.default_hex()}",
                         theme.GREEN)
        else:
            self.note = ("Set the room to a single color first", theme.AMBER)
        self.app.refresh()

    def revert(self):
        self.load()
        self.app.refresh()

    def save(self):
        a = self.app
        try:
            port = int(self.vars["port"].get())
            dur = float(self.vars["effect_duration"].get())
            cooldown = float(self.vars["command_cooldown"].get())
            if not 1 <= port <= 65535:
                raise ValueError("Port must be between 1 and 65535")
            if dur <= 0:
                raise ValueError("Duration must be positive")
            if cooldown < 0:
                raise ValueError("Cooldown cannot be negative")
            gif_cooldown = float(self.vars["gif_cooldown"].get())
            gif_return = float(self.vars["gif_web_seconds"].get())
            if gif_cooldown < 0 or gif_return < 0:
                raise ValueError("The GIF seconds cannot be negative")
        except ValueError as e:
            messagebox.showerror("Invalid value", str(e), parent=a)
            return
        port_changed = (port != a.cfg.get("port")
                        or self.flags["lan_access"] != a.running_lan)
        flags = dict(self.flags)
        a.cfg["after_effect"] = ("previous" if flags.pop("return_previous")
                                 else "default")
        a.cfg.update(flags)
        a.cfg["port"] = port
        a.cfg["effect_duration"] = dur
        a.cfg["command_cooldown"] = cooldown
        a.cfg["gif_cooldown"] = gif_cooldown
        a.cfg["gif_web_seconds"] = gif_return
        if not flags["gif_remember"] and a.curtain.acct.pop("password", None):
            a.curtain._save_account()            # forget the kept password
        a.save()
        a.attributes("-topmost", self.flags["always_on_top"])
        self.load()
        self.note = ("Saved. Restart the app to apply the server change."
                     if port_changed else "Settings saved", theme.GREEN)
        a.refresh()
