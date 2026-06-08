import os
import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from collections import defaultdict

import requests
from flask import Flask, request, jsonify, Response


# ============================================================
# HTC Weather / AccuWeather-like proxy -> OpenWeatherMap
# File: weather_proxy.py
# Version: htc-weather-proxy-v10-htc-parser-safe
# ============================================================

app = Flask(__name__)

VERSION = "htc-weather-proxy-v10-htc-parser-safe"

OPENWEATHER_API_KEY = (
    os.environ.get("OPENWEATHER_API_KEY")
    or os.environ.get("OPENWEATHER_KEY")
    or os.environ.get("OWM_API_KEY")
    or ""
).strip()

DEFAULT_LANG = "ru"
DEFAULT_COUNTRY = "UA"

OWM_BASE = "https://api.openweathermap.org"
TIMEOUT = 12
CACHE_TTL = 300

CACHE = {}
LOCATION_CACHE = {}

try:
    KYIV_TZ = ZoneInfo("Europe/Kyiv")
    KYIV_TZ_FALLBACK = False
except ZoneInfoNotFoundError:
    KYIV_TZ = timezone(timedelta(hours=3), name="EEST")
    KYIV_TZ_FALLBACK = True


# ============================================================
# Base helpers
# ============================================================

def now_kyiv():
    return datetime.now(KYIV_TZ)


def to_kyiv(timestamp=None):
    if timestamp is None:
        return now_kyiv()
    return datetime.fromtimestamp(int(timestamp), KYIV_TZ)


def iso_kyiv(dt=None):
    if dt is None:
        dt = now_kyiv()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KYIV_TZ)
    return dt.astimezone(KYIV_TZ).isoformat(timespec="seconds")


def epoch(dt=None):
    if dt is None:
        dt = now_kyiv()
    return int(dt.timestamp())


