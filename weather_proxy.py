from flask import Flask, request, jsonify, Response
import requests
import os
import time
import math
from datetime import datetime, timezone, timedelta

app = Flask(__name__)
app.json.ensure_ascii = False

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")

OWM_WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
OWM_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
OWM_DIRECT_URL = "https://api.openweathermap.org/geo/1.0/direct"

CACHE = {}
CACHE_TTL = 300


# ============================================================
# CACHE
# ============================================================

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


# ============================================================
# SAFE HTTP
# ============================================================

def safe_get(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=12)
        print("REQUEST:", r.url, "STATUS:", r.status_code)
        return r.json()
    except Exception as e:
        print("REQUEST ERROR:", e)
        return {}


# ============================================================
# HELPERS
# ============================================================

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def parse_key(location_key):
    """
    HTC/AccuWeather Location Key у нас = "lat,lon".
    Например: 50.4501,30.5234
    """
    try:
        key = str(location_key).strip()
        key = key.replace("%2C", ",").replace("%2c", ",")
        lat, lon = key.split(",", 1)
        return lat.strip(), lon.strip()
    except Exception:
        return "50.4501", "30.5234"


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
        now = int(data.get("dt", time.time()))
        sys = data.get("sys", {})
        sunrise = int(sys.get("sunrise", 0))
        sunset = int(sys.get("sunset", 0))

        if sunrise and sunset:
            return sunrise <= now <= sunset
    except Exception:
        pass

    h = datetime.now().hour
    return 6 <= h <= 20


def htc_icon(weather_id=None, main="", is_day=True):
    """
    Примерное соответствие OpenWeather -> AccuWeather/HTC icon id.
    """
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

    # Fog / mist / haze
    if 700 <= wid < 800 or "fog" in m or "mist" in m or "haze" in m:
        return 20

    # Clear
    if wid == 800 or "clear" in m:
        return 1 if is_day else 33

    # Clouds
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


# ============================================================
# LOCATION
# ============================================================

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
        "limit": 8,
        "appid": OPENWEATHER_API_KEY
    }

    data = safe_get(OWM_DIRECT_URL, params)

    result = []

    if isinstance(data, list) and data:
        for item in data:
            lat = str(item.get("lat", "50.4501"))
            lon = str(item.get("lon", "30.5234"))
            name = (
                item.get("local_names", {}).get("ru")
                or item.get("local_names", {}).get("uk")
                or item.get("name")
                or query
            )
            country = item.get("country") or "UA"
            result.append(accuweather_location_object(lat, lon, name, country))
    else:
        result.append(accuweather_location_object("50.4501", "30.5234", "Kyiv", "UA"))

    cache_set(cache_key, result)
    return result


# ============================================================
# CURRENT CONDITIONS — FULL HTC/ACCUWEATHER COMPATIBLE
# ============================================================

