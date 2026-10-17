# Changelog

Every version keeps every URL from the versions before it working exactly the
same; the automatic tests check this on each change.

## V1.4

- Ready to share: generic branding, no personal details in the code.
- README, screenshots, demo, offline tests, `Start Govee Controller.bat`.

## V1.3

- `/color/<hex>` (also takes a colour name), for tools that build a colour themselves.
- Optional *Accept requests from my network* setting, so a second PC or a NAS can
  send commands. Off by default; requests from the internet are always refused.

## V1.2

- Profile pictures on the curtain: `/gif/avatar?url=$useravatar` (Twitch and YouTube).
- GIFs from web requests stay for a show time (default 8 seconds), then the
  default GIF returns. `&seconds=N` changes it per request.
- Optional queue for web-request GIFs, so they play one after another.
- *Set as default* button on every saved GIF; the default has a yellow border.

## V1.1

- GIFs on Govee Curtain Lights (H70B6): GIFs page with a paste box and a library,
  `/gif/<name>`, `/gif/default` and `/gif?url=<link>` for chat.
- Curtain mode: its switch on the Dashboard chooses between following room
  commands and *GIF mode*.
- Govee account section in Settings, with the emailed-code sign-in and encrypted storage.
- Chat links limited to Giphy, Tenor and Imgur, with a cooldown.
- A second copy of the app now shows "Server offline" instead of silently
  sharing the port.

## V1.0

- Nine new effects: chase, police, two-colour alternate, fire flicker, breathe,
  fade, lightning, sparkle, countdown.
- Scenes (a colour per light plus brightness) and alert presets.
- `/queue/...` and queued alerts, so effects can wait their turn.
- `?speed=`, `?brightness=` and `?seconds=` options on any effect.
- Single lights: `/light/<name>/<color|on|off>`.
- Optional *return to the previous look* after an effect.

## v9

- New interface: sidebar, Dashboard with a now-playing bar, light cards with
  switches, colour swatches, effect tiles with copy buttons, scrollable Settings.
- Split into `engine.py`, `server.py` and `ui/`.
- Fixed: `/stop`, `/off` and colour commands did not end an effect that was
  already running.

## v8

- The original single-file controller: colours, flash, strobe, pulse, rainbow,
  rainbow strobe, brightness, and the MixItUp URLs everything since builds on.
