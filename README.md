# Kindle Dashboard

Turn a jailbroken **Kindle 4** (or similar e-ink device running
[KOReader](https://koreader.rocks/)) into an always on status panel showing the
clock, weather, server health, and a calendar agenda, refreshed over wifi.

The device does no real work. A small server renders an 800×600 PNG, and the
Kindle just downloads and displays it, flipping pages with the physical page
turn buttons. That split is what makes it reliable on ancient hardware.

```
   SERVER                                       KINDLE
┌──────────────────────────┐                ┌──────────────────────────┐
│ render.py -> page*.png    │   wifi (HTTP)  │ kindledash.koplugin       │
│  page0 clock+weather+host │◄──────────────►│  shows page, side buttons │
│  page1..N calendar agenda │  :8137/...     │  flip pages, 30s refresh  │
│ systemd: render + serve   │                │  Back = exit, stays awake │
└──────────────────────────┘                └──────────────────────────┘
```

## What you need

You do **not** need a homelab. The "server" is just any always on computer on
your wifi that can run Python and serve a file:

* A **Raspberry Pi** (even a ~$15 Pi Zero 2 W) is the classic choice.
* A **NAS** (Synology, QNAP), an **old laptop**, a **mini PC**, or a spare Mac.
* Even your **main desktop**. It works while the machine is on, and the Kindle
  just shows the last image when it is off.

Anything that is powered on, on the same network as the Kindle, and can run
`python3` will do. (No always on machine at all? You can render on a cheap cloud
VPS and have the Kindle fetch over the internet, but then your calendar token
lives in the cloud and you are exposing an endpoint. A small Pi on your own wifi
is simpler and more private.)

Plus a jailbroken Kindle (this targets the Kindle 4, but other KOReader devices
work with tweaks) and, optionally, a Google Calendar.

### No homelab? That is fine

The only homelab specific feature is the **server health line** (CPU temp, load,
container count), which connects to a host over SSH. If you do not have one, just
leave `KD_PROXMOX` blank and that row falls back gracefully. The panel still
shows clock, weather, and calendar, which needs zero homelab. (Or open
`render.py` and remove the `get_homelab()` call in `draw_combo()` to drop the row
entirely.)

## What is here

| File | Runs on | What it does |
|---|---|---|
| `render.py` | server | Renders 800×600 grayscale PNGs (dashboard plus agenda, optional dithered photo). |
| `render.sh` | server | Loads `config.env`, runs `render.py --mode pages`. |
| `deploy/*.service`, `*.timer` | server | systemd units: an HTTP server on port 8137 plus a render timer. |
| `kindledash.koplugin/` | Kindle | KOReader plugin: fetches pages, full screen display, button nav, auto refresh, keeps the device awake. |
| `deploy-plugin.sh` | your computer | Pushes the plugin to the Kindle over SSH. |
| `config.env.example` | | Copy to `config.env` and fill in. Holds your private calendar URL (gitignored). |

## Configuration

All of your settings, including the calendar link and the optional homelab info,
go in one file: **`config.env`**. Copy the example and edit it:

```bash
cp config.env.example config.env
```

Then open `config.env` and fill in the values:

```bash
export KD_LAT=40.71                 # your latitude (for weather)
export KD_LON=-74.0                 # your longitude
export KD_CITY="Your City"          # label shown on the panel
export KD_PROXMOX=root@192.168.1.10 # OPTIONAL: host for server stats; leave blank if none
export KD_ICS="https://calendar.google.com/calendar/ical/.../private-XXXX/basic.ics"
```

**Where do the values come from?**

* **Weather** (`KD_LAT`, `KD_LON`, `KD_CITY`): look up your latitude and
  longitude (right click your spot in Google Maps, or search "my coordinates").
  No API key is needed.
* **Calendar** (`KD_ICS`): in Google Calendar, go to **Settings**, pick your
  calendar, scroll to **Integrate calendar**, and copy the **"Secret address in
  iCal format"**. It is a long URL ending in `/basic.ics`. Paste that as
  `KD_ICS`. (Keep it private. Anyone with this URL can read that calendar.)
* **Server health** (`KD_PROXMOX`): only if you have a homelab. Set it to the
  SSH target whose CPU temp and load you want shown, for example
  `root@192.168.1.10`. The machine running the renderer must be able to SSH there
  without a password (key based). If you have no homelab, leave this blank.

`config.env` is listed in `.gitignore` so your calendar token never gets
committed.

## Setup

### 1. Server

```bash
cp config.env.example config.env   # then edit it (see Configuration above)
pip install pillow
./render.sh                         # writes pages/page0.png ...
```

Install the systemd units (adjust the paths inside them to where you put the
repo and your `pages/` folder):

```bash
sudo cp deploy/*.service deploy/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now kindle-dash-http.service kindle-dash-render.timer
```

The PNGs are now served at `http://YOUR_SERVER_IP:8137/`.

### 2. Kindle

Requires a jailbroken Kindle running KOReader. Set the server address in
`kindledash.koplugin/main.lua` (`BASE = "http://YOUR_SERVER_IP:8137"`), then copy
the `kindledash.koplugin/` folder into the Kindle's `koreader/plugins/`
directory.

Easiest install: connect the Kindle by USB, let it mount as a drive, and copy the
folder to `<KINDLE>/koreader/plugins/kindledash.koplugin/`. Eject, then fully quit
and reopen KOReader (a cold start is required to load new plugins).

Open it from KOReader: **Tools, then Homelab dashboard**.

## Controls

* **Side page turn buttons** flip between the dashboard and agenda pages.
* **Back** or **Home** exits.

## Refresh rate

Both sides default to 30 seconds (`OnUnitActiveSec=30s` in the timer,
`REFRESH_SEC = 30` in `main.lua`). Worst case lag is the server interval plus the
device pull, roughly 30 to 60 seconds. Each refresh does a full e-ink flash, so
going much below 30 seconds is not worth it.

## Notes and gotchas

These cost me an evening, so here they are to save you the trouble:

* **ImageWidget caches by filename, not modified time.** Re-downloading
  `page0.png` with the same name shows the stale cached bitmap, so the clock
  appears frozen. The fix is `ImageWidget:new{ file = ..., file_do_cache =
  false }`.
* **KOReader key bindings need the exact nested form**: a triple nested keydef
  plus an explicit `event=`, for example
  `{ { { "RPgFwd","LPgFwd","Right" } }, event = "DashNext" }`. Get it wrong and
  nothing binds, not even exit, which traps the UI. (Hold power about 30 seconds
  to reboot out.)
* **The device sleeps when idle**, which drops wifi. The plugin calls
  `UIManager:preventStandby()` while open. You may also want to disable auto
  suspend and standby in KOReader's settings for true always on use.
* **Wall charger versus computer.** Plug into a dumb USB wall charger and it just
  charges, so wifi stays on and the panel keeps running. Plugging into a computer
  can trigger USB Drive Mode, which drops wifi.
* **Keep secrets out of git.** Your calendar URL contains a private token. It
  lives in `config.env`, which is gitignored.

## Photo mode

`render.py --mode photo` dithers an image (Floyd Steinberg) for e-ink. Point
`KD_PHOTO_DIR` at a folder and enable the photo page in `render_pages()` for a
photo frame rotation. Off by default.

## License

MIT
