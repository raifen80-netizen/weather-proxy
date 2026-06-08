# weather_proxy.py
# HTC Weather / WeatherClock proxy for Android 15
# Version: htc-weather-proxy-v13-force-hourly-daytime
#
# Render Start Command:
#   gunicorn weather_proxy:app
#
# requirements.txt:
#   flask
#   requests
#   tzdata
#   gunicorn
#
# Render Environment:
#   OPENWEATHER_API_KEY = your OpenWeatherMap API key

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests
from flask import Flask, Response, jsonify, request

app = Flask(__name__)
app.json.ensure_ascii = False

VERSION = "htc-weather-proxy-v13-force-hourly-daytime"

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "").strip()
OWM_BASE = "https://api.openweathermap.org"

DEFAULT_LANGUAGE = "ru"
DEFAULT_TZ_NAME = "Europe/Kyiv"
KYIV_TZ = ZoneInfo(DEFAULT_TZ_NAME)

SHYROKE_KEY = "324178"
OLD_SHYROKE_KEY = "KP0476847E0332645"
SHYROKE_LAT = 47.6846511
SHYROKE_LON = 33.2645369
SHYROKE_NAME_RU = "Широке"
SHYROKE_NAME_EN = "Shyroke"
SHYROKE_ADMIN = "Днепропетровская область"
SHYROKE_COUNTRY = "UA"

_CACHE: Dict[str, Tuple[float, Any]] = {}
CACHE_SECONDS = 600


def now_kyiv() -> datetime:
    return datetime.now(KYIV_TZ)


def local_iso(dt: datetime) -> str:
    return dt.astimezone(KYIV_TZ).isoformat(timespec="seconds")


def epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def get_language() -> str:
    lang = request.args.get("language") or request.args.get("lang") or DEFAULT_LANGUAGE
    lang = lang.lower().split("-")[0]
    if lang not in {"ru", "uk", "en"}:
        lang = DEFAULT_LANGUAGE
    return lang


def cache_get(key: str) -> Optional[Any]:
    hit = _CACHE.get(key)
    if not hit:
        return None

    ts, data = hit
    if time.time() - ts > CACHE_SECONDS:
        _CACHE.pop(key, None)
        return None

    return data


def cache_set(key: str, data: Any) -> Any:
    _CACHE[key] = (time.time(), data)
    return data


def require_api_key() -> Optional[Response]:
    if not OPENWEATHER_API_KEY:
        return jsonify({
            "error": "OPENWEATHER_API_KEY is not set",
            "version": VERSION,
        }), 500
    return None


def owm_get(path: str, params: Dict[str, Any], cache_key: str) -> Any:
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    if not OPENWEATHER_API_KEY:
        raise RuntimeError("OPENWEATHER_API_KEY is not set")

    final_params = dict(params)
    final_params["appid"] = OPENWEATHER_API_KEY

    url = f"{OWM_BASE}{path}"
    r = requests.get(url, params=final_params, timeout=15)
    r.raise_for_status()

    return cache_set(cache_key, r.json())


def round1(value: Any, default: float = 0.0) -> float:
    try:
        return round(float(value), 1)
    except Exception:
        return default


