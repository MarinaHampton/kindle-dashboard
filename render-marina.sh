#!/bin/bash
# Render the Marina Green Kindle feed: same family pages, but with the homelab
# watchdog enabled (KD_HEALTH=1) so a hot CPU / high load / downed container
# adds a full-screen "Homelab Alert" page that takes over the panel.
set -a; . /opt/kindle-dash/config.env; set +a
export KD_HEALTH=1
# marina-only: merge the local dashcal feed (events added via dashcal.py) onto
# Marina Green ONLY (the family Kana render sources config.env without this line).
# `dashcal.py add ...` writes local_cal.ics; events appear here within one cycle.
export KD_ICS_FEEDS="${KD_ICS_FEEDS:+$KD_ICS_FEEDS;}Marina|/opt/kindle-dash/local_cal.ics"
cd /opt/kindle-dash
python3 render_family.py --mode pages --outdir marina_pages >/dev/null 2>>/opt/kindle-dash/render-marina.log
