from flask import Flask, request, jsonify, Response
import requests
import os
import time
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")

OWM_WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
OWM_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
OWM_DIRECT_URL = "https://api.openweathermap.org/geo/1.0/direct"
OWM_REVERSE_URL = "https://api.openweathermap.org/geo/1.0/reverse"

CACHE = {}
CACHE_TTL = 300


# =========================
# CACHE
# =========================

def cache_get(key):
    item = CACHE.get(key)
    if not item:
        return None

    data, ts = item
    if time.time() - ts < CACHE_TTL:
        return data

    return None


def cache_set(key, data):
    CACHE[key] = (data, time.time())


# =========================
# SAFE REQUEST
# =========================

def safe_get(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=10)
        return r.json()
    except Exception as e:
        print("REQUEST ERROR:", e)
        return {}


# =========================
# HELPERS
# =========================

def parse_key(location_key):
    try:
        lat, lon = location_key.split(",", 1)
        return lat.strip(), lon.strip()
    except Exception:
        return "50", "30"


def is_daytime_by_data(data):
    try:
        now = int(data.get("dt", time.time()))
        sys = data.get("sys", {})
        sunrise = int(sys.get("sunrise", 0))
        sunset = int(sys.get("sunset", 0))
        return sunrise <= now <= sunset
    except Exception:
        h = datetime.now().hour
        return 6 <= h <= 20


def htc_icon(weather_id=None, main="", is_day=True):
    try:
        wid = int(weather_id)
    except Exception:
        wid = 0

    m = (main or "").lower()

    # Thunderstorm
    if 200 <= wid < 300 or "thunder" in m or "storm" in m:
        return 15

    # Drizzle
    if 300 <= wid < 400 or "drizzle" in m:
        return 11

    # Rain
    if 500 <= wid < 600 or "rain" in m:
        return 12

    # Snow
    if 600 <= wid < 700 or "snow" in m:
        return 22

    # Atmosphere: mist, fog, haze
    if 700 <= wid < 800 or "fog" in m or "mist" in m or "haze" in m:
        return 20

    # Clear
    if wid == 800 or "clear" in m:
        return 1 if is_day else 33

    # Clouds
    if 801 <= wid <= 804 or "cloud" in m:
        return 7

    return 7


def accuweather_location_object(lat, lon, name="Unknown", country="UA"):
    key = f"{lat},{lon}"

    return {
        "Version": 1,
        "Key": key,
        "Type": "City",
        "Rank": 10,
        "LocalizedName": name or "Unknown",
        "EnglishName": name or "Unknown",
        "PrimaryPostalCode": "",
        "Region": {
            "ID": "EUR",
            "LocalizedName": "Europe",
            "EnglishName": "Europe"
        },
        "Country": {
            "ID": country or "UA",
            "LocalizedName": country or "UA",
            "EnglishName": country or "UA"
        },
        "AdministrativeArea": {
            "ID": "",
            "LocalizedName": "",
            "EnglishName": "",
            "Level": 1,
            "LocalizedType": "",
            "EnglishType": "",
            "CountryID": country or "UA"
        },
        "TimeZone": {
            "Code": "EET",
            "Name": "Europe/Kyiv",
            "GmtOffset": 2,
            "IsDaylightSaving": False,
            "NextOffsetChange": None
        },
        "GeoPosition": {
            "Latitude": float(lat),
            "Longitude": float(lon),
            "Elevation": {
                "Metric": {
                    "Value": 0,
                    "Unit": "m",
                    "UnitType": 5
                }
            }
        },
        "IsAlias": False,
        "SupplementalAdminAreas": [],
        "DataSets": [
            "AirQualityCurrentConditions",
            "Alerts",
            "DailyAirQualityForecast",
            "DailyPollenForecast",
            "ForecastConfidence"
        ]
    }