def round0(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except Exception:
        return default


def c_to_f(c: float) -> float:
    return round((c * 9 / 5) + 32, 1)


def ms_to_kmh(ms: Any) -> float:
    try:
        return round(float(ms) * 3.6, 1)
    except Exception:
        return 0.0


def deg_to_dir(deg: Any) -> str:
    try:
        d = float(deg) % 360
    except Exception:
        return "N"

    dirs = [
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    ]
    return dirs[int((d + 11.25) / 22.5) % 16]


def metric_value(value: Any, unit: str, unit_type: int) -> Dict[str, Any]:
    return {
        "Value": value,
        "Unit": unit,
        "UnitType": unit_type,
    }


def temp_block_c(c: Any) -> Dict[str, Any]:
    c = round1(c)
    return {
        "Metric": metric_value(c, "C", 17),
        "Imperial": metric_value(c_to_f(c), "F", 18),
    }


def timezone_block() -> Dict[str, Any]:
    return {
        "Code": "EEST",
        "GmtOffset": 3,
        "IsDaylightSaving": True,
        "Name": DEFAULT_TZ_NAME,
        "NextOffsetChange": "",
    }


def parse_location_key(location_key: str) -> Tuple[float, float, str, str, str, str]:
    key = str(location_key or "").strip()

    if key in {"", "0", SHYROKE_KEY, OLD_SHYROKE_KEY, "shyroke", "Shyroke"}:
        return (
            SHYROKE_LAT,
            SHYROKE_LON,
            SHYROKE_KEY,
            SHYROKE_NAME_RU,
            SHYROKE_ADMIN,
            SHYROKE_COUNTRY,
        )

    if "," in key:
        try:
            lat_s, lon_s = key.split(",", 1)
            lat = float(lat_s.strip())
            lon = float(lon_s.strip())
            return (lat, lon, key, "Current location", "", "")
        except Exception:
            pass

    return (
        SHYROKE_LAT,
        SHYROKE_LON,
        SHYROKE_KEY,
        SHYROKE_NAME_RU,
        SHYROKE_ADMIN,
        SHYROKE_COUNTRY,
    )


def location_object(
    key: str = SHYROKE_KEY,
    name: str = SHYROKE_NAME_RU,
    lat: float = SHYROKE_LAT,
    lon: float = SHYROKE_LON,
    admin: str = SHYROKE_ADMIN,
    country: str = SHYROKE_COUNTRY,
) -> Dict[str, Any]:
    return {
        "Version": 1,
        "Key": str(key),
        "Type": "City",
        "Rank": 35,
        "LocalizedName": name,
        "EnglishName": SHYROKE_NAME_EN if str(key) == SHYROKE_KEY else name,
        "PrimaryPostalCode": "",
        "Region": {
            "ID": "EUR",
            "LocalizedName": "Европа",
            "EnglishName": "Europe",
        },
        "Country": {
            "ID": country or "UA",
            "LocalizedName": "Украина" if (country or "UA") == "UA" else country,
            "EnglishName": "Ukraine" if (country or "UA") == "UA" else country,
        },
        "AdministrativeArea": {
            "ID": "",
            "LocalizedName": admin or "",
            "EnglishName": admin or "",
            "Level": 1,
            "LocalizedType": "область",
            "EnglishType": "Oblast",
            "CountryID": country or "UA",
        },
        "TimeZone": timezone_block(),
        "GeoPosition": {
            "Latitude": lat,
            "Longitude": lon,
            "Elevation": {
                "Metric": metric_value(0, "m", 5),
                "Imperial": metric_value(0, "ft", 0),
            },
        },
        "IsAlias": False,
        "SupplementalAdminAreas": [],
        "DataSets": [
            "AirQualityCurrentConditions",
            "AirQualityForecasts",
            "Alerts",
            "DailyAirQualityForecast",
            "DailyPollenForecast",
            "ForecastConfidence",
            "MinuteCast",
        ],
    }


def search_locations(q: str, lang: str) -> List[Dict[str, Any]]:
    q_clean = (q or "").strip().lower()

    if not q_clean:
        return [location_object()]

    if any(x in q_clean for x in ["shyroke", "shiroke", "широке", "широкое"]):
        return [location_object()]

    try:
        data = owm_get(
            "/geo/1.0/direct",
            {"q": q, "limit": 5},
            f"geo_direct:{lang}:{q}",
        )

        out: List[Dict[str, Any]] = []
        for idx, item in enumerate(data or []):
            lat = float(item.get("lat"))
            lon = float(item.get("lon"))
            name = item.get("local_names", {}).get(lang) or item.get("name") or q
            admin = item.get("state") or ""
            country = item.get("country") or ""
            key = f"OWM{idx}_{round(lat, 5)}_{round(lon, 5)}".replace(".", "p").replace("-", "m")
            out.append(location_object(key, name, lat, lon, admin, country))

        return out or [location_object()]
    except Exception:
        return [location_object()]


def reverse_geoposition(q: str, lang: str) -> Dict[str, Any]:
    try:
        lat_s, lon_s = q.split(",", 1)
        lat = float(lat_s.strip())
        lon = float(lon_s.strip())
    except Exception:
        lat, lon = SHYROKE_LAT, SHYROKE_LON

    if abs(lat - SHYROKE_LAT) < 0.35 and abs(lon - SHYROKE_LON) < 0.35:
        return location_object()

    try:
        data = owm_get(
            "/geo/1.0/reverse",
            {"lat": lat, "lon": lon, "limit": 1},
            f"geo_reverse:{lang}:{lat:.5f},{lon:.5f}",
        )

        if data:
            item = data[0]
            name = item.get("local_names", {}).get(lang) or item.get("name") or "Current location"
            admin = item.get("state") or ""
            country = item.get("country") or ""
            key = f"OWM_{round(lat, 5)}_{round(lon, 5)}".replace(".", "p").replace("-", "m")
            return location_object(key, name, lat, lon, admin, country)
    except Exception:
        pass

    return location_object(SHYROKE_KEY, SHYROKE_NAME_RU, lat, lon, SHYROKE_ADMIN, SHYROKE_COUNTRY)


def owm_phrase(weather: Dict[str, Any], lang: str) -> str:
    desc = (weather or {}).get("description") or (weather or {}).get("main") or ""
    desc = str(desc).strip()
    if desc:
        return desc
    return "Переменная облачность" if lang == "ru" else "Partly cloudy"


def accu_icon_from_owm(weather_id: int, clouds: int, is_day: bool) -> int:
    wid = int(weather_id or 800)
    c = int(clouds or 0)

    if 200 <= wid <= 232:
        return 15 if is_day else 41

    if 300 <= wid <= 321:
        return 12 if is_day else 39

    if 500 <= wid <= 504:
        return 18

    if wid == 511:
        return 26

    if 520 <= wid <= 531:
        return 12 if is_day else 39

    if 600 <= wid <= 622:
        return 22

    if 701 <= wid <= 781:
        return 11

    if wid == 800:
        return 1 if is_day else 33

    if 801 <= wid <= 804:
        if c <= 25:
            return 2 if is_day else 34
        if c <= 50:
            return 3 if is_day else 35
        if c <= 75:
            return 6 if is_day else 38
        return 7 if is_day else 38

    return 3 if is_day else 35


def precipitation_from_owm(weather_id: int) -> Tuple[bool, str, str]:
    wid = int(weather_id or 800)

    if 200 <= wid <= 232:
        return True, "Rain", "Heavy"

    if 300 <= wid <= 321:
        return True, "Rain", "Light"

    if 500 <= wid <= 504:
        return True, "Rain", "Moderate"

    if wid == 511:
        return True, "Ice", "Moderate"

    if 520 <= wid <= 531:
        return True, "Rain", "Moderate"

    if 600 <= wid <= 622:
        return True, "Snow", "Moderate"

    return False, "", ""


def make_daynight_block(item: Dict[str, Any], lang: str, force_day: bool) -> Dict[str, Any]:
    weather = (item.get("weather") or [{}])[0]
    weather_id = int(weather.get("id", 800))
    clouds = int((item.get("clouds") or {}).get("all", 0))
    phrase = owm_phrase(weather, lang)
    icon = accu_icon_from_owm(weather_id, clouds, force_day)
    has_precip, precip_type, precip_intensity = precipitation_from_owm(weather_id)

    wind = item.get("wind") or {}
    wind_ms = wind.get("speed", 0)
    wind_deg = wind.get("deg", 0)
    pop = round0(float(item.get("pop", 0)) * 100, 0)

    rain_mm = 0.0
    snow_mm = 0.0

    if isinstance(item.get("rain"), dict):
        rain_mm = round1(item["rain"].get("3h", 0.0))

    if isinstance(item.get("snow"), dict):
        snow_mm = round1(item["snow"].get("3h", 0.0))

    return {
        "Icon": icon,
        "IconPhrase": phrase,
        "HasPrecipitation": has_precip,
        "PrecipitationType": precip_type,
        "PrecipitationIntensity": precip_intensity,
        "ShortPhrase": phrase,
        "LongPhrase": phrase,
        "PrecipitationProbability": pop,
        "ThunderstormProbability": pop if 200 <= weather_id <= 232 else 0,
        "RainProbability": pop if precip_type == "Rain" else 0,
        "SnowProbability": pop if precip_type == "Snow" else 0,
        "IceProbability": pop if precip_type == "Ice" else 0,
        "Wind": {
            "Direction": {
                "Degrees": round0(wind_deg),
                "Localized": deg_to_dir(wind_deg),
                "English": deg_to_dir(wind_deg),
            },
            "Speed": {
                "Metric": metric_value(ms_to_kmh(wind_ms), "km/h", 7),
                "Imperial": metric_value(round1(ms_to_kmh(wind_ms) / 1.60934), "mi/h", 9),
            },
        },
        "WindGust": {
            "Speed": {
                "Metric": metric_value(ms_to_kmh(wind.get("gust", wind_ms)), "km/h", 7),
                "Imperial": metric_value(round1(ms_to_kmh(wind.get("gust", wind_ms)) / 1.60934), "mi/h", 9),
            },
        },
        "Rain": {
            "Value": rain_mm,
            "Unit": "mm",
            "UnitType": 3,
        },
        "Snow": {
            "Value": snow_mm,
            "Unit": "cm",
            "UnitType": 4,
        },
        "Ice": {
            "Value": 0.0,
            "Unit": "mm",
            "UnitType": 3,
        },
        "HoursOfPrecipitation": 1 if has_precip else 0,
        "HoursOfRain": 1 if precip_type == "Rain" else 0,
        "HoursOfSnow": 1 if precip_type == "Snow" else 0,
        "HoursOfIce": 1 if precip_type == "Ice" else 0,
        "CloudCover": clouds,
    }


def default_forecast_item(dt: datetime, temp_c: float = 22.0) -> Dict[str, Any]:
    return {
        "dt": epoch(dt),
        "dt_txt": dt.strftime("%Y-%m-%d %H:%M:%S"),
        "main": {
            "temp": temp_c,
            "temp_min": temp_c - 2,
            "temp_max": temp_c + 2,
            "feels_like": temp_c,
            "humidity": 60,
            "pressure": 1012,
        },
        "weather": [{
            "id": 801,
            "main": "Clouds",
            "description": "облачно с прояснениями",
            "icon": "02d",
        }],
        "clouds": {
            "all": 50,
        },
        "wind": {
            "speed": 3.0,
            "deg": 90,
        },
        "pop": 0.0,
    }


def air_and_pollen() -> List[Dict[str, Any]]:
    names = ["AirQuality", "Grass", "Mold", "Ragweed", "Tree", "UVIndex"]

    out = []
    for name in names:
        out.append({
            "Name": name,
            "Value": 0,
            "Category": "Good" if name != "UVIndex" else "Low",
            "CategoryValue": 1,
            "Type": name,
        })

    return out


def make_headline() -> Dict[str, Any]:
    dt = now_kyiv()

    return {
        "EffectiveDate": local_iso(dt),
        "EffectiveEpochDate": epoch(dt),
        "Severity": 7,
        "Text": "Прогноз обновлён через HTC Weather Proxy",
        "Category": "general",
        "EndDate": None,
        "EndEpochDate": None,
        "MobileLink": "",
        "Link": "",
    }


def normalize_daily_forecasts_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    forecasts = payload.get("DailyForecasts", [])

    for f in forecasts:
        day = f.get("Day")
        night = f.get("Night")

        if not isinstance(day, dict):
            day = {}

        if not isinstance(night, dict):
            night = {}

        if not day.get("IconPhrase") and night.get("IconPhrase"):
            day["IconPhrase"] = night.get("IconPhrase")

        if not day.get("ShortPhrase"):
            day["ShortPhrase"] = day.get("IconPhrase", "Переменная облачность")

        if not day.get("LongPhrase"):
            day["LongPhrase"] = day.get("IconPhrase", "Переменная облачность")

        if "Icon" not in day or not day.get("Icon") or int(day.get("Icon", 3)) >= 33:
            day["Icon"] = 3

        if "HasPrecipitation" not in day:
            day["HasPrecipitation"] = False

        if "PrecipitationType" not in day or day["PrecipitationType"] is None:
            day["PrecipitationType"] = ""

        if "PrecipitationIntensity" not in day or day["PrecipitationIntensity"] is None:
            day["PrecipitationIntensity"] = ""

        if not night.get("IconPhrase"):
            night["IconPhrase"] = day.get("IconPhrase", "Переменная облачность")

        if not night.get("ShortPhrase"):
            night["ShortPhrase"] = night.get("IconPhrase", day.get("IconPhrase", ""))

        if not night.get("LongPhrase"):
            night["LongPhrase"] = night.get("IconPhrase", day.get("IconPhrase", ""))

        if "Icon" not in night or not night.get("Icon"):
            night["Icon"] = day.get("Icon", 3)

        if "HasPrecipitation" not in night:
            night["HasPrecipitation"] = False

        if "PrecipitationType" not in night or night["PrecipitationType"] is None:
            night["PrecipitationType"] = ""

        if "PrecipitationIntensity" not in night or night["PrecipitationIntensity"] is None:
            night["PrecipitationIntensity"] = ""

        if "AirAndPollen" not in f or not isinstance(f.get("AirAndPollen"), list) or len(f["AirAndPollen"]) < 6:
            f["AirAndPollen"] = air_and_pollen()

        f["Day"] = day
        f["Night"] = night

    payload["DailyForecasts"] = forecasts
    return payload


def force_day_forecast_into_night(payload: Dict[str, Any]) -> Dict[str, Any]:
    forecasts = payload.get("DailyForecasts", [])

    for f in forecasts:
        day = f.get("Day")
        night = f.get("Night")

        if not isinstance(day, dict):
            continue

        if not isinstance(night, dict):
            night = {}

        night["Icon"] = day.get("Icon", night.get("Icon", 3))
        night["IconPhrase"] = day.get("IconPhrase", night.get("IconPhrase", ""))
        night["ShortPhrase"] = day.get("ShortPhrase", day.get("IconPhrase", night.get("ShortPhrase", "")))
        night["LongPhrase"] = day.get("LongPhrase", day.get("IconPhrase", night.get("LongPhrase", "")))
        night["HasPrecipitation"] = day.get("HasPrecipitation", False)
        night["PrecipitationType"] = day.get("PrecipitationType", "")
        night["PrecipitationIntensity"] = day.get("PrecipitationIntensity", "")

        for key in [
            "PrecipitationProbability",
            "ThunderstormProbability",
            "RainProbability",
            "SnowProbability",
            "IceProbability",
            "Wind",
            "WindGust",
            "Rain",
            "Snow",
            "Ice",
            "HoursOfPrecipitation",
            "HoursOfRain",
            "HoursOfSnow",
            "HoursOfIce",
            "CloudCover",
        ]:
            if key in day:
                night[key] = day[key]

        f["Night"] = night

    payload["DailyForecasts"] = forecasts
    return payload


def build_daily_forecast_payload(location_key: str, lang: str) -> Dict[str, Any]:
    lat, lon, key, name, admin, country = parse_location_key(location_key)

    data = owm_get(
        "/data/2.5/forecast",
        {
            "lat": lat,
            "lon": lon,
            "units": "metric",
            "lang": lang,
        },
        f"forecast5:{lang}:{lat:.5f},{lon:.5f}",
    )

    items = data.get("list") or []
    by_day: Dict[str, List[Dict[str, Any]]] = {}

    for item in items:
        dt = datetime.fromtimestamp(int(item.get("dt")), tz=timezone.utc).astimezone(KYIV_TZ)
        by_day.setdefault(dt.strftime("%Y-%m-%d"), []).append(item)

    today = now_kyiv().date()
    forecasts: List[Dict[str, Any]] = []

    for offset in range(1, 11):
        d = today + timedelta(days=offset)
        day_key = d.strftime("%Y-%m-%d")
        day_items = by_day.get(day_key, [])

        if not day_items:
            last_temp = 22.0
            if forecasts:
                last_temp = forecasts[-1]["Temperature"]["Maximum"]["Value"]

            fake_dt = datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=KYIV_TZ)
            day_items = [default_forecast_item(fake_dt, last_temp)]

        def item_dt(it: Dict[str, Any]) -> datetime:
            return datetime.fromtimestamp(int(it.get("dt", epoch(now_kyiv()))), tz=timezone.utc).astimezone(KYIV_TZ)

        day_item = min(day_items, key=lambda it: abs(item_dt(it).hour - 12))
        night_item = min(day_items, key=lambda it: min(abs(item_dt(it).hour - 21), abs(item_dt(it).hour - 0)))

        temps = []
        for it in day_items:
            main = it.get("main") or {}
            temps.append(round1(main.get("temp_min", main.get("temp", 0))))
            temps.append(round1(main.get("temp_max", main.get("temp", 0))))

        min_c = min(temps) if temps else round1((day_item.get("main") or {}).get("temp_min", 0))
        max_c = max(temps) if temps else round1((day_item.get("main") or {}).get("temp_max", 0))

        noon = datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=KYIV_TZ)

        day_block = make_daynight_block(day_item, lang, True)
        night_block = make_daynight_block(night_item, lang, False)

        forecast = {
            "Date": local_iso(noon),
            "EpochDate": epoch(noon),
            "Sun": {
                "Rise": local_iso(datetime(d.year, d.month, d.day, 5, 0, 0, tzinfo=KYIV_TZ)),
                "EpochRise": epoch(datetime(d.year, d.month, d.day, 5, 0, 0, tzinfo=KYIV_TZ)),
                "Set": local_iso(datetime(d.year, d.month, d.day, 20, 45, 0, tzinfo=KYIV_TZ)),
                "EpochSet": epoch(datetime(d.year, d.month, d.day, 20, 45, 0, tzinfo=KYIV_TZ)),
            },
            "Moon": {
                "Rise": local_iso(datetime(d.year, d.month, d.day, 22, 0, 0, tzinfo=KYIV_TZ)),
                "EpochRise": epoch(datetime(d.year, d.month, d.day, 22, 0, 0, tzinfo=KYIV_TZ)),
                "Set": local_iso(datetime(d.year, d.month, d.day, 7, 0, 0, tzinfo=KYIV_TZ)),
                "EpochSet": epoch(datetime(d.year, d.month, d.day, 7, 0, 0, tzinfo=KYIV_TZ)),
                "Phase": "WaxingCrescent",
                "Age": offset,
            },
            "Temperature": {
                "Minimum": metric_value(round1(min_c), "C", 17),
                "Maximum": metric_value(round1(max_c), "C", 17),
            },
            "RealFeelTemperature": {
                "Minimum": metric_value(round1(min_c), "C", 17),
                "Maximum": metric_value(round1(max_c), "C", 17),
            },
            "RealFeelTemperatureShade": {
                "Minimum": metric_value(round1(min_c), "C", 17),
                "Maximum": metric_value(round1(max_c), "C", 17),
            },
            "HoursOfSun": 8.0,
            "DegreeDaySummary": {
                "Heating": metric_value(0, "C", 17),
                "Cooling": metric_value(0, "C", 17),
            },
            "AirAndPollen": air_and_pollen(),
            "Day": day_block,
            "Night": night_block,
            "Sources": ["OpenWeatherMap"],
            "MobileLink": "",
            "Link": "",
        }

        forecasts.append(forecast)

    payload = {
        "Headline": make_headline(),
        "DailyForecasts": forecasts,
    }

    payload = normalize_daily_forecasts_payload(payload)
    payload = force_day_forecast_into_night(payload)

    return payload


