"""Weather and traffic: how temperature (and rain) affects how many drinks sell each hour.

Hourly weather comes from Open-Meteo (open-meteo.com: free, no account or key). The shop sets
its location once on Settings; the server then keeps the last two weeks and the next two days
up to date, and can backfill older history to match older sales. Temperatures are stored in °C
and shown in the unit chosen on Settings.

The analysis lines up drinks sold in each open hour with that hour's temperature:
  * average drinks by hour of the day (the daily rhythm),
  * how drinks change with temperature once the time of day is taken out: for every hour,
    compare drinks and temperature with that hour's usual level; the slope of one against the
    other is "extra drinks per hour per degree", and r says how consistent that is,
  * drinks per hour in temperature bands, and in rainy versus dry hours,
  * a forecast for today and tomorrow: each hour's usual drinks, adjusted by the slope for the
    forecast temperature.
"""

import json
import math
import random
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

from .store import Store, ValidationError

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
HOURLY = "temperature_2m,precipitation"
MIN_HOURS = 48          # fewer matched hours than this: not enough to say anything
RAIN_MM = 0.2           # an hour with at least this much rain counts as rainy
REFRESH_MINUTES = 60


def _get(url, params, timeout=20):
    """GET JSON. Tests replace this to avoid the network."""
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": "menu-inventory/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ValidationError(f"Couldn't reach the weather service ({e}). Check the server's internet connection.")


def settings(store: Store):
    st = store.data["settings"]
    st.setdefault("location", None)        # {"name", "lat", "lon", "timezone"}
    st.setdefault("temp_unit", "F")
    st.setdefault("open_hour", 7)
    st.setdefault("close_hour", 19)        # last hour that opens for business, e.g. 19 = 7-8pm
    store.data.setdefault("weather", {"source": "", "hours": {}, "fetched_at": ""})
    return st


def to_unit(c, unit):
    return None if c is None else (c * 9 / 5 + 32 if unit == "F" else c)


def per_degree(unit):
    """Size of one display degree in °C (slopes are stored per °C)."""
    return 5 / 9 if unit == "F" else 1.0


# ------------------------------------------------------------------ setup
def find_places(query):
    query = str(query or "").strip()
    if len(query) < 2:
        raise ValidationError("Type a town or city name")
    data = _get(GEOCODE_URL, {"name": query, "count": 6, "language": "en", "format": "json"})
    return [{"name": ", ".join(x for x in (r.get("name"), r.get("admin1"), r.get("country")) if x),
             "lat": r["latitude"], "lon": r["longitude"], "timezone": r.get("timezone", "auto")}
            for r in data.get("results") or []]


def update_settings(store: Store, payload):
    with store.lock:
        st = settings(store)
        if "location" in payload:
            loc = payload["location"]
            if loc:
                try:
                    lat, lon = float(loc["lat"]), float(loc["lon"])
                except (KeyError, TypeError, ValueError):
                    raise ValidationError("Location needs a latitude and longitude")
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    raise ValidationError("That isn't a valid latitude and longitude")
                new = {"name": str(loc.get("name") or f"{lat:.3f}, {lon:.3f}")[:80], "lat": lat, "lon": lon,
                       "timezone": str(loc.get("timezone") or "auto")[:60]}
                if st["location"] and (st["location"]["lat"], st["location"]["lon"]) != (lat, lon):
                    store.data["weather"] = {"source": "", "hours": {}, "fetched_at": ""}  # old place's weather
                st["location"] = new
            else:
                st["location"] = None
        if "temp_unit" in payload:
            if payload["temp_unit"] not in ("F", "C"):
                raise ValidationError("Temperature unit must be F or C")
            st["temp_unit"] = payload["temp_unit"]
        for key in ("open_hour", "close_hour"):
            if key in payload:
                try:
                    v = int(payload[key])
                except (TypeError, ValueError):
                    raise ValidationError("Opening hours must be whole hours (0-23)")
                if not 0 <= v <= 23:
                    raise ValidationError("Opening hours must be whole hours (0-23)")
                st[key] = v
        if st["open_hour"] > st["close_hour"]:
            raise ValidationError("Opening hour must be before the last hour of business")
        return st


