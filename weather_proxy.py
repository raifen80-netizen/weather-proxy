from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

# 🔐 API KEY берётся из Render Environment Variables
OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY")


# -----------------------------
# 1. GEO POSITION SEARCH (HTC)
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
        "Country": {
            "ID": data.get("sys", {}).get("country", "")
        },
        "GeoPosition": {
            "Latitude": float(lat),
            "Longitude": float(lon)
        }
    })


# -----------------------------
# 2. CURRENT CONDITIONS (HTC SAFE)
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
            "WeatherIcon": 1,
            "HasPrecipitation": False,
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
# 3. FORECAST (5 DAY SIMPLE)
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

        daily = []
        for i in range(0, min(5, len(data.get("list", [])))):
            item = data["list"][i]

            daily.append({
                "Date": item.get("dt_txt", ""),
                "Temperature": {
                    "Maximum": {"Value": item["main"].get("temp_max", 0)},
                    "Minimum": {"Value": item["main"].get("temp_min", 0)}
                },
                "Day": {
                    "Icon": 1,
                    "IconPhrase": (item.get("weather") or [{}])[0].get("main", "")
                }
            })

        return jsonify({
            "DailyForecasts": daily
        })

    except Exception as e:
        print("FORECAST ERROR:", e)

        return jsonify({
            "DailyForecasts": []
        })


# -----------------------------
# HEALTH CHECK
# -----------------------------
@app.route("/")
def home():
    return "HTC Weather Proxy Running"


# -----------------------------
# START
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
