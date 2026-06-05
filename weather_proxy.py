from flask import Flask, request, jsonify
import requests
import os
from datetime import datetime

app = Flask(__name__)

API_KEY = os.environ.get("OPENWEATHER_API_KEY")


# =========================
# HELP: OpenWeather fetch
# =========================
def get_weather(lat, lon):
    url = "https://api.openweathermap.org/data/2.5/weather"
    return requests.get(url, params={
        "lat": lat,
        "lon": lon,
        "appid": API_KEY,
        "units": "metric",
        "lang": "ru"
    }).json()


# =========================
# 1. LOCATION SEARCH (HTC)
# =========================
@app.route("/locations/v1/cities/geoposition/search")
def geo_search():
    q = request.args.get("q", "0,0")
    lat, lon = q.split(",")

    return jsonify({
        "Key": f"{lat}_{lon}",
        "Type": "City",
        "LocalizedName": "Fastiv",
        "Country": {"ID": "UA"},
        "GeoPosition": {
            "Latitude": float(lat),
            "Longitude": float(lon)
        }
    })


# =========================
# 2. CURRENT CONDITIONS
# =========================
@app.route("/currentconditions/v1/<location_key>")
def current(location_key):
    lat, lon = location_key.split("_")
    data = get_weather(lat, lon)

    return jsonify([{
        "LocalObservationDateTime": datetime.utcnow().isoformat() + "Z",
        "EpochTime": int(datetime.utcnow().timestamp()),

        "WeatherText": data["weather"][0]["description"],
        "WeatherIcon": 7,  # можно улучшить позже mapping

        "HasPrecipitation": "rain" in data["weather"][0]["main"].lower(),

        "Temperature": {
            "Metric": {
                "Value": round(data["main"]["temp"], 1),
                "Unit": "C"
            }
        },

        "RealFeelTemperature": {
            "Metric": {
                "Value": round(data["main"]["feels_like"], 1),
                "Unit": "C"
            }
        },

        "RelativeHumidity": data["main"]["humidity"],

        "Wind": {
            "Speed": {
                "Metric": {
                    "Value": data["wind"]["speed"],
                    "Unit": "m/s"
                }
            }
        }
    }])


# =========================
# 3. 5-DAY FORECAST (HTC style)
# =========================
@app.route("/forecasts/v1/daily/5day/<location_key>")
def forecast(location_key):
    lat, lon = location_key.split("_")

    data = get_weather(lat, lon)
    temp = data["main"]["temp"]

    # простая эмуляция (HTC важно наличие структуры)
    days = []

    for i in range(5):
        days.append({
            "Date": datetime.utcnow().isoformat() + "Z",
            "EpochDate": int(datetime.utcnow().timestamp()),

            "Temperature": {
                "Minimum": {"Value": temp - 3 - i},
                "Maximum": {"Value": temp + 2 + i}
            },

            "Day": {
                "Icon": 7,
                "IconPhrase": data["weather"][0]["description"]
            },

            "Night": {
                "Icon": 33,
                "IconPhrase": "clear"
            }
        })

    return jsonify({
        "Headline": {
            "Text": "Forecast",
            "Category": "weather"
        },
        "DailyForecasts": days
    })


# =========================
# HEALTH CHECK
# =========================
@app.route("/")
def home():
    return "HTC Weather Emulator FULL RUNNING"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
