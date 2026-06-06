from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# =========================
# CONFIG
# =========================

OPENWEATHER_KEY = "PUT_YOUR_OPENWEATHER_KEY_HERE"

# =========================
# HELPERS
# =========================

def owm_geocode(lat, lon):
    url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={OPENWEATHER_KEY}&units=metric"
    r = requests.get(url, timeout=10)
    data = r.json()

    return {
        "Key": f"{lat},{lon}",
        "LocalizedName": data.get("name", "Unknown"),
        "Country": data.get("sys", {}).get("country", "")
    }


def owm_current(lat, lon):
    url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={OPENWEATHER_KEY}&units=metric"
    r = requests.get(url, timeout=10)
    data = r.json()

    weather = data.get("weather", [{}])[0]

    return [{
        "WeatherText": weather.get("main", "Clear"),
        "WeatherIcon": 1,
        "Temperature": {
            "Metric": {
                "Value": data.get("main", {}).get("temp", 20)
            }
        }
    }]


def owm_forecast(lat, lon):
    url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={OPENWEATHER_KEY}&units=metric"
    r = requests.get(url, timeout=10)
    data = r.json()

    daily = {}

    for item in data.get("list", []):
        date = item["dt_txt"].split(" ")[0]
        temp = item["main"]["temp"]
        weather = item["weather"][0]["main"]

        if date not in daily:
            daily[date] = {
                "min": temp,
                "max": temp,
                "text": weather
            }
        else:
            daily[date]["min"] = min(daily[date]["min"], temp)
            daily[date]["max"] = max(daily[date]["max"], temp)

    forecasts = []

    for i, (date, v) in enumerate(list(daily.items())[:5]):
        forecasts.append({
            "Date": date,
            "Day": {
                "Icon": 1,
                "IconPhrase": v["text"]
            },
            "Temperature": {
                "Minimum": {"Value": v["min"]},
                "Maximum": {"Value": v["max"]}
            }
        })

    return {"DailyForecasts": forecasts}


# =========================
# HTC ENDPOINTS
# =========================

@app.route("/locations/v1/cities/geoposition/search")
def geoposition_search():
    q = request.args.get("q", "0,0")

    try:
        lat, lon = q.split(",")
    except:
        lat, lon = "0", "0"

    return jsonify([owm_geocode(lat, lon)])


@app.route("/currentconditions/v1/<key>")
def current_conditions(key):
    try:
        lat, lon = key.split(",")
    except:
        lat, lon = "0", "0"

    return jsonify(owm_current(lat, lon))


@app.route("/forecasts/v1/daily/5day/<key>")
def forecast(key):
    try:
        lat, lon = key.split(",")
    except:
        lat, lon = "0", "0"

    return jsonify(owm_forecast(lat, lon))


# =========================
# HEALTH CHECK
# =========================

@app.route("/")
def index():
    return "HTC Weather Proxy OK"


# =========================
# RUN
# =========================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