def get_location_by_coords(lat, lon):
    cache_key = f"geo:{lat},{lon}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    params = {
        "lat": lat,
        "lon": lon,
        "appid": OPENWEATHER_API_KEY,
        "units": "metric",
        "lang": "ru"
    }

    data = safe_get(OWM_WEATHER_URL, params)

    if str(data.get("cod")) == "200":
        name = data.get("name") or "Unknown"
        country = data.get("sys", {}).get("country") or "UA"
        result = accuweather_location_object(lat, lon, name, country)
    else:
        result = accuweather_location_object(lat, lon, "Kyiv", "UA")

    cache_set(cache_key, result)
    return result


def search_locations_by_text(query):
    cache_key = f"search:{query}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    params = {
        "q": query,
        "limit": 5,
        "appid": OPENWEATHER_API_KEY
    }

    data = safe_get(OWM_DIRECT_URL, params)

    result = []

    if isinstance(data, list) and data:
        for item in data:
            lat = str(item.get("lat", "50"))
            lon = str(item.get("lon", "30"))
            name = item.get("local_names", {}).get("ru") or item.get("name") or query
            country = item.get("country") or "UA"
            result.append(accuweather_location_object(lat, lon, name, country))
    else:
        result.append(accuweather_location_object("50", "30", "Kyiv", "UA"))

    cache_set(cache_key, result)
    return result


# =========================
# CURRENT CONDITIONS
# =========================

def safe_current():
    return [{
        "LocalObservationDateTime": datetime.now(timezone.utc).isoformat(),
        "EpochTime": int(time.time()),
        "WeatherText": "Clear",
        "WeatherIcon": 1,
        "HasPrecipitation": False,
        "PrecipitationType": None,
        "IsDayTime": True,
        "Temperature": {
            "Metric": {
                "Value": 20,
                "Unit": "C",
                "UnitType": 17
            }
        },
        "RealFeelTemperature": {
            "Metric": {
                "Value": 20,
                "Unit": "C",
                "UnitType": 17
            }
        },
        "RelativeHumidity": 50,
        "Wind": {
            "Speed": {
                "Metric": {
                    "Value": 0,
                    "Unit": "km/h",
                    "UnitType": 7
                }
            }
        }
    }]


def get_current_conditions(lat, lon):
    cache_key = f"current:{lat},{lon}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    params = {
        "lat": lat,
        "lon": lon,
        "appid": OPENWEATHER_API_KEY,
        "units": "metric",
        "lang": "ru"
    }

    data = safe_get(OWM_WEATHER_URL, params)

    if str(data.get("cod")) != "200":
        return safe_current()

    weather = (data.get("weather") or [{}])[0]
    main = data.get("main", {})
    wind = data.get("wind", {})

    is_day = is_daytime_by_data(data)
    wid = weather.get("id")
    weather_main = weather.get("main") or "Clear"
    description = weather.get("description") or weather_main
    temp = main.get("temp", 20)
    feels = main.get("feels_like", temp)

    result = [{
        "LocalObservationDateTime": datetime.now(timezone.utc).isoformat(),
        "EpochTime": int(data.get("dt", time.time())),
        "WeatherText": description,
        "WeatherIcon": htc_icon(wid, weather_main, is_day),
        "HasPrecipitation": weather_main.lower() in ["rain", "drizzle", "thunderstorm", "snow"],
        "PrecipitationType": weather_main if weather_main.lower() in ["rain", "snow"] else None,
        "IsDayTime": is_day,
        "Temperature": {
            "Metric": {
                "Value": round(float(temp), 1),
                "Unit": "C",
                "UnitType": 17
            }
        },
        "RealFeelTemperature": {
            "Metric": {
                "Value": round(float(feels), 1),
                "Unit": "C",
                "UnitType": 17
            }
        },
        "RelativeHumidity": main.get("humidity", 50),
        "Wind": {
            "Speed": {
                "Metric": {
                    "Value": round(float(wind.get("speed", 0)) * 3.6, 1),
                    "Unit": "km/h",
                    "UnitType": 7
                }
            }
        }
    }]

    cache_set(cache_key, result)
    return result


# =========================
# DAILY FORECAST 10 DAY
# =========================