def build_current_conditions(location_key: str, lang: str) -> List[Dict[str, Any]]:
    lat, lon, key, name, admin, country = parse_location_key(location_key)

    data = owm_get(
        "/data/2.5/weather",
        {
            "lat": lat,
            "lon": lon,
            "units": "metric",
            "lang": lang,
        },
        f"current:{lang}:{lat:.5f},{lon:.5f}",
    )

    dt = datetime.fromtimestamp(int(data.get("dt", time.time())), tz=timezone.utc).astimezone(KYIV_TZ)
    weather = (data.get("weather") or [{}])[0]
    weather_id = int(weather.get("id", 800))
    clouds = int((data.get("clouds") or {}).get("all", 0))
    phrase = owm_phrase(weather, lang)

    # v13 fix: force current conditions to daytime mode.
    day = True
    icon = accu_icon_from_owm(weather_id, clouds, True)

    has_precip, precip_type, precip_intensity = precipitation_from_owm(weather_id)

    main = data.get("main") or {}
    wind = data.get("wind") or {}

    temp_c = round1(main.get("temp", 0))
    feels_c = round1(main.get("feels_like", temp_c))
    humidity = round0(main.get("humidity", 0))
    pressure = round1(main.get("pressure", 0))
    wind_speed = ms_to_kmh(wind.get("speed", 0))
    wind_deg = round0(wind.get("deg", 0))

    return [{
        "LocalObservationDateTime": local_iso(dt),
        "EpochTime": epoch(dt),
        "WeatherText": phrase,
        "WeatherIcon": icon,
        "HasPrecipitation": has_precip,
        "PrecipitationType": precip_type,
        "IsDayTime": day,
        "Temperature": temp_block_c(temp_c),
        "RealFeelTemperature": temp_block_c(feels_c),
        "RealFeelTemperatureShade": temp_block_c(feels_c),
        "RelativeHumidity": humidity,
        "IndoorRelativeHumidity": humidity,
        "DewPoint": temp_block_c(round1(temp_c - ((100 - humidity) / 5))),
        "Wind": {
            "Direction": {
                "Degrees": wind_deg,
                "Localized": deg_to_dir(wind_deg),
                "English": deg_to_dir(wind_deg),
            },
            "Speed": {
                "Metric": metric_value(wind_speed, "km/h", 7),
                "Imperial": metric_value(round1(wind_speed / 1.60934), "mi/h", 9),
            },
        },
        "WindGust": {
            "Speed": {
                "Metric": metric_value(ms_to_kmh(wind.get("gust", wind.get("speed", 0))), "km/h", 7),
                "Imperial": metric_value(round1(ms_to_kmh(wind.get("gust", wind.get("speed", 0))) / 1.60934), "mi/h", 9),
            },
        },
        "UVIndex": 0,
        "UVIndexText": "Low",
        "Visibility": {
            "Metric": metric_value(round1(float(data.get("visibility", 10000)) / 1000), "km", 6),
            "Imperial": metric_value(round1((float(data.get("visibility", 10000)) / 1000) / 1.60934), "mi", 2),
        },
        "ObstructionsToVisibility": "",
        "CloudCover": clouds,
        "Ceiling": {
            "Metric": metric_value(0, "m", 5),
            "Imperial": metric_value(0, "ft", 0),
        },
        "Pressure": {
            "Metric": metric_value(pressure, "mb", 14),
            "Imperial": metric_value(round1(pressure * 0.02953), "inHg", 12),
        },
        "PressureTendency": {
            "LocalizedText": "Steady",
            "Code": "S",
        },
        "ApparentTemperature": temp_block_c(feels_c),
        "WindChillTemperature": temp_block_c(feels_c),
        "WetBulbTemperature": temp_block_c(temp_c),
        "Precip1hr": {
            "Metric": metric_value(0.0, "mm", 3),
            "Imperial": metric_value(0.0, "in", 1),
        },
        "PrecipitationSummary": {
            "Precipitation": {
                "Metric": metric_value(0.0, "mm", 3),
                "Imperial": metric_value(0.0, "in", 1),
            },
            "PastHour": {
                "Metric": metric_value(0.0, "mm", 3),
                "Imperial": metric_value(0.0, "in", 1),
            },
            "Past3Hours": {
                "Metric": metric_value(0.0, "mm", 3),
                "Imperial": metric_value(0.0, "in", 1),
            },
            "Past6Hours": {
                "Metric": metric_value(0.0, "mm", 3),
                "Imperial": metric_value(0.0, "in", 1),
            },
            "Past9Hours": {
                "Metric": metric_value(0.0, "mm", 3),
                "Imperial": metric_value(0.0, "in", 1),
            },
            "Past12Hours": {
                "Metric": metric_value(0.0, "mm", 3),
                "Imperial": metric_value(0.0, "in", 1),
            },
            "Past18Hours": {
                "Metric": metric_value(0.0, "mm", 3),
                "Imperial": metric_value(0.0, "in", 1),
            },
            "Past24Hours": {
                "Metric": metric_value(0.0, "mm", 3),
                "Imperial": metric_value(0.0, "in", 1),
            },
        },
        "TemperatureSummary": {
            "Past6HourRange": {
                "Minimum": temp_block_c(temp_c),
                "Maximum": temp_block_c(temp_c),
            },
            "Past12HourRange": {
                "Minimum": temp_block_c(temp_c),
                "Maximum": temp_block_c(temp_c),
            },
            "Past24HourRange": {
                "Minimum": temp_block_c(temp_c),
                "Maximum": temp_block_c(temp_c),
            },
        },
        "MobileLink": "",
        "Link": "",
    }]


