"""
Govee Light Controller  V1.4
━━━━━━━━━━━━━━━━━━━━━━━━━
Persistent background app - controls Govee lights via a local HTTP server.
MixItUp sends web requests, zero process spawning, zero focus stealing.

  !red          → http://localhost:8765/red
  !off          → http://localhost:8765/off
  !stop         → http://localhost:8765/stop
  rainbow forever → http://localhost:8765/rainbow/forever
  !followlights → http://localhost:8765/rainbow-strobe
                  http://localhost:8765/rainbow-strobe/5        (5 seconds)
                  http://localhost:8765/rainbow-strobe/forever

New in V1.0: /chase /police /alternate /flicker /breathe /fade /lightning
/sparkle /countdown, plus /scene/<name>, /alert/<name>, /queue/<url>,
/light/<name>/<color> and ?speed= ?brightness= ?seconds= options.
The full list is in server.py and on the Settings page.

New in V1.1: GIFs on Govee Curtain Lights (H70B6) - /gif/<name>, /gif/default,
/gif?url=<Giphy, Tenor or Imgur link>. Needs a Govee account (see Settings).
New in V1.2: /gif/avatar?url=<profile picture>, a GIF queue, and web-request
GIFs that return to the default GIF after a show time.
New in V1.3: /color/<hex> (e.g. /color/ff0080) and an opt-in setting that
lets other devices on the home network (a NAS running Vibe TV) send commands.
V1.4: ready to publish - generic branding, no personal details in the code.

Code layout:  engine.py (lights + effects) · curtain.py (curtain GIFs) ·
              server.py (MixItUp URLs) · ui/
"""

import sys


def main():
    # Crisp rendering on scaled (125%/150%) displays
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    from ui.app import GoveeApp
    GoveeApp().mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        try:
            input("\nPress Enter to close…")
        except Exception:
            pass