def get_daily_forecast(lat, lon):
    cache_key = f"daily:{lat},{lon}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    params = {
        "lat": lat,
        "lon": lon,
        "appid": OPENWEATHER_API_KEY,
        "units": "metric",
        "lang": "ru"
    }

    data = safe_get(OWM_FORECAST_URL, params)

    if str(data.get("cod")) != "200":
        return {"Headline": {"Text": "Weather forecast"}, "DailyForecasts": []}

    days = {}

    for item in data.get("list", []):
        date = item.get("dt_txt", "").split(" ")[0]
        if not date:
            continue

        temp = item.get("main", {}).get("temp", 20)
        weather = (item.get("weather") or [{}])[0]
        wid = weather.get("id")
        main = weather.get("main") or "Clear"
        desc = weather.get("description") or main

        if date not in days:
            days[date] = {
                "min": temp,
                "max": temp,
                "main": main,
                "desc": desc,
                "icon": htc_icon(wid, main, True),
                "epoch": int(item.get("dt", time.time()))
            }
        else:
            days[date]["min"] = min(days[date]["min"], temp)
            days[date]["max"] = max(days[date]["max"], temp)

    forecasts = []

    for date, d in list(days.items())[:10]:
        forecasts.append({
            "Date": f"{date}T07:00:00+03:00",
            "EpochDate": d["epoch"],
            "Temperature": {
                "Minimum": {
                    "Value": round(float(d["min"]), 1),
                    "Unit": "C",
                    "UnitType": 17
                },
                "Maximum": {
                    "Value": round(float(d["max"]), 1),
                    "Unit": "C",
                    "UnitType": 17
                }
            },
            "Day": {
                "Icon": d["icon"],
                "IconPhrase": d["desc"],
                "HasPrecipitation": d["main"].lower() in ["rain", "drizzle", "thunderstorm", "snow"]
            },
            "Night": {
                "Icon": d["icon"],
                "IconPhrase": d["desc"],
                "HasPrecipitation": d["main"].lower() in ["rain", "drizzle", "thunderstorm", "snow"]
            },
            "Sources": ["OpenWeather"],
            "MobileLink": "",
            "Link": ""
        })

    # HTC может ждать именно 10 дней. OpenWeather free даёт около 5.
    # Для стабильности UI дублируем последний день, если дней меньше 10.
    while forecasts and len(forecasts) < 10:
        last = dict(forecasts[-1])
        last["EpochDate"] = last["EpochDate"] + 86400
        last_date = datetime.fromtimestamp(last["EpochDate"], tz=timezone.utc).date().isoformat()
        last["Date"] = f"{last_date}T07:00:00+03:00"
        forecasts.append(last)

    result = {
        "Headline": {
            "EffectiveDate": datetime.now(timezone.utc).isoformat(),
            "EffectiveEpochDate": int(time.time()),
            "Severity": 1,
            "Text": "Weather forecast",
            "Category": "general",
            "EndDate": None,
            "EndEpochDate": None,
            "MobileLink": "",
            "Link": ""
        },
        "DailyForecasts": forecasts
    }

    cache_set(cache_key, result)
    return result


# =========================
# HOURLY FORECAST 12 HOUR
# =========================

def get_hourly_forecast(lat, lon):
    cache_key = f"hourly:{lat},{lon}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    params = {
        "lat": lat,
        "lon": lon,
        "appid": OPENWEATHER_API_KEY,
        "units": "metric",
        "lang": "ru"
    }

    data = safe_get(OWM_FORECAST_URL, params)

    if str(data.get("cod")) != "200":
        return []

    result = []

    for item in data.get("list", [])[:12]:
        weather = (item.get("weather") or [{}])[0]
        main = weather.get("main") or "Clear"
        desc = weather.get("description") or main
        wid = weather.get("id")
        temp = item.get("main", {}).get("temp", 20)
        epoch = int(item.get("dt", time.time()))

        dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
        local_hour = dt.hour
        is_day = 6 <= local_hour <= 20

        result.append({
            "DateTime": dt.isoformat(),
            "EpochDateTime": epoch,
            "WeatherIcon": htc_icon(wid, main, is_day),
            "IconPhrase": desc,
            "HasPrecipitation": main.lower() in ["rain", "drizzle", "thunderstorm", "snow"],
            "IsDaylight": is_day,
            "Temperature": {
                "Value": round(float(temp), 1),
                "Unit": "C",
                "UnitType": 17
            },
            "PrecipitationProbability": 0,
            "MobileLink": "",
            "Link": ""
        })

    cache_set(cache_key, result)
    return result


