from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

# =========================
# CONFIG
# =========================

OPENWEATHER_KEY = os.getenv("OPENWEATHER_API_KEY")
BASE_URL = "https://api.openweathermap.org/data/2.5"


# =========================
# SAFETY CHECK
# =========================

def owm_ok(data):
    return isinstance(data, dict) and str(data.get("cod")) == "200"


# =========================
# GEOCODE (HTC SEARCH)
# =========================

def geocode(lat, lon):
    url = f"{BASE_URL}/weather?lat={lat}&lon={lon}&appid={OPENWEATHER_KEY}&units=metric"
    r = requests.get(url, timeout=10)
    data = r.json()

    if not owm_ok(data):
        return {
            "Key": f"{lat},{lon}",
            "LocalizedName": "Kyiv",
            "Country": "UA"
        }

    return {
        "Key": f"{lat},{lon}",
        "LocalizedName": data.get("name") or "Kyiv",
        "Country": data.get("sys", {}).get("country") or "UA"
    }


# =========================
# CURRENT CONDITIONS
# =========================

def current_conditions(lat, lon):
    url = f"{BASE_URL}/weather?lat={lat}&lon={lon}&appid={OPENWEATHER_KEY}&units=metric"
    r = requests.get(url, timeout=10)
    data = r.json()

    if not owm_ok(data):
        return [{
            "WeatherText": "Clear",
            "WeatherIcon": 1,
            "Temperature": {
                "Metric": {"Value": 20}
            }
        }]

    weather = (data.get("weather") or [{}])[0]
    main = data.get("main", {})

    return [{
        "WeatherText": weather.get("main", "Clear"),
        "WeatherIcon": 1,
        "Temperature": {
            "Metric": {
                "Value": main.get("temp", 20)
            }
        }
    }]


# =========================
# FORECAST (5 DAY)
# =========================

def forecast(lat, lon):
    url = f"{BASE_URL}/forecast?lat={lat}&lon={lon}&appid={OPENWEATHER_KEY}&units=metric"
    r = requests.get(url, timeout=10)
    data = r.json()

    if not owm_ok(data):
        return {"DailyForecasts": []}

    daily = {}

    for item in data.get("list", []):
        date = item["dt_txt"].split(" ")[0]
        temp = item["main"]["temp"]
        text = item["weather"][0]["main"]

        if date not in daily:
            daily[date] = {
                "min": temp,
                "max": temp,
                "text": text
            }
        else:
            daily[date]["min"] = min(daily[date]["min"], temp)
            daily[date]["max"] = max(daily[date]["max"], temp)

    result = []

    for date, v in list(daily.items())[:5]:
        result.append({
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

    return {"DailyForecasts": result}


# =========================
# ENDPOINTS (HTC COMPATIBLE)
# =========================

@app.route("/")
def index():
    return "HTC Weather Proxy OK"


@app.route("/locations/v1/cities/geoposition/search")
def search():
    q = request.args.get("q", "0,0")

    try:
        lat, lon = q.split(",")
    except:
        lat, lon = "0", "0"

    return jsonify([geocode(lat, lon)])


@app.route("/currentconditions/v1/<key>")
def current(key):
    try:
        lat, lon = key.split(",")
    except:
        lat, lon = "0", "0"

    return jsonify(current_conditions(lat, lon))


@app.route("/forecasts/v1/daily/5day/<key>")
def daily(key):
    try:
        lat, lon = key.split(",")
    except:
        lat, lon = "0", "0"

    return jsonify(forecast(lat, lon))


# =========================
# RUN
# =========================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
