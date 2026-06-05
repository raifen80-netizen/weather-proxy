from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

API_KEY = "ТВОЙ_OPENWEATHERMAP_KEY"

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
        "lang": "en"
    }

    r = requests.get(url, params=params)

    return jsonify(r.json())


@app.route("/forecast")
def forecast():
    lat = request.args.get("lat")
    lon = request.args.get("lon")

    url = "https://api.openweathermap.org/data/2.5/forecast"

    params = {
        "lat": lat,
        "lon": lon,
        "appid": API_KEY,
        "units": "metric",
        "lang": "en"
    }

    r = requests.get(url, params=params)

    return jsonify(r.json())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
