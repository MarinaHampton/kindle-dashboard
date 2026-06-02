#!/bin/bash
set -a; . /opt/kindle-dash/config.env; set +a
cd /opt/kindle-dash
python3 render.py --mode pages --outdir pages >/dev/null 2>>/opt/kindle-dash/render.log
