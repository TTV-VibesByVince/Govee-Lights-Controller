# Govee Light Controller

A tkinter desktop app that runs a local HTTP server (default port 8765) so
MixItUp can control Govee lights over the LAN with plain web requests, and
play GIFs on Govee Curtain Lights through the Govee cloud.

## Project rules

1. **Standard library + Pillow only.** No other third-party packages.
2. **Bump the version on every update.** The current version is V1.4 (it
   followed v8, v9, V1.0, V1.1, V1.2 and V1.3). The next update is V1.5.
   Change `APP_VERSION` in `engine.py` and rename the entry point to match
   (`govee_controller_v1.4.py` -> `govee_controller_v1.5.py`).
   Leave `govee_controller_v8.py` untouched (it is kept locally only and is
   not in the GitHub repository - see `.gitignore`).
3. **Never change existing MixItUp URLs.** Every URL that works today must keep
   working with the same meaning. New URLs may be added; existing ones may not
   be renamed, removed or given different behaviour. The list is in the
   docstring of `LightRequestHandler` in `server.py`. Watch for clashes with
   colour names: `/fire` is a colour, which is why the fire effect is
   `/flicker`.
4. **Curtain lights have two modes, chosen by their switch on the Dashboard.**
   Curtain models are listed in `curtain_skus` (default `["H70B6"]`).
   - Switch off = **GIF mode** (the default for a newly found curtain): room
     commands never reach it - no colours, effects, brightness, scenes or
     all-on/all-off, and `/light/<name>/...` refuses it. Only GIF commands
     change it.
   - Switch on = it follows room commands like any other light. GIFs can still
     be sent, but the next room command replaces them.
   The All / None buttons never change a curtain's mode. `excluded_ips` and
   `excluded_skus` still hard-exclude an address or model from room commands.
5. **Updates must not remove features or change defaults.** New behaviour that
   differs from before (e.g. "return to previous look") is an opt-in setting.
6. **This project will be published on GitHub. Keep private data out of the
   code and out of commits.** No real IP addresses, emails, keys or tokens in
   source files or docs. Everything personal lives in files listed in
   `.gitignore` (`govee_config.json`, `govee_account.json`, `gifs/`, the
   scratch files in `tools/`, plus `govee_controller_v8.py` and
   `Dashboard-html.zip`, which contain real addresses). Secrets in
   `govee_account.json` are encrypted for the Windows user (DPAPI); never log
   or print them. Before every commit, scan what is staged for addresses,
   emails and keys. Commits use the GitHub no-reply address, not a personal
   email. The repository is public:
   https://github.com/TTV-VibesByVince/govee-light-controller

## Layout

- `govee_controller_v1.4.py` - entry point; run this.
- `engine.py` - config, colour table, LAN discovery, UDP sending, effects,
  the effect queue, scenes and alert presets. No UI code.
- `curtain.py` - curtain GIFs: Govee sign-in, GIF conversion (30x32, 256
  colours), upload, the saved-GIF library, chat-link rules. No UI code.
  `curtain_chunk1.txt` is a fixed block of data the upload needs.
- `server.py` - the HTTP server and URL handling for MixItUp. No UI code.
- `ui/` - the tkinter interface. Everything is drawn on canvases, with rounded
  shapes, glows, gradients and icons rendered by Pillow.
  - `theme.py` colours and fonts, `draw.py` Pillow rendering,
    `stage.py` canvas helper (layout units, hover/click zones, scrollbar),
    `app.py` window + sidebar + actions, and one file per page:
    `dashboard.py`, `colors.py` (also the colour picker), `scenes.py`,
    `alerts.py`, `gifs.py`, `settings.py`.
- `tools/curtain_test.py` - standalone script that sends a test pattern or a
  GIF to the curtain and prints every step. Use it to diagnose the Govee
  side without the app.
- `govee_config.json` - saved lights, settings, scenes, alerts, GIF list.
- `govee_account.json` - Govee API key and sign-in (encrypted).
- `gifs/` - saved GIFs, already converted to 30x32.
- `Dashboard-html.zip` - the design mockup the UI follows (local only).
- `README.md`, `LICENSE` (MIT), `requirements.txt` - for the GitHub page.

## How effects work

- Every effect is a loop in `EffectsEngine` registered in `EFFECTS` /
  `_loops`, started through `engine.play(...)`. To add one: add the loop, add
  it to both tables, add its URL in `server.py`, a preview in `ui/draw.py`
  (`_BANDS` or `_GRADS`, plus `FX_CHIP`) and a tile in `ui/dashboard.py`.
- A plain command replaces whatever is running and empties the queue (the
  original behaviour). `/alert/...` and `/queue/...` wait their turn instead.
- After the last effect the room is restored: default colour, or the previous
  look if `after_effect` is `"previous"`. `/stop` always restores the default.

## How curtain GIFs work

- The LAN protocol can only set one colour per device, so GIFs go through
  Govee's cloud the way the Govee Home phone app does: sign in (Govee may
  email a code), upload the GIF as a temporary DIY effect, tell the curtain
  to play it through the official API, delete the temporary effect. About 5
  seconds per GIF. Needs internet, a Govee account and a developer API key.
- The upload uses the phone app's **private, undocumented API**. If GIFs stop
  working after a Govee app update, run `tools/curtain_test.py` first to see
  which step fails. The method comes from tailgunner357's "Govee GIF Player".
- One GIF uploads at a time. A second web request while one is loading is
  refused, unless "Queue web-request GIFs" is on (`gif_queue`, off by
  default; at most `gif_queue_max` waiting).
- **Web requests and the app behave differently on purpose.** A GIF from a
  web request (`/gif/...`) gets a show time (`gif_web_seconds`, default 8, or
  `&seconds=N` on the URL); when it is up the next queued GIF plays, or the
  default GIF comes back. A GIF played from the app's GIFs page stays until
  replaced, and clears the queue. With no default GIF set, nothing returns.
- Links from chat (`/gif?url=`) are limited to Giphy, Tenor and Imgur and
  have a cooldown, both adjustable in Settings. The app's own GIFs page is
  not limited.
- `/gif/avatar?url=` shows a profile picture (for `$useravatar` in MixItUp).
  It only accepts Twitch / YouTube image hosts (`AVATAR_SITES`), has no
  cooldown, and fetches the link directly. A still picture is sent as two
  identical frames.

## Running and checking

```
python govee_controller_v1.4.py
```

Launching the app talks to the real lights (and applies the default colour if
that setting is on). After any change, run the app, check
`http://localhost:8765/status`, and fix errors before moving on. Compare old
URLs against `govee_controller_v8.py` to prove nothing changed. Only one copy
of the app can hold the port; a second copy shows "Server offline".

The server listens on localhost only, unless `lan_access` ("Accept requests
from my network", off by default) is on; then it listens on all adapters but
still refuses any non-private address. Vibe TV on the NAS needs it on.
