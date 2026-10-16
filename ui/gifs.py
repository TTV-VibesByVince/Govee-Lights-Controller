"""GIFs page: paste a link (or pick a file) to play on the curtain lights,
and keep a library of saved GIFs that MixItUp can play by name."""

import math
import os
import tkinter as tk
from tkinter import filedialog, simpledialog

from PIL import Image

import engine as core
from curtain import CurtainError

from . import draw, theme
from .theme import fit, measure

PREVIEW_W, PREVIEW_H = 120, 128          # 30 x 32 LEDs, four pixels each
CARD_H = 14 + PREVIEW_H + 12 + 22 + 18 + 12 + 34 + 8 + 34 + 14


class GifsPage:
    def __init__(self, app):
        self.app = app
        self.link = tk.StringVar(master=app)
        self.note = ""                 # a problem to show under the box
        self._frames: dict = {}        # path -> (stamp, frame count)
        self._hover = None             # (canvas item, path, stamp, count)
        self._hover_frame = 0
        self._anim_job = None

    # ══════════════════════════════════════════════════════════

    def render(self, st, width) -> float:
        a = self.app
        c = a.curtain
        x = 32
        w = max(600, min(width - 64, 1180))
        y = 28

        st.txt(x, y + 18, "GIFs", 28, "bold")
        st.txt(x, y + 51, fit(self._mode_text(), 14, "reg", w), 14,
               fill=theme.MUTED)
        y += 62 + 22

        if not c.ready():
            st.img(x, y, draw.rrect, w, 92, 18, theme.CARD, theme.NOW_LINE)
            st.txt(x + 24, y + 34, "Connect your Govee account first", 17, "bold")
            st.txt(x + 24, y + 60,
                   fit("GIFs reach the curtain through Govee's cloud, so the app "
                       "needs your Govee API key and sign-in.", 13, "reg",
                       w - 48 - 170), 13, fill=theme.MUTED)
            st.button(x + w - 24, y + 24, 44, lambda: a.go("settings"),
                      "Open Settings", "gear", fg="#FFFFFF", fill=theme.ACCENT,
                      hover="#8B4DF5", line=None, align_right=True)
            y += 92 + 22

        y = self._paste_box(st, x, y, w) + 22
        y = self._library(st, x, y, w)
        return y + 40

    def _mode_text(self) -> str:
        a = self.app
        curtains = [l for l in a.cfg.get("lights", [])
                    if core.is_curtain(a.cfg, l)]
        if not curtains:
            return "Plays GIFs on Govee Curtain Lights through your Govee account"
        name = curtains[0].get("name", curtains[0]["sku"])
        if any(core.in_gif_mode(a.cfg, l) for l in curtains):
            return f"{name} is in GIF mode · room colors and effects leave it alone"
        return (f"{name} follows room commands · the next room color or effect "
                "will replace a GIF")

    # ── paste box ───────────────────────────────────────────

    def _paste_box(self, st, x, y, w) -> float:
        a = self.app
        c = a.curtain
        h = 20 + 24 + 14 + 44 + 14 + 20 + 18
        st.img(x, y, draw.rrect, w, h, 18, theme.CARD, theme.LINE)
        ix, iw = x + 20, w - 40
        st.txt(ix, y + 32, "Play a GIF", 17, "bold")
        st.txt(ix + measure("Play a GIF", 17, "bold") + 14, y + 33,
               fit("Paste a Giphy, Tenor or Imgur link, a .gif link, or pick a "
                   "file", 13, "reg", iw - 120), 13, fill=theme.MUTED)

        by = y + 20 + 24 + 14
        bx = ix + iw
        bx -= st.button(bx, by, 44, self.play, "Play", "play", fg="#FFFFFF",
                        fill=theme.ACCENT, hover="#8B4DF5", line=None,
                        icon_size=14, align_right=True) + 8
        bx -= st.button(bx, by, 44, self.save, "Save", "plus", icon_size=14,
                        align_right=True) + 8
        bx -= st.button(bx, by, 44, self.browse, "Browse", "folder",
                        icon_size=15, align_right=True) + 10
        fw = bx - ix
        st.img(ix, by, draw.rrect, fw, 44, 12, theme.BG, theme.GHOST_LINE)
        entry = tk.Entry(st, textvariable=self.link, relief="flat", bd=0,
                         bg=theme.BG, fg=theme.TEXT, insertbackground=theme.TEXT,
                         selectbackground=theme.ACCENT,
                         selectforeground="#FFFFFF", highlightthickness=0,
                         font=theme.font(13, "mono"))
        entry.bind("<Return>", lambda _e: self.play())
        st.widget(ix + 14, by + 10, fw - 28, 24, entry)

        # Status line
        sy = by + 44 + 14 + 10
        state = c.state
        kind = state.get("kind")
        if self.note:
            dot, text = theme.RED, self.note
        elif kind == "working":
            dot, text = theme.AMBER, state.get("text", "Working…")
        elif kind == "playing":
            dot, text = theme.GREEN, f"Playing {state.get('name', 'a GIF')}"
        elif kind == "error":
            dot, text = theme.RED, state.get("text", "Something went wrong")
        else:
            dot, text = theme.UNLIT, state.get("text") or \
                "Sending takes about 5 seconds"
        waiting = c.queue_length()
        if waiting and not self.note:
            text += f"  ·  {waiting} waiting"
        if kind in ("working", "playing") and not self.note:
            st.img(ix + 5, sy, draw.status_dot, dot, anchor="center")   # glows
        else:
            st.img(ix + 5, sy, draw.circle, 8, dot, anchor="center")
        st.txt(ix + 18, sy, fit(text, 13, "reg", iw - 18), 13,
               fill=theme.TEXT if dot != theme.UNLIT else theme.MUTED)
        return y + h

    # ── library ─────────────────────────────────────────────

    def _library(self, st, x, y, w) -> float:
        a = self.app
        gifs = a.curtain.gifs()
        st.txt(x, y + 16, "Library", 17, "bold")
        st.txt(x + measure("Library", 17, "bold") + 12, y + 17,
               f"{len(gifs)} saved" if gifs else "", 13, fill=theme.MUTED)
        y += 32 + 14
        if not gifs:
            st.img(x, y, draw.rrect, w, 96, 16, theme.CARD, theme.LINE)
            st.txt(x + 24, y + 36, "Nothing saved yet", 15, "bold")
            st.txt(x + 24, y + 62,
                   fit("Paste a link above and click Save to keep it. MixItUp can "
                       "then play it with  /gif/<name>", 13, "reg", w - 48), 13,
                   fill=theme.MUTED)
            return y + 96
        cols = max(1, int((w + 12) // (210 + 12)))
        cw = (w - 12 * (cols - 1)) / cols
        for i, gif in enumerate(gifs):
            self._card(st, x + (i % cols) * (cw + 12),
                       y + (i // cols) * (CARD_H + 12), cw, gif)
        rows = math.ceil(len(gifs) / cols)
        return y + rows * CARD_H + (rows - 1) * 12

    def _info(self, path):
        """(modified time, frame count) of a library file."""
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            return (0, 1)
        cached = self._frames.get(path)
        if not cached or cached[0] != stamp:
            try:
                with Image.open(path) as im:
                    count = getattr(im, "n_frames", 1)
            except Exception:
                count = 1
            cached = self._frames[path] = (stamp, count)
        return cached

    def _card(self, st, x, y, w, gif):
        a = self.app
        c = a.curtain
        is_default = core.slug(gif["name"]) == core.slug(
            a.cfg.get("gif_default") or "")
        playing = (c.state.get("kind") == "playing"
                   and c.state.get("name") == gif["name"])
        # The default GIF gets a yellow border round the whole box
        border = theme.AMBER if is_default else (
            theme.ACCENT if playing else theme.LINE)
        st.img(x, y, draw.rrect, w, CARD_H, 16, theme.CARD, border,
               2.0 if is_default else 1.0)

        path = c.path_of(gif)
        stamp, count = self._info(path)
        px = x + (w - PREVIEW_W) / 2
        item = st.img(px, y + 14, draw.gif_frame, path, stamp, 0,
                      PREVIEW_W, PREVIEW_H, 10)
        st.zone(px, y + 14, PREVIEW_W, PREVIEW_H,
                click=lambda: self.play_saved(gif),
                enter=lambda: self._start_anim(item, path, stamp, count),
                leave=lambda: self._stop_anim(item, path, stamp))

        ty = y + 14 + PREVIEW_H + 12
        st.txt(x + w / 2, ty + 11, fit(gif["name"], 15, "bold", w - 28), 15,
               "bold", anchor="center")
        url = "/gif/" + core.slug(gif["name"])
        st.txt(x + w / 2, ty + 22 + 9, fit(url, 11, "mono", w - 28), 11, "mono",
               theme.MONO_DIM, anchor="center")

        # Tags in the top corners (drawn over the preview's margin)
        if is_default:
            pw = measure("Default", 11, "semi") + 18
            st.img(x + w - 10 - pw, y + 10, draw.rrect, pw, 24, 12,
                   theme.AMBER_BG, theme.AMBER)
            st.txt(x + w - 10 - pw / 2, y + 22, "Default", 11, "semi",
                   theme.AMBER, anchor="center")
        if playing:
            pw = measure("Playing", 11, "semi") + 18
            st.img(x + 10, y + 10, draw.rrect, pw, 24, 12, theme.ACCENT_BG)
            st.txt(x + 10 + pw / 2, y + 22, "Playing", 11, "semi",
                   theme.ACCENT_TEXT, anchor="center")

        by = ty + 22 + 18 + 12
        key = "gif:" + url
        copied = a.copied == key
        bw = w - 28                                   # both rows share a width
        play_w = bw - 2 * 34 - 2 * 6
        bx = x + 14
        st.button(bx, by, 34, lambda: self.play_saved(gif), "Play", "play",
                  w=play_w, r=10, size=13, icon_size=13)
        bx += play_w + 6
        st.button(bx, by, 34, lambda: a.copy_url(key, url),
                  icon="check" if copied else "copy", w=34, r=10, icon_size=15,
                  fg=theme.GREEN if copied else theme.DIM, fill=None, line=None)
        bx += 34 + 6
        st.button(bx, by, 34, lambda: self.remove(gif), icon="x", w=34, r=10,
                  icon_size=15, fg=theme.DIM, fill=None, line=None)
        by += 34 + 8
        if is_default:
            st.button(x + 14, by, 34, lambda: self.toggle_default(gif),
                      "Default GIF", "star-on", w=bw, r=10, size=13,
                      icon_size=14, fg=theme.AMBER, fill=theme.AMBER_BG,
                      hover="#3A3018", line=None)
        else:
            st.button(x + 14, by, 34, lambda: self.toggle_default(gif),
                      "Set as default", "star", w=bw, r=10, size=13,
                      icon_size=14, fg=theme.DIM)

    # ── hover animation ─────────────────────────────────────

    def _start_anim(self, item, path, stamp, count):
        self._stop_timer()
        if count < 2:
            return
        self._hover = (item, path, stamp, count)
        self._hover_frame = 0
        self._step()

    def _step(self):
        self._anim_job = None
        if not self._hover or self.app.page != "gifs":
            return
        item, path, stamp, count = self._hover
        self._hover_frame = (self._hover_frame + 1) % count
        try:
            self.app.main.set_img(item, draw.gif_frame, path, stamp,
                                  self._hover_frame, PREVIEW_W, PREVIEW_H, 10)
        except tk.TclError:              # the page was redrawn
            self._hover = None
            return
        self._anim_job = self.app.after(90, self._step)

    def _stop_timer(self):
        if self._anim_job is not None:
            self.app.after_cancel(self._anim_job)
            self._anim_job = None
        self._hover = None

    def _stop_anim(self, item, path, stamp):
        self._stop_timer()
        try:
            self.app.main.set_img(item, draw.gif_frame, path, stamp, 0,
                                  PREVIEW_W, PREVIEW_H, 10)
        except tk.TclError:
            pass

    def tick(self):
        pass

    # ── actions ─────────────────────────────────────────────

    def _try(self, action):
        """Run a curtain call; show its complaint under the box if it has one."""
        self.note = ""
        try:
            action()
        except CurtainError as e:
            self.note = str(e)
        self.app.refresh()

    def play(self):
        a = self.app
        source = self.link.get().strip()

        def go():
            a.curtain.play_source(source)
            a.log_add("gif", "GIFs page", theme.ACCENT_SOFT)
        self._try(go)

    def play_saved(self, gif):
        a = self.app

        def go():
            a.curtain.play_saved(gif)
            a.log_add("/gif/" + core.slug(gif["name"]), "GIFs page",
                      theme.ACCENT_SOFT)
        self._try(go)

    def save(self):
        a = self.app
        source = self.link.get().strip()
        if not source and not a.curtain.last:
            self.note = "Paste a GIF link first"
            a.refresh()
            return
        name = simpledialog.askstring(
            "Save GIF", "Name for this GIF (used in the URL, e.g. hype):",
            parent=a)
        if not name or not core.slug(name):
            a.refresh()
            return
        self._try(lambda: a.curtain.save(name.strip(), source))

    def browse(self):
        path = filedialog.askopenfilename(
            parent=self.app, title="Pick a GIF or picture",
            filetypes=[("GIFs and pictures", "*.gif *.png *.jpg *.jpeg *.webp"),
                       ("All files", "*.*")])
        if path:
            self.link.set(path)
        self.app.refresh()

    def toggle_default(self, gif):
        a = self.app
        is_default = core.slug(gif["name"]) == core.slug(
            a.cfg.get("gif_default") or "")
        a.curtain.set_default(None if is_default else gif)
        a.refresh()

    def remove(self, gif):
        self._stop_timer()
        self.app.curtain.remove(gif)
        self.app.refresh()