def safe_current():
    now = datetime.now(timezone.utc)
    epoch = int(time.time())

    return [{
        "LocalObservationDateTime": now.isoformat(),
        "EpochTime": epoch,
        "WeatherText": "Clear",
        "WeatherIcon": 1,
        "HasPrecipitation": False,
        "PrecipitationType": None,
        "IsDayTime": True,

        "Temperature": {
            "Metric": {
                "Value": 20.0,
                "Unit": "C",
                "UnitType": 17
            },
            "Imperial": {
                "Value": 68.0,
                "Unit": "F",
                "UnitType": 18
            }
        },

        "RealFeelTemperature": {
            "Metric": {
                "Value": 20.0,
                "Unit": "C",
                "UnitType": 17,
                "Phrase": ""
            },
            "Imperial": {
                "Value": 68.0,
                "Unit": "F",
                "UnitType": 18,
                "Phrase": ""
            }
        },

        "RealFeelTemperatureShade": {
            "Metric": {
                "Value": 20.0,
                "Unit": "C",
                "UnitType": 17,
                "Phrase": ""
            },
            "Imperial": {
                "Value": 68.0,
                "Unit": "F",
                "UnitType": 18,
                "Phrase": ""
            }
        },

        "RelativeHumidity": 50,
        "IndoorRelativeHumidity": 50,

        "DewPoint": {
            "Metric": {
                "Value": 10.0,
                "Unit": "C",
                "UnitType": 17
            },
            "Imperial": {
                "Value": 50.0,
                "Unit": "F",
                "UnitType": 18
            }
        },

        "Wind": {
            "Direction": {
                "Degrees": 0,
                "Localized": "N",
                "English": "N"
            },
            "Speed": {
                "Metric": {
                    "Value": 0.0,
                    "Unit": "km/h",
                    "UnitType": 7
                },
                "Imperial": {
                    "Value": 0.0,
                    "Unit": "mi/h",
                    "UnitType": 9
                }
            }
        },

        "WindGust": {
            "Speed": {
                "Metric": {
                    "Value": 0.0,
                    "Unit": "km/h",
                    "UnitType": 7
                },
                "Imperial": {
                    "Value": 0.0,
                    "Unit": "mi/h",
                    "UnitType": 9
                }
            }
        },

        "UVIndex": 0,
        "UVIndexText": "Low",

        "Visibility": {
            "Metric": {
                "Value": 10.0,
                "Unit": "km",
                "UnitType": 6
            },
            "Imperial": {
                "Value": 6.2,
                "Unit": "mi",
                "UnitType": 2
            }
        },

        "CloudCover": 0,

        "Ceiling": {
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
        },

        "Pressure": {
            "Metric": {
                "Value": 1013.0,
                "Unit": "mb",
                "UnitType": 14
            },
            "Imperial": {
                "Value": 29.91,
                "Unit": "inHg",
                "UnitType": 12
            }
        },

        "PressureTendency": {
            "LocalizedText": "Steady",
            "Code": "S"
        },

        "Past24HourTemperatureDeparture": {
            "Metric": {
                "Value": 0.0,
                "Unit": "C",
                "UnitType": 17
            },
            "Imperial": {
                "Value": 0.0,
                "Unit": "F",
                "UnitType": 18
            }
        },

        "ApparentTemperature": {
            "Metric": {
                "Value": 20.0,
                "Unit": "C",
                "UnitType": 17
            },
            "Imperial": {
                "Value": 68.0,
                "Unit": "F",
                "UnitType": 18
            }
        },

        "WindChillTemperature": {
            "Metric": {
                "Value": 20.0,
                "Unit": "C",
                "UnitType": 17
            },
            "Imperial": {
                "Value": 68.0,
                "Unit": "F",
                "UnitType": 18
            }
        },

        "WetBulbTemperature": {
            "Metric": {
                "Value": 20.0,
                "Unit": "C",
                "UnitType": 17
            },
            "Imperial": {
                "Value": 68.0,
                "Unit": "F",
                "UnitType": 18
            }
        },

        "Precip1hr": {
            "Metric": {
                "Value": 0.0,
                "Unit": "mm",
                "UnitType": 3
            },
            "Imperial": {
                "Value": 0.0,
                "Unit": "in",
                "UnitType": 1
            }
        },

        "PrecipitationSummary": {
            "Precipitation": {
                "Metric": {
                    "Value": 0.0,
                    "Unit": "mm",
                    "UnitType": 3
                },
                "Imperial": {
                    "Value": 0.0,
                    "Unit": "in",
                    "UnitType": 1
                }
            },
            "PastHour": {
                "Metric": {
                    "Value": 0.0,
                    "Unit": "mm",
                    "UnitType": 3
                },
                "Imperial": {
                    "Value": 0.0,
                    "Unit": "in",
                    "UnitType": 1
                }
            },
            "Past3Hours": {
                "Metric": {
                    "Value": 0.0,
                    "Unit": "mm",
                    "UnitType": 3
                },
                "Imperial": {
                    "Value": 0.0,
                    "Unit": "in",
                    "UnitType": 1
                }
            },
            "Past6Hours": {
                "Metric": {
                    "Value": 0.0,
                    "Unit": "mm",
                    "UnitType": 3
                },
                "Imperial": {
                    "Value": 0.0,
                    "Unit": "in",
                    "UnitType": 1
                }
            },
            "Past9Hours": {
                "Metric": {
                    "Value": 0.0,
                    "Unit": "mm",
                    "UnitType": 3
                },
                "Imperial": {
                    "Value": 0.0,
                    "Unit": "in",
                    "UnitType": 1
                }
            },
            "Past12Hours": {
                "Metric": {
                    "Value": 0.0,
                    "Unit": "mm",
                    "UnitType": 3
                },
                "Imperial": {
                    "Value": 0.0,
                    "Unit": "in",
                    "UnitType": 1
                }
            },
            "Past18Hours": {
                "Metric": {
                    "Value": 0.0,
                    "Unit": "mm",
                    "UnitType": 3
                },
                "Imperial": {
                    "Value": 0.0,
                    "Unit": "in",
                    "UnitType": 1
                }
            },
            "Past24Hours": {
                "Metric": {
                    "Value": 0.0,
                    "Unit": "mm",
                    "UnitType": 3
                },
                "Imperial": {
                    "Value": 0.0,
                    "Unit": "in",
                    "UnitType": 1
                }
            }
        },

        "TemperatureSummary": {
            "Past6HourRange": {
                "Minimum": {
                    "Metric": {
                        "Value": 20.0,
                        "Unit": "C",
                        "UnitType": 17
                    },
                    "Imperial": {
                        "Value": 68.0,
                        "Unit": "F",
                        "UnitType": 18
                    }
                },
                "Maximum": {
                    "Metric": {
                        "Value": 20.0,
                        "Unit": "C",
                        "UnitType": 17
                    },
                    "Imperial": {
                        "Value": 68.0,
                        "Unit": "F",
                        "UnitType": 18
                    }
                }
            },
            "Past12HourRange": {
                "Minimum": {
                    "Metric": {
                        "Value": 20.0,
                        "Unit": "C",
                        "UnitType": 17
                    },
                    "Imperial": {
                        "Value": 68.0,
                        "Unit": "F",
                        "UnitType": 18
                    }
                },
                "Maximum": {
                    "Metric": {
                        "Value": 20.0,
                        "Unit": "C",
                        "UnitType": 17
                    },
                    "Imperial": {
                        "Value": 68.0,
                        "Unit": "F",
                        "UnitType": 18
                    }
                }
            },
            "Past24HourRange": {
                "Minimum": {
                    "Metric": {
                        "Value": 20.0,
                        "Unit": "C",
                        "UnitType": 17
                    },
                    "Imperial": {
                        "Value": 68.0,
                        "Unit": "F",
                        "UnitType": 18
                    }
                },
                "Maximum": {
                    "Metric": {
                        "Value": 20.0,
                        "Unit": "C",
                        "UnitType": 17
                    },
                    "Imperial": {
                        "Value": 68.0,
                        "Unit": "F",
                        "UnitType": 18
                    }
                }
            }
        },

        "MobileLink": "",
        "Link": ""
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
        print("OWM current failed:", data)
        return safe_current()

    weather = (data.get("weather") or [{}])[0]
    main = data.get("main", {})
    wind = data.get("wind", {})
    clouds = data.get("clouds", {})

    is_day = is_daytime_by_data(data)

    wid = weather.get("id")
    weather_main = weather.get("main") or "Clear"
    description = weather.get("description") or weather_main

    temp = float(main.get("temp", 20.0))
    feels = float(main.get("feels_like", temp))
    humidity = int(main.get("humidity", 50))
    pressure = float(main.get("pressure", 1013))
    cloud_cover = int(clouds.get("all", 0))

    wind_speed_ms = float(wind.get("speed", 0.0))
    wind_speed_kmh = ms_to_kmh(wind_speed_ms)
    wind_speed_mph = kmh_to_mph(wind_speed_kmh)
    wind_deg = int(wind.get("deg", 0))
    wind_text = wind_direction_text(wind_deg)

    temp_f = c_to_f(temp)
    feels_f = c_to_f(feels)

    dew_c = round(temp - ((100 - humidity) / 5), 1)
    dew_f = c_to_f(dew_c)

    epoch = int(data.get("dt", time.time()))
    now = datetime.now(timezone.utc)

    has_precip = weather_main.lower() in ["rain", "drizzle", "thunderstorm", "snow"]

    precip_type = None
    if weather_main.lower() == "rain":
        precip_type = "Rain"
    elif weather_main.lower() == "snow":
        precip_type = "Snow"
    elif weather_main.lower() == "drizzle":
        precip_type = "Rain"
    elif weather_main.lower() == "thunderstorm":
        precip_type = "Rain"

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

    precip_1h = round(rain_1h + snow_1h, 1)

    result = [{
        "LocalObservationDateTime": now.isoformat(),
        "EpochTime": epoch,
        "WeatherText": description,
        "WeatherIcon": htc_icon(wid, weather_main, is_day),
        "HasPrecipitation": has_precip,
        "PrecipitationType": precip_type,
        "IsDayTime": is_day,

        "Temperature": {
            "Metric": {
                "Value": round(temp, 1),
                "Unit": "C",
                "UnitType": 17
            },
            "Imperial": {
                "Value": temp_f,
                "Unit": "F",
                "UnitType": 18
            }
        },

        "RealFeelTemperature": {
            "Metric": {
                "Value": round(feels, 1),
                "Unit": "C",
                "UnitType": 17,
                "Phrase": ""
            },
            "Imperial": {
                "Value": feels_f,
                "Unit": "F",
                "UnitType": 18,
                "Phrase": ""
            }
        },

        "RealFeelTemperatureShade": {
            "Metric": {
                "Value": round(feels, 1),
                "Unit": "C",
                "UnitType": 17,
                "Phrase": ""
            },
            "Imperial": {
                "Value": feels_f,
                "Unit": "F",
                "UnitType": 18,
                "Phrase": ""
            }
        },

        "RelativeHumidity": humidity,
        "IndoorRelativeHumidity": humidity,

        "DewPoint": {
            "Metric": {
                "Value": dew_c,
                "Unit": "C",
                "UnitType": 17
            },
            "Imperial": {
                "Value": dew_f,
                "Unit": "F",
                "UnitType": 18
            }
        },

        "Wind": {
            "Direction": {
                "Degrees": wind_deg,
                "Localized": wind_text,
                "English": wind_text
            },
            "Speed": {
                "Metric": {
                    "Value": wind_speed_kmh,
                    "Unit": "km/h",
                    "UnitType": 7
                },
                "Imperial": {
                    "Value": wind_speed_mph,
                    "Unit": "mi/h",
                    "UnitType": 9
                }
            }
        },

        "WindGust": {
            "Speed": {
                "Metric": {
                    "Value": wind_speed_kmh,
                    "Unit": "km/h",
                    "UnitType": 7
                },
                "Imperial": {
                    "Value": wind_speed_mph,
                    "Unit": "mi/h",
                    "UnitType": 9
                }
            }
        },

        "UVIndex": 0,
        "UVIndexText": "Low",

        "Visibility": {
            "Metric": {
                "Value": 10.0,
                "Unit": "km",
                "UnitType": 6
            },
            "Imperial": {
                "Value": 6.2,
                "Unit": "mi",
                "UnitType": 2
            }
        },

        "CloudCover": cloud_cover,

        "Ceiling": {
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
        },

        "Pressure": {
            "Metric": {
                "Value": pressure,
                "Unit": "mb",
                "UnitType": 14
            },
            "Imperial": {
                "Value": pressure_mb_to_inhg(pressure),
                "Unit": "inHg",
                "UnitType": 12
            }
        },

        "PressureTendency": {
            "LocalizedText": "Steady",
            "Code": "S"
        },

        "Past24HourTemperatureDeparture": {
            "Metric": {
                "Value": 0.0,
                "Unit": "C",
                "UnitType": 17
            },
            "Imperial": {
                "Value": 0.0,
                "Unit": "F",
                "UnitType": 18
            }
        },

        "ApparentTemperature": {
            "Metric": {
                "Value": round(feels, 1),
                "Unit": "C",
                "UnitType": 17
            },
            "Imperial": {
                "Value": feels_f,
                "Unit": "F",
                "UnitType": 18
            }
        },

        "WindChillTemperature": {
            "Metric": {
                "Value": round(feels, 1),
                "Unit": "C",
                "UnitType": 17
            },
            "Imperial": {
                "Value": feels_f,
                "Unit": "F",
                "UnitType": 18
            }
        },

        "WetBulbTemperature": {
            "Metric": {
                "Value": round(temp, 1),
                "Unit": "C",
                "UnitType": 17
            },
            "Imperial": {
                "Value": temp_f,
                "Unit": "F",
                "UnitType": 18
            }
        },

        "Precip1hr": {
            "Metric": {
                "Value": precip_1h,
                "Unit": "mm",
                "UnitType": 3
            },
            "Imperial": {
                "Value": round(precip_1h / 25.4, 2),
                "Unit": "in",
                "UnitType": 1
            }
        },

        "PrecipitationSummary": {
            "Precipitation": {
                "Metric": {
                    "Value": precip_1h,
                    "Unit": "mm",
                    "UnitType": 3
                },
                "Imperial": {
                    "Value": round(precip_1h / 25.4, 2),
                    "Unit": "in",
                    "UnitType": 1
                }
            },
            "PastHour": {
                "Metric": {
                    "Value": precip_1h,
                    "Unit": "mm",
                    "UnitType": 3
                },
                "Imperial": {
                    "Value": round(precip_1h / 25.4, 2),
                    "Unit": "in",
                    "UnitType": 1
                }
            },
            "Past3Hours": {
                "Metric": {
                    "Value": precip_1h,
                    "Unit": "mm",
                    "UnitType": 3
                },
                "Imperial": {
                    "Value": round(precip_1h / 25.4, 2),
                    "Unit": "in",
                    "UnitType": 1
                }
            },
            "Past6Hours": {
                "Metric": {
                    "Value": precip_1h,
                    "Unit": "mm",
                    "UnitType": 3
                },
                "Imperial": {
                    "Value": round(precip_1h / 25.4, 2),
                    "Unit": "in",
                    "UnitType": 1
                }
            },
            "Past9Hours": {
                "Metric": {
                    "Value": precip_1h,
                    "Unit": "mm",
                    "UnitType": 3
                },
                "Imperial": {
                    "Value": round(precip_1h / 25.4, 2),
                    "Unit": "in",
                    "UnitType": 1
                }
            },
            "Past12Hours": {
                "Metric": {
                    "Value": precip_1h,
                    "Unit": "mm",
                    "UnitType": 3
                },
                "Imperial": {
                    "Value": round(precip_1h / 25.4, 2),
                    "Unit": "in",
                    "UnitType": 1
                }
            },
            "Past18Hours": {
                "Metric": {
                    "Value": precip_1h,
                    "Unit": "mm",
                    "UnitType": 3
                },
                "Imperial": {
                    "Value": round(precip_1h / 25.4, 2),
                    "Unit": "in",
                    "UnitType": 1
                }
            },
            "Past24Hours": {
                "Metric": {
                    "Value": precip_1h,
                    "Unit": "mm",
                    "UnitType": 3
                },
                "Imperial": {
                    "Value": round(precip_1h / 25.4, 2),
                    "Unit": "in",
                    "UnitType": 1
                }
            }
        },

        "TemperatureSummary": {
            "Past6HourRange": {
                "Minimum": {
                    "Metric": {
                        "Value": round(temp, 1),
                        "Unit": "C",
                        "UnitType": 17
                    },
                    "Imperial": {
                        "Value": temp_f,
                        "Unit": "F",
                        "UnitType": 18
                    }
                },
                "Maximum": {
                    "Metric": {
                        "Value": round(temp, 1),
                        "Unit": "C",
                        "UnitType": 17
                    },
                    "Imperial": {
                        "Value": temp_f,
                        "Unit": "F",
                        "UnitType": 18
                    }
                }
            },
            "Past12HourRange": {
                "Minimum": {
                    "Metric": {
                        "Value": round(temp, 1),
                        "Unit": "C",
                        "UnitType": 17
                    },
                    "Imperial": {
                        "Value": temp_f,
                        "Unit": "F",
                        "UnitType": 18
                    }
                },
                "Maximum": {
                    "Metric": {
                        "Value": round(temp, 1),
                        "Unit": "C",
                        "UnitType": 17
                    },
                    "Imperial": {
                        "Value": temp_f,
                        "Unit": "F",
                        "UnitType": 18
                    }
                }
            },
            "Past24HourRange": {
                "Minimum": {
                    "Metric": {
                        "Value": round(temp, 1),
                        "Unit": "C",
                        "UnitType": 17
                    },
                    "Imperial": {
                        "Value": temp_f,
                        "Unit": "F",
                        "UnitType": 18
                    }
                },
                "Maximum": {
                    "Metric": {
                        "Value": round(temp, 1),
                        "Unit": "C",
                        "UnitType": 17
                    },
                    "Imperial": {
                        "Value": temp_f,
                        "Unit": "F",
                        "UnitType": 18
                    }
                }
            }
        },

        "MobileLink": "",
        "Link": ""
    }]

    cache_set(cache_key, result)
    return result


# ============================================================
# DAILY FORECAST 10 DAY
# ============================================================

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
        print("OWM daily failed:", data)
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
        wid = weather.get("id")
        main = weather.get("main") or "Clear"
        desc = weather.get("description") or main

        epoch = int(item.get("dt", time.time()))

        if date not in days:
            days[date] = {
                "min": temp_min,
                "max": temp_max,
                "main": main,
                "desc": desc,
                "wid": wid,
                "epoch": epoch
            }
        else:
            days[date]["min"] = min(days[date]["min"], temp_min)
            days[date]["max"] = max(days[date]["max"], temp_max)

    forecasts = []

    for date, d in list(days.items())[:10]:
        min_c = round(float(d["min"]), 1)
        max_c = round(float(d["max"]), 1)
        min_f = c_to_f(min_c)
        max_f = c_to_f(max_c)

        icon_day = htc_icon(d["wid"], d["main"], True)
        icon_night = htc_icon(d["wid"], d["main"], False)
        has_precip = d["main"].lower() in ["rain", "drizzle", "thunderstorm", "snow"]

        forecasts.append({
            "Date": f"{date}T07:00:00+03:00",
            "EpochDate": int(d["epoch"]),
            "Sun": {
                "Rise": f"{date}T05:00:00+03:00",
                "EpochRise": int(d["epoch"]),
                "Set": f"{date}T20:30:00+03:00",
                "EpochSet": int(d["epoch"]) + 43200
            },
            "Moon": {
                "Rise": f"{date}T20:00:00+03:00",
                "EpochRise": int(d["epoch"]) + 36000,
                "Set": f"{date}T06:00:00+03:00",
                "EpochSet": int(d["epoch"]) + 86400,
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
            "Day": {
                "Icon": icon_day,
                "IconPhrase": d["desc"],
                "HasPrecipitation": has_precip,
                "PrecipitationType": "Rain" if has_precip else None,
                "PrecipitationIntensity": "Light" if has_precip else None,
                "ShortPhrase": d["desc"],
                "LongPhrase": d["desc"],
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
            },
            "Night": {
                "Icon": icon_night,
                "IconPhrase": d["desc"],
                "HasPrecipitation": has_precip,
                "PrecipitationType": "Rain" if has_precip else None,
                "PrecipitationIntensity": "Light" if has_precip else None,
                "ShortPhrase": d["desc"],
                "LongPhrase": d["desc"],
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
            },
            "Sources": ["OpenWeather"],
            "MobileLink": "",
            "Link": ""
        })

    while forecasts and len(forecasts) < 10:
        last = dict(forecasts[-1])
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


# ============================================================
# HOURLY FORECAST 12 HOUR
# ============================================================

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
        print("OWM hourly failed:", data)
        return []

    result = []

    for item in data.get("list", [])[:12]:
        weather = (item.get("weather") or [{}])[0]
        main = weather.get("main") or "Clear"
        desc = weather.get("description") or main
        wid = weather.get("id")

        temp = float(item.get("main", {}).get("temp", 20.0))
        epoch = int(item.get("dt", time.time()))

        dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
        is_day = 6 <= dt.hour <= 20
        has_precip = main.lower() in ["rain", "drizzle", "thunderstorm", "snow"]

        result.append({
            "DateTime": dt.isoformat(),
            "EpochDateTime": epoch,
            "WeatherIcon": htc_icon(wid, main, is_day),
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
            "RelativeHumidity": 70,
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


# ============================================================
# ROUTES
# ============================================================

@app.route("/")
def home():
    return "HTC Weather Proxy FULL OK"


@app.route("/debug")
def debug():
    return jsonify({
        "status": "ok",
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
    q = request.args.get("q") or request.args.get("query") or "50.4501,30.5234"

    try:
        lat, lon = q.split(",", 1)
    except Exception:
        lat, lon = "50.4501", "30.5234"

    return jsonify(get_location_by_coords(lat.strip(), lon.strip()))


@app.route("/locations/v1/search")
def location_search():
    q = (
        request.args.get("q")
        or request.args.get("query")
        or request.args.get("city")
        or "Kyiv"
    )

    return jsonify(search_locations_by_text(q))


@app.route("/locations/v1/timezones")
def timezones():
    return jsonify([
        accu_timezone()
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
    first = results[0] if results else accuweather_location_object("50.4501", "30.5234", "Kyiv", "UA")

    name = first.get("LocalizedName", "Kyiv")
    country = first.get("Country", {}).get("ID", "UA")
    geo = first.get("GeoPosition", {})
    lat = geo.get("Latitude", 50.4501)
    lon = geo.get("Longitude", 30.5234)

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<adc_database>
    <citylist>
        <location city="{name}" state="" country="{country}" latitude="{lat}" longitude="{lon}" timezone="2" timezonecode="EET"/>
    </citylist>
</adc_database>
"""

    return Response(xml, mimetype="text/xml")


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
