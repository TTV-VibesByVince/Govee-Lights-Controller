"""Canvas helpers.

Stage   - a canvas you draw on in layout (mockup) pixels, with hover/click
          zones instead of per-item bindings.
Scroller - a slim rounded scrollbar drawn with Pillow.
"""

import tkinter as tk

from PIL import ImageTk

from . import draw, theme


class Zone:
    __slots__ = ("x0", "y0", "x1", "y1", "click", "enter", "leave", "press")

    def __init__(self, x, y, w, h, click, enter, leave, press):
        self.x0, self.y0, self.x1, self.y1 = x, y, x + w, y + h
        self.click, self.enter, self.leave, self.press = click, enter, leave, press

    def hit(self, x, y):
        return self.x0 <= x < self.x1 and self.y0 <= y < self.y1


class Stage(tk.Canvas):
    def __init__(self, master, bg=theme.BG):
        super().__init__(master, bg=bg, highlightthickness=0, bd=0)
        self._zones: list[Zone] = []
        self._active: list[Zone] = []
        self._refs: dict = {}          # canvas item -> its image (keeps it alive)
        self._widgets: list = []       # embedded tk widgets
        self._drag = None              # (move_fn, release_fn) while dragging
        self.bind("<Motion>", lambda e: self._hover(*self._at(e)))
        self.bind("<Leave>", lambda e: self._hover(-1e9, -1e9))
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)

    # ── frame lifecycle ─────────────────────────────────────

    def begin(self):
        """Wipe the canvas before drawing a fresh frame."""
        self.delete("all")
        self._refs.clear()
        for w in self._widgets:
            w.destroy()
        self._widgets.clear()
        self._zones = []
        self._active = []
        self._drag = None

    def end(self):
        """Call after drawing: re-applies hover for wherever the mouse is."""
        self.refresh_hover()

    def refresh_hover(self):
        px, py = self.winfo_pointerx(), self.winfo_pointery()
        if self.winfo_containing(px, py) is self:
            x = self.canvasx(px - self.winfo_rootx()) / theme.SCALE
            y = self.canvasy(py - self.winfo_rooty()) / theme.SCALE
            self._hover(x, y)
        else:
            self._hover(-1e9, -1e9)

    def size(self):
        """Visible size in layout pixels."""
        return (self.winfo_width() / theme.SCALE,
                self.winfo_height() / theme.SCALE)

    # ── drawing ─────────────────────────────────────────────

    def img(self, x, y, fn, *args, anchor="nw", **kw):
        """Draw draw.<fn>(*args) (cached) at layout position x, y."""
        p = draw.photo(fn, *args)
        item = self.create_image(x * theme.SCALE, y * theme.SCALE,
                                 image=p, anchor=anchor, **kw)
        self._refs[item] = p
        return item

    def set_img(self, item, fn, *args):
        p = draw.photo(fn, *args)
        self.itemconfigure(item, image=p)
        self._refs[item] = p

    def raw(self, x, y, pil_image, anchor="nw", slot=None):
        """Draw a one-off (uncached) image. Pass the item as `slot` to replace
        that item's picture instead of making a new item."""
        p = ImageTk.PhotoImage(pil_image)
        if slot is None:
            slot = self.create_image(x * theme.SCALE, y * theme.SCALE,
                                     image=p, anchor=anchor)
        else:
            self.itemconfigure(slot, image=p)
        self._refs[slot] = p
        return slot

    def txt(self, x, y, text, size, weight="reg", fill=theme.TEXT,
            anchor="w", **kw):
        return self.create_text(x * theme.SCALE, y * theme.SCALE, text=text,
                                font=theme.font(size, weight), fill=fill,
                                anchor=anchor, **kw)

    def hline(self, x, y, w, color=theme.LINE):
        s = theme.SCALE
        return self.create_rectangle(x * s, y * s, (x + w) * s,
                                     y * s + max(1, round(s)),
                                     fill=color, outline="")

    def widget(self, x, y, w, h, widget):
        self._widgets.append(widget)
        return self.create_window(x * theme.SCALE, y * theme.SCALE, anchor="nw",
                                  window=widget, width=w * theme.SCALE,
                                  height=h * theme.SCALE)

    # ── interaction ─────────────────────────────────────────

    def zone(self, x, y, w, h, click=None, enter=None, leave=None, press=None):
        """A rectangle that reacts to the mouse.

        click()        - called on mouse-down
        enter()/leave()- hover callbacks
        press(x, y)    - mouse-down with coordinates (for sliders); may call
                         stage.drag(...) to follow the mouse.
        Later zones sit on top of earlier ones for clicks; hover applies to
        every zone under the pointer, so a card and a button inside it can
        both be hovered.
        """
        self._zones.append(Zone(x, y, w, h, click, enter, leave, press))

    def drag(self, move, release=None):
        self._drag = (move, release)

    def _at(self, e):
        return (self.canvasx(e.x) / theme.SCALE, self.canvasy(e.y) / theme.SCALE)

    def _hover(self, x, y):
        now = [z for z in self._zones if z.hit(x, y)]
        old = self._active
        self._active = now
        for z in old:
            if z not in now and z.leave:
                z.leave()
        for z in now:
            if z not in old and z.enter:
                z.enter()
        clickable = any(z.click or z.press for z in now)
        self.configure(cursor="hand2" if clickable else "")

    def _on_press(self, e):
        self.focus_set()
        x, y = self._at(e)
        self._hover(x, y)
        for z in reversed(self._active):
            if z.press:
                z.press(x, y)
                return
            if z.click:
                z.click()
                return

    def _on_drag(self, e):
        if self._drag:
            self._drag[0](*self._at(e))

    def _on_release(self, e):
        if self._drag:
            drag, self._drag = self._drag, None
            if drag[1]:
                drag[1](*self._at(e))

    # ── ready-made pieces ───────────────────────────────────

    def button(self, x, y, h, command, text=None, icon=None, *, w=None,
               pad=18, r=12, size=14, weight="semi", fg=theme.TEXT,
               fill=theme.GHOST, hover=theme.GHOST_HOVER, line=theme.GHOST_LINE,
               icon_size=16, gap=8, align_right=False):
        """Rounded button. Returns its width. fill=None makes a flat button
        that only shows a background on hover."""
        tw = theme.measure(text, size, weight) if text else 0
        content = tw + (icon_size if icon else 0) + (gap if icon and text else 0)
        if w is None:
            w = content + 2 * pad
        if align_right:
            x -= w
        bg = None
        if fill:
            bg = self.img(x, y, draw.rrect, w, h, r, fill, line)
        hov = self.img(x, y, draw.rrect, w, h, r, hover, line, state="hidden")
        cx = x + (w - content) / 2
        if icon:
            self.img(cx, y + (h - icon_size) / 2, draw.icon, icon, icon_size, fg)
            cx += icon_size + gap
        if text:
            self.txt(cx, y + h / 2, text, size, weight, fg)
        self.zone(x, y, w, h, click=command,
                  enter=lambda: self.itemconfigure(hov, state="normal"),
                  leave=lambda: self.itemconfigure(hov, state="hidden"))
        return w

    def switch(self, x, y, on, command, alpha=1.0):
        """44x26 toggle switch."""
        self.img(x, y, draw.toggle, bool(on), alpha)
        self.zone(x, y, 44, 26, click=command)

    def slider(self, x, y, w, value, lo, hi, on_change=None, on_release=None):
        """Horizontal slider centred on y. Callbacks get the integer value."""
        knob_d, h = 16, 6
        state = {"v": value}

        def frac(v):
            return (v - lo) / (hi - lo)

        track = self.raw(x, y - h / 2, draw.bar(w, h, frac(value), theme.ACCENT))
        knob = self.img(x + frac(value) * w, y, draw.circle, knob_d, "#FFFFFF",
                        anchor="center")

        def move(mx, _my):
            v = round(lo + max(0.0, min(1.0, (mx - x) / w)) * (hi - lo))
            if v != state["v"]:
                state["v"] = v
                self.raw(0, 0, draw.bar(w, h, frac(v), theme.ACCENT), slot=track)
                self.coords(knob, (x + frac(v) * w) * theme.SCALE, y * theme.SCALE)
                if on_change:
                    on_change(v)

        def release(mx, my):
            move(mx, my)
            if on_release:
                on_release(state["v"])

        def press(mx, my):
            move(mx, my)
            self.drag(move, release)

        self.zone(x - knob_d / 2, y - 12, w + knob_d, 24, press=press)


