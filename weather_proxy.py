from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

API_KEY = os.environ.get("OPENWEATHER_API_KEY")

@app.route("/weather")
def weather():
    lat = request.args.get("lat")
    lon = request.args.get("lon")

    if not lat or not lon:
        return jsonify({"error": "missing lat/lon"}), 400

    url = "https://api.openweathermap.org/data/2.5/weather"

    params = {
        "lat": lat,
        "lon": lon,
        "appid": API_KEY,
        "units": "metric",
        "lang": "ru"
    }

    r = requests.get(url, params=params)
    data = r.json()

    # защита от ошибки API
    if "cod" in data and data["cod"] != 200:
        return jsonify(data), 400

    return jsonify({
        "city": data.get("name"),
        "country": data["sys"]["country"],
        "lat": lat,
        "lon": lon,
        "temperature": data["main"]["temp"],
        "feels_like": data["main"]["feels_like"],
        "humidity": data["main"]["humidity"],
        "pressure": data["main"]["pressure"],
        "weather": data["weather"][0]["main"],
        "description": data["weather"][0]["description"],
        "icon": data["weather"][0]["icon"],
        "wind_speed": data["wind"]["speed"]
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