def build_hourly_forecast(location_key: str, lang: str) -> List[Dict[str, Any]]:
    lat, lon, key, name, admin, country = parse_location_key(location_key)

    data = owm_get(
        "/data/2.5/forecast",
        {
            "lat": lat,
            "lon": lon,
            "units": "metric",
            "lang": lang,
        },
        f"hourly:{lang}:{lat:.5f},{lon:.5f}",
    )

    items = data.get("list") or []
    if not items:
        items = [default_forecast_item(now_kyiv() + timedelta(hours=3), 22.0)]

    normalized = []
    for item in items:
        dt = datetime.fromtimestamp(int(item.get("dt")), tz=timezone.utc).astimezone(KYIV_TZ)
        normalized.append((dt, item))

    out: List[Dict[str, Any]] = []
    start = now_kyiv().replace(minute=0, second=0, microsecond=0)

    for h in range(1, 13):
        target = start + timedelta(hours=h)
        nearest_dt, nearest = min(normalized, key=lambda pair: abs((pair[0] - target).total_seconds()))

        weather = (nearest.get("weather") or [{}])[0]
        weather_id = int(weather.get("id", 800))
        clouds = int((nearest.get("clouds") or {}).get("all", 0))
        phrase = owm_phrase(weather, lang)

        # v13 fix: force hourly forecast to daytime too.
        day = True
        icon = accu_icon_from_owm(weather_id, clouds, True)

        has_precip, precip_type, precip_intensity = precipitation_from_owm(weather_id)

        main = nearest.get("main") or {}
        wind = nearest.get("wind") or {}

        temp_c = round1(main.get("temp", 0))
        feels_c = round1(main.get("feels_like", temp_c))
        humidity = round0(main.get("humidity", 60))
        pop = round0(float(nearest.get("pop", 0)) * 100, 0)

        out.append({
            "DateTime": local_iso(target),
            "EpochDateTime": epoch(target),
            "WeatherIcon": icon,
            "IconPhrase": phrase,
            "HasPrecipitation": has_precip,
            "PrecipitationType": precip_type,
            "PrecipitationIntensity": precip_intensity,
            "IsDaylight": day,
            "Temperature": metric_value(temp_c, "C", 17),
            "RealFeelTemperature": metric_value(feels_c, "C", 17),
            "WetBulbTemperature": metric_value(temp_c, "C", 17),
            "DewPoint": metric_value(round1(temp_c - ((100 - humidity) / 5)), "C", 17),
            "Wind": {
                "Speed": metric_value(ms_to_kmh(wind.get("speed", 0)), "km/h", 7),
                "Direction": {
                    "Degrees": round0(wind.get("deg", 0)),
                    "Localized": deg_to_dir(wind.get("deg", 0)),
                    "English": deg_to_dir(wind.get("deg", 0)),
                },
            },
            "WindGust": {
                "Speed": metric_value(ms_to_kmh(wind.get("gust", wind.get("speed", 0))), "km/h", 7),
            },
            "RelativeHumidity": humidity,
            "Visibility": metric_value(10.0, "km", 6),
            "CloudCover": clouds,
            "UVIndex": 0,
            "UVIndexText": "Low",
            "PrecipitationProbability": pop,
            "ThunderstormProbability": pop if 200 <= weather_id <= 232 else 0,
            "RainProbability": pop if precip_type == "Rain" else 0,
            "SnowProbability": pop if precip_type == "Snow" else 0,
            "IceProbability": pop if precip_type == "Ice" else 0,
            "TotalLiquid": metric_value(0.0, "mm", 3),
            "Rain": metric_value(0.0, "mm", 3),
            "Snow": metric_value(0.0, "cm", 4),
            "Ice": metric_value(0.0, "mm", 3),
            "MobileLink": "",
            "Link": "",
        })

    return out


