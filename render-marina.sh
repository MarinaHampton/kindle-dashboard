#!/bin/bash
# Render the Marina Green Kindle feed: same family pages, but with the homelab
# watchdog enabled (KD_HEALTH=1) so a hot CPU / high load / downed container
# adds a full-screen "Homelab Alert" page that takes over the panel.
set -a; . /opt/kindle-dash/config.env; set +a
export KD_HEALTH=1
cd /opt/kindle-dash
python3 render_family.py --mode pages --outdir marina_pages >/dev/null 2>>/opt/kindle-dash/render-marina.log
