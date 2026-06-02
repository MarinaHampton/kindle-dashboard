#!/usr/bin/env python3
"""Kindle 4 e-ink dashboard renderer.

Produces an 800x600 grayscale PNG for a jailbroken Kindle 4 (mkk, 800x600,
16-level grayscale) to fetch over wifi and draw fullscreen with `eips`.

Two modes:
  combo  - clock + weather + homelab health + next calendar event
  photo  - a library photo, Floyd-Steinberg dithered for e-ink

Rotation is decided by the caller (see --mode / cron). Output is a single PNG.

Data is gathered live; every source degrades gracefully to a placeholder so a
single unreachable source never blanks the whole panel.
"""
import argparse
import datetime as dt
import json
import os
import random
import subprocess
import sys
import urllib.request

from PIL import Image, ImageDraw, ImageFont

W, H = 800, 600
BLACK, GREY, LGREY, WHITE = 0, 96, 176, 255

# ---- config (override via env / later a config file) ----
LAT = float(os.environ.get("KD_LAT", "40.71"))
LON = float(os.environ.get("KD_LON", "-74.0"))
CITY = os.environ.get("KD_CITY", "Home")
PROXMOX = os.environ.get("KD_PROXMOX", "root@192.168.1.10")
PHOTO_DIR = os.environ.get(
    "KD_PHOTO_DIR", "/path/to/photos"
)

# Cross-platform font lookup: macOS Arial (build host) or Linux DejaVu (the Linux server).
FONT_CANDIDATES = {
    "bold": [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ],
    "regular": [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ],
}
def font(weight, size):
    for path in FONT_CANDIDATES[weight]:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()

F_HUGE  = font("bold", 150)   # clock
F_BIG   = font("bold", 60)
F_MED   = font("bold", 34)
F_REG   = font("regular", 30)
F_SMALL = font("regular", 24)

def fit_text(d, text, fnt, max_w):
    """Truncate text with an ellipsis so it fits within max_w pixels."""
    if d.textlength(text, font=fnt) <= max_w:
        return text
    ell = "…"
    while text and d.textlength(text + ell, font=fnt) > max_w:
        text = text[:-1]
    return text.rstrip() + ell


WMO = {
    0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Fog", 51: "Drizzle", 53: "Drizzle", 55: "Drizzle",
    61: "Rain", 63: "Rain", 65: "Heavy rain", 71: "Snow", 73: "Snow",
    75: "Heavy snow", 80: "Showers", 81: "Showers", 82: "Showers",
    95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm",
}


def get_weather():
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}"
            "&current=temperature_2m,weather_code"
            "&daily=temperature_2m_max,temperature_2m_min"
            "&temperature_unit=fahrenheit&forecast_days=1&timezone=auto"
        )
        with urllib.request.urlopen(url, timeout=8) as r:
            d = json.load(r)
        cur = d["current"]
        day = d["daily"]
        return {
            "temp": round(cur["temperature_2m"]),
            "cond": WMO.get(cur["weather_code"], "n/a"),
            "hi": round(day["temperature_2m_max"][0]),
            "lo": round(day["temperature_2m_min"][0]),
        }
    except Exception as e:
        return {"temp": "--", "cond": f"(no weather)", "hi": "--", "lo": "--"}


def get_homelab():
    """SSH the Proxmox host for load, CPU temp, and container up-count."""
    cmd = (
        "uptime | sed 's/.*load average: //'; "
        "sensors 2>/dev/null | awk '/Tctl/{print $2}'; "
        "pct list 2>/dev/null | tail -n +2 | awk '{print $2}' | sort | uniq -c"
    )
    try:
        out = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=6", "-o", "BatchMode=yes", PROXMOX, cmd],
            capture_output=True, text=True, timeout=15,
        ).stdout.splitlines()
        load = out[0].split(",")[0].strip() if out else "?"
        temp = next((l for l in out if "°C" in l), "?").replace("+", "").strip()
        running = stopped = 0
        for l in out:
            l = l.strip()
            if l.endswith("running"):
                running = int(l.split()[0])
            elif l.endswith("stopped"):
                stopped = int(l.split()[0])
        return {"load": load, "temp": temp, "up": running, "down": stopped}
    except Exception:
        return {"load": "?", "temp": "?", "up": "?", "down": "?"}


