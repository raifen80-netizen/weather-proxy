from flask import Flask, request, jsonify
import requests
import os
import time

app = Flask(__name__)

OPENWEATHER_KEY = os.getenv("OPENWEATHER_API_KEY")
BASE = "https://api.openweathermap.org/data/2.5"

# =========================
# CACHE (Sense-like speed)
# =========================

CACHE = {}
CACHE_TTL = 300  # 5 min


# =========================
# HTC ICON MAP (REALISTIC)
# =========================

def icon_map(main):
    m = (main or "").lower()

    if "thunder" in m:
        return 15
    if "drizzle" in m:
        return 11
    if "rain" in m:
        return 12
    if "snow" in m:
        return 22
    if "fog" in m or "mist" in m:
        return 20
    if "cloud" in m:
        return 7
    if "clear" in m or "sun" in m:
        return 1

    return 7


# =========================
# SAFE FETCH
# =========================

def get_json(url):
    try:
        r = requests.get(url, timeout=10)
        return r.json()
    except:
        return {}


# =========================
# CACHE WRAPPER
# =========================

def cached(key, fn):
    now = time.time()

    if key in CACHE:
        data, ts = CACHE[key]
        if now - ts < CACHE_TTL:
            return data

    data = fn()
    CACHE[key] = (data, now)
    return data


# =========================
# SAFE WEATHER STATE
# =========================

def safe_state():
    return [{
        "WeatherText": "Clear",
        "WeatherIcon": 1,
        "Temperature": {"Metric": {"Value": 20}}
    }]


# =========================
# CURRENT CONDITIONS (SENSE CORE)
# =========================

def current(lat, lon):
    def fetch():
        url = f"{BASE}/weather?lat={lat}&lon={lon}&appid={OPENWEATHER_KEY}&units=metric"
        d = get_json(url)

        if str(d.get("cod")) != "200":
            return safe_state()

        weather = (d.get("weather") or [{}])[0]
        main = d.get("main", {})

        temp = main.get("temp", 20)

        return [{
            "WeatherText": weather.get("main", "Clear"),
            "WeatherIcon": icon_map(weather.get("main")),
            "Temperature": {
                "Metric": {"Value": temp}
            }
        }]

    return cached(f"cur:{lat},{lon}", fetch)


# =========================
# GEO LOCATION (HTC STYLE)
# =========================

def geo(lat, lon):
    def fetch():
        url = f"{BASE}/weather?lat={lat}&lon={lon}&appid={OPENWEATHER_KEY}&units=metric"
        d = get_json(url)

        if str(d.get("cod")) != "200":
            return {
                "Key": f"{lat},{lon}",
                "LocalizedName": "Kyiv",
                "Country": "UA"
            }

        return {
            "Key": f"{lat},{lon}",
            "LocalizedName": d.get("name") or "Kyiv",
            "Country": d.get("sys", {}).get("country") or "UA"
        }

    return cached(f"geo:{lat},{lon}", fetch)


# =========================
# FORECAST (HTC STYLE 5 DAY)
# =========================

def forecast(lat, lon):
    def fetch():
        url = f"{BASE}/forecast?lat={lat}&lon={lon}&appid={OPENWEATHER_KEY}&units=metric"
        d = get_json(url)

        if str(d.get("cod")) != "200":
            return {"DailyForecasts": []}

        days = {}

        for i in d.get("list", []):
            date = i["dt_txt"].split(" ")[0]
            temp = i["main"]["temp"]
            txt = i["weather"][0]["main"]

            if date not in days:
                days[date] = {"min": temp, "max": temp, "txt": txt}
            else:
                days[date]["min"] = min(days[date]["min"], temp)
                days[date]["max"] = max(days[date]["max"], temp)

        out = []
        for date, v in list(days.items())[:5]:
            out.append({
                "Date": date,
                "Day": {
                    "Icon": icon_map(v["txt"]),
                    "IconPhrase": v["txt"]
                },
                "Temperature": {
                    "Minimum": {"Value": v["min"]},
                    "Maximum": {"Value": v["max"]}
                }
            })

        return {"DailyForecasts": out}

    return cached(f"fc:{lat},{lon}", fetch)


# =========================
# ENDPOINTS (HTC COMPATIBLE)
# =========================

@app.route("/")
def home():
    return "HTC Sense Weather Proxy OK"


@app.route("/locations/v1/cities/geoposition/search")
def search():
    q = request.args.get("q", "0,0")
    try:
        lat, lon = q.split(",")
    except:
        lat, lon = "0", "0"

    return jsonify([geo(lat, lon)])


@app.route("/currentconditions/v1/<key>")
def cur(key):
    lat, lon = key.split(",")
    return jsonify(current(lat, lon))


@app.route("/forecasts/v1/daily/5day/<key>")
def fc(key):
    lat, lon = key.split(",")
    return jsonify(forecast(lat, lon))


# =========================
# RUN
# =========================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
