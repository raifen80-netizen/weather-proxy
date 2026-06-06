from flask import Flask, jsonify, request
import requests
import os
import time

app = Flask(__name__)

# =========================
# CONFIG
# =========================

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
BASE_URL = "https://api.openweathermap.org/data/2.5"

# =========================
# CACHE (HTC style speed)
# =========================

CACHE = {}
CACHE_TTL = 300  # 5 minutes


# =========================
# HTC ICON MAPPING
# =========================

def get_icon(main):
    m = (main or "").lower()

    if "thunder" in m:
        return 15
    if "drizzle" in m or "rain" in m:
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
# SAFE REQUEST
# =========================

def safe_get(url):
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
# SAFE FALLBACK (CRITICAL HTC FIX)
# =========================

def safe_weather():
    return [{
        "WeatherText": "Clear",
        "WeatherIcon": 1,
        "Temperature": {
            "Metric": {
                "Value": 20
            }
        }
    }]


# =========================
# CURRENT CONDITIONS
# =========================

def get_current(lat, lon):
    def build():
        url = f"{BASE_URL}/weather?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric"
        data = safe_get(url)

        if str(data.get("cod")) != "200":
            return safe_weather()

        weather = (data.get("weather") or [{}])[0]
        main = data.get("main", {})

        temp = main.get("temp")
        if temp is None:
            temp = 20

        return [{
            "WeatherText": weather.get("main", "Clear"),
            "WeatherIcon": get_icon(weather.get("main")),
            "Temperature": {
                "Metric": {
                    "Value": temp
                }
            }
        }]

    return cached(f"cur:{lat},{lon}", build)


# =========================
# GEO LOCATION (HTC STYLE)
# =========================

def get_geo(lat, lon):
    def build():
        url = f"{BASE_URL}/weather?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric"
        data = safe_get(url)

        if str(data.get("cod")) != "200":
            return {
                "Key": f"{lat},{lon}",
                "LocalizedName": "Unknown",
                "Country": "UA"
            }

        return {
            "Key": f"{lat},{lon}",
            "LocalizedName": data.get("name") or "Unknown",
            "Country": data.get("sys", {}).get("country") or "UA"
        }

    return cached(f"geo:{lat},{lon}", build)


# =========================
# FORECAST (5 DAY HTC STYLE)
# =========================

def get_forecast(lat, lon):
    def build():
        url = f"{BASE_URL}/forecast?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric"
        data = safe_get(url)

        if str(data.get("cod")) != "200":
            return {"DailyForecasts": []}

        days = {}

        for item in data.get("list", []):
            date = item["dt_txt"].split(" ")[0]
            temp = item["main"]["temp"]
            text = item["weather"][0]["main"]

            if date not in days:
                days[date] = {
                    "min": temp,
                    "max": temp,
                    "text": text
                }
            else:
                days[date]["min"] = min(days[date]["min"], temp)
                days[date]["max"] = max(days[date]["max"], temp)

        result = []
        for date, v in list(days.items())[:5]:
            result.append({
                "Date": date,
                "Day": {
                    "Icon": get_icon(v["text"]),
                    "IconPhrase": v["text"]
                },
                "Temperature": {
                    "Minimum": {"Value": v["min"]},
                    "Maximum": {"Value": v["max"]}
                }
            })

        return {"DailyForecasts": result}

    return cached(f"fc:{lat},{lon}", build)


# =========================
# ENDPOINTS (HTC COMPATIBLE)
# =========================

@app.route("/")
def home():
    return "HTC Sense Weather Proxy Running"


@app.route("/locations/v1/cities/geoposition/search")
def search():
    q = request.args.get("q", "0,0")
    lat, lon = q.split(",")

    return jsonify([get_geo(lat, lon)])


@app.route("/currentconditions/v1/<key>")
def current(key):
    lat, lon = key.split(",")
    return jsonify(get_current(lat, lon))


@app.route("/forecasts/v1/daily/5day/<key>")
def forecast(key):
    lat, lon = key.split(",")
    return jsonify(get_forecast(lat, lon))


# =========================
# RUN SERVER
# =========================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
