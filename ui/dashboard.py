"""Dashboard page: header, now-playing bar, light cards, colours, activity
and effect tiles. Laid out in mockup pixels; reflows with the window width."""

import math
import time

import engine as core
from engine import COLORS

from . import draw, theme
from .theme import fit, measure

# (colour name sent to the lights, swatch colour shown) - from the mockup
SWATCHES = (
    ("red", "#EF4444"), ("orange", "#F97316"), ("gold", "#FBBF24"),
    ("gaming", "#22C55E"), ("cyan", "#06B6D4"), ("blue", "#3B82F6"),
    ("purple", "#8B5CF6"), ("hotpink", "#EC4899"),
)
EFFECTS = (
    ("flash", "Flash"), ("strobe", "Strobe"), ("pulse", "Pulse"),
    ("rainbow", "Rainbow"), ("rainbow-strobe", "Rainbow Strobe"),
    ("chase", "Chase"), ("police", "Police"), ("flicker", "Fire Flicker"),
    ("breathe", "Breathe"), ("fade", "Fade"), ("lightning", "Lightning"),
    ("sparkle", "Sparkle"), ("countdown", "Countdown"),
)
# Speed presets -> seconds between strobe flashes
SPEEDS = (("Slow", 0.30), ("Normal", 0.15), ("Fast", 0.09), ("Max", 0.05))
CARD_H = 102
TILE_H = 142


def nice_name(name: str) -> str:
    return {"hotpink": "Hot pink", "royalblue": "Royal blue",
            "xmas": "Xmas"}.get(name, name.capitalize())


