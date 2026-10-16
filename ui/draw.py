"""Pillow rendering: rounded shapes, glows, gradients and icons.

Every function takes sizes in layout pixels and returns an RGBA image sized
for the screen (layout pixels x theme.SCALE). Shapes are drawn oversized and
scaled down so edges come out smooth.
"""

from collections import OrderedDict

from PIL import Image, ImageDraw, ImageFilter, ImageTk

from . import theme

SS = 3            # supersampling factor for shapes
DOT_PAD = 20      # transparent margin around dot() for its glow
SWATCH_PAD = 22   # ... around swatch()
LOGO_PAD = 26     # ... around logo()
NOW_PAD = 44      # ... around the now-playing card glow


# ── colour helpers ────────────────────────────────────────────

def rgb(c: str) -> tuple:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def hexc(r, g, b) -> str:
    return f"#{int(r):02X}{int(g):02X}{int(b):02X}"


def mix(fg: str, bg: str, t: float) -> str:
    """fg at opacity t over bg."""
    a, b = rgb(fg), rgb(bg)
    return hexc(*(round(b[i] + (a[i] - b[i]) * t) for i in range(3)))


def dev(n: float) -> int:
    return max(1, int(round(n * theme.SCALE)))


# ── cache ─────────────────────────────────────────────────────

_cache: OrderedDict = OrderedDict()
_CACHE_MAX = 700


def photo(fn, *args) -> ImageTk.PhotoImage:
    """PhotoImage for fn(*args), rendered once and reused.

    The cache is bounded (least recently used goes first), so whoever shows
    an image must keep its own reference - Stage does that.
    """
    key = (fn.__name__,) + args
    p = _cache.get(key)
    if p is None:
        p = _cache[key] = ImageTk.PhotoImage(fn(*args))
        if len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    else:
        _cache.move_to_end(key)
    return p


# ── shapes ────────────────────────────────────────────────────

