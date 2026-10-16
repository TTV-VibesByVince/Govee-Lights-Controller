"""Alerts page: named presets (effect + colour + duration + speed) that
MixItUp triggers with /alert/<name>. Every change is saved straight away."""

import tkinter as tk

import engine as core
from engine import COLORS, EFFECTS

from . import draw, theme
from .dashboard import nice_name
from .theme import fit, measure

LABEL_W = 78          # width of the "Effect / Color / Speed" label column
CHIP_H = 30
SPEEDS = ((None, "Default"), ("slow", "Slow"), ("normal", "Normal"),
          ("fast", "Fast"), ("max", "Max"))
# "alternate" is offered as "Two colors"; police is its red/blue shortcut
EFFECT_ORDER = ("flash", "strobe", "pulse", "rainbow", "rainbow-strobe",
                "chase", "alternate", "police", "flicker", "breathe", "fade",
                "lightning", "sparkle", "countdown")


def effect_label(fx: str) -> str:
    return "Two colors" if fx == "alternate" else EFFECTS[fx][0]


def flow(labels, max_w, size=13):
    """Wrap chips into rows. Returns ([(x, row, width)], number of rows)."""
    out, x, row = [], 0.0, 0
    for label in labels:
        cw = measure(label, size, "semi") + 24
        if x and x + cw > max_w:
            x, row = 0.0, row + 1
        out.append((x, row, cw))
        x += cw + 8
    return out, row + 1