# =========================
# ROUTES
# =========================

@app.route("/")
def home():
    return "HTC Weather Proxy FULL OK"


@app.route("/debug")
def debug():
    return jsonify({
        "status": "ok",
        "openweather_key_present": bool(OPENWEATHER_API_KEY),
        "supported": [
            "/locations/v1/cities/geoposition/search",
            "/locations/v1/cities/geoposition/search.json",
            "/locations/v1/search",
            "/locations/v1/timezones",
            "/locations/v1/<key>",
            "/currentconditions/v1/<key>",
            "/forecasts/v1/daily/10day/<key>",
            "/forecasts/v1/hourly/12hour/<key>",
            "/widget/htc2/city-find.asp"
        ]
    })


@app.route("/locations/v1/cities/geoposition/search")
@app.route("/locations/v1/cities/geoposition/search.json")
def geoposition_search():
    q = request.args.get("q") or request.args.get("query") or "50,30"

    try:
        lat, lon = q.split(",", 1)
    except Exception:
        lat, lon = "50", "30"

    return jsonify(get_location_by_coords(lat.strip(), lon.strip()))


@app.route("/locations/v1/search")
def location_search():
    q = request.args.get("q") or request.args.get("query") or request.args.get("city") or "Kyiv"
    return jsonify(search_locations_by_text(q))


@app.route("/locations/v1/timezones")
def timezones():
    return jsonify([
        {
            "Code": "EET",
            "Name": "Europe/Kyiv",
            "GmtOffset": 2,
            "IsDaylightSaving": False,
            "NextOffsetChange": None
        }
    ])


@app.route("/locations/v1/<path:location_key>")
def location_by_key(location_key):
    lat, lon = parse_key(location_key)
    return jsonify(get_location_by_coords(lat, lon))


@app.route("/currentconditions/v1/<path:location_key>")
def currentconditions(location_key):
    lat, lon = parse_key(location_key)
    return jsonify(get_current_conditions(lat, lon))


@app.route("/forecasts/v1/daily/10day/<path:location_key>")
def forecast_10day(location_key):
    lat, lon = parse_key(location_key)
    return jsonify(get_daily_forecast(lat, lon))


@app.route("/forecasts/v1/daily/5day/<path:location_key>")
def forecast_5day(location_key):
    lat, lon = parse_key(location_key)
    data = get_daily_forecast(lat, lon)
    data["DailyForecasts"] = data.get("DailyForecasts", [])[:5]
    return jsonify(data)


@app.route("/forecasts/v1/hourly/12hour/<path:location_key>")
def forecast_12hour(location_key):
    lat, lon = parse_key(location_key)
    return jsonify(get_hourly_forecast(lat, lon))


@app.route("/widget/htc2/city-find.asp")
def city_find_asp():
    q = (
        request.args.get("location")
        or request.args.get("q")
        or request.args.get("query")
        or request.args.get("city")
        or "Kyiv"
    )

    results = search_locations_by_text(q)
    first = results[0] if results else accuweather_location_object("50", "30", "Kyiv", "UA")

    name = first.get("LocalizedName", "Kyiv")
    country = first.get("Country", {}).get("ID", "UA")
    lat = first.get("GeoPosition", {}).get("Latitude", 50)
    lon = first.get("GeoPosition", {}).get("Longitude", 30)

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<adc_database>
    <citylist>
        <location city="{name}" state="" country="{country}" latitude="{lat}" longitude="{lon}" timezone="2" timezonecode="EET"/>
    </citylist>
</adc_database>
"""

    return Response(xml, mimetype="text/xml")


# =========================
# START
# =========================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
