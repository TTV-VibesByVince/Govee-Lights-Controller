"""Scenes page: saved looks (a colour per light plus brightness)."""

import math

import engine as core

from . import draw, theme
from .theme import fit, measure

CARD_H = 150


class ScenesPage:
    def __init__(self, app):
        self.app = app

    def render(self, st, width) -> float:
        a = self.app
        x = 32
        w = max(600, min(width - 64, 1180))
        y = 28

        st.txt(x, y + 18, "Scenes", 28, "bold")
        st.txt(x, y + 51, "A scene remembers each light's color and the "
               "brightness", 14, fill=theme.MUTED)
        st.button(x + w, y + 8, 44, a.save_scene, "Save current look", "plus",
                  fg="#FFFFFF", fill=theme.ACCENT, hover="#8B4DF5", line=None,
                  align_right=True)
        y += 62 + 22

        scenes = a.cfg.get("scenes", [])
        if not scenes:
            st.img(x, y, draw.rrect, w, 168, 18, theme.CARD, theme.LINE)
            st.txt(x + 24, y + 36, "No scenes yet", 17, "bold")
            for i, line in enumerate((
                    "1.  Set up the room: pick a color, or hover a light on the "
                    "Dashboard and use its color button to give each light its own.",
                    "2.  Set the brightness you want.",
                    "3.  Click Save current look and give it a name.",
                    "MixItUp can then recall it with  /scene/<name>")):
                st.txt(x + 24, y + 70 + i * 24, fit(line, 13, "reg", w - 48), 13,
                       fill=theme.MUTED)
            return y + 168 + 40

        cols = max(1, int((w + 12) // (300 + 12)))
        cw = (w - 12 * (cols - 1)) / cols
        for i, scene in enumerate(scenes):
            self._card(st, x + (i % cols) * (cw + 12),
                       y + (i // cols) * (CARD_H + 12), cw, scene)
        rows = math.ceil(len(scenes) / cols)
        return y + rows * CARD_H + (rows - 1) * 12 + 40

    def _card(self, st, x, y, w, scene):
        a = self.app
        now = a.engine.now
        active = now.get("kind") == "scene" and now.get("name") == scene["name"]
        st.img(x, y, draw.rrect, w, CARD_H, 16, theme.CARD,
               theme.ACCENT if active else theme.LINE)

        path = "/scene/" + core.slug(scene["name"])
        key = "scene:" + path
        copied = a.copied == key
        st.txt(x + 18, y + 31, fit(scene["name"], 17, "bold", w - 36 - 72), 17,
               "bold")
        st.button(x + w - 14 - 30, y + 16, 30, lambda: a.delete_scene(scene),
                  icon="x", w=30, r=8, icon_size=15, fg=theme.DIM, fill=None,
                  line=None)
        st.button(x + w - 14 - 64, y + 16, 30, lambda: a.copy_url(key, path),
                  icon="check" if copied else "copy", w=30, r=8, icon_size=15,
                  fg=theme.GREEN if copied else theme.DIM, fill=None, line=None)

        # One dot per light in the scene
        names = {l["ip"]: l.get("name", l["sku"]) for l in a.cfg.get("lights", [])}
        dx = x + 18 + 10
        for ip, value in scene.get("lights", {}).items():
            if dx > x + w - 28:
                break
            if value == "off":
                st.img(dx, y + 70, draw.dot, 18, theme.UNLIT, False,
                       anchor="center")
            else:
                st.img(dx, y + 70, draw.dot, 18, draw.hexc(*value), True,
                       anchor="center")
            dx += 30
        count = len(scene.get("lights", {}))
        missing = len([ip for ip in scene.get("lights", {}) if ip not in names])
        info = f"{count} light{'' if count == 1 else 's'}"
        if scene.get("brightness"):
            info += f" · {scene['brightness']}%"
        if missing:
            info += f" · {missing} no longer listed"

        bw = st.button(x + w - 18, y + 100, 34, lambda: a.apply_scene(scene),
                       "Apply", "play", pad=14, r=10, size=13, icon_size=13,
                       align_right=True)
        room = w - 36 - bw - 12
        st.txt(x + 18, y + 108, fit(path, 12, "mono", room), 12, "mono")
        st.txt(x + 18, y + 127, fit(info, 12, "reg", room), 12, fill=theme.MUTED)