class AlertsPage:
    def __init__(self, app):
        self.app = app
        self.vars: dict = {}       # id(alert) -> StringVar for its seconds box

    def render(self, st, width) -> float:
        a = self.app
        x = 32
        w = max(600, min(width - 64, 980))
        y = 28

        st.txt(x, y + 18, "Alerts", 28, "bold")
        st.txt(x, y + 51,
               "Presets MixItUp plays with one URL · tune them here, not in "
               "MixItUp", 14, fill=theme.MUTED)
        st.button(x + w, y + 8, 44, a.new_alert, "New alert", "plus",
                  fg="#FFFFFF", fill=theme.ACCENT, hover="#8B4DF5", line=None,
                  align_right=True)
        y += 62 + 22

        alerts = a.cfg.get("alerts", [])
        if not alerts:
            st.img(x, y, draw.rrect, w, 144, 18, theme.CARD, theme.LINE)
            st.txt(x + 24, y + 36, "No alerts yet", 17, "bold")
            for i, line in enumerate((
                    "Click New alert and name it after the event, e.g. sub, "
                    "raid or follow.",
                    "Pick its effect, color, length and speed, then point "
                    "MixItUp at  /alert/<name>",
                    "Alerts that arrive together play one after another "
                    "(change this in Settings).")):
                st.txt(x + 24, y + 70 + i * 24, fit(line, 13, "reg", w - 48), 13,
                       fill=theme.MUTED)
            return y + 144 + 40

        for alert in alerts:
            y = self._card(st, x, y, w, alert) + 16
        return y + 24

    # ══════════════════════════════════════════════════════════

    def _card(self, st, x, y, w, alert) -> float:
        a = self.app
        ix, iw = x + 20, w - 40
        fx = alert.get("effect") if alert.get("effect") in EFFECTS else "strobe"
        takes = EFFECTS[fx][1]
        chips_x = ix + LABEL_W
        chip_pos, chip_rows = flow([effect_label(e) for e in EFFECT_ORDER],
                                   iw - LABEL_W)
        fx_h = chip_rows * CHIP_H + (chip_rows - 1) * 8
        h = 20 + 36 + 16 + fx_h + 14 + 36 + 14 + CHIP_H + 20
        st.img(x, y, draw.rrect, w, h, 18, theme.CARD, theme.LINE)

        # Row 1: name, URL, test / copy / delete
        path = "/alert/" + core.slug(alert["name"])
        key = "alert:" + path
        copied = a.copied == key
        cy = y + 20
        bx = ix + iw
        bx -= st.button(bx, cy, 36, lambda: a.delete_alert(alert), icon="x",
                        w=36, r=10, icon_size=15, fg=theme.DIM, fill=None,
                        line=None, align_right=True) + 4
        bx -= st.button(bx, cy, 36, lambda: a.copy_url(key, path),
                        icon="check" if copied else "copy", w=36, r=10,
                        icon_size=15, fg=theme.GREEN if copied else theme.DIM,
                        fill=None, line=None, align_right=True) + 8
        bx -= st.button(bx, cy, 36, lambda: a.test_alert(alert), "Test", "play",
                        pad=14, r=10, size=13, icon_size=13,
                        align_right=True) + 14
        name = fit(alert["name"], 17, "bold", (bx - ix) * 0.5)
        st.txt(ix, cy + 18, name, 17, "bold")
        nx = ix + measure(name, 17, "bold") + 14
        st.txt(nx, cy + 19, fit(path, 12, "mono", bx - nx), 12, "mono",
               theme.MONO_DIM)
        cy += 36 + 16

        # Row 2: effect
        st.txt(ix, cy + CHIP_H / 2, "Effect", 13, fill=theme.MUTED)
        for e, (px, row, cw) in zip(EFFECT_ORDER, chip_pos):
            self._chip(st, chips_x + px, cy + row * (CHIP_H + 8), cw,
                       effect_label(e), e == fx,
                       lambda e=e: self._set(alert, "effect", e))
        cy += fx_h + 14

        # Row 3: colour(s) and length
        cx = chips_x
        if takes >= 1:
            st.txt(ix, cy + 18, "Color", 13, fill=theme.MUTED)
            cx += self._color_pill(st, cx, cy + 1, alert, "color", "red") + 10
            if takes >= 2:
                cx += self._color_pill(st, cx, cy + 1, alert, "color2",
                                       "blue") + 10
            cx += 14
            st.txt(cx, cy + 18, "Seconds", 13, fill=theme.MUTED)
            cx += measure("Seconds", 13) + 10
        else:
            st.txt(ix, cy + 18, "Seconds", 13, fill=theme.MUTED)
        self._seconds(st, cx, cy, alert)
        default = "2" if fx == "fade" else f"{a.cfg.get('effect_duration', 8):g}"
        hint = f"blank = {default}s"
        if cx + 96 + 12 + measure(hint, 12) < ix + iw:
            st.txt(cx + 96 + 12, cy + 18, hint, 12, fill=theme.FAINT)
        cy += 36 + 14

        # Row 4: speed
        st.txt(ix, cy + CHIP_H / 2, "Speed", 13, fill=theme.MUTED)
        sx = chips_x
        for value, label in SPEEDS:
            cw = measure(label, 13, "semi") + 24
            self._chip(st, sx, cy, cw, label, alert.get("speed") == value,
                       lambda v=value: self._set(alert, "speed", v))
            sx += cw + 8
        return y + h

    def _chip(self, st, x, y, w, label, on, command):
        st.button(x, y, CHIP_H, command, label, w=w, r=CHIP_H / 2, size=13,
                  fg="#FFFFFF" if on else theme.DIM,
                  fill=theme.ACCENT if on else theme.PILL,
                  hover=theme.ACCENT if on else theme.GHOST_HOVER, line=None)

    def _color_pill(self, st, x, y, alert, key, fallback) -> float:
        a = self.app
        name = alert.get(key) if alert.get(key) in COLORS else fallback
        label = nice_name(name)
        w = 10 + 14 + 8 + measure(label, 13, "semi") + 14
        st.img(x, y, draw.rrect, w, 34, 17, theme.PILL)
        hov = st.img(x, y, draw.rrect, w, 34, 17, theme.GHOST_HOVER,
                     state="hidden")
        st.img(x + 10, y + 10, draw.circle, 14, draw.hexc(*COLORS[name]))
        st.txt(x + 32, y + 17, label, 13, "semi")
        st.zone(x, y, w, 34,
                click=lambda: a.pick_color(
                    f"Color for the {alert['name']} alert",
                    "Second color" if key == "color2" else
                    "The color this alert's effect uses",
                    name, lambda n: self._set(alert, key, n, redraw=False),
                    "alerts"),
                enter=lambda: st.itemconfigure(hov, state="normal"),
                leave=lambda: st.itemconfigure(hov, state="hidden"))
        return w

    def _seconds(self, st, x, y, alert):
        var = self.vars.get(id(alert))
        if var is None:
            secs = alert.get("seconds")
            var = self.vars[id(alert)] = tk.StringVar(
                master=self.app, value=f"{secs:g}" if secs else "")
        st.img(x, y, draw.rrect, 96, 36, 10, theme.BG, theme.GHOST_LINE)
        e = tk.Entry(st, textvariable=var, justify="center", relief="flat", bd=0,
                     bg=theme.BG, fg=theme.TEXT, insertbackground=theme.TEXT,
                     selectbackground=theme.ACCENT, selectforeground="#FFFFFF",
                     highlightthickness=0, font=theme.font(13, "mono"))
        e.bind("<Return>", lambda _e: (self._commit(alert), st.focus_set()))
        e.bind("<FocusOut>", lambda _e: self._commit(alert))
        st.widget(x + 10, y + 7, 76, 22, e)

    # ── changes ─────────────────────────────────────────────

    def _commit(self, alert):
        """Store what was typed in the seconds box (blank or bad = default)."""
        var = self.vars.get(id(alert))
        if var is None or alert not in self.app.cfg.get("alerts", []):
            return
        try:
            secs = max(0.5, min(600.0, float(var.get())))
        except ValueError:
            secs = None
        shown = f"{secs:g}" if secs else ""
        if var.get() != shown:
            var.set(shown)
        if alert.get("seconds") != secs:
            alert["seconds"] = secs
            self.app.save()

    def _set(self, alert, key, value, redraw=True):
        self._commit(alert)
        alert[key] = value
        self.app.save()
        if redraw:
            self.app.refresh()
