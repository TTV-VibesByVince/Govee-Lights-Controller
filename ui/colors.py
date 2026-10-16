"""All-colours page. Also used as a colour picker by other pages."""

import math

from engine import COLORS

from . import draw, theme
from .dashboard import nice_name


class ColorsPage:
    def __init__(self, app):
        self.app = app
        # None: clicking a colour sets the room.
        # dict(title, sub, current, choose, back): picker mode - choose(name)
        # is called and the app goes back to page `back`. See app.pick_color.
        self.pick: dict | None = None

    def render(self, st, width) -> float:
        a = self.app
        pick = self.pick
        x = 32
        w = max(600, min(width - 64, 1180))
        y = 28

        st.txt(x, y + 18, pick["title"] if pick else "Colors", 28, "bold")
        st.txt(x, y + 51,
               pick["sub"] if pick else
               f"{len(COLORS)} colors · click one to set the room",
               14, fill=theme.MUTED)
        back = pick["back"] if pick else "dashboard"
        st.button(x + w, y + 8, 44, lambda: a.go(back),
                  "Back" if pick else "Dashboard", "back", align_right=True)
        y += 62 + 22

        cols = max(1, int((w - 36) // 96))
        rows = math.ceil(len(COLORS) / cols)
        cell = (w - 36) / cols
        h = 18 + rows * 96 + 10
        st.img(x, y, draw.rrect, w, h, 18, theme.CARD, theme.LINE)

        now = a.engine.now
        if pick:
            current = pick["current"]
        else:
            current = now.get("label") if now.get("kind") == "color" else None

        for i, (name, rgb) in enumerate(COLORS.items()):
            cx = x + 18 + (i % cols) * cell + cell / 2
            cy = y + 18 + (i // cols) * 96 + 30
            shown = draw.hexc(*rgb)
            selected = name == current
            item = st.img(cx, cy, draw.swatch, 44, shown, selected, 1.0,
                          anchor="center")
            st.txt(cx, cy + 40, nice_name(name), 12,
                   fill=theme.TEXT if selected else theme.MUTED, anchor="center")
            st.zone(cx - 22, cy - 22, 44, 44,
                    click=lambda n=name: self.choose(n),
                    enter=lambda it=item, c=shown, s=selected:
                        st.set_img(it, draw.swatch, 44, c, s, 1.08),
                    leave=lambda it=item, c=shown, s=selected:
                        st.set_img(it, draw.swatch, 44, c, s, 1.0))
        return y + h + 40

    def choose(self, name: str):
        a = self.app
        if self.pick:
            pick, self.pick = self.pick, None
            pick["choose"](name)
            a.go(pick["back"])
        else:
            a.apply_color(name)
            a.refresh()