def rrect(w, h, r, fill=None, outline=None, bw=1.0) -> Image.Image:
    """Rounded rectangle, optionally with a border."""
    W, H = dev(w), dev(h)
    rad = min(r * theme.SCALE, W / 2, H / 2)
    line = max(1, int(round(bw * theme.SCALE))) if outline else 0
    c = min(int(rad + 0.999) + line + 1, W // 2, H // 2)   # corner block size
    if (W <= 96 and H <= 96) or c < 1:
        return _rrect(W, H, rad, fill, outline, line)
    # Big shape: draw one small tile and stretch its middle (9-slice), so the
    # cost doesn't grow with the size of the card.
    t = 2 * c + 2
    tile = _rrect(t, t, rad, fill, outline, line)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    xs = ((0, c, 0, c), (c, c + 2, c, W - c), (t - c, t, W - c, W))
    ys = ((0, c, 0, c), (c, c + 2, c, H - c), (t - c, t, H - c, H))
    for sx0, sx1, dx0, dx1 in xs:
        for sy0, sy1, dy0, dy1 in ys:
            if dx1 <= dx0 or dy1 <= dy0:
                continue
            part = tile.crop((sx0, sy0, sx1, sy1))
            if part.size != (dx1 - dx0, dy1 - dy0):
                part = part.resize((dx1 - dx0, dy1 - dy0), Image.NEAREST)
            out.paste(part, (dx0, dy0))
    return out


def _rrect(W, H, rad, fill, outline, line) -> Image.Image:
    """Supersampled rounded rectangle; all sizes in device pixels."""
    k = SS
    im = Image.new("RGBA", (W * k, H * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle(
        (0, 0, W * k - 1, H * k - 1), radius=rad * k,
        fill=rgb(fill) + (255,) if fill else None,
        outline=rgb(outline) + (255,) if outline else None,
        width=line * k)
    return im.resize((W, H), Image.LANCZOS)


def circle(d, fill) -> Image.Image:
    return rrect(d, d, d / 2, fill)


def _with_glow(shape: Image.Image, color: str, layers, pad) -> Image.Image:
    """Put soft glows (CSS box-shadow style) behind a shape.

    layers: (blur, opacity) pairs. The result is `pad` layout pixels larger
    than the shape on every side.
    """
    p = dev(pad)
    w, h = shape.size
    out = Image.new("RGBA", (w + 2 * p, h + 2 * p), (0, 0, 0, 0))
    base = Image.new("L", out.size, 0)
    base.paste(shape.getchannel("A"), (p, p))
    for blur, opacity in layers:
        a = base.filter(ImageFilter.GaussianBlur(blur * theme.SCALE / 2))
        a = a.point(lambda v, o=opacity: int(v * o))
        layer = Image.new("RGBA", out.size, rgb(color) + (0,))
        layer.putalpha(a)
        out = Image.alpha_composite(out, layer)
    out.alpha_composite(shape, (p, p))
    return out


def glow_rrect(w, h, r, fill, outline, glow, blur, opacity, pad) -> Image.Image:
    return _with_glow(rrect(w, h, r, fill, outline), glow, ((blur, opacity),), pad)


def dot(d, color, lit) -> Image.Image:
    """A light's colour dot; glows when lit. Padded by DOT_PAD."""
    layers = ((18, 0.85), (4, 1.0)) if lit else ()
    return _with_glow(circle(d, color), color, layers, DOT_PAD)


def status_dot(color) -> Image.Image:
    return _with_glow(circle(8, color), color, ((10, 1.0),), DOT_PAD)


def swatch(d, color, selected, grow) -> Image.Image:
    """Round colour swatch. Padded by SWATCH_PAD (measured at grow=1)."""
    size = d * grow
    if selected:
        ring = circle(size + 10, color)
        gap = circle(size + 6, theme.CARD)
        ring.alpha_composite(gap, ((ring.width - gap.width) // 2,) * 2)
        core = circle(size, color)
        ring.alpha_composite(core, ((ring.width - core.width) // 2,) * 2)
        shape, layers, extra = ring, ((20, 0.9),), 5
    else:
        shape, layers, extra = circle(size, color), ((14, 0.33),), 0
    pad = SWATCH_PAD - extra - d * (grow - 1) / 2
    return _with_glow(shape, color, layers, pad)


def toggle(on, alpha) -> Image.Image:
    """44x26 switch. alpha < 1 fades it into the card (disabled look)."""
    track = theme.ACCENT if on else theme.TRACK_OFF
    im = rrect(44, 26, 13, mix(track, theme.CARD, alpha))
    knob = circle(20, mix("#FFFFFF", theme.CARD, alpha))
    im.alpha_composite(knob, (dev(21 if on else 3), dev(3)))
    return im


def logo() -> Image.Image:
    """The purple app tile with its glow and the bulb icon."""
    tile = rrect(38, 38, 11, theme.ACCENT)
    ic = icon("bulb", 20, "#FFFFFF")
    tile.alpha_composite(ic, ((tile.width - ic.width) // 2,
                              (tile.height - ic.height) // 2))
    return _with_glow(tile, theme.ACCENT, ((24, 0.45),), LOGO_PAD)


# ── effect previews / gradients ───────────────────────────────

_DARK = "#0B0B12"
_RAINBOW = ("#EF4444", "#F59E0B", "#EAB308", "#22C55E",
            "#06B6D4", "#3B82F6", "#8B5CF6", "#EC4899")
_BANDS = {
    "flash": (("#F59E0B", .22), (_DARK, .39), ("#F59E0B", .61),
              (_DARK, .78), ("#F59E0B", 1.01)),
    "rainbow-strobe": (("#EF4444", .12), (_DARK, .22), ("#EAB308", .34),
                       (_DARK, .44), ("#22C55E", .56), (_DARK, .66),
                       ("#3B82F6", .78), (_DARK, .88), ("#EC4899", 1.01)),
    "chase": ((_DARK, .18), ("#0B3B46", .36), ("#0E7490", .54),
              ("#22D3EE", .72), (_DARK, 1.01)),
    "police": (("#EF4444", .25), ("#2563EB", .5), ("#EF4444", .75),
               ("#2563EB", 1.01)),
    "lightning": ((_DARK, .28), ("#FFFFFF", .32), (_DARK, .37), ("#C7D2FE", .40),
                  (_DARK, .74), ("#FFFFFF", .79), (_DARK, 1.01)),
    "sparkle": (("#7C3AED", .20), ("#FFFFFF", .24), ("#7C3AED", .55),
                ("#FFFFFF", .59), ("#7C3AED", .82), ("#FFFFFF", .85),
                ("#7C3AED", 1.01)),
}
_BANDS["alternate"] = _BANDS["police"]
_GRADS = {
    "pulse": (_DARK, "#EC4899", _DARK),
    "rainbow-bar": ("#EF4444", "#EAB308", "#22C55E", "#3B82F6", "#EC4899"),
    "flicker": ("#7C2D12", "#F97316", "#FBBF24", "#EA580C", "#FDE68A",
                "#F97316", "#7C2D12"),
    "breathe": ("#172554", "#3B82F6", "#172554"),
    "fade": ("#8B5CF6", "#06B6D4"),
    "countdown": ("#22C55E", "#EAB308", "#EF4444"),
}
FX_CHIP = {"flash": "#F59E0B", "strobe": "#F43F5E", "pulse": "#EC4899",
           "rainbow": "#8B5CF6", "rainbow-strobe": "#EC4899",
           "chase": "#22D3EE", "alternate": "#3B82F6", "police": "#3B82F6",
           "flicker": "#F97316", "breathe": "#3B82F6", "fade": "#8B5CF6",
           "lightning": "#C7D2FE", "sparkle": "#A78BFA",
           "countdown": "#EAB308"}


def _lerp_stops(stops, t):
    n = len(stops) - 1
    i = min(int(t * n), n - 1)
    f = t * n - i
    a, b = rgb(stops[i]), rgb(stops[i + 1])
    return tuple(round(a[j] + (b[j] - a[j]) * f) for j in range(3))


def _fx_color(kind, t, x):
    """Colour of an effect preview at fraction t / layout x."""
    if kind in _BANDS:
        for color, end in _BANDS[kind]:
            if t < end:
                return rgb(color)
    if kind == "strobe":
        return rgb("#F43F5E") if int(x // 9) % 2 == 0 else rgb(_DARK)
    if kind in _GRADS:
        return _lerp_stops(_GRADS[kind], t)
    return _lerp_stops(_RAINBOW, t)


def _strip(kind, w, h, r) -> Image.Image:
    W, H = dev(w), dev(h)
    row = Image.new("RGB", (W, 1))
    px = row.load()
    for x in range(W):
        px[x, 0] = _fx_color(kind, x / max(W - 1, 1), x / theme.SCALE)
    im = row.resize((W, H), Image.NEAREST).convert("RGBA")
    im.putalpha(rrect(w, h, r, "#FFFFFF").getchannel("A"))
    return im


def fx_preview(kind, w, h, r) -> Image.Image:
    """The striped / gradient preview on an effect tile."""
    return _strip(kind, w, h, r)


def bar(w, h, frac, kind) -> Image.Image:
    """Progress / slider track: a rounded groove filled to `frac`.

    kind is a hex colour or "rainbow-bar".
    """
    im = rrect(w, h, h / 2, theme.TILE_LINE)
    frac = max(0.0, min(1.0, frac))
    if frac > 0:
        fw = max(h, w * frac)
        fill = (_strip(kind, fw, h, h / 2) if kind == "rainbow-bar"
                else rrect(fw, h, h / 2, kind))
        im.alpha_composite(fill, (0, 0))
    return im


def gif_frame(path, stamp, index, w, h, r) -> Image.Image:
    """One frame of a GIF file, blown up with hard pixel edges (the curtain
    is a grid of LEDs) and given rounded corners. `stamp` is the file's
    modified time, so a replaced file is not served from the cache."""
    try:
        with Image.open(path) as im:
            im.seek(index % getattr(im, "n_frames", 1))
            frame = im.convert("RGB")
    except Exception:
        frame = Image.new("RGB", (30, 32), rgb(theme.TILE_LINE))
    out = frame.resize((dev(w), dev(h)), Image.NEAREST).convert("RGBA")
    out.putalpha(rrect(w, h, r, "#FFFFFF").getchannel("A"))
    return out


# ── icons (24-unit grid, round-capped strokes, like the mockup's SVGs) ──

def icon(name, size, color, sw=2.0) -> Image.Image:
    px = dev(size)
    k = 4
    n = px * k
    u = n / 24.0
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    col = rgb(color) + (255,)
    w = max(1, int(round(sw * u)))

    def cap(x, y):
        d.ellipse((x * u - w / 2, y * u - w / 2, x * u + w / 2, y * u + w / 2),
                  fill=col)

    def line(*pts, close=False):
        pts = list(pts) + ([pts[0]] if close else [])
        d.line([(x * u, y * u) for x, y in pts], fill=col, width=w)
        for x, y in pts:
            cap(x, y)

    def arc(cx, cy, r, a0, a1):
        d.arc(((cx - r) * u - w / 2, (cy - r) * u - w / 2,
               (cx + r) * u + w / 2, (cy + r) * u + w / 2),
              a0, a1, fill=col, width=w)

    def box(x0, y0, x1, y1, r, fill=False):
        d.rounded_rectangle(
            (x0 * u - w / 2, y0 * u - w / 2, x1 * u + w / 2, y1 * u + w / 2),
            radius=r * u + w / 2, outline=col, width=w,
            fill=col if fill else None)

    if name == "grid":
        for x, y in ((3, 3), (14, 3), (3, 14), (14, 14)):
            box(x, y, x + 7, y + 7, 1.5)
    elif name == "bulb":
        arc(12, 9, 6, 125.5, 54.5)
        line((8.5, 13.9), (9.5, 16), (14.5, 16), (15.5, 13.9))
        line((9, 18.6), (15, 18.6))
        line((10, 21.4), (14, 21.4))
    elif name == "sparkles":
        line((12, 3), (13.8, 7.7), (18.5, 9.5), (13.8, 11.3), (12, 16),
             (10.2, 11.3), (5.5, 9.5), (10.2, 7.7), close=True)
        line((19, 15), (19.8, 17.2), (22, 18), (19.8, 18.8), (19, 21),
             (18.2, 18.8), (16, 18), (18.2, 17.2), close=True)
    elif name == "layers":
        line((12, 3), (21, 8), (12, 13), (3, 8), close=True)
        line((3, 13), (12, 18), (21, 13))
    elif name == "gear":
        arc(12, 12, 3, 0, 360)
        for a, b in (((12, 2), (12, 5)), ((12, 19), (12, 22)),
                     ((4.9, 4.9), (7, 7)), ((17, 17), (19.1, 19.1)),
                     ((2, 12), (5, 12)), ((19, 12), (22, 12)),
                     ((4.9, 19.1), (7, 17)), ((17, 7), (19.1, 4.9))):
            line(a, b)
    elif name == "refresh":
        arc(12, 12, 9, 0, 315)
        cap(21, 12)
        line((18.4, 5.6), (21, 8))
        line((21, 3), (21, 8), (16, 8))
    elif name == "power":
        line((12, 3), (12, 12))
        arc(12, 12, 8, 315, 225)
        cap(6.3, 6.3)
        cap(17.7, 6.3)
    elif name == "stop":
        box(7, 7, 17, 17, 1, fill=True)
    elif name == "pencil":
        line((4, 20), (8, 20), (19, 9), (15, 5), (4, 16), close=True)
    elif name == "x":
        line((6, 6), (18, 18))
        line((18, 6), (6, 18))
    elif name == "copy":
        box(9, 9, 20, 20, 2)
        line((5, 15), (5, 5))
        arc(7, 5, 2, 180, 270)
        line((7, 3), (17, 3))
    elif name == "check":
        line((5, 12), (10, 17), (19, 7))
    elif name == "back":
        line((15, 5), (8, 12), (15, 19))
    elif name == "zap":
        line((13, 2), (4, 14), (11, 14), (10, 22), (20, 9), (13, 9), close=True)
    elif name == "drop":
        line((7.3, 11.6), (12, 3.5), (16.7, 11.6))
        arc(12, 14.5, 5.5, 328, 212)
    elif name == "play":
        line((8, 5), (19, 12), (8, 19), close=True)
    elif name == "plus":
        line((12, 5), (12, 19))
        line((5, 12), (19, 12))
    elif name == "image":
        box(3, 4, 21, 20, 2)
        line((4.5, 17.5), (9, 12.5), (13, 16.5), (16, 13.5), (19.5, 17))
        arc(15.5, 8.8, 1.3, 0, 360)
    elif name in ("star", "star-on"):
        import math
        pts = [(12 + (9.2 if i % 2 == 0 else 3.9) * math.sin(i * math.pi / 5),
                12.6 - (9.2 if i % 2 == 0 else 3.9) * math.cos(i * math.pi / 5))
               for i in range(10)]
        if name == "star-on":
            d.polygon([(x * u, y * u) for x, y in pts], fill=col)
        line(*pts, close=True)
    elif name == "folder":
        line((3, 7), (3, 19), (21, 19), (21, 9), (12, 9), (10, 6), (3, 6),
             close=True)
    elif name == "sun":
        arc(12, 12, 4, 0, 360)
        for a, b in (((12, 2), (12, 4)), ((12, 20), (12, 22)),
                     ((2, 12), (4, 12)), ((20, 12), (22, 12)),
                     ((4.9, 4.9), (6.3, 6.3)), ((17.7, 17.7), (19.1, 19.1)),
                     ((4.9, 19.1), (6.3, 17.7)), ((17.7, 6.3), (19.1, 4.9))):
            line(a, b)
    return im.resize((px, px), Image.LANCZOS)