@app.route("/", methods=["GET"], strict_slashes=False)
def root() -> Response:
    return jsonify({
        "ok": True,
        "version": VERSION,
        "status": "/status",
    })


@app.route("/status", methods=["GET"], strict_slashes=False)
def status() -> Response:
    return jsonify({
        "ok": True,
        "version": VERSION,
        "openweather_key_present": bool(OPENWEATHER_API_KEY),
        "shyroke_key": SHYROKE_KEY,
        "old_shyroke_key": OLD_SHYROKE_KEY,
        "timezone": timezone_block(),
        "fixes": {
            "numeric_city_key": True,
            "geoposition_search": True,
            "daily_10day": True,
            "day_forecast_copied_into_night": True,
            "current_conditions_forced_daytime": True,
            "hourly_forecast_forced_daytime": True,
        },
    })


@app.route("/locations/v1/search", methods=["GET"], strict_slashes=False)
def locations_search() -> Response:
    err = require_api_key()
    if err:
        return err

    lang = get_language()
    q = request.args.get("q") or request.args.get("query") or ""
    return jsonify(search_locations(q, lang))


@app.route("/locations/v1/cities/geoposition/search", methods=["GET"], strict_slashes=False)
@app.route("/locations/v1/cities/geoposition/search.json", methods=["GET"], strict_slashes=False)
def locations_geoposition_search() -> Response:
    err = require_api_key()
    if err:
        return err

    lang = get_language()
    q = request.args.get("q") or f"{SHYROKE_LAT},{SHYROKE_LON}"
    return jsonify(reverse_geoposition(q, lang))