class DashboardPage:
    def __init__(self, app):
        self.app = app
        self.anchors: dict = {}
        self._rev = -1
        self._dots: list = []      # [item, light, diameter, last_state]
        self._np = None            # now-playing items to update while ticking

    # ══════════════════════════════════════════════════════════

    def render(self, st, width) -> float:
        a = self.app
        self._rev = a.engine.rev
        self._dots = []
        self._np = None
        x = 32
        w = max(600, min(width - 64, 1180))
        y = 28

        y = self._header(st, x, y, w) + 22
        y = self._now_playing(st, x, y, w) + 22

        side_by_side = w >= 480 + 22 + 320
        self.anchors["lights"] = y
        if side_by_side:
            left_w = w - 320 - 22
            y_left = self._lights(st, x, y, left_w)
            rx = x + left_w + 22
            y_right = self._colors(st, rx, y, 320) + 22
            y_right = self._activity(st, rx, y_right, 320)
            y = max(y_left, y_right) + 22
        else:
            y = self._lights(st, x, y, w) + 22
            y = self._colors(st, x, y, w) + 22
            y = self._activity(st, x, y, w) + 22

        self.anchors["effects"] = y
        y = self._effects(st, x, y, w)
        return y + 40

    # ── header ──────────────────────────────────────────────

    def _header(self, st, x, y, w):
        a = self.app
        lights = a.cfg.get("lights", [])
        online = len([l for l in lights if not l.get("_offline")])
        room = len(a.engine.lights)
        st.txt(x, y + 18, "Dashboard", 28, "bold")
        st.txt(x, y + 51,
               f"{online} of {len(lights)} lights online · {room} in room commands",
               14, fill=theme.MUTED)
        bx = x + w
        bx -= st.button(bx, y + 8, 44, a.all_off, "All off", "power",
                        align_right=True) + 10
        bx -= st.button(bx, y + 8, 44, a.all_on, "All on", "sun",
                        align_right=True) + 10
        st.button(bx, y + 8, 44, a.scan,
                  "Scanning…" if a.scanning else "Scan network", "refresh",
                  align_right=True)
        return y + 62

    # ── now playing ─────────────────────────────────────────

    def _np_info(self) -> dict:
        a = self.app
        now = a.engine.now
        kind = now.get("kind")
        if kind == "effect":
            forever = now["forever"]
            total = max(0.001, now["end"] - now["start"])
            left = max(0.0, now["end"] - time.time())
            sub = f"{a.base_url()}/{now['label']}"
            fx = now["effect"]
            queued = a.engine.queue_length()
            if queued:
                sub += f"  ·  {queued} more queued"
            elif fx == "fade":
                pass                                  # a fade stays where it ends
            elif not forever and a.cfg.get("restore_after_effect", True):
                if a.cfg.get("after_effect") == "previous":
                    sub += "  ·  then returns to the previous look"
                else:
                    sub += f"  ·  then restores {a.default_hex()}"
            return {
                "label": "NOW PLAYING", "label_fg": theme.ACCENT_TEXT,
                "title": now["title"] + (" · forever" if forever
                                         else f" · {math.ceil(left)}s left"),
                "sub": sub, "active": True,
                "frac": 1.0 if forever else 1.0 - left / total,
                "bar": "rainbow-bar" if fx.startswith("rainbow")
                       else draw.FX_CHIP.get(fx, theme.ACCENT),
            }
        info = {"label": "STATIC COLOR", "label_fg": theme.MUTED,
                "sub": "No effect running", "active": False,
                "frac": 0.0, "bar": "#3A3A4E"}
        if kind == "off":
            info.update(label="LIGHTS OFF", title="All lights off", sub="/off")
        elif kind == "color":
            label = now.get("label")
            if label == "default":
                info["title"] = f"Default color {a.default_hex()}"
            elif label in COLORS:
                info["title"] = f"Solid {nice_name(label)}"
            else:
                info["title"] = f"Solid {draw.hexc(*now['rgb'])}"
        elif kind == "scene":
            info.update(label="SCENE", label_fg=theme.ACCENT_TEXT,
                        title=now.get("name", "Scene"),
                        sub=f"/scene/{core.slug(now.get('name', ''))}")
        elif kind == "custom":
            info["title"] = "Per-light colors"
        elif kind == "on":
            info["title"] = "Lights on"
        else:
            info["title"] = "Ready"
        return info

    def _now_playing(self, st, x, y, w):
        a = self.app
        h = 130
        info = self._np_info()
        if info["active"]:
            st.img(x - draw.NOW_PAD, y - draw.NOW_PAD, draw.glow_rrect, w, h, 18,
                   theme.CARD, theme.NOW_LINE, theme.ACCENT, 40, 0.18,
                   draw.NOW_PAD)
        else:
            st.img(x, y, draw.rrect, w, h, 18, theme.CARD, theme.LINE)

        stop_w = 44 + 16 + 8 + measure("Stop", 15, "bold")
        sx = x + w - 22 - stop_w
        st.button(sx, y + (h - 48) / 2, 48, a.stop, "Stop", "stop", w=stop_w,
                  r=14, size=15, weight="bold", fg=theme.BG, fill=theme.TEXT,
                  hover="#FFFFFF", line=None)

        tx = x + 22
        lights = a.visible_lights()
        room = sx - 24 - tx - 240 - 24          # space left for light dots
        count = max(0, min(len(lights), int((room + 18) // 70)))
        gx = sx - 24 - (count * 70 - 18) if count else sx
        for i, light in enumerate(lights[:count]):
            cx = gx + i * 70 + 26
            cy = y + h / 2 - 11
            self._dot(st, cx, cy, 26, light)
            st.txt(cx, cy + 28, fit(light.get("name", light["sku"]), 11, "reg", 64),
                   11, fill=theme.MUTED, anchor="center")

        tw = gx - 24 - tx
        st.txt(tx, y + 27, info["label"], 11, "bold", info["label_fg"])
        title = st.txt(tx, y + 52, fit(info["title"], 22, "bold", tw), 22, "bold")
        st.txt(tx, y + 80, fit(info["sub"], 12, "mono", tw), 12, "mono",
               theme.MUTED)
        bar = st.raw(tx, y + 100, draw.bar(tw, 4, info["frac"], info["bar"]))
        if info["active"]:
            self._np = (title, bar, tw)
        return y + h

    # ── lights ──────────────────────────────────────────────

    def _dot_state(self, light) -> tuple:
        """(colour, lit) for a light's dot, from what was last sent to it."""
        a = self.app
        ip = light["ip"]
        if core.in_gif_mode(a.cfg, light) and not light.get("_offline"):
            # A curtain in GIF mode: lit while a GIF is on it
            kind = a.curtain.state.get("kind")
            if kind == "playing":
                return (theme.ACCENT_SOFT, True)
            return (theme.AMBER, True) if kind == "working" else (theme.UNLIT, False)
        if (a.is_excluded(light) or not light.get("enabled", True)
                or light.get("_offline") or a.engine.power.get(ip) is False):
            return (theme.UNLIT, False)
        c = a.engine.light_colors.get(ip)
        if c is None:
            return ("#4A4A60", False)
        if max(c) < 24:
            return (theme.UNLIT, False)
        return (draw.hexc(*(min(255, round(v / 17) * 17) for v in c)), True)

    def _dot(self, st, cx, cy, d, light):
        state = self._dot_state(light)
        item = st.img(cx, cy, draw.dot, d, *state, anchor="center")
        self._dots.append([item, light, d, state])

    def _lights(self, st, x, y, w):
        a = self.app
        st.txt(x, y + 16, "Lights", 17, "bold")
        bx = x + w
        for text, cmd in (("Clear offline", a.clear_offline),
                          ("None", lambda: a.select_all(False)),
                          ("All", lambda: a.select_all(True))):
            bx -= st.button(bx, y, 32, cmd, text, pad=12, r=8, size=13,
                            fg=theme.DIM, fill=None, line=None,
                            align_right=True) + 2
        y += 32 + 14

        lights = a.visible_lights()
        if not lights:
            st.img(x, y, draw.rrect, w, CARD_H, 16, theme.CARD, theme.LINE)
            st.txt(x + w / 2, y + CARD_H / 2,
                   "Scanning for lights…" if a.scanning
                   else "No lights yet. Click Scan network to find them.",
                   14, fill=theme.MUTED, anchor="center")
            return y + CARD_H

        cols = max(1, int((w + 12) // (264 + 12)))
        cw = (w - 12 * (cols - 1)) / cols
        for i, light in enumerate(lights):
            self._light_card(st, x + (i % cols) * (cw + 12),
                             y + (i // cols) * (CARD_H + 12), cw, light, i)
        rows = math.ceil(len(lights) / cols)
        return y + rows * CARD_H + (rows - 1) * 12

    def _light_card(self, st, x, y, w, light, index):
        a = self.app
        excluded = a.is_excluded(light)            # no room commands reach it
        gif_mode = core.in_gif_mode(a.cfg, light)  # a curtain, switched off
        blocked = excluded and not gif_mode        # excluded address / model
        enabled = light.get("enabled", True)
        offline = bool(light.get("_offline"))
        alpha = 0.62 if blocked else (1.0 if enabled or gif_mode else 0.55)
        if offline:
            alpha = min(alpha, 0.55)

        def fade(c):
            return draw.mix(c, theme.CARD, alpha)

        st.img(x, y, draw.rrect, w, CARD_H, 16, theme.CARD, theme.LINE)
        hov = st.img(x, y, draw.rrect, w, CARD_H, 16, theme.CARD,
                     theme.CARD_HOVER, state="hidden")

        # Row 2 text + hover actions (declared first so the card zone, added
        # before the buttons, can show/hide them)
        meta = f"{light['sku']} · {light['ip']}" + (" · offline" if offline else "")
        meta_fg = fade(theme.RED if offline else theme.MONO_DIM)
        n_actions = 3 if excluded else 4          # no colour button if excluded
        actions_w = n_actions * 30 + (n_actions - 1) * 4
        short = fit(meta, 11, "mono", w - 32 - actions_w - 8)
        full = fit(meta, 11, "mono", w - 32)
        meta_item = st.txt(x + 16, y + 71, full, 11, "mono", meta_fg)
        tag = f"actions{index}"

        def enter():
            st.itemconfigure(hov, state="normal")
            st.itemconfigure(tag, state="normal")
            st.itemconfigure(meta_item, text=short)

        def leave():
            st.itemconfigure(hov, state="hidden")
            st.itemconfigure(tag, state="hidden")
            st.itemconfigure(meta_item, text=full)

        st.zone(x, y, w, CARD_H, enter=enter, leave=leave)

        # Row 1: dot, name, switch / badge
        self._dot(st, x + 23, y + 29, 14, light)
        name = light.get("name", light["sku"])
        def badge(text, right_edge):
            bw = measure(text, 11, "semi") + 18
            st.img(right_edge - bw, y + 17, draw.rrect, bw, 24, 12,
                   fade(theme.AMBER_BG))
            st.txt(right_edge - bw / 2, y + 29, text, 11, "semi",
                   fade(theme.AMBER), anchor="center")
            return bw

        if blocked:
            right = badge("Excluded", x + w - 16)
        else:
            # For a curtain the switch means "follows room commands";
            # off = GIF mode (only GIF commands change it).
            st.switch(x + w - 16 - 44, y + 16, enabled,
                      lambda: a.toggle_light(light),
                      alpha=0.55 if offline else 1.0)
            right = 44
            if gif_mode:
                right += 8 + badge("GIF mode", x + w - 16 - 44 - 8)
            elif core.is_curtain(a.cfg, light):
                right += 8 + badge("Room", x + w - 16 - 44 - 8)
        st.txt(x + 42, y + 29, fit(name, 15, "bold", w - 42 - 16 - right - 12),
               15, "bold", fade(theme.TEXT))

        # Hover actions: power, rename, remove
        powered = a.engine.power.get(light["ip"], True)
        ax = x + w - 16 - actions_w
        actions = [("power", theme.GREEN if powered else theme.DIM,
                    lambda: a.light_power(light))]
        if not excluded:
            actions.append(("drop", theme.DIM, lambda: a.pick_light_color(light)))
        actions += [("pencil", theme.DIM, lambda: a.rename_light(light)),
                    ("x", theme.DIM, lambda: a.remove_light(light))]
        for icon, color, cmd in actions:
            bg = st.img(ax, y + 56, draw.rrect, 30, 30, 8, theme.GHOST_HOVER,
                        state="hidden")
            st.img(ax + 7.5, y + 63.5, draw.icon, icon, 15, color,
                   state="hidden", tags=(tag,))
            st.zone(ax, y + 56, 30, 30, click=cmd,
                    enter=lambda bg=bg: st.itemconfigure(bg, state="normal"),
                    leave=lambda bg=bg: st.itemconfigure(bg, state="hidden"))
            ax += 34

    # ── colours ─────────────────────────────────────────────

    def _colors(self, st, x, y, w):
        a = self.app
        h = 284
        st.img(x, y, draw.rrect, w, h, 18, theme.CARD, theme.LINE)
        ix, iw = x + 18, w - 36
        cy = y + 18
        st.txt(ix, cy + 15, "Colors", 17, "bold")
        st.button(ix + iw, cy, 30, lambda: a.go("colors"),
                  f"All {len(COLORS)} →", pad=10, r=8, size=13, fg=theme.LINK,
                  fill=None, line=None, align_right=True)
        cy += 30 + 16

        now = a.engine.now
        current = now.get("label") if now.get("kind") == "color" else None
        cell = (iw - 3 * 14) / 4
        for i, (name, shown) in enumerate(SWATCHES):
            sx = ix + (i % 4) * (cell + 14) + cell / 2
            sy = cy + (i // 4) * (44 + 14) + 22
            selected = name == current
            item = st.img(sx, sy, draw.swatch, 44, shown, selected, 1.0,
                          anchor="center")
            st.zone(sx - 22, sy - 22, 44, 44,
                    click=lambda n=name: a.apply_color(n),
                    enter=lambda it=item, c=shown, s=selected:
                        st.set_img(it, draw.swatch, 44, c, s, 1.08),
                    leave=lambda it=item, c=shown, s=selected:
                        st.set_img(it, draw.swatch, 44, c, s, 1.0))
        cy += 102 + 16

        st.hline(ix, cy, iw)
        cy += 10
        st.txt(ix, cy + 16, "Default restore color", 13, fill=theme.MUTED)
        hexv = a.default_hex()
        pw = 6 + 20 + 8 + measure(hexv, 12, "mono") + 12
        px = ix + iw - pw
        st.img(px, cy, draw.rrect, pw, 32, 16, theme.PILL)
        hov = st.img(px, cy, draw.rrect, pw, 32, 16, theme.GHOST_HOVER,
                     state="hidden")
        st.img(px + 6, cy + 6, draw.circle, 20, hexv)
        st.txt(px + 34, cy + 16, hexv, 12, "mono")
        st.zone(px, cy, pw, 32, click=a.pick_default,
                enter=lambda: st.itemconfigure(hov, state="normal"),
                leave=lambda: st.itemconfigure(hov, state="hidden"))
        cy += 32 + 16

        st.txt(ix, cy + 12, "Brightness", 13, fill=theme.MUTED)
        value = st.txt(ix + iw, cy + 12, f"{a.engine.brightness_value}%", 12,
                       "mono", anchor="e")
        sl_x = ix + measure("Brightness", 13) + 20
        st.slider(sl_x, cy + 12, ix + iw - 48 - sl_x, a.engine.brightness_value,
                  1, 100,
                  on_change=lambda v: st.itemconfigure(value, text=f"{v}%"),
                  on_release=a.set_brightness)
        return y + h

    # ── activity ────────────────────────────────────────────

    def _activity(self, st, x, y, w):
        a = self.app
        rows = 5
        h = 18 + 24 + 12 + rows * 26 + (rows - 1) * 8 + 18
        st.img(x, y, draw.rrect, w, h, 18, theme.CARD, theme.LINE)
        ix, iw = x + 18, w - 36
        st.txt(ix, y + 18 + 12, "Activity", 17, "bold")
        cy = y + 18 + 24 + 12
        if not a.log:
            st.txt(ix, cy + 13, "No commands yet", 13, fill=theme.FAINT)
        for e in a.log[:rows]:
            st.txt(ix, cy + 13, e["t"], 11, "mono", theme.FAINT)
            px = ix + 68
            cmd = fit(e["cmd"], 12, "mono", iw - 68 - 34)
            pw = 10 + 7 + 7 + measure(cmd, 12, "mono") + 10
            st.img(px, cy + 1, draw.rrect, pw, 24, 12, theme.PILL)
            st.img(px + 10, cy + 9.5, draw.circle, 7, e["c"])
            st.txt(px + 24, cy + 13, cmd, 12, "mono")
            room = iw - 68 - pw - 10
            if room > 30:
                st.txt(px + pw + 10, cy + 13, fit(e["src"], 12, "reg", room),
                       12, fill=theme.FAINT)
            cy += 34
        return y + h

    # ── effects ─────────────────────────────────────────────

    def _effects(self, st, x, y, w):
        a = self.app
        ix, iw = x + 20, w - 40

        # Measure the controls to decide whether they share the title row
        speed_ws = [measure(label, 13, "semi") + 28 for label, _ in SPEEDS]
        speed_w = sum(speed_ws) + 8
        forever_w = 44 + 10 + measure("Run forever", 14, "semi")
        cname = nice_name(a.effect_color)
        pill_w = 10 + 14 + 8 + measure(cname, 13, "semi") + 14
        color_w = measure("Color", 13) + 10 + pill_w
        controls_w = color_w + 18 + speed_w + 18 + forever_w
        one_row = iw - measure("Effects", 17, "bold") - 24 >= controls_w
        head_h = 44 if one_row else 28 + 12 + 44

        cols = max(1, int((iw + 12) // (190 + 12)))
        rows = math.ceil(len(EFFECTS) / cols)
        h = 20 + head_h + 14 + rows * TILE_H + (rows - 1) * 12 + 20
        st.img(x, y, draw.rrect, w, h, 18, theme.CARD, theme.LINE)

        st.txt(ix, y + 20 + (22 if one_row else 14), "Effects", 17, "bold")
        cy = y + 20 + (0 if one_row else 40)          # top of the control row
        cx = ix + iw - controls_w if one_row else ix
        mid = cy + 22

        # Effect colour
        st.txt(cx, mid, "Color", 13, fill=theme.MUTED)
        px = cx + measure("Color", 13) + 10
        st.img(px, mid - 17, draw.rrect, pill_w, 34, 17, theme.PILL)
        hov = st.img(px, mid - 17, draw.rrect, pill_w, 34, 17, theme.GHOST_HOVER,
                     state="hidden")
        st.img(px + 10, mid - 7, draw.circle, 14,
               draw.hexc(*COLORS.get(a.effect_color, (255, 255, 255))))
        st.txt(px + 32, mid, cname, 13, "semi")
        st.zone(px, mid - 17, pill_w, 34, click=self._pick_effect_color,
                enter=lambda: st.itemconfigure(hov, state="normal"),
                leave=lambda: st.itemconfigure(hov, state="hidden"))
        cx += color_w + 18

        # Speed
        st.img(cx, mid - 21, draw.rrect, speed_w, 42, 12, theme.BG, theme.LINE)
        current = a.speed_index()
        bx = cx + 4
        for i, (label, _) in enumerate(SPEEDS):
            on = i == current
            st.button(bx, mid - 17, 34, lambda i=i: a.set_speed(i), label,
                      w=speed_ws[i], r=9, size=13,
                      fg="#FFFFFF" if on else theme.DIM,
                      fill=theme.ACCENT if on else None,
                      hover=theme.ACCENT if on else theme.GHOST_HOVER, line=None)
            bx += speed_ws[i]
        cx += speed_w + 18

        # Run forever
        st.switch(cx, mid - 13, a.forever, a.toggle_forever)
        st.txt(cx + 54, mid, "Run forever", 14, "semi")
        st.zone(cx, mid - 22, forever_w, 44, click=a.toggle_forever)

        # Tiles
        ty = y + 20 + head_h + 14
        tw = (iw - 12 * (cols - 1)) / cols
        now = a.engine.now
        playing = now.get("effect") if now.get("kind") == "effect" else None
        for i, (fx, title) in enumerate(EFFECTS):
            self._tile(st, ix + (i % cols) * (tw + 12),
                       ty + (i // cols) * (TILE_H + 12), tw, fx, title,
                       fx == playing)
        return y + h

    def _pick_effect_color(self):
        a = self.app

        def choose(name):
            a.effect_color = name

        a.pick_color("Pick effect color",
                     "Effects that take a color will use the one you pick",
                     a.effect_color, choose, "effects")

    def _tile(self, st, x, y, w, fx, title, active):
        a = self.app
        if active:
            st.img(x - 30, y - 30, draw.glow_rrect, w, TILE_H, 16, theme.TILE,
                   theme.ACCENT, theme.ACCENT, 28, 0.35, 30)
        else:
            st.img(x, y, draw.rrect, w, TILE_H, 16, theme.TILE, theme.TILE_LINE)
            hov = st.img(x, y, draw.rrect, w, TILE_H, 16, theme.TILE,
                         theme.TILE_HOVER, state="hidden")
            st.zone(x, y, w, TILE_H,
                    enter=lambda: st.itemconfigure(hov, state="normal"),
                    leave=lambda: st.itemconfigure(hov, state="hidden"))

        st.img(x + 14, y + 14, draw.fx_preview, fx, w - 28, 64, 11)
        st.zone(x + 14, y + 14, w - 28, 64, click=lambda: a.run_effect(fx))

        path = a.effect_path(fx)
        by = y + 14 + 64 + 12
        st.txt(x + 14, by + 9, title, 15, "bold")
        st.txt(x + 14, by + 29, fit(path, 11, "mono", w - 28 - 34 - 8), 11,
               "mono", theme.MONO_DIM)
        copied = a.copied == fx
        st.button(x + w - 14 - 34, by + 2, 34, lambda: a.copy_url(fx, path),
                  icon="check" if copied else "copy", w=34, r=9, icon_size=15,
                  fg=theme.GREEN if copied else theme.DIM, fill=theme.TILE)

    # ══════════════════════════════════════════════════════════

    def tick(self):
        """Called a few times a second: live dots, countdown and progress."""
        a = self.app
        st = a.main
        if a.engine.rev != self._rev:
            a.render()
            return
        if self._np and a.engine.now.get("kind") == "effect":
            title, bar, tw = self._np
            info = self._np_info()
            st.itemconfigure(title, text=fit(info["title"], 22, "bold", tw))
            st.raw(0, 0, draw.bar(tw, 4, info["frac"], info["bar"]), slot=bar)
        for entry in self._dots:
            item, light, d, last = entry
            state = self._dot_state(light)
            if state != last:
                entry[3] = state
                st.set_img(item, draw.dot, d, *state)
