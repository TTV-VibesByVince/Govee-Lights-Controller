# Govee Light Controller

A Windows desktop app for streamers that controls Govee lights from
[MixItUp](https://mixitupapp.com/) (or Streamer.bot, a Stream Deck, or anything
else that can open a web address). Each chat command, channel-point reward or
alert sends a plain web request such as `http://localhost:8765/red` and the
lights react instantly over your home network. No cloud, no scripts, no
windows popping up.

It also plays **GIFs on Govee Curtain Lights (H70B6)**, including GIF links
from chat and viewers' profile pictures as entrance animations.

![The Dashboard: every light, what is playing, colours and recent activity](docs/screenshots/dashboard.png)

| Effects | Curtain GIFs |
|---|---|
| ![Effect tiles, each with a copy button for its MixItUp URL](docs/screenshots/effects.png) | ![The GIF library with a default GIF](docs/screenshots/gifs.png) |
| **Alert presets** | **Scenes** |
| ![Alert presets for raids, subs and follows](docs/screenshots/alerts.png) | ![Saved scenes with a colour per light](docs/screenshots/scenes.png) |

## Features

- **Colours:** 46 named colours (`/red`, `/hotpink`, `/gaming`...) or any hex
  colour (`/ff0080`).
- **Effects:** flash, strobe, pulse, rainbow, rainbow strobe, chase, police,
  two-colour alternate, fire flicker, breathe, fade, lightning, sparkle and
  countdown, each timed or `/forever`, with optional speed, brightness and
  duration.
- **Scenes:** save a colour per light plus brightness and recall it with one
  URL.
- **Alerts:** named presets (effect + colour + length + speed) for subs,
  raids, follows; alerts that arrive together play one after another.
- **Curtain GIFs:** paste a Giphy / Tenor / Imgur link, keep a library of
  saved GIFs, set a default GIF that comes back after each chat GIF, queue
  GIFs from chat, and show Twitch or YouTube profile pictures.
- **Curtain mode:** a curtain can follow room colours like any other light,
  or stay in "GIF mode" where only GIF commands change it.
- **Dashboard:** live view of every light, what is playing, recent activity,
  and a copy button for every URL.

## Requirements

- Windows 10 or 11 (other systems are untested; the encrypted sign-in
  storage is Windows-only).
- Python 3.10 or newer, from [python.org](https://www.python.org/downloads/).
- Govee lights with **LAN Control** turned on: in the Govee Home app, open
  each light's settings and switch on *LAN Control*. The PC and the lights
  must be on the same network.
- For curtain GIFs only: an internet connection, your Govee account, and a
  free Govee developer API key (see below).

## Install and run

```
git clone https://github.com/TTV-VibesByVince/govee-light-controller.git
cd govee-light-controller
pip install -r requirements.txt
python govee_controller_v1.4.py
```

The first time, click **Scan network** on the Dashboard to find your lights.
If Windows Firewall asks about Python, allow it on **private** networks, or
the lights can't be found. Your lights and settings are saved in
`govee_config.json` next to the program.

## Using it with MixItUp

Add a **Web Request** action to a command and point it at one of the URLs
below. The **Settings** page lists every URL with a copy button.

| What | URL |
|---|---|
| Colour | `http://localhost:8765/red` or `/ff0080` |
| Room on / off | `/on`, `/off` |
| Stop the effect, back to your default colour | `/stop` |
| Brightness | `/dim`, `/medium`, `/bright` |
| Strobe red for the effect duration | `/strobe/red` |
| Strobe until `/stop` | `/strobe/red/forever` |
| Rainbow strobe for 5 seconds | `/rainbow-strobe/5` |
| Other effects | `/chase/red`, `/police`, `/flicker`, `/breathe/blue`, `/lightning`, `/sparkle/purple`, `/fade/blue/3`, `/countdown/10` |
| Effect options | `/strobe/red?speed=fast&brightness=40&seconds=3` |
| Saved scene / alert | `/scene/chill`, `/alert/raid` |
| Wait for the running effect | `/queue/strobe/red` |
| One light | `/light/desk/red` |
| Status (JSON) | `/status` |

### Curtain GIFs from chat

| What | URL |
|---|---|
| A saved GIF | `/gif/hype` |
| Your default GIF | `/gif/default` |
| A link from chat, e.g. `!playgif <link>` | `/gif?url=$arg1text` |
| An entrance with the viewer's profile picture | `/gif/avatar?url=$useravatar` |
| Choose how long it stays | add `&seconds=15` |

Chat links are limited to Giphy, Tenor and Imgur, with a cooldown; both can
be changed in Settings. After a GIF from a web request has been up for 8
seconds (adjustable), the default GIF returns.

## Setting up curtain GIFs

The LAN protocol can only set one colour per light, so pictures are sent
through Govee's cloud, the same way the Govee Home app does it.

1. Get a Govee developer API key: in the Govee Home app go to
   **Profile > Settings > Apply for API Key**. The key arrives by email.
2. In the app, open **Settings > Govee account**, enter the key, your Govee
   email and password, and click **Connect**. Govee may email you a
   verification code the first time.
3. On the **Dashboard**, switch the curtain off to keep it in GIF mode (room
   colours and effects then leave it alone), or on to have it follow the
   room.
4. On the **GIFs** page, paste a link and press **Play**, or **Save** it to
   the library. Mark one as the default.

Sending a GIF takes about 5 seconds.

## Privacy

Everything stays on your PC. Your Govee API key and sign-in are stored in
`govee_account.json`, encrypted for your Windows user account. Your password
is only kept (also encrypted) if *Stay signed in* is on, and is only ever
sent to Govee. By default the web server accepts requests from this PC only;
the *Accept requests from my network* setting opens it to other devices on
your home network, never to the internet.

## Troubleshooting

- **No lights found:** check that LAN Control is on for each light in the
  Govee Home app, that the PC is on the same network, and that the firewall
  allowed Python on private networks.
- **"Server offline" in the sidebar:** another copy of the app (or another
  program) is using port 8765. Close it, or change the port in Settings.
- **GIFs stopped working:** run `python tools/curtain_test.py` for a
  step-by-step report of the Govee side.

## Disclaimer

This is an unofficial project, not affiliated with or endorsed by Govee.
Curtain GIFs use the Govee Home app's private, undocumented interface, which
Govee may change at any time, and which may not be covered by Govee's terms
of service. Use it at your own risk.

## Credits

Thanks to **tailgunner357**: the curtain GIF upload method, including the
fixed data block in `curtain_chunk1.txt`, comes from his *Govee GIF Player*
and is used with his permission.

## License

[MIT](LICENSE)
