from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

API_KEY = os.environ.get("OPENWEATHER_API_KEY")

# =========================
# 1. LOCATION SEARCH (HTC ищет город)
# =========================
@app.route("/locations/v1/cities/geoposition/search")
def location_search():
    lat = request.args.get("q", "").split(",")[0]
    lon = request.args.get("q", "").split(",")[1] if "," in request.args.get("q", "") else ""

    return jsonify({
        "Key": f"{lat}_{lon}",
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

    url = "https://api.openweathermap.org/data/2.5/weather"
    r = requests.get(url, params={
        "lat": lat,
        "lon": lon,
        "appid": API_KEY,
        "units": "metric",
        "lang": "ru"
    })

    data = r.json()

    return jsonify([{
        "LocalObservationDateTime": "2026-01-01T12:00:00+00:00",
        "WeatherText": data["weather"][0]["description"],
        "WeatherIcon": 7,
        "Temperature": {
            "Metric": {
                "Value": data["main"]["temp"]
            }
        },
        "RealFeelTemperature": {
            "Metric": {
                "Value": data["main"]["feels_like"]
            }
        },
        "RelativeHumidity": data["main"]["humidity"],
        "Wind": {
            "Speed": {
                "Metric": {
                    "Value": data["wind"]["speed"]
                }
            }
        }
    }])


# =========================
# 3. DAILY FORECAST (заглушка 1 день)
# =========================
@app.route("/forecasts/v1/daily/1day/<location_key>")
def forecast(location_key):
    lat, lon = location_key.split("_")

    url = "https://api.openweathermap.org/data/2.5/weather"
    data = requests.get(url, params={
        "lat": lat,
        "lon": lon,
        "appid": API_KEY,
        "units": "metric"
    }).json()

    temp = data["main"]["temp"]

    return jsonify({
        "DailyForecasts": [{
            "Temperature": {
                "Maximum": {"Value": temp + 2},
                "Minimum": {"Value": temp - 3}
            },
            "Day": {
                "Icon": 7,
                "IconPhrase": data["weather"][0]["description"]
            }
        }]
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