def _load_ics(src):
    """Read an ICS from a URL or local file path, with line unfolding."""
    if src.startswith(("http://", "https://")):
        with urllib.request.urlopen(src, timeout=8) as r:
            raw = r.read().decode("utf-8", "replace")
    else:
        with open(os.path.expanduser(src), "r", encoding="utf-8",
                  errors="replace") as f:
            raw = f.read()
    # RFC5545 line unfolding: continuation lines begin with space/tab
    out = []
    for line in raw.splitlines():
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def _parse_dt(val):
    """Parse a DTSTART value: 20260602, 20260602T140000(Z)."""
    val = val.strip().rstrip("Z")
    try:
        if "T" in val:
            return dt.datetime.strptime(val[:15], "%Y%m%dT%H%M%S")
        return dt.datetime.strptime(val[:8], "%Y%m%d")
    except ValueError:
        return None


def get_events():
    """All upcoming events from KD_ICS, sorted soonest-first.

    Returns list of dicts: {start: datetime, summary: str, allday: bool}.
    Empty list on any failure or if unconfigured.
    """
    ics = os.environ.get("KD_ICS")
    if not ics:
        return []
    try:
        lines = _load_ics(ics)
        events, cur = [], {}
        for line in lines:
            key = line.split(":", 1)[0].split(";", 1)[0]
            if line.startswith("BEGIN:VEVENT"):
                cur = {}
            elif key == "DTSTART":
                raw = line.split(":", 1)[-1]
                cur["start"] = _parse_dt(raw)
                cur["allday"] = "VALUE=DATE" in line or "T" not in raw
            elif key == "SUMMARY":
                cur["summary"] = line.split(":", 1)[-1].strip().replace("\\,", ",")
            elif line.startswith("END:VEVENT") and cur.get("start"):
                cur.setdefault("summary", "(busy)")
                events.append(cur)
        today = dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        upcoming = [e for e in events if e["start"] >= today]
        upcoming.sort(key=lambda e: e["start"])
        return upcoming
    except Exception:
        return []


def get_next_event():
    """One-line summary of the soonest event, for the combo dashboard."""
    ics = os.environ.get("KD_ICS")
    if not ics:
        return "Calendar: (not configured)"
    ev = get_events()
    if not ev:
        return "No upcoming events"
    e = ev[0]
    stamp = e["start"].strftime("%a %b %-d") if e["allday"] else \
        e["start"].strftime("%a %-I:%M%p")
    return f"Next: {stamp} · {e['summary'][:42]}"


