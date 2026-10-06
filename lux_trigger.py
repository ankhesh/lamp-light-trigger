"""
Outdoor-light lamp trigger for Alexa — no hardware needed.

Every run (started every 5 minutes by cron-job.org):
  1. Pulls modeled solar radiation (W/m²) for your location from Open-Meteo
     (free, no API key, 15-minute resolution for the US).
  2. When a NEW 15-minute reading shows the light just dropped below your
     "dark" threshold, calls a Voice Monkey URL once, which triggers an
     Alexa routine that turns your lamps on.

Rough conversion: 1 W/m² of sunlight ≈ 120 lux.
  32 W/m²  ≈  3,800 lux outdoors  -> indoors is getting dim

Settings come from environment variables (GitHub Secrets):
  LIGHTS_ON_URL   - Voice Monkey trigger URL for the "lamps on" routine
  LIGHTS_OFF_URL  - optional, for a "lamps off" routine in the morning
"""

import os
import sys
import json
import time
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

# ---------- TUNE THESE ----------
LATITUDE = 40.7831      # Manhattan — change to your exact spot
LONGITUDE = -73.9712
DARK_WM2 = 29.0         # lamps ON when radiation drops below this
BRIGHT_WM2 = 60.0       # lamps OFF when radiation rises above this
TZ = "America/New_York"
# Only act on a reading if it is this fresh. Runs are 5 min apart, so exactly
# one run sees each new 15-min reading as "fresh" -> one trigger per crossing.
FRESH_MINUTES = 5
# --------------------------------

# Some services (Voice Monkey among them) reject Python's default
# "Python-urllib" user agent with 403 Forbidden, so we send a normal one.
HEADERS = {"User-Agent": "Mozilla/5.0 (lamp-light-trigger; +github.com/ankhesh)"}

API = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={LATITUDE}&longitude={LONGITUDE}"
    "&minutely_15=shortwave_radiation"
    "&past_minutely_15=8&forecast_minutely_15=1"
    f"&timezone={TZ.replace('/', '%2F')}"
)


def fetch(url: str, attempts: int = 3) -> bytes | None:
    """GET a URL with retries. Returns the body, or None if every attempt failed."""
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read()
        except Exception as e:
            print(f"  attempt {i + 1} failed: {e!r}")
            if i < attempts - 1:
                time.sleep(5)
    return None


def trigger(url_env: str, label: str) -> None:
    url = (os.environ.get(url_env) or "").strip()   # strip stray spaces/newlines
    if not url:
        print(f"{label}: no {url_env} set, skipping")
        return
    print(f"{label}: calling Voice Monkey...")
    if fetch(url) is None:
        # Fail loudly: this is the part that actually matters
        sys.exit(f"{label}: Voice Monkey call FAILED after retries")
    print(f"{label}: triggered")


def main() -> None:
    body = fetch(API)
    if body is None:
        print("No weather data this run — skipping (will retry in 5 min)")
        return
    data = json.loads(body.decode()).get("minutely_15") or {}

    now = datetime.now(ZoneInfo(TZ)).replace(tzinfo=None)

    # Keep only intervals that have already happened
    readings = [
        (datetime.fromisoformat(t), v)
        for t, v in zip(data.get("time", []), data.get("shortwave_radiation", []))
        if v is not None and datetime.fromisoformat(t) <= now
    ]
    if len(readings) < 2:
        print(f"Only {len(readings)} readings returned — skipping this run")
        return

    (current_time, current), (_, previous) = readings[-1], readings[-2]
    age_min = (now - current_time).total_seconds() / 60
    print(f"{current_time:%H:%M}  radiation={current:.0f} W/m² "
          f"(~{current * 120:,.0f} lux)  previous={previous:.0f}  "
          f"reading age={age_min:.1f} min")

    if age_min >= FRESH_MINUTES:
        print("Reading already handled by an earlier run — nothing to do")
        return

    # Just got dark: this reading is below DARK, the one before was not
    if current < DARK_WM2 <= previous:
        trigger("LIGHTS_ON_URL", "Lamps ON")

    # Just got bright: this reading is above BRIGHT, the one before was not
    elif previous <= BRIGHT_WM2 < current:
        trigger("LIGHTS_OFF_URL", "Lamps OFF")

    else:
        print("No crossing — nothing to do")


if __name__ == "__main__":
    main()
