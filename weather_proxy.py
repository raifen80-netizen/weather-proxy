from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

OPENWEATHER_API_KEY = "YOUR_OPENWEATHER_KEY"

# -----------------------------
# 1. GEO SEARCH (HTC -> OpenWeather)
# -----------------------------
@app.route("/locations/v1/cities/geoposition/search")
def geoposition_search():
    q = request.args.get("q", "0,0")

    try:
        lat, lon = q.split(",")
    except:
        lat, lon = "0", "0"

    url = (
        "https://api.openweathermap.org/data/2.5/weather"
        f"?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric"
    )

    data = requests.get(url).json()

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
# 2. CURRENT CONDITIONS (HTC)
# -----------------------------
@app.route("/currentconditions/v1/<location_key>")
def current_conditions(location_key):
    lat = request.args.get("lat", "0")
    lon = request.args.get("lon", "0")

    url = (
        "https://api.openweathermap.org/data/2.5/weather"
        f"?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric"
    )

    data = requests.get(url).json()

    weather = data["weather"][0]

    return jsonify([{
        "WeatherText": weather["main"],
        "WeatherIcon": int(weather["icon"].replace("n", "").replace("d", "01") if weather["icon"].isdigit() else 1),
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
        },
        "UVIndex": 0
    }])


# -----------------------------
# 3. FORECAST (5 DAY SIMPLIFIED)
# -----------------------------
@app.route("/forecasts/v1/daily/5day/<location_key>")
def forecast(location_key):
    lat = request.args.get("lat", "0")
    lon = request.args.get("lon", "0")

    url = (
        "https://api.openweathermap.org/data/2.5/forecast"
        f"?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric"
    )

    data = requests.get(url).json()

    daily = []

    for i in range(0, min(len(data["list"]), 5)):
        item = data["list"][i]

        daily.append({
            "Date": item["dt_txt"],
            "Temperature": {
                "Maximum": {"Value": item["main"]["temp_max"]},
                "Minimum": {"Value": item["main"]["temp_min"]}
            },
            "Day": {
                "Icon": item["weather"][0]["icon"],
                "IconPhrase": item["weather"][0]["main"]
            }
        })

    return jsonify({
        "DailyForecasts": daily
    })


# -----------------------------
# START
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