@app.route("/locations/v1/<path:location_key>", methods=["GET"], strict_slashes=False)
def location_by_key(location_key: str) -> Response:
    lat, lon, key, name, admin, country = parse_location_key(location_key)
    return jsonify(location_object(key, name, lat, lon, admin, country))


@app.route("/currentconditions/v1/<path:location_key>", methods=["GET"], strict_slashes=False)
def current_conditions(location_key: str) -> Response:
    err = require_api_key()
    if err:
        return err

    lang = get_language()
    return jsonify(build_current_conditions(location_key, lang))


@app.route("/forecasts/v1/daily/10day/<path:location_key>", methods=["GET"], strict_slashes=False)
def daily_10day(location_key: str) -> Response:
    err = require_api_key()
    if err:
        return err

    lang = get_language()
    return jsonify(build_daily_forecast_payload(location_key, lang))


@app.route("/forecasts/v1/hourly/12hour/<path:location_key>", methods=["GET"], strict_slashes=False)
def hourly_12hour(location_key: str) -> Response:
    err = require_api_key()
    if err:
        return err

    lang = get_language()
    return jsonify(build_hourly_forecast(location_key, lang))


@app.route("/widget/htc2/city-find.asp", methods=["GET"], strict_slashes=False)
def widget_city_find() -> Response:
    q = request.args.get("q") or request.args.get("city") or request.args.get("name") or "shyroke"
    lang = get_language()
    locs = search_locations(q, lang)
    loc = locs[0] if locs else location_object()

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<citylist>
  <city
    name="{loc.get("LocalizedName", SHYROKE_NAME_RU)}"
    country="{loc.get("Country", {}).get("ID", "UA")}"
    state="{loc.get("AdministrativeArea", {}).get("LocalizedName", "")}"
    code="{loc.get("Key", SHYROKE_KEY)}"
    latitude="{loc.get("GeoPosition", {}).get("Latitude", SHYROKE_LAT)}"
    longitude="{loc.get("GeoPosition", {}).get("Longitude", SHYROKE_LON)}" />
</citylist>
"""
    return Response(xml, mimetype="application/xml; charset=utf-8")


@app.errorhandler(404)
def not_found(e: Exception) -> Response:
    return jsonify({
        "error": "not_found",
        "path": request.path,
        "version": VERSION,
    }), 404


@app.errorhandler(Exception)
def handle_exception(e: Exception) -> Response:
    return jsonify({
        "error": str(e),
        "type": e.__class__.__name__,
        "version": VERSION,
    }), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
