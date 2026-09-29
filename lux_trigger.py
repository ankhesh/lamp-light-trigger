"""
Outdoor-light lamp trigger for Alexa — no hardware needed.

Every run:
  1. Pulls modeled solar radiation (W/m²) for your location from Open-Meteo
     (free, no API key, 15-minute resolution for the US).
  2. Checks whether it just crossed your "dark" or "bright" threshold.
  3. If so, calls a Voice Monkey URL, which triggers an Alexa routine
     that turns your lamps on (or off).

Rough conversion: 1 W/m² of sunlight ≈ 120 lux.
  25 W/m²  ≈  3,000 lux outdoors  -> indoors is getting dim
  60 W/m²  ≈  7,000 lux outdoors  -> clearly daytime again

Settings come from environment variables (GitHub Secrets):
  LIGHTS_ON_URL   - Voice Monkey trigger URL for the "lamps on" routine
  LIGHTS_OFF_URL  - optional, for a "lamps off" routine in the morning
"""

import os
import sys
import json
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

# ---------- TUNE THESE ----------
LATITUDE = 40.7831      # Manhattan — change to your exact spot
LONGITUDE = -73.9712
DARK_WM2 = 32.0         # lamps ON when radiation drops below this
BRIGHT_WM2 = 60.0       # lamps OFF when radiation rises above this
LOOKBACK = 4            # how many 15-min intervals back to look for a crossing
TZ = "America/New_York"
# --------------------------------

API = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={LATITUDE}&longitude={LONGITUDE}"
    "&minutely_15=shortwave_radiation"
    "&past_minutely_15=8&forecast_minutely_15=1"
    f"&timezone={TZ.replace('/', '%2F')}"
)


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.loads(r.read().decode())


def trigger(url_env: str, label: str) -> None:
    url = os.environ.get(url_env)
    if not url:
        print(f"{label}: no {url_env} set, skipping")
        return
    with urllib.request.urlopen(url, timeout=20) as r:
        print(f"{label}: triggered (HTTP {r.status})")


def main() -> None:
    data = get_json(API)["minutely_15"]
    now = datetime.now(ZoneInfo(TZ)).replace(tzinfo=None)

    # Keep only intervals that have already happened
    readings = [
        (datetime.fromisoformat(t), v)
        for t, v in zip(data["time"], data["shortwave_radiation"])
        if v is not None and datetime.fromisoformat(t) <= now
    ]
    if len(readings) < LOOKBACK + 1:
        sys.exit("Not enough data returned")

    current_time, current = readings[-1]
    earlier = [v for _, v in readings[-(LOOKBACK + 1):-1]]
    print(f"{current_time:%H:%M}  radiation={current:.0f} W/m² "
          f"(~{current * 120:,.0f} lux)  earlier={earlier}")

    # Just got dark: now below DARK, recently above it
    if current < DARK_WM2 and any(v >= DARK_WM2 for v in earlier):
        trigger("LIGHTS_ON_URL", "Lamps ON")

    # Just got bright: now above BRIGHT, recently below it
    elif current > BRIGHT_WM2 and any(v <= BRIGHT_WM2 for v in earlier):
        trigger("LIGHTS_OFF_URL", "Lamps OFF")

    else:
        print("No crossing — nothing to do")


if __name__ == "__main__":
    main()