def kyiv_timezone_block():
    if KYIV_TZ_FALLBACK:
        return {
            "Code": "EEST",
            "GmtOffset": 3,
            "IsDaylightSaving": True,
            "Name": "Europe/Kyiv",
            "NextOffsetChange": "",
        }

    n = now_kyiv()
    offset = n.utcoffset() or timedelta(hours=2)
    dst = n.dst() or timedelta(0)
    offset_hours = int(offset.total_seconds() // 3600)
    is_dst = dst.total_seconds() != 0

    return {
        "Code": "EEST" if is_dst else "EET",
        "GmtOffset": offset_hours,
        "IsDaylightSaving": bool(is_dst),
        "Name": "Europe/Kyiv",
        "NextOffsetChange": "",
    }


def get_lang():
    value = request.args.get("language") or request.args.get("lang") or DEFAULT_LANG
    value = value.lower()

    if value.startswith("ru"):
        return "ru"
    if value.startswith("uk"):
        return "uk"
    if value.startswith("en"):
        return "en"

    return "ru"


def cache_get(key):
    item = CACHE.get(key)
    if not item:
        return None

    created, value = item
    if time.time() - created > CACHE_TTL:
        CACHE.pop(key, None)
        return None

    return value


def cache_set(key, value):
    CACHE[key] = (time.time(), value)
    return value


def owm_get(path, params=None):
    params = dict(params or {})

    if not OPENWEATHER_API_KEY:
        raise RuntimeError("OPENWEATHER_API_KEY is not set")

    params["appid"] = OPENWEATHER_API_KEY

    cache_key = "owm:" + path + "?" + "&".join(
        f"{k}={params[k]}" for k in sorted(params)
    )

    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    r = requests.get(OWM_BASE + path, params=params, timeout=TIMEOUT)

    if not r.ok:
        raise RuntimeError(f"OpenWeatherMap error {r.status_code}: {r.text[:500]}")

    return cache_set(cache_key, r.json())


def num(value, digits=1, default=0.0):
    try:
        if value is None:
            return default
        return round(float(value), digits)
    except Exception:
        return default


def pct(value):
    try:
        return int(round(float(value)))
    except Exception:
        return 0


# ============================================================
# AccuWeather-like value blocks
# ============================================================

def metric_temp(c):
    return {
        "Value": num(c, 1),
        "Unit": "C",
        "UnitType": 17,
    }


def imperial_temp(c):
    f = float(num(c, 1)) * 9 / 5 + 32
    return {
        "Value": num(f, 1),
        "Unit": "F",
        "UnitType": 18,
    }


def temp_block(c):
    return {
        "Metric": metric_temp(c),
        "Imperial": imperial_temp(c),
    }


def daily_temp_value(c):
    return {
        "Value": num(c, 1),
        "Unit": "C",
        "UnitType": 17,
    }


def speed_block_kmh(kmh):
    kmh = num(kmh, 1)
    mph = kmh / 1.609344

    return {
        "Metric": {
            "Value": kmh,
            "Unit": "km/h",
            "UnitType": 7,
        },
        "Imperial": {
            "Value": num(mph, 1),
            "Unit": "mi/h",
            "UnitType": 9,
        },
    }


def distance_block_km(km):
    km = num(km, 1)
    mi = km / 1.609344

    return {
        "Metric": {
            "Value": km,
            "Unit": "km",
            "UnitType": 6,
        },
        "Imperial": {
            "Value": num(mi, 1),
            "Unit": "mi",
            "UnitType": 2,
        },
    }


def pressure_block_hpa(hpa):
    hpa = num(hpa, 1)
    inhg = hpa * 0.0295299830714

    return {
        "Metric": {
            "Value": hpa,
            "Unit": "mb",
            "UnitType": 14,
        },
        "Imperial": {
            "Value": num(inhg, 2),
            "Unit": "inHg",
            "UnitType": 12,
        },
    }


def mm_block(mm):
    mm = num(mm, 1)
    inch = mm / 25.4

    return {
        "Metric": {
            "Value": mm,
            "Unit": "mm",
            "UnitType": 3,
        },
        "Imperial": {
            "Value": num(inch, 2),
            "Unit": "in",
            "UnitType": 1,
        },
    }


def deg_to_compass(deg):
    try:
        deg = float(deg)
    except Exception:
        deg = 0

    dirs = [
        "N", "NNE", "NE", "ENE",
        "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW",
        "W", "WNW", "NW", "NNW",
    ]

    return dirs[int((deg + 11.25) / 22.5) % 16]


def wind_direction_block(deg):
    return {
        "Degrees": int(num(deg, 0)),
        "Localized": deg_to_compass(deg),
        "English": deg_to_compass(deg),
    }


def wind_block(wind_kmh, wind_deg):
    return {
        "Speed": speed_block_kmh(wind_kmh),
        "Direction": wind_direction_block(wind_deg),
    }


def is_daytime_by_icon(icon):
    return str(icon or "").endswith("d")


def precipitation_type(weather_id):
    try:
        wid = int(weather_id)
    except Exception:
        wid = 800

    if 200 <= wid < 600:
        return "Rain"
    if 600 <= wid < 700:
        return "Snow"

    return ""


def has_precipitation(weather_id, pop=0, rain_mm=0, snow_mm=0):
    try:
        wid = int(weather_id)
    except Exception:
        wid = 800

    return (
        200 <= wid < 700
        or float(pop or 0) > 0.1
        or float(rain_mm or 0) > 0
        or float(snow_mm or 0) > 0
    )


def weather_text(description, weather_id=800, is_day=True):
    if description:
        return str(description).strip()

    try:
        wid = int(weather_id)
    except Exception:
        wid = 800

    if 200 <= wid < 300:
        return "гроза"
    if 300 <= wid < 400:
        return "морось"
    if 500 <= wid < 600:
        return "дождь"
    if 600 <= wid < 700:
        return "снег"
    if 700 <= wid < 800:
        return "туман"
    if wid == 800:
        return "ясно"
    if wid == 801:
        return "малооблачно"
    if wid == 802:
        return "переменная облачность"
    if wid in (803, 804):
        return "пасмурно"

    return "облачно"


def accuweather_icon(weather_id=800, owm_icon=None, clouds=0, is_day=True):
    try:
        wid = int(weather_id)
    except Exception:
        wid = 800

    if owm_icon:
        is_day = is_daytime_by_icon(owm_icon)

    if 200 <= wid < 300:
        return 15 if is_day else 42
    if 300 <= wid < 400:
        return 12 if is_day else 40
    if 500 <= wid < 600:
        if wid == 511:
            return 26
        return 18 if is_day else 40
    if 600 <= wid < 700:
        return 22 if is_day else 44
    if 700 <= wid < 800:
        return 11
    if wid == 800:
        return 1 if is_day else 33
    if wid == 801:
        return 3 if is_day else 35
    if wid == 802:
        return 4 if is_day else 36
    if wid in (803, 804):
        return 7 if is_day else 38

    try:
        clouds = int(clouds)
    except Exception:
        clouds = 0

    if clouds <= 10:
        return 1 if is_day else 33
    if clouds <= 40:
        return 3 if is_day else 35
    if clouds <= 75:
        return 6 if is_day else 38

    return 7 if is_day else 38


def air_and_pollen_block():
    return [
        {
            "Name": "AirQuality",
            "Value": 0,
            "Category": "Good",
            "CategoryValue": 1,
            "Type": "Ozone",
        },
        {
            "Name": "Grass",
            "Value": 0,
            "Category": "Low",
            "CategoryValue": 1,
        },
        {
            "Name": "Mold",
            "Value": 0,
            "Category": "Low",
            "CategoryValue": 1,
        },
        {
            "Name": "Ragweed",
            "Value": 0,
            "Category": "Low",
            "CategoryValue": 1,
        },
        {
            "Name": "Tree",
            "Value": 0,
            "Category": "Low",
            "CategoryValue": 1,
        },
        {
            "Name": "UVIndex",
            "Value": 0,
            "Category": "Low",
            "CategoryValue": 1,
        },
    ]


# ============================================================
# Location helpers
# ============================================================

def make_key(lat, lon):
    lat = float(lat)
    lon = float(lon)

    ew = "E" if lon >= 0 else "W"
    lat_i = int(round(abs(lat) * 10000))
    lon_i = int(round(abs(lon) * 10000))

    return f"KP{lat_i:07d}{ew}{lon_i:07d}"


def parse_key(key):
    m = re.match(r"^KP(\d{7})([EW])(\d{7})$", str(key or ""))
    if not m:
        return None

    lat = int(m.group(1)) / 10000.0
    lon = int(m.group(3)) / 10000.0

    if m.group(2) == "W":
        lon = -lon

    return lat, lon


def country_names(country_code):
    if country_code == "UA":
        return "Ukraine", "Украина"

    return country_code or "", country_code or ""


def admin_area(state="", country="UA"):
    state = state or ""

    lower = state.lower()
    if "dnipro" in lower or "дніпр" in lower or "днепр" in lower:
        return {
            "ID": "12",
            "LocalizedName": "Днепропетровская область",
            "EnglishName": "Dnipropetrovsk Oblast",
            "Level": 1,
            "LocalizedType": "Область",
            "EnglishType": "Oblast",
            "CountryID": "UA",
        }

    return {
        "ID": "",
        "LocalizedName": state,
        "EnglishName": state,
        "Level": 1,
        "LocalizedType": "Область",
        "EnglishType": "Oblast",
        "CountryID": country,
    }


def build_location(
    lat,
    lon,
    localized_name="Широкое",
    english_name="Shyroke",
    country="UA",
    state="Dnipropetrovsk Oblast",
):
    key = make_key(lat, lon)
    country_en, country_local = country_names(country)

    obj = {
        "Version": 1,
        "Key": key,
        "Type": "City",
        "Rank": 10,
        "LocalizedName": localized_name,
        "EnglishName": english_name,
        "PrimaryPostalCode": "",
        "Region": {
            "ID": "EUR",
            "LocalizedName": "Европа",
            "EnglishName": "Europe",
        },
        "Country": {
            "ID": country,
            "LocalizedName": country_local,
            "EnglishName": country_en,
        },
        "AdministrativeArea": admin_area(state, country),
        "TimeZone": kyiv_timezone_block(),
        "GeoPosition": {
            "Latitude": float(lat),
            "Longitude": float(lon),
        },
        "IsAlias": False,
        "SupplementalAdminAreas": [],
        "DataSets": [
            "AirQualityCurrentConditions",
            "AirQualityForecasts",
            "Alerts",
            "DailyPollenForecast",
            "ForecastConfidence",
            "MinuteCast",
        ],
    }

    LOCATION_CACHE[key] = obj
    return obj


def default_shyroke_location():
    return build_location(
        47.6846511,
        33.2645369,
        localized_name="Широкое",
        english_name="Shyroke",
        country="UA",
        state="Dnipropetrovsk Oblast",
    )


def location_by_key(key):
    if key in LOCATION_CACHE:
        return LOCATION_CACHE[key]

    parsed = parse_key(key)
    if parsed:
        lat, lon = parsed
        return build_location(
            lat,
            lon,
            localized_name="Широкое",
            english_name="Shyroke",
            country="UA",
            state="Dnipropetrovsk Oblast",
        )

    return default_shyroke_location()


def localized_name_from_owm(item, fallback="Широкое"):
    names = item.get("local_names") or {}
    language = get_lang()

    return (
        names.get(language)
        or names.get("uk")
        or names.get("ru")
        or names.get("en")
        or item.get("name")
        or fallback
    )


def english_name_from_owm(item, fallback="Shyroke"):
    names = item.get("local_names") or {}

    return (
        names.get("en")
        or item.get("name")
        or fallback
    )


def search_locations(q):
    q = (q or "").strip()
    q_lower = q.lower()

    if not q:
        return [default_shyroke_location()]

    if q_lower in ("shyroke", "shiroke", "shyrokoe", "широкое", "широке"):
        return [default_shyroke_location()]

    try:
        data = owm_get(
            "/geo/1.0/direct",
            {
                "q": q,
                "limit": 5,
            },
        )
    except Exception:
        return [default_shyroke_location()]

    result = []

    for item in data:
        lat = item.get("lat")
        lon = item.get("lon")

        if lat is None or lon is None:
            continue

        country = item.get("country") or DEFAULT_COUNTRY
        state = item.get("state") or ""

        result.append(
            build_location(
                lat,
                lon,
                localized_name=localized_name_from_owm(item, q),
                english_name=english_name_from_owm(item, q),
                country=country,
                state=state,
            )
        )

    if not result:
        result = [default_shyroke_location()]

    return result


def reverse_location(lat, lon):
    try:
        data = owm_get(
            "/geo/1.0/reverse",
            {
                "lat": lat,
                "lon": lon,
                "limit": 1,
            },
        )

        if data:
            item = data[0]
            return build_location(
                lat,
                lon,
                localized_name=localized_name_from_owm(item, "Широкое"),
                english_name=english_name_from_owm(item, "Shyroke"),
                country=item.get("country") or "UA",
                state=item.get("state") or "Dnipropetrovsk Oblast",
            )
    except Exception:
        pass

    return build_location(
        lat,
        lon,
        localized_name="Широкое",
        english_name="Shyroke",
        country="UA",
        state="Dnipropetrovsk Oblast",
    )


def parse_geo_query():
    q = (
        request.args.get("q")
        or request.args.get("query")
        or request.args.get("geoposition")
        or request.args.get("geoPosition")
        or ""
    ).strip()

    lat = (
        request.args.get("lat")
        or request.args.get("latitude")
        or request.args.get("Latitude")
    )

    lon = (
        request.args.get("lon")
        or request.args.get("lng")
        or request.args.get("longitude")
        or request.args.get("Longitude")
    )

    if lat and lon:
        try:
            lat_f = float(str(lat).replace(",", "."))
            lon_f = float(str(lon).replace(",", "."))
            return lat_f, lon_f
        except Exception:
            pass

    m = re.match(
        r"^\s*(-?\d+(?:[\.,]\d+)?)\s*,\s*(-?\d+(?:[\.,]\d+)?)\s*$",
        q,
    )

    if m:
        try:
            lat_f = float(m.group(1).replace(",", "."))
            lon_f = float(m.group(2).replace(",", "."))
            return lat_f, lon_f
        except Exception:
            pass

    return None


# ============================================================
# OpenWeather helpers
# ============================================================

def get_current_owm(lat, lon):
    return owm_get(
        "/data/2.5/weather",
        {
            "lat": lat,
            "lon": lon,
            "units": "metric",
            "lang": get_lang(),
        },
    )


def get_forecast_owm(lat, lon):
    return owm_get(
        "/data/2.5/forecast",
        {
            "lat": lat,
            "lon": lon,
            "units": "metric",
            "lang": get_lang(),
        },
    )


def try_onecall_owm(lat, lon):
    try:
        return owm_get(
            "/data/3.0/onecall",
            {
                "lat": lat,
                "lon": lon,
                "exclude": "minutely,alerts",
                "units": "metric",
                "lang": get_lang(),
            },
        )
    except Exception:
        return None


# ============================================================
# Current conditions
# ============================================================

def current_conditions_response(key):
    loc = location_by_key(key)
    lat = loc["GeoPosition"]["Latitude"]
    lon = loc["GeoPosition"]["Longitude"]

    data = get_current_owm(lat, lon)

    main = data.get("main") or {}
    wind = data.get("wind") or {}
    clouds = data.get("clouds") or {}
    weather = (data.get("weather") or [{}])[0]

    dt = to_kyiv(data.get("dt"))
    wid = weather.get("id", 800)
    owm_icon = weather.get("icon")
    is_day = is_daytime_by_icon(owm_icon)

    temp = num(main.get("temp"), 1)
    feels = num(main.get("feels_like", temp), 1)
    humidity = pct(main.get("humidity"))
    pressure = num(main.get("pressure"), 1)
    wind_kmh = num((wind.get("speed") or 0) * 3.6, 1)
    wind_deg = int(wind.get("deg") or 0)
    cloud_cover = pct(clouds.get("all"))
    visibility_km = num((data.get("visibility") or 10000) / 1000.0, 1)

    rain_1h = (data.get("rain") or {}).get("1h") or 0
    snow_1h = (data.get("snow") or {}).get("1h") or 0
    precip_1h = num(rain_1h + snow_1h, 1)

    text = weather_text(weather.get("description"), wid, is_day)
    icon = accuweather_icon(wid, owm_icon, cloud_cover, is_day)
    ptype = precipitation_type(wid)

    return [
        {
            "LocalObservationDateTime": iso_kyiv(dt),
            "EpochTime": epoch(dt),
            "WeatherText": text,
            "WeatherIcon": icon,
            "HasPrecipitation": has_precipitation(wid, rain_mm=rain_1h, snow_mm=snow_1h),
            "PrecipitationType": ptype,
            "IsDayTime": bool(is_day),

            "Temperature": temp_block(temp),
            "RealFeelTemperature": {
                "Metric": {**metric_temp(feels), "Phrase": ""},
                "Imperial": {**imperial_temp(feels), "Phrase": ""},
            },
            "RealFeelTemperatureShade": {
                "Metric": {**metric_temp(feels), "Phrase": ""},
                "Imperial": {**imperial_temp(feels), "Phrase": ""},
            },
            "ApparentTemperature": temp_block(feels),
            "WindChillTemperature": {
                "Metric": {**metric_temp(feels), "Phrase": ""},
                "Imperial": {**imperial_temp(feels), "Phrase": ""},
            },
            "WetBulbTemperature": temp_block(temp),
            "DewPoint": temp_block(num(main.get("temp_min", temp), 1)),

            "RelativeHumidity": humidity,
            "IndoorRelativeHumidity": humidity,

            "Wind": {
                "Direction": wind_direction_block(wind_deg),
                "Speed": speed_block_kmh(wind_kmh),
            },
            "WindGust": {
                "Speed": speed_block_kmh(num((wind.get("gust") or wind.get("speed") or 0) * 3.6, 1)),
            },

            "UVIndex": 0,
            "UVIndexText": "Low",
            "Visibility": distance_block_km(visibility_km),
            "ObstructionsToVisibility": "",
            "CloudCover": cloud_cover,
            "Ceiling": {
                "Metric": {"Value": 0.0, "Unit": "m", "UnitType": 5},
                "Imperial": {"Value": 0.0, "Unit": "ft", "UnitType": 0},
            },

            "Pressure": pressure_block_hpa(pressure),
            "PressureTendency": {
                "LocalizedText": "Steady",
                "Code": "S",
            },

            "Past24HourTemperatureDeparture": temp_block(0),
            "TemperatureSummary": {
                "Past6HourRange": {
                    "Minimum": temp_block(num(main.get("temp_min", temp), 1)),
                    "Maximum": temp_block(num(main.get("temp_max", temp), 1)),
                },
                "Past12HourRange": {
                    "Minimum": temp_block(num(main.get("temp_min", temp), 1)),
                    "Maximum": temp_block(num(main.get("temp_max", temp), 1)),
                },
                "Past24HourRange": {
                    "Minimum": temp_block(num(main.get("temp_min", temp), 1)),
                    "Maximum": temp_block(num(main.get("temp_max", temp), 1)),
                },
            },

            "Precip1hr": mm_block(precip_1h),
            "PrecipitationSummary": {
                "Precipitation": mm_block(precip_1h),
                "PastHour": mm_block(precip_1h),
                "Past3Hours": mm_block(precip_1h),
                "Past6Hours": mm_block(precip_1h),
                "Past9Hours": mm_block(precip_1h),
                "Past12Hours": mm_block(precip_1h),
                "Past18Hours": mm_block(precip_1h),
                "Past24Hours": mm_block(precip_1h),
            },

            "MobileLink": "",
            "Link": "",
        }
    ]


def fallback_current(error=None):
    obj = [{
        "LocalObservationDateTime": iso_kyiv(),
        "EpochTime": epoch(),
        "WeatherText": "пасмурно",
        "WeatherIcon": 7,
        "HasPrecipitation": False,
        "PrecipitationType": "",
        "IsDayTime": True,
        "Temperature": temp_block(20),
        "RealFeelTemperature": {
            "Metric": {**metric_temp(20), "Phrase": ""},
            "Imperial": {**imperial_temp(20), "Phrase": ""},
        },
        "RealFeelTemperatureShade": {
            "Metric": {**metric_temp(20), "Phrase": ""},
            "Imperial": {**imperial_temp(20), "Phrase": ""},
        },
        "RelativeHumidity": 60,
        "Wind": {
            "Direction": wind_direction_block(0),
            "Speed": speed_block_kmh(0),
        },
        "Pressure": pressure_block_hpa(1013),
        "CloudCover": 100,
        "Visibility": distance_block_km(10),
        "MobileLink": "",
        "Link": "",
    }]

    if error:
        obj[0]["ProxyError"] = str(error)

    return obj


# ============================================================
# Daily forecast
# ============================================================

def make_daily_item(
    dt,
    min_c,
    max_c,
    day_icon,
    night_icon,
    phrase,
    weather_id,
    pop,
    rain_mm,
    snow_mm,
    wind_kmh,
    wind_deg,
    humidity,
    clouds,
):
    ptype = precipitation_type(weather_id)
    has_prec = has_precipitation(weather_id, pop, rain_mm, snow_mm)
    pop_percent = pct((pop or 0) * 100 if pop <= 1 else pop)

    precip_intensity = "Light" if has_prec else ""

    day = {
        "Icon": int(day_icon),
        "IconPhrase": phrase,
        "HasPrecipitation": bool(has_prec),
        "PrecipitationType": ptype,
        "PrecipitationIntensity": precip_intensity,
        "ShortPhrase": phrase,
        "LongPhrase": phrase,
        "PrecipitationProbability": pop_percent,
        "ThunderstormProbability": 0,
        "RainProbability": pop_percent if ptype == "Rain" else 0,
        "SnowProbability": pop_percent if ptype == "Snow" else 0,
        "IceProbability": 0,
        "Wind": wind_block(wind_kmh, wind_deg),
        "WindGust": wind_block(wind_kmh, wind_deg),
        "TotalLiquid": mm_block(rain_mm + snow_mm),
        "Rain": mm_block(rain_mm),
        "Snow": mm_block(snow_mm),
        "Ice": mm_block(0),
        "HoursOfPrecipitation": 1 if has_prec else 0,
        "HoursOfRain": 1 if ptype == "Rain" else 0,
        "HoursOfSnow": 1 if ptype == "Snow" else 0,
        "HoursOfIce": 0,
        "CloudCover": pct(clouds),
    }

    night = {
        **day,
        "Icon": int(night_icon),
    }

    return {
        "Date": iso_kyiv(dt),
        "EpochDate": epoch(dt),
        "Sun": {
            "Rise": iso_kyiv(dt.replace(hour=5, minute=0, second=0)),
            "EpochRise": epoch(dt.replace(hour=5, minute=0, second=0)),
            "Set": iso_kyiv(dt.replace(hour=20, minute=45, second=0)),
            "EpochSet": epoch(dt.replace(hour=20, minute=45, second=0)),
        },
        "Moon": {
            "Rise": iso_kyiv(dt.replace(hour=0, minute=0, second=0)),
            "EpochRise": epoch(dt.replace(hour=0, minute=0, second=0)),
            "Set": iso_kyiv(dt.replace(hour=12, minute=0, second=0)),
            "EpochSet": epoch(dt.replace(hour=12, minute=0, second=0)),
            "Phase": "WaxingCrescent",
            "Age": 5,
        },
        "Temperature": {
            "Minimum": daily_temp_value(min_c),
            "Maximum": daily_temp_value(max_c),
        },
        "RealFeelTemperature": {
            "Minimum": daily_temp_value(min_c),
            "Maximum": daily_temp_value(max_c),
        },
        "RealFeelTemperatureShade": {
            "Minimum": daily_temp_value(min_c),
            "Maximum": daily_temp_value(max_c),
        },
        "HoursOfSun": 8.0,
        "DegreeDaySummary": {
            "Heating": daily_temp_value(0),
            "Cooling": daily_temp_value(0),
        },
        "AirAndPollen": air_and_pollen_block(),
        "Day": day,
        "Night": night,
        "Sources": ["OpenWeatherMap"],
        "MobileLink": "",
        "Link": "",
    }


def group_3h_by_day(forecast):
    groups = defaultdict(list)

    for item in forecast.get("list") or []:
        dt = to_kyiv(item.get("dt"))
        groups[dt.date()].append(item)

    return groups


def daily_from_onecall(onecall, count):
    result = []

    for item in (onecall.get("daily") or [])[:count]:
        dt = to_kyiv(item.get("dt"))
        temp = item.get("temp") or {}
        weather = (item.get("weather") or [{}])[0]
        wid = weather.get("id", 800)
        desc = weather_text(weather.get("description"), wid, True)
        clouds = item.get("clouds", 0)
        rain = item.get("rain") or 0
        snow = item.get("snow") or 0
        pop = item.get("pop") or 0

        result.append(
            make_daily_item(
                dt=dt,
                min_c=temp.get("min", temp.get("day", 0)),
                max_c=temp.get("max", temp.get("day", 0)),
                day_icon=accuweather_icon(wid, weather.get("icon"), clouds, True),
                night_icon=accuweather_icon(wid, weather.get("icon"), clouds, False),
                phrase=desc,
                weather_id=wid,
                pop=pop,
                rain_mm=rain,
                snow_mm=snow,
                wind_kmh=(item.get("wind_speed") or 0) * 3.6,
                wind_deg=item.get("wind_deg") or 0,
                humidity=item.get("humidity") or 0,
                clouds=clouds,
            )
        )

    return result


def daily_from_3h_forecast(forecast, count):
    groups = group_3h_by_day(forecast)
    result = []

    for day_date in sorted(groups.keys()):
        items = groups[day_date]
        if not items:
            continue

        temps = []
        pops = []
        rain_total = 0
        snow_total = 0
        clouds_list = []
        humidity_list = []
        wind_speeds = []
        wind_degs = []
        weather_ids = []
        descriptions = []

        for item in items:
            main = item.get("main") or {}
            wind = item.get("wind") or {}
            clouds = item.get("clouds") or {}
            weather = (item.get("weather") or [{}])[0]

            temps.append(main.get("temp"))
            pops.append(item.get("pop") or 0)
            rain_total += (item.get("rain") or {}).get("3h") or 0
            snow_total += (item.get("snow") or {}).get("3h") or 0
            clouds_list.append(clouds.get("all") or 0)
            humidity_list.append(main.get("humidity") or 0)
            wind_speeds.append((wind.get("speed") or 0) * 3.6)
            wind_degs.append(wind.get("deg") or 0)
            weather_ids.append(weather.get("id") or 800)
            descriptions.append(weather.get("description") or "")

        min_c = min([x for x in temps if x is not None] or [0])
        max_c = max([x for x in temps if x is not None] or [0])

        wid = max(set(weather_ids), key=weather_ids.count) if weather_ids else 800
        phrase = next((x for x in descriptions if x), weather_text("", wid, True))
        cloud_avg = sum(clouds_list) / len(clouds_list) if clouds_list else 0
        humidity_avg = sum(humidity_list) / len(humidity_list) if humidity_list else 0
        wind_avg = sum(wind_speeds) / len(wind_speeds) if wind_speeds else 0
        wind_deg = wind_degs[0] if wind_degs else 0
        pop = max(pops or [0])

        dt = datetime(
            day_date.year,
            day_date.month,
            day_date.day,
            12,
            0,
            0,
            tzinfo=KYIV_TZ,
        )

        result.append(
            make_daily_item(
                dt=dt,
                min_c=min_c,
                max_c=max_c,
                day_icon=accuweather_icon(wid, None, cloud_avg, True),
                night_icon=accuweather_icon(wid, None, cloud_avg, False),
                phrase=phrase,
                weather_id=wid,
                pop=pop,
                rain_mm=rain_total,
                snow_mm=snow_total,
                wind_kmh=wind_avg,
                wind_deg=wind_deg,
                humidity=humidity_avg,
                clouds=cloud_avg,
            )
        )

    while len(result) < count and result:
        prev = result[-1]
        prev_dt = datetime.fromtimestamp(prev["EpochDate"], KYIV_TZ)
        new_dt = prev_dt + timedelta(days=1)
        clone = dict(prev)
        clone["Date"] = iso_kyiv(new_dt)
        clone["EpochDate"] = epoch(new_dt)
        result.append(clone)

    return result[:count]


def daily_forecast_response(key, count):
    loc = location_by_key(key)
    lat = loc["GeoPosition"]["Latitude"]
    lon = loc["GeoPosition"]["Longitude"]

    onecall = try_onecall_owm(lat, lon)

    if onecall and onecall.get("daily"):
        items = daily_from_onecall(onecall, count)
    else:
        forecast = get_forecast_owm(lat, lon)
        items = daily_from_3h_forecast(forecast, count)

    if not items:
        n = now_kyiv()
        items = [
            make_daily_item(
                dt=n + timedelta(days=i),
                min_c=15,
                max_c=25,
                day_icon=7,
                night_icon=38,
                phrase="пасмурно",
                weather_id=804,
                pop=0,
                rain_mm=0,
                snow_mm=0,
                wind_kmh=5,
                wind_deg=180,
                humidity=60,
                clouds=100,
            )
            for i in range(count)
        ]

    return {
        "Headline": {
            "EffectiveDate": items[0]["Date"],
            "EffectiveEpochDate": items[0]["EpochDate"],
            "Severity": 7,
            "Text": items[0]["Day"]["IconPhrase"],
            "Category": "general",
            "EndDate": items[-1]["Date"],
            "EndEpochDate": items[-1]["EpochDate"],
            "MobileLink": "",
            "Link": "",
        },
        "DailyForecasts": items,
    }


# ============================================================
# Hourly forecast
# ============================================================

def make_hourly_item(
    dt,
    temp,
    feels,
    weather_id,
    desc,
    clouds,
    pop,
    rain_mm,
    snow_mm,
    wind_kmh,
    wind_deg,
    humidity,
):
    is_day = 6 <= dt.hour <= 20
    phrase = weather_text(desc, weather_id, is_day)
    icon = accuweather_icon(weather_id, None, clouds, is_day)
    ptype = precipitation_type(weather_id)
    has_prec = has_precipitation(weather_id, pop, rain_mm, snow_mm)

    pop_percent = pct((pop or 0) * 100 if pop <= 1 else pop)

    return {
        "DateTime": iso_kyiv(dt),
        "EpochDateTime": epoch(dt),
        "WeatherIcon": icon,
        "IconPhrase": phrase,
        "HasPrecipitation": bool(has_prec),
        "PrecipitationType": ptype,
        "PrecipitationIntensity": "Light" if has_prec else "",
        "IsDaylight": bool(is_day),
        "Temperature": metric_temp(temp),
        "RealFeelTemperature": metric_temp(feels),
        "WetBulbTemperature": metric_temp(temp),
        "DewPoint": metric_temp(num(temp, 1) - 2),
        "Wind": {
            "Speed": speed_block_kmh(wind_kmh),
            "Direction": wind_direction_block(wind_deg),
        },
        "WindGust": {
            "Speed": speed_block_kmh(wind_kmh),
        },
        "RelativeHumidity": pct(humidity),
        "Visibility": distance_block_km(10),
        "Ceiling": {
            "Metric": {"Value": 0.0, "Unit": "m", "UnitType": 5},
            "Imperial": {"Value": 0.0, "Unit": "ft", "UnitType": 0},
        },
        "UVIndex": 0,
        "UVIndexText": "Low",
        "PrecipitationProbability": pop_percent,
        "RainProbability": pop_percent if ptype == "Rain" else 0,
        "SnowProbability": pop_percent if ptype == "Snow" else 0,
        "IceProbability": 0,
        "TotalLiquid": mm_block(rain_mm + snow_mm),
        "Rain": mm_block(rain_mm),
        "Snow": mm_block(snow_mm),
        "Ice": mm_block(0),
        "CloudCover": pct(clouds),
        "MobileLink": "",
        "Link": "",
    }


def hourly_forecast_response(key):
    loc = location_by_key(key)
    lat = loc["GeoPosition"]["Latitude"]
    lon = loc["GeoPosition"]["Longitude"]

    onecall = try_onecall_owm(lat, lon)
    result = []

    if onecall and onecall.get("hourly"):
        for item in onecall["hourly"][:12]:
            dt = to_kyiv(item.get("dt"))
            weather = (item.get("weather") or [{}])[0]

            result.append(
                make_hourly_item(
                    dt=dt,
                    temp=item.get("temp", 0),
                    feels=item.get("feels_like", item.get("temp", 0)),
                    weather_id=weather.get("id", 800),
                    desc=weather.get("description", ""),
                    clouds=item.get("clouds", 0),
                    pop=item.get("pop", 0),
                    rain_mm=(item.get("rain") or {}).get("1h", 0),
                    snow_mm=(item.get("snow") or {}).get("1h", 0),
                    wind_kmh=(item.get("wind_speed") or 0) * 3.6,
                    wind_deg=item.get("wind_deg", 0),
                    humidity=item.get("humidity", 0),
                )
            )

        return result

    forecast = get_forecast_owm(lat, lon)
    items = forecast.get("list") or []

    expanded = []
    for item in items[:6]:
        dt3 = to_kyiv(item.get("dt"))
        for h in range(3):
            clone = dict(item)
            clone["_dt_hour"] = dt3 - timedelta(hours=2 - h)
            expanded.append(clone)

    expanded = [x for x in expanded if x["_dt_hour"] >= now_kyiv() - timedelta(hours=1)]
    expanded = expanded[:12]

    for item in expanded:
        main = item.get("main") or {}
        wind = item.get("wind") or {}
        clouds = item.get("clouds") or {}
        weather = (item.get("weather") or [{}])[0]

        result.append(
            make_hourly_item(
                dt=item["_dt_hour"],
                temp=main.get("temp", 0),
                feels=main.get("feels_like", main.get("temp", 0)),
                weather_id=weather.get("id", 800),
                desc=weather.get("description", ""),
                clouds=clouds.get("all", 0),
                pop=item.get("pop", 0),
                rain_mm=((item.get("rain") or {}).get("3h", 0)) / 3,
                snow_mm=((item.get("snow") or {}).get("3h", 0)) / 3,
                wind_kmh=(wind.get("speed") or 0) * 3.6,
                wind_deg=wind.get("deg", 0),
                humidity=main.get("humidity", 0),
            )
        )

    while len(result) < 12:
        base = result[-1] if result else None
        dt = (
            datetime.fromtimestamp(base["EpochDateTime"], KYIV_TZ) + timedelta(hours=1)
            if base
            else now_kyiv().replace(minute=0, second=0, microsecond=0)
        )

        result.append(
            make_hourly_item(
                dt=dt,
                temp=base["Temperature"]["Value"] if base else 20,
                feels=base["RealFeelTemperature"]["Value"] if base else 20,
                weather_id=804,
                desc="пасмурно",
                clouds=100,
                pop=0,
                rain_mm=0,
                snow_mm=0,
                wind_kmh=5,
                wind_deg=180,
                humidity=60,
            )
        )

    return result[:12]


# ============================================================
# Routes
# ============================================================

@app.before_request
def log_request():
    print(
        f"{request.remote_addr} {request.method} {request.path}?{request.query_string.decode('utf-8', 'ignore')}",
        flush=True,
    )


@app.after_request
def add_headers(resp):
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@app.route("/")
@app.route("/status")
def status():
    return jsonify(
        {
            "status": "ok",
            "version": VERSION,
            "openweather_key_present": bool(OPENWEATHER_API_KEY),
            "timezone": kyiv_timezone_block(),
            "now": iso_kyiv(),
            "routes": [
                "/locations/v1/search",
                "/locations/v1/cities/geoposition/search",
                "/locations/v1/cities/geoposition/search.json",
                "/locations/v1/timezones",
                "/locations/v1/<key>",
                "/currentconditions/v1/<key>",
                "/forecasts/v1/daily/10day/<key>",
                "/forecasts/v1/daily/5day/<key>",
                "/forecasts/v1/hourly/12hour/<key>",
                "/widget/htc2/city-find.asp",
            ],
        }
    )


@app.route("/locations/v1/search")
def route_locations_search():
    q = request.args.get("q") or request.args.get("query") or ""
    return jsonify(search_locations(q))


@app.route("/locations/v1/cities/geoposition/search")
@app.route("/locations/v1/cities/geoposition/search.json")
def route_geoposition_search():
    parsed = parse_geo_query()

    if parsed:
        lat, lon = parsed
        return jsonify(reverse_location(lat, lon))

    q = (
        request.args.get("q")
        or request.args.get("query")
        or request.args.get("geoposition")
        or request.args.get("geoPosition")
        or ""
    ).strip()

    if q:
        found = search_locations(q)
        if found:
            return jsonify(found[0])

    return jsonify(default_shyroke_location())


@app.route("/locations/v1/timezones")
def route_timezones():
    return jsonify([kyiv_timezone_block()])


@app.route("/locations/v1/<key>")
def route_location_by_key(key):
    return jsonify(location_by_key(key))


@app.route("/currentconditions/v1/<key>")
def route_currentconditions(key):
    try:
        return jsonify(current_conditions_response(key))
    except Exception as e:
        print(f"currentconditions fallback: {e}", flush=True)
        return jsonify(fallback_current(e))


@app.route("/forecasts/v1/daily/10day/<key>")
def route_forecast_10day(key):
    try:
        return jsonify(daily_forecast_response(key, 10))
    except Exception as e:
        print(f"10day fallback: {e}", flush=True)
        n = now_kyiv()

        items = [
            make_daily_item(
                dt=n + timedelta(days=i),
                min_c=15,
                max_c=25,
                day_icon=7,
                night_icon=38,
                phrase="пасмурно",
                weather_id=804,
                pop=0,
                rain_mm=0,
                snow_mm=0,
                wind_kmh=5,
                wind_deg=180,
                humidity=60,
                clouds=100,
            )
            for i in range(10)
        ]

        return jsonify(
            {
                "Headline": {
                    "EffectiveDate": items[0]["Date"],
                    "EffectiveEpochDate": items[0]["EpochDate"],
                    "Severity": 7,
                    "Text": "Прогноз временно недоступен",
                    "Category": "general",
                    "EndDate": items[-1]["Date"],
                    "EndEpochDate": items[-1]["EpochDate"],
                    "MobileLink": "",
                    "Link": "",
                },
                "DailyForecasts": items,
                "ProxyError": str(e),
            }
        )


@app.route("/forecasts/v1/daily/5day/<key>")
def route_forecast_5day(key):
    try:
        return jsonify(daily_forecast_response(key, 5))
    except Exception as e:
        print(f"5day fallback: {e}", flush=True)
        n = now_kyiv()

        items = [
            make_daily_item(
                dt=n + timedelta(days=i),
                min_c=15,
                max_c=25,
                day_icon=7,
                night_icon=38,
                phrase="пасмурно",
                weather_id=804,
                pop=0,
                rain_mm=0,
                snow_mm=0,
                wind_kmh=5,
                wind_deg=180,
                humidity=60,
                clouds=100,
            )
            for i in range(5)
        ]

        return jsonify(
            {
                "Headline": {
                    "EffectiveDate": items[0]["Date"],
                    "EffectiveEpochDate": items[0]["EpochDate"],
                    "Severity": 7,
                    "Text": "Прогноз временно недоступен",
                    "Category": "general",
                    "EndDate": items[-1]["Date"],
                    "EndEpochDate": items[-1]["EpochDate"],
                    "MobileLink": "",
                    "Link": "",
                },
                "DailyForecasts": items,
                "ProxyError": str(e),
            }
        )


@app.route("/forecasts/v1/hourly/12hour/<key>")
def route_forecast_12hour(key):
    try:
        return jsonify(hourly_forecast_response(key))
    except Exception as e:
        print(f"12hour fallback: {e}", flush=True)
        n = now_kyiv().replace(minute=0, second=0, microsecond=0)

        return jsonify(
            [
                make_hourly_item(
                    dt=n + timedelta(hours=i),
                    temp=20,
                    feels=20,
                    weather_id=804,
                    desc="пасмурно",
                    clouds=100,
                    pop=0,
                    rain_mm=0,
                    snow_mm=0,
                    wind_kmh=5,
                    wind_deg=180,
                    humidity=60,
                )
                for i in range(12)
            ]
        )


@app.route("/widget/htc2/city-find.asp")
def route_htc_city_find():
    q = (
        request.args.get("q")
        or request.args.get("ac")
        or request.args.get("city")
        or request.args.get("name")
        or ""
    )

    locations = search_locations(q)
    tz = kyiv_timezone_block()

    rows = []

    for loc in locations:
        rows.append(
            f'<location '
            f'key="{loc["Key"]}" '
            f'name="{loc["LocalizedName"]}" '
            f'city="{loc["LocalizedName"]}" '
            f'english="{loc["EnglishName"]}" '
            f'country="{loc["Country"]["ID"]}" '
            f'latitude="{loc["GeoPosition"]["Latitude"]}" '
            f'longitude="{loc["GeoPosition"]["Longitude"]}" '
            f'timezone="Europe/Kyiv" '
            f'gmtOffset="{tz["GmtOffset"]}" '
            f'/>'
        )

    xml = '<?xml version="1.0" encoding="UTF-8"?><locations>' + "".join(rows) + "</locations>"
    return Response(xml, content_type="text/xml; charset=utf-8")


@app.route("/favicon.ico")
def favicon():
    return Response("", status=204)


@app.errorhandler(404)
def not_found(e):
    return jsonify(
        {
            "status": "not_found",
            "path": request.path,
            "version": VERSION,
        }
    ), 404


@app.errorhandler(Exception)
def handle_exception(e):
    print(f"proxy error: {e}", flush=True)
    return jsonify(
        {
            "status": "error",
            "error": str(e),
            "path": request.path,
            "version": VERSION,
        }
    ), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    host = os.environ.get("HOST", "0.0.0.0")
    app.run(host=host, port=port)
