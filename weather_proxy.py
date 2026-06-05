from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

ACCU_KEY = "c93f47e94a7243e3a3eb028fdbb6fbc0"

# 🔍 поиск города (как AccuWeather search)
@app.route("/search")
def search():
    q = request.args.get("q", "")

    url = "http://dataservice.accuweather.com/locations/v1/cities/search"
    params = {
        "apikey": ACCU_KEY,
        "q": q,
        "language": "en-us"
    }

    r = requests.get(url, params=params)
    return jsonify(r.json())


# 🌡 текущая погода
@app.route("/weather")
def weather():
    loc = request.args.get("loc")

    url = f"http://dataservice.accuweather.com/currentconditions/v1/{loc}"
    params = {
        "apikey": ACCU_KEY,
        "language": "en-us",
        "details": "true"
    }

    r = requests.get(url, params=params)
    return jsonify(r.json())


# 🌦 прогноз 5 дней
@app.route("/forecast")
def forecast():
    loc = request.args.get("loc")

    url = f"http://dataservice.accuweather.com/forecasts/v1/daily/5day/{loc}"
    params = {
        "apikey": ACCU_KEY,
        "language": "en-us",
        "metric": "true"
    }

    r = requests.get(url, params=params)
    return jsonify(r.json())


# 🚀 запуск (локально, Render использует gunicorn)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
