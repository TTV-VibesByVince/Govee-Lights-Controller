# Contributing

Thanks for helping. Bug reports and ideas are as welcome as code.

## Reporting a bug or asking for a feature

Open an [issue](https://github.com/TTV-VibesByVince/Govee-Lights-Controller/issues/new/choose)
and pick a template. For bugs, say which light models you have, the app
version (shown in the sidebar) and the exact URL you sent. **Don't paste your
`govee_config.json` or `govee_account.json`**: they hold your network
addresses and Govee sign-in.

## Ground rules for code

1. **Standard library + Pillow only.** No other packages, so anyone can run it
   with one `pip install`.
2. **Never change what an existing URL does.** Streamers have these wired into
   MixItUp. New URLs are fine; changing old ones is not. `tests/v8_replies.json`
   holds the original replies and the tests check them.
3. **New behaviour that differs from before is opt-in** (a setting, off by
   default), so updating never surprises anyone mid-stream.
4. **No personal data in commits:** no real IP addresses, emails, keys or tokens.
5. **Keep the parts separate:** `engine.py`, `server.py` and `curtain.py` have
   no interface code; everything on screen lives in `ui/`.

## Running the tests

The tests need no lights and no Govee account; the network and Govee are faked.

```
python tests/test_server.py
python tests/test_curtain.py
```

They run automatically on every push and pull request (Windows, Python 3.10
and 3.13).

## Adding an effect

Every effect is a loop in `EffectsEngine` (`engine.py`), listed in `EFFECTS`
and `_loops`. Add its URL in `server.py`, a preview in `ui/draw.py` (`_BANDS`
or `_GRADS`, plus `FX_CHIP`) and a tile in `ui/dashboard.py`. Make sure the
name doesn't clash with a colour name: `/fire` is a colour, which is why the
fire effect is `/flicker`.

## Pull requests

Keep them focused, describe what changed and how you checked it, and include
a screenshot for anything visible.
