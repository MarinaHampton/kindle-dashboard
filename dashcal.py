#!/usr/bin/env python3
"""dashcal — add events to the Marina Green Kindle dashboard, easily.

Each `add` does two things:
  1. writes the event into a LOCAL ics feed (`--ics`, default /opt/kindle-dash/local_cal.ics)
     that the Marina Green renderer reads every cycle, so it shows on the Kindle in ~40s;
  2. writes a standalone `.ics` invite into `--invites` so you can add it to your own
     calendar / phone (double-click → Add to Calendar).

The canonical store is a JSON file next to the ics; the ics is regenerated from it on
every change, so add/list/rm always produce a valid calendar. Recurring events are
EXPANDED into individual occurrences in the feed (robust for any ICS reader); the
standalone invite uses a real RRULE (clean for Google/Apple Calendar).

Usage:
  dashcal.py add "Title" "2026-06-24 19:00" [--dur 45] [--label Homelab]
                 [--repeat daily|weekdays|weekly] [--count 14] [--desc "..."] [--loc "..."]
  dashcal.py list
  dashcal.py rm <uid-prefix|index>
  dashcal.py regen        # rebuild the ics from the json store

Stdlib only — runs anywhere with python3 (CT 114, the Mac, etc.).
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys

ICS_DEFAULT = os.environ.get("DASHCAL_ICS", "/opt/kindle-dash/local_cal.ics")
INVITES_DEFAULT = os.environ.get("DASHCAL_INVITES", "/opt/kindle-dash/invites")
PRODID = "-//H4M-PT0N homelab//dashcal//EN"
_REPEAT = {"daily": "DAILY", "weekly": "WEEKLY", "weekdays": "WEEKLY"}


def _store_path(ics):
    return os.path.splitext(ics)[0] + ".json"


def _load(ics):
    p = _store_path(ics)
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return []


def _save(ics, events):
    with open(_store_path(ics), "w") as f:
        json.dump(events, f, indent=2)
    _write_ics(ics, events)


def _fold(line):
    """RFC5545: fold lines >75 octets with CRLF + leading space."""
    out = line
    chunks = []
    while len(out.encode("utf-8")) > 73:
        # find a safe cut <=73 bytes
        cut = 73
        while len(out[:cut].encode("utf-8")) > 73:
            cut -= 1
        chunks.append(out[:cut])
        out = " " + out[cut:]
    chunks.append(out)
    return "\r\n".join(chunks)


def _esc(s):
    return (s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _dtfmt(s):
    """'2026-06-24 19:00' -> naive local '20260624T190000' (dashboard parses naive=local)."""
    d = dt.datetime.strptime(s, "%Y-%m-%d %H:%M")
    return d.strftime("%Y%m%dT%H%M%S"), d


def _occurrences(start_dt, repeat, count):
    if not repeat or repeat == "none":
        return [start_dt]
    out, d, made = [], start_dt, 0
    step = dt.timedelta(days=7) if repeat == "weekly" else dt.timedelta(days=1)
    while made < count:
        if repeat == "weekdays" and d.weekday() >= 5:
            d += dt.timedelta(days=1)
            continue
        out.append(d)
        d += step
        made += 1
    return out


def _vevent(uid, dtstamp, start_dt, dur_min, summary, desc, loc, rrule=None):
    end_dt = start_dt + dt.timedelta(minutes=dur_min)
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART:{start_dt.strftime('%Y%m%dT%H%M%S')}",
        f"DTEND:{end_dt.strftime('%Y%m%dT%H%M%S')}",
        f"SUMMARY:{_esc(summary)}",
    ]
    if rrule:
        lines.append(f"RRULE:{rrule}")
    if desc:
        lines.append(f"DESCRIPTION:{_esc(desc)}")
    if loc:
        lines.append(f"LOCATION:{_esc(loc)}")
    lines.append("END:VEVENT")
    return [_fold(x) for x in lines]


def _calendar(vevent_blocks, name="Marina dashboard"):
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}",
           "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{_esc(name)}"]
    for b in vevent_blocks:
        out.extend(b)
    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"


def _write_ics(ics, events):
    blocks = []
    for e in events:
        sd = dt.datetime.strptime(e["start"], "%Y%m%dT%H%M%S")
        for occ in _occurrences(sd, e.get("repeat"), e.get("count", 1)):
            uid = e["uid"] if e.get("repeat", "none") == "none" else \
                f"{occ.strftime('%Y%m%d')}-{e['uid']}"
            blocks.append(_vevent(uid, e["dtstamp"], occ, e["dur"],
                                  e["summary"], e.get("desc"), e.get("loc")))
    os.makedirs(os.path.dirname(ics) or ".", exist_ok=True)
    with open(ics, "w", newline="") as f:
        f.write(_calendar(blocks))


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "event"


def cmd_add(a):
    start_str, start_dt = _dtfmt(a.when)
    dtstamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    uid = hashlib.sha1(f"{a.title}{start_str}{dtstamp}".encode()).hexdigest()[:12] + "@dashcal"
    ev = {"uid": uid, "summary": a.title, "start": start_str, "dur": a.dur,
          "repeat": a.repeat, "count": a.count, "label": a.label,
          "desc": a.desc, "loc": a.loc, "dtstamp": dtstamp}
    events = _load(a.ics)
    events.append(ev)
    events.sort(key=lambda e: e["start"])
    _save(a.ics, events)

    # standalone invite (single VEVENT, real RRULE if recurring)
    rrule = None
    if a.repeat and a.repeat != "none":
        freq = _REPEAT[a.repeat]
        rrule = f"FREQ={freq};COUNT={a.count}"
        if a.repeat == "weekdays":
            rrule += ";BYDAY=MO,TU,WE,TH,FR"
    inv = _calendar([_vevent(uid, dtstamp, start_dt, a.dur, a.title, a.desc, a.loc, rrule)],
                    name=a.title)
    os.makedirs(a.invites, exist_ok=True)
    path = os.path.join(a.invites, f"{_slug(a.title)}.ics")
    with open(path, "w", newline="") as f:
        f.write(inv)
    rep = "" if a.repeat == "none" else f" (x{a.count} {a.repeat})"
    print(f"added: {a.title} @ {a.when}{rep}")
    print(f"  feed:   {a.ics}")
    print(f"  invite: {path}")


def cmd_list(a):
    events = _load(a.ics)
    if not events:
        print("(no events)")
        return
    for i, e in enumerate(events):
        sd = dt.datetime.strptime(e["start"], "%Y%m%dT%H%M%S")
        rep = "" if e.get("repeat", "none") == "none" else f"  [x{e.get('count')} {e['repeat']}]"
        print(f"{i:2}  {sd:%a %b %-d %-I:%M%p}  {e['summary']}{rep}  ({e['uid'][:8]})")


def cmd_rm(a):
    events = _load(a.ics)
    target = a.id
    kept = []
    removed = 0
    for i, e in enumerate(events):
        if str(i) == target or e["uid"].startswith(target):
            removed += 1
            continue
        kept.append(e)
    _save(a.ics, kept)
    print(f"removed {removed} event(s)")


def cmd_regen(a):
    _write_ics(a.ics, _load(a.ics))
    print(f"regenerated {a.ics} ({len(_load(a.ics))} events)")


def main():
    p = argparse.ArgumentParser(description="Add events to the Marina Green Kindle dashboard")
    p.add_argument("--ics", default=ICS_DEFAULT)
    p.add_argument("--invites", default=INVITES_DEFAULT)
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("add")
    pa.add_argument("title")
    pa.add_argument("when", help="'YYYY-MM-DD HH:MM' (local time)")
    pa.add_argument("--dur", type=int, default=45, help="minutes (default 45)")
    pa.add_argument("--label", default="Marina")
    pa.add_argument("--repeat", choices=["none", "daily", "weekdays", "weekly"], default="none")
    pa.add_argument("--count", type=int, default=14, help="occurrences if --repeat")
    pa.add_argument("--desc", default="")
    pa.add_argument("--loc", default="")
    pa.set_defaults(func=cmd_add)

    sub.add_parser("list").set_defaults(func=cmd_list)
    pr = sub.add_parser("rm")
    pr.add_argument("id", help="index or uid-prefix")
    pr.set_defaults(func=cmd_rm)
    sub.add_parser("regen").set_defaults(func=cmd_regen)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
