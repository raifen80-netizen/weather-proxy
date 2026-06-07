from flask import Flask, request, jsonify, Response
import requests
import os
import time
import copy
import re
from datetime import datetime, timezone

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

try:
    app.json.ensure_ascii = False
except Exception:
    pass


PROXY_VERSION = "htc-full-current-v6-numeric-key-2026-06-07"

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")

OWM_WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
OWM_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
OWM_DIRECT_URL = "https://api.openweathermap.org/geo/1.0/direct"

CACHE = {}
CACHE_TTL = 300


@app.before_request
def log_request():
    print(
        "HTC_REQUEST:",
        request.method,
        request.path,
        dict(request.args),
        flush=True
    )


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


def safe_get(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=12)
        print("OPENWEATHER:", r.url, "STATUS:", r.status_code, flush=True)
        return r.json()
    except Exception as e:
        print("OPENWEATHER_ERROR:", str(e), flush=True)
        return {}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def make_location_key(lat, lon):
    """
    Безопасный HTC/AccuWeather-like ключ.

    Пример:
    47.6846511, 33.2645369
    -> KP0476847E0332645
    """
    lat_f = float(lat)
    lon_f = float(lon)

    lat_sign = "P" if lat_f >= 0 else "M"
    lon_sign = "E" if lon_f >= 0 else "W"

    lat_num = int(round(abs(lat_f) * 10000))
    lon_num = int(round(abs(lon_f) * 10000))

    return f"K{lat_sign}{lat_num:07d}{lon_sign}{lon_num:07d}"


def parse_key(location_key):
    """
    Поддерживает:
    KP0476847E0332645
    47.6846511_33.2645369
    47.6846511,33.2645369
    """
    try:
        key = str(location_key).strip()

        if key.endswith(".json"):
            key = key[:-5]

        key = key.replace("%2C", ",").replace("%2c", ",")
        key = key.replace("%5F", "_").replace("%5f", "_")

        m = re.match(r"^K([PM])(\d{7})([EW])(\d{7})$", key)
        if m:
            lat_sign, lat_raw, lon_sign, lon_raw = m.groups()

            lat = int(lat_raw) / 10000.0
            lon = int(lon_raw) / 10000.0

            if lat_sign == "M":
                lat = -lat

            if lon_sign == "W":
                lon = -lon

            return str(lat), str(lon)

        if "_" in key:
            lat, lon = key.split("_", 1)
            return lat.strip(), lon.strip()

        if "," in key:
            lat, lon = key.split(",", 1)
            return lat.strip(), lon.strip()

        return "47.6847", "33.2645"

    except Exception:
        return "47.6847", "33.2645"


def c_to_f(c):
    return round((float(c) * 9 / 5) + 32, 1)


def kmh_to_mph(kmh):
    return round(float(kmh) * 0.621371, 1)


def ms_to_kmh(ms):
    return round(float(ms) * 3.6, 1)


def pressure_mb_to_inhg(mb):
    return round(float(mb) * 0.02953, 2)


def wind_direction_text(deg):
    try:
        deg = int(deg)
    except Exception:
        deg = 0

    dirs = [
        "N", "NNE", "NE", "ENE",
        "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW",
        "W", "WNW", "NW", "NNW"
    ]

    ix = int((deg + 11.25) / 22.5) % 16
    return dirs[ix]


def is_daytime_by_data(data):
    try:
        current_time = int(data.get("dt", time.time()))
        sys_data = data.get("sys", {})
        sunrise = int(sys_data.get("sunrise", 0))
        sunset = int(sys_data.get("sunset", 0))

        if sunrise and sunset:
            return sunrise <= current_time <= sunset
    except Exception:
        pass

    hour = datetime.now().hour
    return 6 <= hour <= 20


def htc_icon(weather_id=None, main="", is_day=True):
    try:
        wid = int(weather_id)
    except Exception:
        wid = 0

    m = (main or "").lower()

    if 200 <= wid < 300 or "thunder" in m or "storm" in m:
        return 15

    if 300 <= wid < 400 or "drizzle" in m:
        return 11

    if 500 <= wid < 600 or "rain" in m:
        return 12

    if 600 <= wid < 700 or "snow" in m:
        return 22

    if 700 <= wid < 800 or "fog" in m or "mist" in m or "haze" in m:
        return 20

    if wid == 800 or "clear" in m:
        return 1 if is_day else 33

    if 801 <= wid <= 804 or "cloud" in m:
        return 7 if is_day else 38

    return 7 if is_day else 38


