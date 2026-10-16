"""Colours and fonts for the v9 interface (values taken from the mockup)."""

import tkinter.font as tkfont

# Device pixels per layout unit. Layout code works in mockup (CSS) pixels;
# everything is multiplied by SCALE when it reaches the screen.
SCALE = 1.0

# Surfaces
BG          = "#0B0B12"
SIDEBAR     = "#0F0F18"
CARD        = "#13131D"
TILE        = "#181824"
LINE        = "#1E1E2C"
TILE_LINE   = "#232333"
PILL        = "#1B1B28"
GHOST       = "#16161F"
GHOST_LINE  = "#2A2A3C"
GHOST_HOVER = "#22222F"
NAV_ACTIVE  = "#1F1A33"
NAV_HOVER   = "#1B1B28"
CARD_HOVER  = "#34344A"
TILE_HOVER  = "#4A3A86"

# Text
TEXT     = "#ECECF4"
MUTED    = "#9393AD"
DIM      = "#A9A9C2"
FAINT    = "#7C7C96"
MONO_DIM = "#8585A0"
LINK     = "#B9A2FF"

# Accents
ACCENT      = "#7C3AED"
ACCENT_SOFT = "#A78BFA"
ACCENT_TEXT = "#C4B5FD"
ACCENT_BG   = "#241D3D"
NOW_LINE    = "#3A2A6E"
TRACK_OFF   = "#2E2E40"
UNLIT       = "#2A2A3A"
GREEN       = "#34D399"
RED         = "#F43F5E"
AMBER       = "#FCD34D"
AMBER_BG    = "#2B2414"

_UI, _SEMI, _MONO = "Segoe UI", None, "Consolas"
_fonts: dict = {}


def init(root):
    """Call once, after the Tk root exists."""
    global SCALE, _UI, _SEMI, _MONO
    # Windows scaling comes in steps (100%, 125%, 150%...); snap to 5%
    SCALE = max(1.0, round(root.winfo_fpixels("1i") / 96.0 * 20) / 20)
    families = set(tkfont.families(root))
    if "Segoe UI" not in families:
        _UI = "TkDefaultFont"
    _SEMI = "Segoe UI Semibold" if "Segoe UI Semibold" in families else None
    if "Consolas" not in families:
        _MONO = "Courier New"


def font(size: float, weight: str = "reg") -> tuple:
    """A Tk font tuple. size is in layout pixels; weight: reg/semi/bold/mono."""
    px = -max(1, int(round(size * SCALE)))
    if weight == "bold":
        return (_UI, px, "bold")
    if weight == "semi":
        return (_SEMI, px) if _SEMI else (_UI, px, "bold")
    if weight == "mono":
        return (_MONO, px)
    return (_UI, px)


def measure(text: str, size: float, weight: str = "reg") -> float:
    """Width of text in layout pixels."""
    spec = font(size, weight)
    f = _fonts.get(spec)
    if f is None:
        f = _fonts[spec] = tkfont.Font(font=spec)
    return f.measure(text) / SCALE


def fit(text: str, size: float, weight: str, max_w: float) -> str:
    """Shorten text with an ellipsis so it fits in max_w layout pixels."""
    if max_w <= 0:
        return ""
    if measure(text, size, weight) <= max_w:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if measure(text[:mid].rstrip() + "…", size, weight) <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + "…" if lo else "…"