class Scroller(tk.Canvas):
    """Slim scrollbar for a Stage. Shows a rounded thumb only when needed."""

    WIDTH = 12

    def __init__(self, master, target: tk.Canvas, bg=theme.BG):
        super().__init__(master, bg=bg, highlightthickness=0, bd=0,
                         width=draw.dev(self.WIDTH))
        self.target = target
        self._range = (0.0, 1.0)
        self._thumb = None
        self._grab = None
        target.configure(yscrollcommand=self.set)
        self.bind("<Configure>", lambda e: self._redraw())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._move)
        self.bind("<ButtonRelease-1>", lambda e: setattr(self, "_grab", None))

    def set(self, lo, hi):
        self._range = (float(lo), float(hi))
        self._redraw()

    def needed(self):
        lo, hi = self._range
        return hi - lo < 0.999

    def _redraw(self):
        self.delete("all")
        if not self.needed():
            return
        lo, hi = self._range
        height = self.winfo_height() / theme.SCALE
        th = max(32, (hi - lo) * height)
        ty = lo * height
        if ty + th > height:
            ty = height - th
        color = theme.GHOST_LINE if self._grab is None else theme.CARD_HOVER
        self._thumb = ImageTk.PhotoImage(draw.rrect(6, th, 3, color))
        self.create_image(3 * theme.SCALE, ty * theme.SCALE, image=self._thumb,
                          anchor="nw")

    def _press(self, e):
        if not self.needed():
            return
        lo, hi = self._range
        f = e.y / max(1, self.winfo_height())
        if not lo <= f <= hi:                       # click on the groove: jump
            self.target.yview_moveto(max(0.0, f - (hi - lo) / 2))
            lo, hi = self._range
        self._grab = f - lo
        self._redraw()

    def _move(self, e):
        if self._grab is None:
            return
        f = e.y / max(1, self.winfo_height())
        self.target.yview_moveto(max(0.0, f - self._grab))