def draw_combo(path):
    img = Image.new("L", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    now = dt.datetime.now()

    # --- top: clock + date ---
    d.text((30, 10), now.strftime("%-I:%M"), font=F_HUGE, fill=BLACK)
    d.text((560, 60), now.strftime("%p"), font=F_BIG, fill=GREY)
    d.text((565, 130), now.strftime("%A"), font=F_MED, fill=BLACK)
    d.text((565, 172), now.strftime("%b %-d"), font=F_MED, fill=GREY)
    d.line((30, 215, W - 30, 215), fill=BLACK, width=3)

    # --- weather ---
    wx = get_weather()
    d.text((30, 235), f"{wx['temp']}°", font=F_BIG, fill=BLACK)
    d.text((180, 245), wx["cond"], font=F_MED, fill=BLACK)
    d.text((180, 290), f"H {wx['hi']}°   L {wx['lo']}°   {CITY}",
           font=F_SMALL, fill=GREY)
    d.line((30, 340, W - 30, 340), fill=BLACK, width=3)

    # --- homelab health ---
    hl = get_homelab()
    d.text((30, 360), "HOMELAB", font=F_SMALL, fill=GREY)
    rows = [
        ("CPU temp", hl["temp"]),
        ("Load", hl["load"]),
        ("Containers", f"{hl['up']} up / {hl['down']} down"),
    ]
    y = 392
    for label, val in rows:
        d.text((30, y), label, font=F_REG, fill=GREY)
        d.text((300, y), str(val), font=F_MED, fill=BLACK)
        y += 44
    d.line((30, 530, W - 30, 530), fill=BLACK, width=2)

    # --- next calendar event ---
    d.text((30, 548), fit_text(d, get_next_event(), F_REG, W - 60),
           font=F_REG, fill=BLACK)

    img.convert("L").save(path)
    return path


def draw_photo(path, src=None):
    if src is None:
        photos = []
        for root, _, files in os.walk(PHOTO_DIR):
            for f in files:
                if f.lower().endswith((".jpg", ".jpeg", ".png")):
                    photos.append(os.path.join(root, f))
            if len(photos) > 2000:
                break
        if not photos:
            return draw_combo(path)
        src = random.choice(photos)
    im = Image.open(src).convert("L")
    # fit within 800x600 preserving aspect, center on white
    im.thumbnail((W, H), Image.LANCZOS)
    canvas = Image.new("L", (W, H), WHITE)
    canvas.paste(im, ((W - im.width) // 2, (H - im.height) // 2))
    # Floyd-Steinberg dither to 1-bit then back to L for crisp e-ink
    dithered = canvas.convert("1").convert("L")
    dithered.save(path)
    return path


AGENDA_PER_PAGE = 9


def draw_agenda(path, page=0, events=None, per_page=AGENDA_PER_PAGE):
    """Render one page of the upcoming-events agenda. Page 0 = soonest."""
    if events is None:
        events = get_events()
    img = Image.new("L", (W, H), WHITE)
    d = ImageDraw.Draw(img)

    total_pages = max(1, (len(events) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    d.text((30, 14), "UPCOMING", font=F_MED, fill=BLACK)
    d.text((640, 26), f"{page + 1}/{total_pages}", font=F_SMALL, fill=GREY)
    d.line((30, 64, W - 30, 64), fill=BLACK, width=3)

    chunk = events[page * per_page:(page + 1) * per_page]
    if not chunk:
        d.text((30, 100), "No upcoming events", font=F_REG, fill=GREY)
        img.save(path)
        return path

    y = 78
    last_day = None
    for e in chunk:
        day = e["start"].strftime("%a %b %-d")
        if day != last_day:
            d.text((30, y), day, font=F_SMALL, fill=GREY)
            last_day = day
        time_s = "all-day" if e["allday"] else e["start"].strftime("%-I:%M%p")
        d.text((175, y), time_s, font=F_REG, fill=BLACK)
        d.text((300, y), fit_text(d, e["summary"], F_REG, (W - 24) - 300),
               font=F_REG, fill=BLACK)
        y += 56

    d.line((30, H - 34, W - 30, H - 34), fill=LGREY, width=1)
    nav = "< prev   |   next >" if total_pages > 1 else ""
    d.text((30, H - 28), nav, font=F_SMALL, fill=GREY)
    img.save(path)
    return path


def render_pages(outdir, photo=False):
    """Render the full page set the Kindle cycles through with page-turn keys.

    page0 = combo dashboard, page1..N = agenda. Returns list of paths.
    """
    os.makedirs(outdir, exist_ok=True)
    paths = [os.path.join(outdir, "page0.png")]
    draw_combo(paths[0])
    events = get_events()
    n_agenda = max(1, (len(events) + AGENDA_PER_PAGE - 1) // AGENDA_PER_PAGE)
    n_agenda = min(n_agenda, 4)  # cap pages we precache
    for i in range(n_agenda):
        p = os.path.join(outdir, f"page{i + 1}.png")
        draw_agenda(p, page=i, events=events)
        paths.append(p)
    if photo:
        p = os.path.join(outdir, f"page{len(paths)}.png")
        draw_photo(p)
        paths.append(p)
    # manifest the Kindle plugin reads to know page count + freshness
    with open(os.path.join(outdir, "index.json"), "w") as f:
        json.dump({
            "count": len(paths),
            "pages": [os.path.basename(p) for p in paths],
            "generated": dt.datetime.now().isoformat(timespec="seconds"),
        }, f)
    return paths


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["combo", "photo", "agenda", "pages"],
                    default="combo")
    ap.add_argument("--out", default="/tmp/kindle.png")
    ap.add_argument("--outdir", default="/tmp/kindle_pages")
    ap.add_argument("--page", type=int, default=0)
    ap.add_argument("--photo", help="specific photo path for --mode photo")
    ap.add_argument("--open", action="store_true", help="open result in Preview")
    a = ap.parse_args()
    if a.mode == "combo":
        draw_combo(a.out); outs = [a.out]
    elif a.mode == "photo":
        draw_photo(a.out, a.photo); outs = [a.out]
    elif a.mode == "agenda":
        draw_agenda(a.out, a.page); outs = [a.out]
    else:
        outs = render_pages(a.outdir)
    for o in outs:
        print(o)
    if a.open:
        subprocess.run(["open"] + outs)
