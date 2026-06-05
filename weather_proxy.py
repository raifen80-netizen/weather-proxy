from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY")


# -----------------------------
# HTC ICON MAPPING
# -----------------------------
def htc_icon(weather_main: str) -> int:
    w = (weather_main or "").lower()

    if "clear" in w:
        return 1
    if "cloud" in w:
        return 3
    if "rain" in w or "drizzle" in w:
        return 12
    if "thunder" in w:
        return 15
    if "snow" in w:
        return 16
    if "mist" in w or "fog" in w or "haze" in w:
        return 7

    return 1


# -----------------------------
# ROOT
# -----------------------------
@app.route("/")
def home():
    return "HTC Weather Proxy Running"


# -----------------------------
# GEO SEARCH
# -----------------------------
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


# -----------------------------
# CURRENT CONDITIONS
# -----------------------------
@app.route("/currentconditions/v1/<location_key>")
def current_conditions(location_key):
    try:
        lat = request.args.get("lat", "50")
        lon = request.args.get("lon", "30")

        url = (
            "https://api.openweathermap.org/data/2.5/weather"
            f"?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric"
        )

        data = requests.get(url, timeout=5).json()

        weather = (data.get("weather") or [{}])[0]
        main = data.get("main") or {}
        wind = data.get("wind") or {}

        return jsonify([{
            "WeatherText": weather.get("main", "Unknown"),
            "WeatherIcon": htc_icon(weather.get("main")),
            "HasPrecipitation": "rain" in (weather.get("main", "").lower()),
            "IsDayTime": True,
            "Temperature": {
                "Metric": {
                    "Value": main.get("temp", 0),
                    "Unit": "C"
                }
            },
            "RealFeelTemperature": {
                "Metric": {
                    "Value": main.get("feels_like", 0),
                    "Unit": "C"
                }
            },
            "RelativeHumidity": main.get("humidity", 0),
            "Wind": {
                "Speed": {
                    "Metric": {
                        "Value": wind.get("speed", 0),
                        "Unit": "km/h"
                    }
                }
            }
        }])

    except Exception as e:
        print("CURRENT ERROR:", e)

        return jsonify([{
            "WeatherText": "Unavailable",
            "WeatherIcon": 0,
            "HasPrecipitation": False,
            "IsDayTime": True,
            "Temperature": {"Metric": {"Value": 0}},
            "RealFeelTemperature": {"Metric": {"Value": 0}},
            "RelativeHumidity": 0,
            "Wind": {"Speed": {"Metric": {"Value": 0}}}
        }])


# -----------------------------
# FORECAST (HTC 5-DAY FIXED + ICONS)
# -----------------------------
@app.route("/forecasts/v1/daily/5day/<location_key>")
def forecast(location_key):
    try:
        lat = request.args.get("lat", "50")
        lon = request.args.get("lon", "30")

        url = (
            "https://api.openweathermap.org/data/2.5/forecast"
            f"?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric"
        )

        data = requests.get(url, timeout=5).json()

        days = {}

        for item in data.get("list", []):
            date = item["dt_txt"].split(" ")[0]

            if date not in days:
                days[date] = {
                    "max": -999,
                    "min": 999,
                    "phrase": ""
                }

            temp = item["main"]["temp"]
            days[date]["max"] = max(days[date]["max"], temp)
            days[date]["min"] = min(days[date]["min"], temp)

            weather = (item.get("weather") or [{}])[0]
            days[date]["phrase"] = weather.get("main", "")

        result = []

        for date, d in list(days.items())[:5]:
            result.append({
                "Date": date,
                "Temperature": {
                    "Maximum": {"Value": d["max"]},
                    "Minimum": {"Value": d["min"]}
                },
                "Day": {
                    "Icon": htc_icon(d["phrase"]),
                    "IconPhrase": d["phrase"]
                }
            })

        return jsonify({
            "DailyForecasts": result
        })

    except Exception as e:
        print("FORECAST ERROR:", e)

        return jsonify({
            "DailyForecasts": []
        })


# -----------------------------
# START
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
