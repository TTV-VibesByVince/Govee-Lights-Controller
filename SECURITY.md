# Security

## Reporting a problem

Please **don't** open a public issue for a security problem. Use GitHub's
private reporting instead: the **Security** tab of this repository →
**Report a vulnerability**. You'll get a reply as soon as possible.

## What the app does with your data

- **Web server:** it answers only this PC by default. With *Accept requests
  from my network* on, it also answers devices on your home network (private
  addresses), and it always refuses requests from public internet addresses.
  There is no password on it, so only turn that setting on for a network you
  trust.
- **Govee sign-in:** your Govee API key, sign-in token and (only if *Stay
  signed in* is on) your password are kept in `govee_account.json`, encrypted
  with Windows' data protection for your Windows user. They are only ever
  sent to Govee.
- **GIF links from chat:** limited to Giphy, Tenor and Imgur by default, with a
  size limit and a cooldown. Chat can't make the app open files on your PC.
- **No telemetry:** the app doesn't contact anything except your lights and,
  for curtain GIFs only, Govee.

## Supported versions

Only the latest release gets fixes.
