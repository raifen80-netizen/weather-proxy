from flask import Flask, request, jsonify
import requests
import os
import time

app = Flask(__name__)

OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY")


# =========================
# CACHE (ULTRA MODE)
# =========================
CACHE = {}
CACHE_TTL_CURRENT = 180
CACHE_TTL_FORECAST = 900


def cache_get(key):
    item = CACHE.get(key)
    if not item:
        return None

    data, ts, ttl = item
    if time.time() - ts < ttl:
        return data
    return None


def cache_set(key, data, ttl):
    CACHE[key] = (data, time.time(), ttl)


# =========================
# DAY / NIGHT LOGIC
# =========================
def is_daytime():
    h = time.localtime().tm_hour
    return 6 <= h <= 19


# =========================
# HTC ICON ENGINE (ULTIMATE)
# =========================
def htc_icon(main: str, description: str = "", is_day: bool = True, intensity: float = 0):
    t = f"{main or ''} {description or ''}".lower()

    # Clear
    if "clear" in t:
        return 1 if is_day else 33

    # Clouds
    if "few" in t:
        return 2 if is_day else 35
    if "scattered" in t:
        return 2
    if "broken" in t:
        return 4
    if "overcast" in t or "cloud" in t:
        return 3

    # Fog / mist
    if "mist" in t:
        return 6
    if "fog" in t:
        return 7
    if "haze" in t:
        return 8

    # Rain
    if "drizzle" in t:
        return 11
    if "rain" in t or "shower" in t:
        if intensity > 6:
            return 14
        elif intensity > 2:
            return 12
        else:
            return 11

    # Thunderstorm
    if "thunder" in t or "storm" in t:
        return 15

    # Snow
    if "snow" in t:
        if intensity > 5:
            return 19
        return 16

    return 1 if is_day else 33


# =========================
# ROOT
# =========================
@app.route("/")
def home():
    return "HTC Weather Proxy ULTRA Running"


# =========================
# GEO SEARCH (HTC STYLE)
# =========================
@app.route("/locations/v1/cities/geoposition/search")
def geoposition_search():
    q = request.args.get("q", "50,30")

    try:
        lat, lon = q.split(",")
    except:
        lat, lon = "50", "30"

    url = (
        "https://api.openweathermap.org/data/2.5/weather"
        f"?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric"
    )

    data = requests.get(url, timeout=5).json()

    return jsonify({
        "Key": str(data.get("id", 0)),
        "LocalizedName": data.get("name", "Unknown"),
        "Country": {"ID": data.get("sys", {}).get("country", "")},
        "GeoPosition": {
            "Latitude": float(lat),
            "Longitude": float(lon)
        }
    })


# =========================
# CURRENT CONDITIONS (ULTRA)
# =========================
@app.route("/currentconditions/v1/<location_key>")
def current_conditions(location_key):
    try:
        lat = request.args.get("lat", "50")
        lon = request.args.get("lon", "30")

        cache_key = f"current:{lat}:{lon}"
        cached = cache_get(cache_key)
        if cached:
            return jsonify(cached)

        url = (
            "https://api.openweathermap.org/data/2.5/weather"
            f"?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric"
        )

        data = requests.get(url, timeout=5).json()

        weather = (data.get("weather") or [{}])[0]
        main = data.get("main") or {}
        wind = data.get("wind") or {}

        is_day = is_daytime()

        response = [{
            "WeatherText": weather.get("main", "Unknown"),
            "WeatherIcon": htc_icon(
                weather.get("main"),
                weather.get("description"),
                is_day
            ),
            "IsDayTime": is_day,

            "Temperature": {
                "Metric": {
                    "Value": round(main.get("temp", 0), 1),
                    "Unit": "C"
                }
            },

            "RealFeelTemperature": {
                "Metric": {
                    "Value": round(main.get("feels_like", 0), 1),
                    "Unit": "C"
                }
            },

            "RelativeHumidity": main.get("humidity", 0),

            "Wind": {
                "Speed": {
                    "Metric": {
                        "Value": round(wind.get("speed", 0), 1),
                        "Unit": "km/h"
                    }
                }
            },

            "HasPrecipitation": "rain" in (weather.get("main","").lower())
        }]

        cache_set(cache_key, response, CACHE_TTL_CURRENT)
        return jsonify(response)

    except Exception as e:
        print("CURRENT ERROR:", e)

        return jsonify([{
            "WeatherText": "N/A",
            "WeatherIcon": 0,
            "IsDayTime": True,
            "Temperature": {"Metric": {"Value": 0}},
            "RealFeelTemperature": {"Metric": {"Value": 0}},
            "RelativeHumidity": 0,
            "Wind": {"Speed": {"Metric": {"Value": 0}}},
            "HasPrecipitation": False
        }])


# =========================
# FORECAST (ULTRA HTC STYLE)
# =========================
@app.route("/forecasts/v1/daily/5day/<location_key>")
def forecast(location_key):
    try:
        lat = request.args.get("lat", "50")
        lon = request.args.get("lon", "30")

        cache_key = f"forecast:{lat}:{lon}"
        cached = cache_get(cache_key)
        if cached:
            return jsonify(cached)

        url = (
            "https://api.openweathermap.org/data/2.5/forecast"
            f"?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric"
        )

        data = requests.get(url, timeout=5).json()

        days = {}

        for item in data.get("list", []):
            date = item["dt_txt"].split(" ")[0]

            main = item["main"]["temp"]
            weather = (item.get("weather") or [{}])[0]

            intensity = 0
            if "rain" in item:
                intensity = item["rain"].get("3h", 0)
            if "snow" in item:
                intensity = max(intensity, item["snow"].get("3h", 0))

            if date not in days:
                days[date] = {
                    "max": main,
                    "min": main,
                    "main": weather.get("main", ""),
                    "desc": weather.get("description", ""),
                    "intensity": intensity
                }

            days[date]["max"] = max(days[date]["max"], main)
            days[date]["min"] = min(days[date]["min"], main)

        result = []

        for date, d in list(days.items())[:5]:
            result.append({
                "Date": date,
                "EpochDate": int(time.time()),

                "Temperature": {
                    "Maximum": {"Value": round(d["max"], 1)},
                    "Minimum": {"Value": round(d["min"], 1)}
                },

                "Day": {
                    "Icon": htc_icon(
                        d["main"],
                        d["desc"],
                        is_daytime(),
                        d["intensity"]
                    ),
                    "IconPhrase": d["main"]
                }
            })

        response = {
            "Headline": {
                "Text": "HTC Ultra Forecast"
            },
            "DailyForecasts": result
        }

        cache_set(cache_key, response, CACHE_TTL_FORECAST)
        return jsonify(response)

    except Exception as e:
        print("FORECAST ERROR:", e)

        return jsonify({
            "DailyForecasts": []
        })


# =========================
# START
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