# ---------------------------------------------------------------- fetching
def _store_hours(store, data, source):
    h = data.get("hourly") or {}
    times, temps, rain = h.get("time") or [], h.get("temperature_2m") or [], h.get("precipitation") or []
    w = store.data["weather"]
    if w.get("source") == "sample":  # real weather replaces the sample entirely
        w["hours"] = {}
    n = 0
    for i, t in enumerate(times):
        if i < len(temps) and temps[i] is not None:
            w["hours"][t[:13]] = {"t": round(temps[i], 1), "p": round(rain[i] or 0, 2) if i < len(rain) else 0}
            n += 1
    w["source"] = source
    w["fetched_at"] = datetime.now().isoformat(timespec="minutes")
    return n


def refresh(store: Store):
    """The last 14 days and the next 2, for the shop's location."""
    with store.lock:
        loc = settings(store)["location"]
    if not loc:
        raise ValidationError("Set the shop's location on Settings first")
    data = _get(FORECAST_URL, {"latitude": loc["lat"], "longitude": loc["lon"], "hourly": HOURLY,
                               "past_days": 14, "forecast_days": 2, "timezone": loc["timezone"] or "auto"})
    with store.lock:
        return _store_hours(store, data, "open-meteo")


def backfill(store: Store, start, end=None):
    """Older history (the archive lags a few days behind today)."""
    with store.lock:
        loc = settings(store)["location"]
    if not loc:
        raise ValidationError("Set the shop's location on Settings first")
    end = end or (date.today() - timedelta(days=2)).isoformat()
    if start > end:
        return 0
    data = _get(ARCHIVE_URL, {"latitude": loc["lat"], "longitude": loc["lon"], "hourly": HOURLY,
                              "start_date": start, "end_date": end, "timezone": loc["timezone"] or "auto"})
    with store.lock:
        return _store_hours(store, data, "open-meteo")


def sample_weather(store: Store, days_back=21, days_ahead=2, seed=11):
    """Made-up but plausible hourly weather for the demo shop (clearly labelled as sample)."""
    rng = random.Random(seed)
    settings(store)
    w = store.data["weather"] = {"source": "sample", "hours": {}, "fetched_at": ""}
    today = date.today()
    for d in range(-days_back, days_ahead + 1):
        day = today + timedelta(days=d)
        mean = 22 + rng.uniform(-6, 6)          # a run of warm and cool days around 22 °C (72 °F)
        rainy = rng.random() < 0.18
        for hour in range(24):
            t = mean + 6 * math.sin((hour - 9) / 24 * 2 * math.pi) + rng.uniform(-0.8, 0.8)
            p = round(rng.uniform(0.3, 2.5), 2) if rainy and 10 <= hour <= 17 and rng.random() < 0.6 else 0
            w["hours"][f"{day.isoformat()}T{hour:02d}"] = {"t": round(t - (2.5 if p else 0), 1), "p": p}
    return w


# ---------------------------------------------------------------- analysis
def hourly_traffic(store: Store, days=28):
    """[{date, hour, drinks, temp_c, rain}] for every open hour of every day that had sales."""
    st = settings(store)
    since = (date.today() - timedelta(days=days)).isoformat()
    today = date.today().isoformat()
    drinks, trading_days = {}, set()
    for s in store.data["sales"]:
        d = s["date"][:10]
        if not since <= d < today:  # whole days only: today isn't over
            continue
        trading_days.add(d)
        key = s["date"][:13]
        drinks[key] = drinks.get(key, 0) + s["qty"]
    hours = store.data["weather"]["hours"]
    rows = []
    for d in sorted(trading_days):
        for h in range(st["open_hour"], st["close_hour"] + 1):
            key = f"{d}T{h:02d}"
            w = hours.get(key)
            rows.append({"date": d, "hour": h, "drinks": drinks.get(key, 0),
                         "temp_c": w["t"] if w else None, "rain": (w["p"] if w else 0) >= RAIN_MM})
    return rows


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _fit(xs, ys):
    """Least-squares slope and Pearson r of ys on xs."""
    mx, my = _mean(xs), _mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0 or syy == 0:
        return 0.0, 0.0
    return sxy / sxx, sxy / math.sqrt(sxx * syy)


