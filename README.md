# Kindle Dashboard

Turn a jailbroken **Kindle 4** (or similar e-ink device running
[KOReader](https://koreader.rocks/)) into an always-on status panel: clock,
weather, server/homelab health, and a calendar agenda — refreshed over wifi.

The device does no real work. A small server renders an 800×600 PNG; the Kindle
just downloads and displays it, flipping pages with the physical page-turn
buttons. That split is what makes it reliable on ancient hardware.

```
   SERVER                                       KINDLE
┌──────────────────────────┐                ┌──────────────────────────┐
│ render.py -> page*.png    │   wifi (HTTP)  │ kindledash.koplugin       │
│  page0 clock+weather+host │◄──────────────►│  shows page, side buttons │
│  page1..N calendar agenda │  :8137/...     │  flip pages, 30s refresh  │
│ systemd: render + serve   │                │  Back = exit, stays awake │
└──────────────────────────┘                └──────────────────────────┘
```

## What's here

| File | Runs on | What it does |
|---|---|---|
| `render.py` | server | Renders 800×600 grayscale PNGs (dashboard + agenda; optional dithered photo). Cross-platform fonts (Arial / DejaVu). |
| `render.sh` | server | Sources `config.env`, runs `render.py --mode pages`. |
| `deploy/*.service`, `*.timer` | server | systemd units: an HTTP server on port 8137 + a render timer. |
| `kindledash.koplugin/` | Kindle | KOReader plugin: fetches pages, full-screen display, button nav, auto-refresh, keeps the device awake. |
| `deploy-plugin.sh` | your computer | Pushes the plugin to the Kindle over SSH. |
| `config.env.example` | — | Copy to `config.env` and fill in. Holds your private calendar URL (gitignored). |

## Setup

### 1. Server

```bash
cp config.env.example config.env   # then edit it (location, calendar URL)
pip install pillow
./render.sh                         # writes pages/page0.png ...
```

Install the systemd units (adjust paths to where you put the repo):

```bash
sudo cp deploy/*.service deploy/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now kindle-dash-http.service kindle-dash-render.timer
```

The PNGs are now served at `http://YOUR_SERVER_IP:8137/`.

### 2. Kindle

Requires a jailbroken Kindle running KOReader. Set the server address in
`kindledash.koplugin/main.lua` (`BASE = "http://YOUR_SERVER_IP:8137"`), then
copy the `kindledash.koplugin/` folder into the Kindle's
`koreader/plugins/` directory.

Easiest install: connect the Kindle by USB, let it mount as a drive, and copy
the folder to `<KINDLE>/koreader/plugins/kindledash.koplugin/`. Eject, then
fully quit and reopen KOReader (a cold start is required to load new plugins).

Open it from KOReader: **Tools → Homelab dashboard**.

## Controls

- **Side page-turn buttons** — flip between the dashboard and agenda pages.
- **Back / Home** — exit.

## Data sources

- **Weather** — [open-meteo](https://open-meteo.com/) (no API key).
- **Calendar** — a Google Calendar "Secret address in iCal format" URL.
  Google caches this feed, so new events can take a while to appear.
- **Server health** — `render.py` optionally SSHes a host for CPU temp
  (`sensors`), load (`uptime`), and container counts. Edit `get_homelab()` for
  your own setup, or remove it.

## Refresh rate

Both sides default to 30 seconds (`OnUnitActiveSec=30s` in the timer,
`REFRESH_SEC = 30` in `main.lua`). Worst-case lag ≈ server interval + device
pull (~30–60s). Each refresh does a full e-ink flash, so going much below 30s
isn't worth it.

## Notes & gotchas

These cost me an evening — saving you the trouble:

- **ImageWidget caches by filename, not mtime.** Re-downloading `page0.png`
  with the same name shows the *stale* cached bitmap, so the clock appears
  frozen. The fix is `ImageWidget:new{ file = ..., file_do_cache = false }`.
- **KOReader key bindings need the exact nested form**: triple-nested keydef +
  explicit `event=`, e.g.
  `{ { { "RPgFwd","LPgFwd","Right" } }, event = "DashNext" }`. Get it wrong and
  *nothing* binds — not even exit, which traps the UI (hold power ~30s to reboot
  out).
- **The device sleeps when idle**, dropping wifi. The plugin calls
  `UIManager:preventStandby()` while open; you may also want to disable
  auto-suspend/standby in KOReader's settings for true always-on use.
- **Wall charger vs computer.** Plug into a dumb USB *wall charger* and it just
  charges — wifi stays on and the panel keeps running. Plugging into a
  *computer* can trigger USB Drive Mode, which drops wifi.
- **Keep secrets out of git.** Your calendar URL contains a private token. It
  lives in `config.env`, which is gitignored.

## Photo mode

`render.py --mode photo` dithers an image (Floyd–Steinberg) for e-ink. Point
`KD_PHOTO_DIR` at a folder and enable the photo page in `render_pages()` for a
photo-frame rotation. Off by default.

## License

MIT