def accu_timezone():
    return {
        "Code": "EET",
        "Name": "Europe/Kyiv",
        "GmtOffset": 2,
        "IsDaylightSaving": False,
        "NextOffsetChange": None
    }


def accuweather_location_object(lat, lon, name="Unknown", country="UA"):
    lat_f = float(lat)
    lon_f = float(lon)

    key = make_location_key(lat_f, lon_f)

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
        "TimeZone": accu_timezone(),
        "GeoPosition": {
            "Latitude": lat_f,
            "Longitude": lon_f,
            "Elevation": {
                "Metric": {
                    "Value": 0.0,
                    "Unit": "m",
                    "UnitType": 5
                },
                "Imperial": {
                    "Value": 0.0,
                    "Unit": "ft",
                    "UnitType": 0
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
            "ForecastConfidence",
            "FutureRadar",
            "MinuteCast"
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
        result = accuweather_location_object(lat, lon, "Широке", "UA")

    cache_set(cache_key, result)
    return result


def search_locations_by_text(query):
    cache_key = f"search:{query}"
    cached = cache_get(cache_key)

    if cached:
        return cached

    params = {
        "q": query,
        "limit": 8,
        "appid": OPENWEATHER_API_KEY
    }

    data = safe_get(OWM_DIRECT_URL, params)
    result = []

    if isinstance(data, list) and data:
        for item in data:
            lat = str(item.get("lat", "47.6847"))
            lon = str(item.get("lon", "33.2645"))

            name = (
                item.get("local_names", {}).get("ru")
                or item.get("local_names", {}).get("uk")
                or item.get("name")
                or query
            )

            country = item.get("country") or "UA"
            result.append(accuweather_location_object(lat, lon, name, country))
    else:
        result.append(
            accuweather_location_object("47.6847", "33.2645", "Широке", "UA")
        )

    cache_set(cache_key, result)
    return result


def unit_value(value, unit, unit_type):
    return {
        "Value": value,
        "Unit": unit,
        "UnitType": unit_type
    }


def make_current_object(
    epoch,
    weather_text,
    weather_icon,
    is_day,
    temp_c,
    feels_c,
    humidity,
    pressure_mb,
    wind_kmh,
    wind_deg,
    cloud_cover,
    has_precip=False,
    precip_type=None,
    precip_1h=0.0
):
    temp_c = round(float(temp_c), 1)
    feels_c = round(float(feels_c), 1)

    temp_f = c_to_f(temp_c)
    feels_f = c_to_f(feels_c)

    humidity = int(humidity)

    dew_c = round(temp_c - ((100 - humidity) / 5), 1)
    dew_f = c_to_f(dew_c)

    wind_kmh = round(float(wind_kmh), 1)
    wind_mph = kmh_to_mph(wind_kmh)
    wind_text = wind_direction_text(wind_deg)

    precip_1h = round(float(precip_1h), 1)
    precip_in = round(precip_1h / 25.4, 2)

    temp_metric = unit_value(temp_c, "C", 17)
    temp_imperial = unit_value(temp_f, "F", 18)

    feels_metric = {
        "Value": feels_c,
        "Unit": "C",
        "UnitType": 17,
        "Phrase": ""
    }

    feels_imperial = {
        "Value": feels_f,
        "Unit": "F",
        "UnitType": 18,
        "Phrase": ""
    }

    precip_metric = unit_value(precip_1h, "mm", 3)
    precip_imperial = unit_value(precip_in, "in", 1)

    return {
        "LocalObservationDateTime": now_iso(),
        "EpochTime": int(epoch),
        "WeatherText": weather_text,
        "WeatherIcon": int(weather_icon),
        "HasPrecipitation": bool(has_precip),
        "PrecipitationType": precip_type,
        "IsDayTime": bool(is_day),

        "Temperature": {
            "Metric": temp_metric,
            "Imperial": temp_imperial
        },

        "RealFeelTemperature": {
            "Metric": feels_metric,
            "Imperial": feels_imperial
        },

        "RealFeelTemperatureShade": {
            "Metric": feels_metric,
            "Imperial": feels_imperial
        },

        "RelativeHumidity": humidity,
        "IndoorRelativeHumidity": humidity,

        "DewPoint": {
            "Metric": unit_value(dew_c, "C", 17),
            "Imperial": unit_value(dew_f, "F", 18)
        },

        "Wind": {
            "Direction": {
                "Degrees": int(wind_deg),
                "Localized": wind_text,
                "English": wind_text
            },
            "Speed": {
                "Metric": unit_value(wind_kmh, "km/h", 7),
                "Imperial": unit_value(wind_mph, "mi/h", 9)
            }
        },

        "WindGust": {
            "Speed": {
                "Metric": unit_value(wind_kmh, "km/h", 7),
                "Imperial": unit_value(wind_mph, "mi/h", 9)
            }
        },

        "UVIndex": 0,
        "UVIndexText": "Low",

        "Visibility": {
            "Metric": unit_value(10.0, "km", 6),
            "Imperial": unit_value(6.2, "mi", 2)
        },

        "ObstructionsToVisibility": "",
        "CloudCover": int(cloud_cover),

        "Ceiling": {
            "Metric": unit_value(0.0, "m", 5),
            "Imperial": unit_value(0.0, "ft", 0)
        },

        "Pressure": {
            "Metric": unit_value(round(float(pressure_mb), 1), "mb", 14),
            "Imperial": unit_value(pressure_mb_to_inhg(pressure_mb), "inHg", 12)
        },

        "PressureTendency": {
            "LocalizedText": "Steady",
            "Code": "S"
        },

        "Past24HourTemperatureDeparture": {
            "Metric": unit_value(0.0, "C", 17),
            "Imperial": unit_value(0.0, "F", 18)
        },

        "ApparentTemperature": {
            "Metric": temp_metric,
            "Imperial": temp_imperial
        },

        "WindChillTemperature": {
            "Metric": feels_metric,
            "Imperial": feels_imperial
        },

        "WetBulbTemperature": {
            "Metric": temp_metric,
            "Imperial": temp_imperial
        },

        "Precip1hr": {
            "Metric": precip_metric,
            "Imperial": precip_imperial
        },

        "PrecipitationSummary": {
            "Precipitation": {
                "Metric": precip_metric,
                "Imperial": precip_imperial
            },
            "PastHour": {
                "Metric": precip_metric,
                "Imperial": precip_imperial
            },
            "Past3Hours": {
                "Metric": precip_metric,
                "Imperial": precip_imperial
            },
            "Past6Hours": {
                "Metric": precip_metric,
                "Imperial": precip_imperial
            },
            "Past9Hours": {
                "Metric": precip_metric,
                "Imperial": precip_imperial
            },
            "Past12Hours": {
                "Metric": precip_metric,
                "Imperial": precip_imperial
            },
            "Past18Hours": {
                "Metric": precip_metric,
                "Imperial": precip_imperial
            },
            "Past24Hours": {
                "Metric": precip_metric,
                "Imperial": precip_imperial
            }
        },

        "TemperatureSummary": {
            "Past6HourRange": {
                "Minimum": {
                    "Metric": temp_metric,
                    "Imperial": temp_imperial
                },
                "Maximum": {
                    "Metric": temp_metric,
                    "Imperial": temp_imperial
                }
            },
            "Past12HourRange": {
                "Minimum": {
                    "Metric": temp_metric,
                    "Imperial": temp_imperial
                },
                "Maximum": {
                    "Metric": temp_metric,
                    "Imperial": temp_imperial
                }
            },
            "Past24HourRange": {
                "Minimum": {
                    "Metric": temp_metric,
                    "Imperial": temp_imperial
                },
                "Maximum": {
                    "Metric": temp_metric,
                    "Imperial": temp_imperial
                }
            }
        },

        "MobileLink": "",
        "Link": ""
    }


def safe_current():
    return [
        make_current_object(
            epoch=int(time.time()),
            weather_text="Clear",
            weather_icon=1,
            is_day=True,
            temp_c=20.0,
            feels_c=20.0,
            humidity=50,
            pressure_mb=1013,
            wind_kmh=0.0,
            wind_deg=0,
            cloud_cover=0,
            has_precip=False,
            precip_type=None,
            precip_1h=0.0
        )
    ]


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
        print("OWM_CURRENT_FAILED:", data, flush=True)
        return safe_current()

    weather = (data.get("weather") or [{}])[0]
    main = data.get("main", {})
    wind = data.get("wind", {})
    clouds = data.get("clouds", {})

    weather_id = weather.get("id")
    weather_main = weather.get("main") or "Clear"
    weather_text = weather.get("description") or weather_main

    temp_c = float(main.get("temp", 20.0))
    feels_c = float(main.get("feels_like", temp_c))
    humidity = int(main.get("humidity", 50))
    pressure_mb = float(main.get("pressure", 1013))

    wind_kmh = ms_to_kmh(float(wind.get("speed", 0.0)))
    wind_deg = int(wind.get("deg", 0))

    cloud_cover = int(clouds.get("all", 0))
    is_day = is_daytime_by_data(data)
    icon = htc_icon(weather_id, weather_main, is_day)

    rain_1h = 0.0
    snow_1h = 0.0

    try:
        rain_1h = float(data.get("rain", {}).get("1h", 0.0))
    except Exception:
        rain_1h = 0.0

    try:
        snow_1h = float(data.get("snow", {}).get("1h", 0.0))
    except Exception:
        snow_1h = 0.0

    precip_1h = rain_1h + snow_1h

    weather_lower = weather_main.lower()
    has_precip = weather_lower in ["rain", "drizzle", "thunderstorm", "snow"]

    precip_type = None

    if weather_lower in ["rain", "drizzle", "thunderstorm"]:
        precip_type = "Rain"
    elif weather_lower == "snow":
        precip_type = "Snow"

    result = [
        make_current_object(
            epoch=int(data.get("dt", time.time())),
            weather_text=weather_text,
            weather_icon=icon,
            is_day=is_day,
            temp_c=temp_c,
            feels_c=feels_c,
            humidity=humidity,
            pressure_mb=pressure_mb,
            wind_kmh=wind_kmh,
            wind_deg=wind_deg,
            cloud_cover=cloud_cover,
            has_precip=has_precip,
            precip_type=precip_type,
            precip_1h=precip_1h
        )
    ]

    cache_set(cache_key, result)
    return result


def make_daily_day_night(desc, icon, has_precip):
    return {
        "Icon": icon,
        "IconPhrase": desc,
        "HasPrecipitation": has_precip,
        "PrecipitationType": "Rain" if has_precip else None,
        "PrecipitationIntensity": "Light" if has_precip else None,
        "ShortPhrase": desc,
        "LongPhrase": desc,
        "PrecipitationProbability": 30 if has_precip else 0,
        "ThunderstormProbability": 0,
        "RainProbability": 30 if has_precip else 0,
        "SnowProbability": 0,
        "IceProbability": 0,
        "Wind": {
            "Speed": {
                "Value": 10.0,
                "Unit": "km/h",
                "UnitType": 7
            },
            "Direction": {
                "Degrees": 0,
                "Localized": "N",
                "English": "N"
            }
        },
        "WindGust": {
            "Speed": {
                "Value": 15.0,
                "Unit": "km/h",
                "UnitType": 7
            },
            "Direction": {
                "Degrees": 0,
                "Localized": "N",
                "English": "N"
            }
        },
        "TotalLiquid": {
            "Value": 0.0,
            "Unit": "mm",
            "UnitType": 3
        },
        "Rain": {
            "Value": 0.0,
            "Unit": "mm",
            "UnitType": 3
        },
        "Snow": {
            "Value": 0.0,
            "Unit": "cm",
            "UnitType": 4
        },
        "Ice": {
            "Value": 0.0,
            "Unit": "mm",
            "UnitType": 3
        },
        "HoursOfPrecipitation": 0.0,
        "HoursOfRain": 0.0,
        "HoursOfSnow": 0.0,
        "HoursOfIce": 0.0,
        "CloudCover": 50
    }


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
        print("OWM_DAILY_FAILED:", data, flush=True)
        return {
            "Headline": {
                "EffectiveDate": now_iso(),
                "EffectiveEpochDate": int(time.time()),
                "Severity": 1,
                "Text": "Weather forecast",
                "Category": "general",
                "EndDate": None,
                "EndEpochDate": None,
                "MobileLink": "",
                "Link": ""
            },
            "DailyForecasts": []
        }

    days = {}

    for item in data.get("list", []):
        date = item.get("dt_txt", "").split(" ")[0]

        if not date:
            continue

        temp = float(item.get("main", {}).get("temp", 20.0))
        temp_min = float(item.get("main", {}).get("temp_min", temp))
        temp_max = float(item.get("main", {}).get("temp_max", temp))

        weather = (item.get("weather") or [{}])[0]
        weather_id = weather.get("id")
        main = weather.get("main") or "Clear"
        desc = weather.get("description") or main
        epoch = int(item.get("dt", time.time()))

        if date not in days:
            days[date] = {
                "min": temp_min,
                "max": temp_max,
                "main": main,
                "desc": desc,
                "weather_id": weather_id,
                "epoch": epoch
            }
        else:
            days[date]["min"] = min(days[date]["min"], temp_min)
            days[date]["max"] = max(days[date]["max"], temp_max)

    forecasts = []

    for date, d in list(days.items())[:10]:
        min_c = round(float(d["min"]), 1)
        max_c = round(float(d["max"]), 1)

        day_icon = htc_icon(d["weather_id"], d["main"], True)
        night_icon = htc_icon(d["weather_id"], d["main"], False)

        has_precip = d["main"].lower() in ["rain", "drizzle", "thunderstorm", "snow"]
        epoch = int(d["epoch"])

        forecast = {
            "Date": f"{date}T07:00:00+03:00",
            "EpochDate": epoch,
            "Sun": {
                "Rise": f"{date}T05:00:00+03:00",
                "EpochRise": epoch,
                "Set": f"{date}T20:30:00+03:00",
                "EpochSet": epoch + 43200
            },
            "Moon": {
                "Rise": f"{date}T20:00:00+03:00",
                "EpochRise": epoch + 36000,
                "Set": f"{date}T06:00:00+03:00",
                "EpochSet": epoch + 86400,
                "Phase": "WaxingCrescent",
                "Age": 5
            },
            "Temperature": {
                "Minimum": {
                    "Value": min_c,
                    "Unit": "C",
                    "UnitType": 17
                },
                "Maximum": {
                    "Value": max_c,
                    "Unit": "C",
                    "UnitType": 17
                }
            },
            "RealFeelTemperature": {
                "Minimum": {
                    "Value": min_c,
                    "Unit": "C",
                    "UnitType": 17
                },
                "Maximum": {
                    "Value": max_c,
                    "Unit": "C",
                    "UnitType": 17
                }
            },
            "RealFeelTemperatureShade": {
                "Minimum": {
                    "Value": min_c,
                    "Unit": "C",
                    "UnitType": 17
                },
                "Maximum": {
                    "Value": max_c,
                    "Unit": "C",
                    "UnitType": 17
                }
            },
            "HoursOfSun": 8.0,
            "DegreeDaySummary": {
                "Heating": {
                    "Value": 0.0,
                    "Unit": "C",
                    "UnitType": 17
                },
                "Cooling": {
                    "Value": 0.0,
                    "Unit": "C",
                    "UnitType": 17
                }
            },
            "AirAndPollen": [],
            "Day": make_daily_day_night(d["desc"], day_icon, has_precip),
            "Night": make_daily_day_night(d["desc"], night_icon, has_precip),
            "Sources": ["OpenWeather"],
            "MobileLink": "",
            "Link": ""
        }

        forecasts.append(forecast)

    while forecasts and len(forecasts) < 10:
        last = copy.deepcopy(forecasts[-1])
        last["EpochDate"] = int(last["EpochDate"]) + 86400
        last_date = datetime.fromtimestamp(last["EpochDate"], tz=timezone.utc).date().isoformat()
        last["Date"] = f"{last_date}T07:00:00+03:00"
        forecasts.append(last)

    result = {
        "Headline": {
            "EffectiveDate": now_iso(),
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
        print("OWM_HOURLY_FAILED:", data, flush=True)
        return []

    result = []

    for item in data.get("list", [])[:12]:
        weather = (item.get("weather") or [{}])[0]
        main = weather.get("main") or "Clear"
        desc = weather.get("description") or main
        weather_id = weather.get("id")

        temp = float(item.get("main", {}).get("temp", 20.0))
        humidity = int(item.get("main", {}).get("humidity", 70))
        epoch = int(item.get("dt", time.time()))

        dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
        is_day = 6 <= dt.hour <= 20

        has_precip = main.lower() in ["rain", "drizzle", "thunderstorm", "snow"]

        result.append({
            "DateTime": dt.isoformat(),
            "EpochDateTime": epoch,
            "WeatherIcon": htc_icon(weather_id, main, is_day),
            "IconPhrase": desc,
            "HasPrecipitation": has_precip,
            "PrecipitationType": "Rain" if has_precip else None,
            "PrecipitationIntensity": "Light" if has_precip else None,
            "IsDaylight": is_day,
            "Temperature": {
                "Value": round(temp, 1),
                "Unit": "C",
                "UnitType": 17
            },
            "RealFeelTemperature": {
                "Value": round(temp, 1),
                "Unit": "C",
                "UnitType": 17,
                "Phrase": ""
            },
            "WetBulbTemperature": {
                "Value": round(temp, 1),
                "Unit": "C",
                "UnitType": 17
            },
            "DewPoint": {
                "Value": round(temp - 2, 1),
                "Unit": "C",
                "UnitType": 17
            },
            "Wind": {
                "Speed": {
                    "Value": 10.0,
                    "Unit": "km/h",
                    "UnitType": 7
                },
                "Direction": {
                    "Degrees": 0,
                    "Localized": "N",
                    "English": "N"
                }
            },
            "WindGust": {
                "Speed": {
                    "Value": 15.0,
                    "Unit": "km/h",
                    "UnitType": 7
                }
            },
            "RelativeHumidity": humidity,
            "Visibility": {
                "Value": 10.0,
                "Unit": "km",
                "UnitType": 6
            },
            "Ceiling": {
                "Value": 0.0,
                "Unit": "m",
                "UnitType": 5
            },
            "UVIndex": 0,
            "UVIndexText": "Low",
            "PrecipitationProbability": 30 if has_precip else 0,
            "RainProbability": 30 if has_precip else 0,
            "SnowProbability": 0,
            "IceProbability": 0,
            "TotalLiquid": {
                "Value": 0.0,
                "Unit": "mm",
                "UnitType": 3
            },
            "Rain": {
                "Value": 0.0,
                "Unit": "mm",
                "UnitType": 3
            },
            "Snow": {
                "Value": 0.0,
                "Unit": "cm",
                "UnitType": 4
            },
            "Ice": {
                "Value": 0.0,
                "Unit": "mm",
                "UnitType": 3
            },
            "CloudCover": 50,
            "MobileLink": "",
            "Link": ""
        })

    cache_set(cache_key, result)
    return result


@app.route("/")
def home():
    return "HTC Weather Proxy FULL OK"


@app.route("/debug")
def debug():
    return jsonify({
        "status": "ok",
        "version": PROXY_VERSION,
        "openweather_key_present": bool(OPENWEATHER_API_KEY),
        "routes": [
            "/locations/v1/cities/geoposition/search",
            "/locations/v1/cities/geoposition/search.json",
            "/locations/v1/search",
            "/locations/v1/timezones",
            "/locations/v1/<key>",
            "/currentconditions/v1/<key>",
            "/forecasts/v1/daily/10day/<key>",
            "/forecasts/v1/daily/5day/<key>",
            "/forecasts/v1/hourly/12hour/<key>",
            "/widget/htc2/city-find.asp"
        ]
    })


@app.route("/locations/v1/cities/geoposition/search")
@app.route("/locations/v1/cities/geoposition/search.json")
def geoposition_search():
    q = request.args.get("q") or request.args.get("query") or "47.6847,33.2645"
    q = str(q).strip()

    if "," in q:
        try:
            lat, lon = q.split(",", 1)
            return jsonify(get_location_by_coords(lat.strip(), lon.strip()))
        except Exception:
            return jsonify(get_location_by_coords("47.6847", "33.2645"))

    results = search_locations_by_text(q)

    if results:
        return jsonify(results[0])

    return jsonify(get_location_by_coords("47.6847", "33.2645"))


@app.route("/locations/v1/search")
def location_search():
    q = (
        request.args.get("q")
        or request.args.get("query")
        or request.args.get("city")
        or "Широке"
    )

    return jsonify(search_locations_by_text(q))


@app.route("/locations/v1/timezones")
def timezones():
    return jsonify([accu_timezone()])


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
        or "Широке"
    )

    results = search_locations_by_text(q)

    if results:
        first = results[0]
    else:
        first = accuweather_location_object("47.6847", "33.2645", "Широке", "UA")

    name = first.get("LocalizedName", "Широке")
    country = first.get("Country", {}).get("ID", "UA")
    geo = first.get("GeoPosition", {})
    lat = geo.get("Latitude", 47.6847)
    lon = geo.get("Longitude", 33.2645)

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<adc_database>
    <citylist>
        <location city="{name}" state="" country="{country}" latitude="{lat}" longitude="{lon}" timezone="2" timezonecode="EET"/>
    </citylist>
</adc_database>
"""

    return Response(xml, mimetype="text/xml")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