def analysis(store: Store, days=28):
    st = settings(store)
    unit = st["temp_unit"]
    rows = hourly_traffic(store, days)
    matched = [r for r in rows if r["temp_c"] is not None]
    w = store.data["weather"]
    out = {"unit": unit, "location": st["location"], "source": w.get("source", ""), "fetched_at": w.get("fetched_at", ""),
           "open_hour": st["open_hour"], "close_hour": st["close_hour"], "days": days,
           "hours_with_sales": len(rows), "hours_matched": len(matched), "enough": len(matched) >= MIN_HOURS}
    hours = list(range(st["open_hour"], st["close_hour"] + 1))
    by_hour = {h: [r for r in matched if r["hour"] == h] for h in hours}
    base = {h: _mean([r["drinks"] for r in by_hour[h]]) for h in hours}
    base_t = {h: _mean([r["temp_c"] for r in by_hour[h]]) for h in hours}
    out["by_hour"] = [{"hour": h, "drinks": round(base[h], 1), "temp": round(to_unit(base_t[h], unit), 1) if by_hour[h] else None,
                       "n": len(by_hour[h])} for h in hours]
    out["points"] = [{"date": r["date"], "hour": r["hour"], "drinks": r["drinks"], "temp": round(to_unit(r["temp_c"], unit), 1),
                      "rain": r["rain"]} for r in matched]
    if not out["enough"]:
        return out

    # temperature effect with the time of day taken out
    dt = [r["temp_c"] - base_t[r["hour"]] for r in matched]
    dd = [r["drinks"] - base[r["hour"]] for r in matched]
    slope_c, r_within = _fit(dt, dd)
    _, r_raw = _fit([r["temp_c"] for r in matched], [r["drinks"] for r in matched])
    slope_u = slope_c * per_degree(unit)
    out.update({"per_degree": round(slope_u, 3), "per_10": round(slope_u * 10, 2), "r": round(r_within, 2),
                "r_raw": round(r_raw, 2), "strength": strength(r_within)})

    # bands: 10 °F or 5 °C wide
    width = 10 if unit == "F" else 5
    bands = {}
    for r in matched:
        lo = math.floor(to_unit(r["temp_c"], unit) / width) * width
        bands.setdefault(lo, []).append(r["drinks"])
    out["bands"] = [{"from": lo, "to": lo + width, "drinks": round(_mean(v), 1), "n": len(v)}
                    for lo, v in sorted(bands.items()) if len(v) >= 3]

    rainy = [r["drinks"] - base[r["hour"]] for r in matched if r["rain"]]
    dry = [r["drinks"] - base[r["hour"]] for r in matched if not r["rain"]]
    out["rain"] = {"rainy_hours": len(rainy), "diff": round(_mean(rainy) - _mean(dry), 2) if len(rainy) >= 6 else None}

    # forecast: today (hours still to come) and tomorrow
    now = datetime.now()
    fc = []
    for d in (date.today(), date.today() + timedelta(days=1)):
        for h in hours:
            if d == date.today() and h <= now.hour:
                continue
            wx = w["hours"].get(f"{d.isoformat()}T{h:02d}")
            if not wx:
                continue
            pred = max(base[h] + slope_c * (wx["t"] - base_t[h]), 0)
            fc.append({"date": d.isoformat(), "hour": h, "temp": round(to_unit(wx["t"], unit), 1), "rain": wx["p"] >= RAIN_MM,
                       "drinks": round(pred, 1), "usual": round(base[h], 1)})
    out["forecast"] = fc
    tomorrow = [f for f in fc if f["date"] == (date.today() + timedelta(days=1)).isoformat()]
    if tomorrow:
        usual = sum(f["usual"] for f in tomorrow)
        total = sum(f["drinks"] for f in tomorrow)
        peak = max(tomorrow, key=lambda f: f["drinks"])
        out["tomorrow"] = {"drinks": round(total), "usual": round(usual), "change": round(total / usual - 1, 3) if usual else 0,
                           "peak_hour": peak["hour"], "peak_drinks": round(peak["drinks"]),
                           "high": max(f["temp"] for f in tomorrow)}
    return out


def strength(r):
    a = abs(r)
    return "strong" if a >= 0.5 else "moderate" if a >= 0.3 else "weak" if a >= 0.1 else "none"
