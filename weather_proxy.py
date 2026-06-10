import os
import time
import math
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from flask import Flask, jsonify, request, Response

app = Flask(__name__)

VERSION = "htc-weather-proxy-v15-openmeteo-cache-fallback"

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "").strip()
OWM_BASE = "https://api.openweathermap.org"
OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"

# Server-side cache. Нужен обязательно: старый HTC часто дергает одни и те же URL,
# а Open-Meteo может дать HTTP 429 при частых daily-запросах.
CACHE = {}
DAILY_CACHE_TTL_SECONDS = 6 * 60 * 60
HOURLY_CACHE_TTL_SECONDS = 30 * 60
CURRENT_CACHE_TTL_SECONDS = 10 * 60


def cache_get(name: str):
    item = CACHE.get(name)
    if not item:
        return None
    expires_at, value = item
    if time.time() > expires_at:
        return None
    return value


def cache_get_any(name: str):
    item = CACHE.get(name)
    if not item:
        return None
    return item[1]


def cache_set(name: str, value, ttl_seconds: int):
    CACHE[name] = (time.time() + ttl_seconds, value)
    return value

KYIV_TZ_NAME = "Europe/Kyiv"
KYIV_TZ = ZoneInfo(KYIV_TZ_NAME)

SHYROKE = {
    "key": "324178",
    "old_key": "KP0476847E0332645",
    "name_ru": "Широке",
    "name_en": "Shyroke",
    "country_id": "UA",
    "country_ru": "Украина",
    "country_en": "Ukraine",
    "admin_ru": "Днепропетровская область",
    "admin_en": "Днепропетровская область",
    "lat": 47.6846511,
    "lon": 33.2645369,
}


def kyiv_now() -> datetime:
    return datetime.now(KYIV_TZ)


def iso_kyiv(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KYIV_TZ)
    return dt.astimezone(KYIV_TZ).isoformat(timespec="seconds")


def epoch(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KYIV_TZ)
    return int(dt.timestamp())


def safe_float(value, default=0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def safe_int(value, default=0) -> int:
    try:
        if value is None:
            return default
        return int(round(float(value)))
    except Exception:
        return default


def c_to_f(c: float) -> float:
    return round((c * 9.0 / 5.0) + 32.0, 1)


def kmh_to_mph(kmh: float) -> float:
    return round(kmh * 0.621371, 1)


def mb_to_inhg(mb: float) -> float:
    return round(mb * 0.0295299830714, 1)


def metric_temp(c: float) -> dict:
    c = round(safe_float(c), 1)
    return {
        "Metric": {"Value": c, "Unit": "C", "UnitType": 17},
        "Imperial": {"Value": c_to_f(c), "Unit": "F", "UnitType": 18},
    }


def daily_temp(c: float) -> dict:
    return {"Value": round(safe_float(c), 1), "Unit": "C", "UnitType": 17}


def metric_length_mm(mm: float) -> dict:
    mm = round(safe_float(mm), 1)
    return {
        "Metric": {"Value": mm, "Unit": "mm", "UnitType": 3},
        "Imperial": {"Value": round(mm / 25.4, 2), "Unit": "in", "UnitType": 1},
    }


def daily_rain_mm(mm: float) -> dict:
    return {"Value": round(safe_float(mm), 1), "Unit": "mm", "UnitType": 3}


def daily_snow_cm(cm: float) -> dict:
    return {"Value": round(safe_float(cm), 1), "Unit": "cm", "UnitType": 4}


def metric_speed_kmh(kmh: float) -> dict:
    kmh = round(safe_float(kmh), 1)
    return {
        "Metric": {"Value": kmh, "Unit": "km/h", "UnitType": 7},
        "Imperial": {"Value": kmh_to_mph(kmh), "Unit": "mi/h", "UnitType": 9},
    }


def direction_from_degrees(deg: float) -> dict:
    deg = safe_int(deg, 0) % 360
    dirs = [
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"
    ]
    idx = int((deg + 11.25) // 22.5) % 16
    name = dirs[idx]
    return {"Degrees": deg, "English": name, "Localized": name}


def timezone_payload() -> dict:
    return {
        "Code": "EEST",
        "Name": KYIV_TZ_NAME,
        "GmtOffset": 3,
        "IsDaylightSaving": True,
        "NextOffsetChange": "",
    }


def location_payload(
    key: str = None,
    name_ru: str = None,
    name_en: str = None,
    lat: float = None,
    lon: float = None,
    country_id: str = "UA",
    country_ru: str = "Украина",
    country_en: str = "Ukraine",
    admin_ru: str = "Днепропетровская область",
    admin_en: str = "Днепропетровская область",
) -> dict:
    key = key or SHYROKE["key"]
    name_ru = name_ru or SHYROKE["name_ru"]
    name_en = name_en or SHYROKE["name_en"]
    lat = SHYROKE["lat"] if lat is None else safe_float(lat)
    lon = SHYROKE["lon"] if lon is None else safe_float(lon)

    return {
        "Version": 1,
        "Key": str(key),
        "Type": "City",
        "Rank": 35,
        "LocalizedName": name_ru,
        "EnglishName": name_en,
        "PrimaryPostalCode": "",
        "Region": {"ID": "EUR", "LocalizedName": "Европа", "EnglishName": "Europe"},
        "Country": {"ID": country_id, "LocalizedName": country_ru, "EnglishName": country_en},
        "AdministrativeArea": {
            "ID": "",
            "LocalizedName": admin_ru,
            "EnglishName": admin_en,
            "Level": 1,
            "LocalizedType": "область",
            "EnglishType": "Oblast",
            "CountryID": country_id,
        },
        "TimeZone": timezone_payload(),
        "GeoPosition": {
            "Latitude": lat,
            "Longitude": lon,
            "Elevation": {
                "Metric": {"Value": 0, "Unit": "m", "UnitType": 5},
                "Imperial": {"Value": 0, "Unit": "ft", "UnitType": 0},
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


def is_shyroke_query(q: str) -> bool:
    q = (q or "").strip().lower()
    return any(x in q for x in ["shyroke", "широке", "shiroke", "шыроке"])


def parse_geoposition() -> tuple[float, float]:
    q = request.args.get("q") or request.args.get("geoposition") or request.args.get("geoPosition")
    if q and "," in q:
        a, b = q.split(",", 1)
        return safe_float(a, SHYROKE["lat"]), safe_float(b, SHYROKE["lon"])

    lat = request.args.get("lat") or request.args.get("latitude") or request.args.get("Latitude")
    lon = request.args.get("lon") or request.args.get("lng") or request.args.get("longitude") or request.args.get("Longitude")
    return safe_float(lat, SHYROKE["lat"]), safe_float(lon, SHYROKE["lon"])


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def resolve_location_key(key: str) -> dict:
    key = str(key or "").strip()
    if key in ["", SHYROKE["key"], SHYROKE["old_key"], "KP0476847E0332645"]:
        return {
            "key": SHYROKE["key"],
            "lat": SHYROKE["lat"],
            "lon": SHYROKE["lon"],
            "name_ru": SHYROKE["name_ru"],
            "name_en": SHYROKE["name_en"],
        }

    # Неизвестный ключ не валим, чтобы HTC не падал.
    return {
        "key": key,
        "lat": SHYROKE["lat"],
        "lon": SHYROKE["lon"],
        "name_ru": SHYROKE["name_ru"],
        "name_en": SHYROKE["name_en"],
    }


def http_get_json(url: str, params: dict, timeout: int = 15) -> dict:
    r = requests.get(url, params=params, timeout=timeout)
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text[:500]}
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {data}")
    return data


def proxy_error(message: str, status_code: int = 500):
    return jsonify({"ok": False, "ProxyError": str(message), "version": VERSION}), status_code


def require_openweather_key():
    if not OPENWEATHER_API_KEY:
        raise RuntimeError("OPENWEATHER_API_KEY is empty on Render")


def openmeteo_icon_phrase(code: int, night: bool = False) -> tuple[int, str]:
    code = safe_int(code, 3)
    if code == 0:
        return (33, "ясно") if night else (1, "солнечно")
    if code == 1:
        return (34, "преимущественно ясно") if night else (2, "небольшая облачность")
    if code == 2:
        return (35, "переменная облачность") if night else (3, "переменная облачность")
    if code == 3:
        return (38, "пасмурно") if night else (7, "пасмурно")
    if code in (45, 48):
        return 11, "туман"
    if code in (51, 53, 55, 56, 57):
        return (39, "морось") if night else (12, "морось")
    if code in (61, 63, 65, 80, 81, 82):
        return (40, "дождь") if night else (18, "дождь")
    if code in (66, 67):
        return (42, "ледяной дождь") if night else (24, "ледяной дождь")
    if code in (71, 73, 75, 77, 85, 86):
        return (44, "снег") if night else (22, "снег")
    if code == 95:
        return (41, "гроза") if night else (15, "гроза")
    if code in (96, 99):
        return (42, "сильная гроза") if night else (17, "сильная гроза")
    return (35, "переменная облачность") if night else (3, "переменная облачность")


def cloud_cover_from_code(code: int) -> int:
    code = safe_int(code, 3)
    if code == 0:
        return 0
    if code == 1:
        return 20
    if code == 2:
        return 50
    if code == 3:
        return 100
    if code in (45, 48):
        return 90
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 71, 73, 75, 77, 80, 81, 82, 85, 86, 95, 96, 99):
        return 85
    return 50


def has_precip_from_code(code: int, precip_mm: float) -> bool:
    if safe_float(precip_mm) > 0.01:
        return True
    return safe_int(code) in {
        51, 53, 55, 56, 57, 61, 63, 65, 66, 67,
        71, 73, 75, 77, 80, 81, 82, 85, 86, 95, 96, 99,
    }


def precip_type_from_code(code: int) -> str:
    code = safe_int(code)
    if code in (71, 73, 75, 77, 85, 86):
        return "Snow"
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99):
        return "Rain"
    return ""


def owm_icon_phrase(weather_id: int, icon: str = "", force_daytime: bool = True) -> tuple[int, str]:
    wid = safe_int(weather_id, 800)
    is_night = (not force_daytime) and str(icon).endswith("n")
    if 200 <= wid < 300:
        return (41, "гроза") if is_night else (15, "гроза")
    if 300 <= wid < 400:
        return (39, "морось") if is_night else (12, "морось")
    if 500 <= wid < 600:
        return (40, "дождь") if is_night else (18, "дождь")
    if 600 <= wid < 700:
        return (44, "снег") if is_night else (22, "снег")
    if 700 <= wid < 800:
        return 11, "туман"
    if wid == 800:
        return (33, "ясно") if is_night else (1, "солнечно")
    if wid == 801:
        return (34, "небольшая облачность") if is_night else (2, "небольшая облачность")
    if wid == 802:
        return (35, "переменная облачность") if is_night else (3, "переменная облачность")
    if wid == 803:
        return (36, "облачно с прояснениями") if is_night else (4, "облачно с прояснениями")
    if wid == 804:
        return (38, "пасмурно") if is_night else (7, "пасмурно")
    return (35, "переменная облачность") if is_night else (3, "переменная облачность")


def make_day_night_block(code, night, precip_prob, precip_mm, rain_mm, snow_cm, wind_kmh, wind_deg, gust_kmh):
    icon, phrase = openmeteo_icon_phrase(code, night=night)
    has_precip = has_precip_from_code(code, precip_mm)
    precip_type = precip_type_from_code(code)
    rain_prob = precip_prob if precip_type == "Rain" else 0
    snow_prob = precip_prob if precip_type == "Snow" else 0
    thunder_prob = precip_prob if safe_int(code) in (95, 96, 99) else 0

    return {
        "Icon": icon,
        "IconPhrase": phrase,
        "ShortPhrase": phrase,
        "LongPhrase": phrase,
        "HasPrecipitation": has_precip,
        "PrecipitationType": precip_type if has_precip else "",
        "PrecipitationIntensity": "Light" if has_precip else "",
        "PrecipitationProbability": safe_int(precip_prob),
        "ThunderstormProbability": safe_int(thunder_prob),
        "RainProbability": safe_int(rain_prob),
        "SnowProbability": safe_int(snow_prob),
        "IceProbability": 0,
        "CloudCover": cloud_cover_from_code(code),
        "HoursOfPrecipitation": 1 if has_precip else 0,
        "HoursOfRain": 1 if rain_prob > 0 else 0,
        "HoursOfSnow": 1 if snow_prob > 0 else 0,
        "HoursOfIce": 0,
        "Rain": daily_rain_mm(rain_mm),
        "Snow": daily_snow_cm(snow_cm),
        "Ice": daily_rain_mm(0),
        "Wind": {
            "Speed": metric_speed_kmh(wind_kmh),
            "Direction": direction_from_degrees(wind_deg),
        },
        "WindGust": {"Speed": metric_speed_kmh(gust_kmh if gust_kmh else wind_kmh)},
    }


def fetch_openmeteo_daily(lat: float, lon: float, days: int) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": KYIV_TZ_NAME,
        "forecast_days": days,
        "daily": ",".join([
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "apparent_temperature_max",
            "apparent_temperature_min",
            "sunrise",
            "sunset",
            "precipitation_sum",
            "rain_sum",
            "showers_sum",
            "snowfall_sum",
            "precipitation_probability_max",
            "wind_speed_10m_max",
            "wind_gusts_10m_max",
            "wind_direction_10m_dominant",
        ]),
    }
    return http_get_json(OPEN_METEO_BASE, params=params)


def build_daily_forecast_from_openmeteo(key: str, days: int):
    loc = resolve_location_key(key)
    data = fetch_openmeteo_daily(loc["lat"], loc["lon"], days)
    daily = data.get("daily") or {}
    times = daily.get("time") or []
    forecasts = []

    for i, d in enumerate(times[:days]):
        date_dt = datetime.fromisoformat(f"{d}T12:00:00+03:00")
        code = safe_int((daily.get("weather_code") or [3])[i], 3)
        tmax = safe_float((daily.get("temperature_2m_max") or [0])[i])
        tmin = safe_float((daily.get("temperature_2m_min") or [0])[i])
        rfmax = safe_float((daily.get("apparent_temperature_max") or [tmax])[i], tmax)
        rfmin = safe_float((daily.get("apparent_temperature_min") or [tmin])[i], tmin)
        precip = safe_float((daily.get("precipitation_sum") or [0])[i])
        rain = safe_float((daily.get("rain_sum") or [0])[i])
        showers = safe_float((daily.get("showers_sum") or [0])[i])
        snow_cm = safe_float((daily.get("snowfall_sum") or [0])[i])
        precip_prob = safe_int((daily.get("precipitation_probability_max") or [0])[i])
        wind_kmh = safe_float((daily.get("wind_speed_10m_max") or [0])[i])
        gust_kmh = safe_float((daily.get("wind_gusts_10m_max") or [wind_kmh])[i], wind_kmh)
        wind_deg = safe_float((daily.get("wind_direction_10m_dominant") or [90])[i], 90)
        rain_total = rain + showers

        sunrise_raw = (daily.get("sunrise") or [f"{d}T05:00"])[i]
        sunset_raw = (daily.get("sunset") or [f"{d}T20:45"])[i]
        try:
            sunrise_dt = datetime.fromisoformat(sunrise_raw).replace(tzinfo=KYIV_TZ)
        except Exception:
            sunrise_dt = datetime.fromisoformat(f"{d}T05:00:00+03:00")
        try:
            sunset_dt = datetime.fromisoformat(sunset_raw).replace(tzinfo=KYIV_TZ)
        except Exception:
            sunset_dt = datetime.fromisoformat(f"{d}T20:45:00+03:00")

        day_block = make_day_night_block(code, False, precip_prob, precip, rain_total, snow_cm, wind_kmh, wind_deg, gust_kmh)
        night_block = make_day_night_block(code, True, precip_prob, precip, rain_total, snow_cm, wind_kmh, wind_deg, gust_kmh)

        forecasts.append(make_daily_item(
            date_dt=date_dt,
            sunrise_dt=sunrise_dt,
            sunset_dt=sunset_dt,
            index=i,
            tmin=tmin,
            tmax=tmax,
            rfmin=rfmin,
            rfmax=rfmax,
            day_block=day_block,
            night_block=night_block,
            source="Open-Meteo",
        ))

    return daily_payload(forecasts, "Прогноз обновлён через HTC Weather Proxy / Open-Meteo")


def make_daily_item(date_dt, sunrise_dt, sunset_dt, index, tmin, tmax, rfmin, rfmax, day_block, night_block, source):
    return {
        "Date": iso_kyiv(date_dt),
        "EpochDate": epoch(date_dt),
        "Sun": {
            "Rise": iso_kyiv(sunrise_dt),
            "EpochRise": epoch(sunrise_dt),
            "Set": iso_kyiv(sunset_dt),
            "EpochSet": epoch(sunset_dt),
        },
        "Moon": {
            "Rise": iso_kyiv(date_dt.replace(hour=22, minute=0, second=0)),
            "EpochRise": epoch(date_dt.replace(hour=22, minute=0, second=0)),
            "Set": iso_kyiv(date_dt.replace(hour=7, minute=0, second=0)),
            "EpochSet": epoch(date_dt.replace(hour=7, minute=0, second=0)),
            "Phase": "WaxingCrescent",
            "Age": index + 1,
        },
        "Temperature": {"Minimum": daily_temp(tmin), "Maximum": daily_temp(tmax)},
        "RealFeelTemperature": {"Minimum": daily_temp(rfmin), "Maximum": daily_temp(rfmax)},
        "RealFeelTemperatureShade": {"Minimum": daily_temp(rfmin), "Maximum": daily_temp(rfmax)},
        "HoursOfSun": 8.0,
        "DegreeDaySummary": {
            "Heating": {"Value": 0, "Unit": "C", "UnitType": 17},
            "Cooling": {"Value": 0, "Unit": "C", "UnitType": 17},
        },
        "AirAndPollen": [
            {"Name": "AirQuality", "Value": 0, "Category": "Good", "CategoryValue": 1, "Type": "AirQuality"},
            {"Name": "Grass", "Value": 0, "Category": "Good", "CategoryValue": 1, "Type": "Grass"},
            {"Name": "Mold", "Value": 0, "Category": "Good", "CategoryValue": 1, "Type": "Mold"},
            {"Name": "Ragweed", "Value": 0, "Category": "Good", "CategoryValue": 1, "Type": "Ragweed"},
            {"Name": "Tree", "Value": 0, "Category": "Good", "CategoryValue": 1, "Type": "Tree"},
            {"Name": "UVIndex", "Value": 0, "Category": "Low", "CategoryValue": 1, "Type": "UVIndex"},
        ],
        "Day": day_block,
        "Night": night_block,
        "Sources": [source],
        "MobileLink": "",
        "Link": "",
    }


def daily_payload(forecasts, text):
    return {
        "Headline": {
            "EffectiveDate": iso_kyiv(kyiv_now()),
            "EffectiveEpochDate": epoch(kyiv_now()),
            "Severity": 7,
            "Text": text,
            "Category": "general",
            "EndDate": None,
            "EndEpochDate": None,
            "MobileLink": "",
            "Link": "",
        },
        "DailyForecasts": forecasts,
    }


def build_daily_forecast_fallback(key: str, days: int, reason: str = ""):
    # Аварийный режим: если Open-Meteo дал 429, не отдаём ProxyError старому HTC.
    # Строим безопасный прогноз из OpenWeatherMap /forecast на ближайшие 5 дней и
    # аккуратно продлеваем до 10 дней. Когда лимит Open-Meteo восстановится, proxy
    # автоматически снова начнёт отдавать Sources=["Open-Meteo"].
    loc = resolve_location_key(key)
    grouped = {}

    try:
        require_openweather_key()
        data = http_get_json(f"{OWM_BASE}/data/2.5/forecast", {
            "lat": loc["lat"],
            "lon": loc["lon"],
            "appid": OPENWEATHER_API_KEY,
            "units": "metric",
            "lang": request.args.get("language", "ru"),
        })
        for item in data.get("list", []):
            dt = datetime.fromtimestamp(safe_int(item.get("dt"), int(time.time())), KYIV_TZ)
            d = dt.date().isoformat()
            main = item.get("main") or {}
            weather = (item.get("weather") or [{}])[0]
            wind = item.get("wind") or {}
            rain = item.get("rain") or {}
            snow = item.get("snow") or {}
            g = grouped.setdefault(d, {"temps": [], "feels": [], "codes": [], "icons": [], "precip": 0, "rain": 0, "snow": 0, "wind": [], "gust": [], "deg": []})
            g["temps"].append(safe_float(main.get("temp")))
            g["feels"].append(safe_float(main.get("feels_like"), main.get("temp", 0)))
            g["codes"].append(safe_int(weather.get("id"), 800))
            g["icons"].append(weather.get("icon", "02d"))
            g["rain"] += safe_float(rain.get("3h"), 0)
            g["snow"] += safe_float(snow.get("3h"), 0) / 10.0
            g["precip"] += safe_float(rain.get("3h"), 0) + safe_float(snow.get("3h"), 0)
            g["wind"].append(safe_float(wind.get("speed"), 0) * 3.6)
            g["gust"].append(safe_float(wind.get("gust"), wind.get("speed", 0)) * 3.6)
            g["deg"].append(safe_float(wind.get("deg"), 90))
    except Exception:
        pass

    today = kyiv_now().date()
    forecasts = []
    last_tmin = 16.0
    last_tmax = 25.0

    for i in range(days):
        target = today.toordinal() + i + 1
        d_obj = datetime.fromordinal(target).replace(hour=12, minute=0, second=0, tzinfo=KYIV_TZ)
        key_date = d_obj.date().isoformat()
        g = grouped.get(key_date)

        if g and g.get("temps"):
            tmin = min(g["temps"])
            tmax = max(g["temps"])
            rfmin = min(g["feels"]) if g.get("feels") else tmin
            rfmax = max(g["feels"]) if g.get("feels") else tmax
            # Берём самый частый/первый код прогноза.
            code_id = g["codes"][0] if g.get("codes") else 801
            icon_raw = g["icons"][0] if g.get("icons") else "02d"
            day_icon, day_phrase = owm_icon_phrase(code_id, icon_raw, force_daytime=True)
            night_icon, night_phrase = owm_icon_phrase(code_id, icon_raw, force_daytime=False)
            precip = g.get("precip", 0)
            rain = g.get("rain", 0)
            snow = g.get("snow", 0)
            wind_kmh = max(g.get("wind") or [8])
            gust_kmh = max(g.get("gust") or [wind_kmh])
            wind_deg = (g.get("deg") or [90])[0]
            precip_prob = 60 if precip > 0.01 else 0
        else:
            # Безопасное продление, чтобы было 10 элементов и HTC не падал.
            tmin = last_tmin + (0.2 if i % 2 == 0 else -0.1)
            tmax = last_tmax + (0.3 if i % 2 == 0 else -0.2)
            rfmin = tmin
            rfmax = tmax
            day_icon, day_phrase = 3, "переменная облачность"
            night_icon, night_phrase = 35, "переменная облачность"
            precip = rain = snow = 0
            wind_kmh = 10.0
            gust_kmh = 14.0
            wind_deg = 90
            precip_prob = 0

        last_tmin, last_tmax = tmin, tmax
        day_block = {
            "Icon": day_icon, "IconPhrase": day_phrase, "ShortPhrase": day_phrase, "LongPhrase": day_phrase,
            "HasPrecipitation": precip > 0.01, "PrecipitationType": "Rain" if rain > 0 else ("Snow" if snow > 0 else ""),
            "PrecipitationIntensity": "Light" if precip > 0.01 else "", "PrecipitationProbability": precip_prob,
            "ThunderstormProbability": 0, "RainProbability": precip_prob if rain > 0 else 0, "SnowProbability": precip_prob if snow > 0 else 0,
            "IceProbability": 0, "CloudCover": 50, "HoursOfPrecipitation": 1 if precip > 0.01 else 0,
            "HoursOfRain": 1 if rain > 0 else 0, "HoursOfSnow": 1 if snow > 0 else 0, "HoursOfIce": 0,
            "Rain": daily_rain_mm(rain), "Snow": daily_snow_cm(snow), "Ice": daily_rain_mm(0),
            "Wind": {"Speed": metric_speed_kmh(wind_kmh), "Direction": direction_from_degrees(wind_deg)},
            "WindGust": {"Speed": metric_speed_kmh(gust_kmh)},
        }
        night_block = dict(day_block)
        night_block["Icon"] = night_icon
        night_block["IconPhrase"] = night_phrase
        night_block["ShortPhrase"] = night_phrase
        night_block["LongPhrase"] = night_phrase

        sunrise_dt = d_obj.replace(hour=5, minute=0, second=0)
        sunset_dt = d_obj.replace(hour=20, minute=45, second=0)
        forecasts.append(make_daily_item(d_obj, sunrise_dt, sunset_dt, i, tmin, tmax, rfmin, rfmax, day_block, night_block, "Fallback"))

    text = "Резервный прогноз: Open-Meteo временно недоступен"
    if reason:
        text += " / " + str(reason)[:80]
    return daily_payload(forecasts, text)


def build_daily_forecast(key: str, days: int):
    cache_key = f"daily:{key}:{days}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    try:
        payload = build_daily_forecast_from_openmeteo(key, days)
        return cache_set(cache_key, payload, DAILY_CACHE_TTL_SECONDS)
    except Exception as e:
        stale = cache_get_any(cache_key)
        if stale:
            return stale
        payload = build_daily_forecast_fallback(key, days, reason=e)
        return cache_set(cache_key, payload, 60 * 60)


def fetch_openmeteo_hourly(lat: float, lon: float) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": KYIV_TZ_NAME,
        "forecast_days": 2,
        "hourly": ",".join([
            "temperature_2m",
            "apparent_temperature",
            "weather_code",
            "precipitation_probability",
            "precipitation",
            "rain",
            "showers",
            "snowfall",
            "wind_speed_10m",
            "wind_direction_10m",
        ]),
    }
    return http_get_json(OPEN_METEO_BASE, params=params)


def build_hourly_forecast(key: str, hours: int = 12):
    loc = resolve_location_key(key)
    data = fetch_openmeteo_hourly(loc["lat"], loc["lon"])
    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    now = kyiv_now().replace(minute=0, second=0, microsecond=0)
    result = []

    for i, t in enumerate(times):
        try:
            dt = datetime.fromisoformat(t).replace(tzinfo=KYIV_TZ)
        except Exception:
            continue
        if dt < now:
            continue

        code = safe_int((hourly.get("weather_code") or [3])[i], 3)
        icon, phrase = openmeteo_icon_phrase(code, night=False)
        temp = safe_float((hourly.get("temperature_2m") or [0])[i])
        feel = safe_float((hourly.get("apparent_temperature") or [temp])[i], temp)
        prob = safe_int((hourly.get("precipitation_probability") or [0])[i])
        precip = safe_float((hourly.get("precipitation") or [0])[i])
        rain = safe_float((hourly.get("rain") or [0])[i]) + safe_float((hourly.get("showers") or [0])[i])
        snow = safe_float((hourly.get("snowfall") or [0])[i])
        wind_kmh = safe_float((hourly.get("wind_speed_10m") or [0])[i])
        wind_deg = safe_float((hourly.get("wind_direction_10m") or [90])[i], 90)
        has_precip = has_precip_from_code(code, precip)
        ptype = precip_type_from_code(code)

        result.append({
            "DateTime": iso_kyiv(dt),
            "EpochDateTime": epoch(dt),
            "WeatherIcon": icon,
            "IconPhrase": phrase,
            "HasPrecipitation": has_precip,
            "PrecipitationType": ptype if has_precip else "",
            "PrecipitationIntensity": "Light" if has_precip else "",
            "IsDaylight": True,
            "Temperature": daily_temp(temp),
            "RealFeelTemperature": daily_temp(feel),
            "WetBulbTemperature": daily_temp(temp),
            "DewPoint": daily_temp(temp - 8),
            "Wind": {"Speed": metric_speed_kmh(wind_kmh), "Direction": direction_from_degrees(wind_deg)},
            "WindGust": {"Speed": metric_speed_kmh(wind_kmh)},
            "RelativeHumidity": 50,
            "IndoorRelativeHumidity": 50,
            "Visibility": {
                "Metric": {"Value": 10.0, "Unit": "km", "UnitType": 6},
                "Imperial": {"Value": 6.2, "Unit": "mi", "UnitType": 2},
            },
            "Ceiling": {
                "Metric": {"Value": 0, "Unit": "m", "UnitType": 5},
                "Imperial": {"Value": 0, "Unit": "ft", "UnitType": 0},
            },
            "UVIndex": 0,
            "UVIndexText": "Low",
            "PrecipitationProbability": prob,
            "RainProbability": prob if ptype == "Rain" else 0,
            "SnowProbability": prob if ptype == "Snow" else 0,
            "IceProbability": 0,
            "TotalLiquid": daily_rain_mm(precip),
            "Rain": daily_rain_mm(rain),
            "Snow": daily_snow_cm(snow),
            "Ice": daily_rain_mm(0),
            "CloudCover": cloud_cover_from_code(code),
            "MobileLink": "",
            "Link": "",
        })

        if len(result) >= hours:
            break

    return result


@app.after_request
def add_headers(resp):
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/")
def index():
    return jsonify({"ok": True, "version": VERSION, "message": "HTC Weather Proxy is running"})


@app.route("/status")
def status():
    return jsonify({
        "ok": True,
        "version": VERSION,
        "openweather_key_present": bool(OPENWEATHER_API_KEY),
        "shyroke_key": SHYROKE["key"],
        "old_shyroke_key": SHYROKE["old_key"],
        "timezone": timezone_payload(),
        "fixes": {
            "numeric_city_key": True,
            "geoposition_search": True,
            "current_conditions_forced_daytime": True,
            "hourly_forecast_forced_daytime": True,
            "daily_openmeteo": True,
            "daily_5day": True,
            "daily_10day": True,
            "separate_day_night": True,
            "night_icons": True,
            "day_forecast_copied_into_night": False,
            "server_side_cache": True,
            "openmeteo_429_fallback": True,
        },
    })


@app.route("/locations/v1/search")
def locations_search():
    q = request.args.get("q", "")
    if is_shyroke_query(q):
        return jsonify([location_payload()])

    try:
        require_openweather_key()
        data = http_get_json(f"{OWM_BASE}/geo/1.0/direct", {"q": q, "limit": 10, "appid": OPENWEATHER_API_KEY})
        results = []
        for item in data:
            lat = safe_float(item.get("lat"), SHYROKE["lat"])
            lon = safe_float(item.get("lon"), SHYROKE["lon"])
            name = item.get("local_names", {}).get("ru") or item.get("name") or q or "City"
            name_en = item.get("name") or name
            country = item.get("country") or "UA"
            state = item.get("state") or ""
            gen_key = str(abs(int(lat * 10000)) + abs(int(lon * 10000)))
            results.append(location_payload(
                key=gen_key,
                name_ru=name,
                name_en=name_en,
                lat=lat,
                lon=lon,
                country_id=country,
                country_ru=country,
                country_en=country,
                admin_ru=state,
                admin_en=state,
            ))
        if results:
            return jsonify(results)
    except Exception:
        pass

    return jsonify([location_payload()])


@app.route("/locations/v1/cities/geoposition/search")
@app.route("/locations/v1/cities/geoposition/search.json")
def geoposition_search():
    lat, lon = parse_geoposition()
    if distance_km(lat, lon, SHYROKE["lat"], SHYROKE["lon"]) < 50:
        return jsonify(location_payload())

    try:
        require_openweather_key()
        data = http_get_json(f"{OWM_BASE}/geo/1.0/reverse", {
            "lat": lat,
            "lon": lon,
            "limit": 1,
            "appid": OPENWEATHER_API_KEY,
        })
        if data:
            item = data[0]
            name = item.get("local_names", {}).get("ru") or item.get("name") or "City"
            name_en = item.get("name") or name
            country = item.get("country") or "UA"
            state = item.get("state") or ""
            gen_key = str(abs(int(lat * 10000)) + abs(int(lon * 10000)))
            return jsonify(location_payload(
                key=gen_key,
                name_ru=name,
                name_en=name_en,
                lat=lat,
                lon=lon,
                country_id=country,
                country_ru=country,
                country_en=country,
                admin_ru=state,
                admin_en=state,
            ))
    except Exception:
        pass

    return jsonify(location_payload())


@app.route("/locations/v1/timezones")
@app.route("/locations/v1/timezones/<path:key>")
def timezones(key=None):
    return jsonify(timezone_payload())


@app.route("/locations/v1/<path:key>")
def location_by_key(key):
    loc = resolve_location_key(key)
    return jsonify(location_payload(
        key=loc["key"],
        name_ru=loc["name_ru"],
        name_en=loc["name_en"],
        lat=loc["lat"],
        lon=loc["lon"],
    ))


@app.route("/currentconditions/v1/<path:key>")
def current_conditions(key):
    try:
        require_openweather_key()
        loc = resolve_location_key(key)
        data = http_get_json(f"{OWM_BASE}/data/2.5/weather", {
            "lat": loc["lat"],
            "lon": loc["lon"],
            "appid": OPENWEATHER_API_KEY,
            "units": "metric",
            "lang": request.args.get("language", "ru"),
        })

        weather = (data.get("weather") or [{}])[0]
        main = data.get("main") or {}
        wind = data.get("wind") or {}
        clouds = data.get("clouds") or {}
        rain = data.get("rain") or {}
        snow = data.get("snow") or {}

        weather_id = safe_int(weather.get("id"), 800)
        icon_code = weather.get("icon", "01d")
        icon, phrase = owm_icon_phrase(weather_id, icon_code, force_daytime=True)

        dt = datetime.fromtimestamp(safe_int(data.get("dt"), int(time.time())), KYIV_TZ)
        temp = safe_float(main.get("temp"))
        feels = safe_float(main.get("feels_like"), temp)
        pressure = safe_float(main.get("pressure"), 1015)
        humidity = safe_int(main.get("humidity"), 50)
        rain_1h = safe_float(rain.get("1h"), 0)
        snow_1h = safe_float(snow.get("1h"), 0)
        precip_1h = rain_1h + snow_1h
        wind_kmh = safe_float(wind.get("speed"), 0) * 3.6
        gust_kmh = safe_float(wind.get("gust"), wind.get("speed", 0)) * 3.6

        payload = [{
            "LocalObservationDateTime": iso_kyiv(dt),
            "EpochTime": epoch(dt),
            "WeatherText": phrase,
            "WeatherIcon": icon,
            "HasPrecipitation": precip_1h > 0.01,
            "PrecipitationType": "Rain" if rain_1h > 0 else ("Snow" if snow_1h > 0 else ""),
            "IsDayTime": True,
            "Temperature": metric_temp(temp),
            "RealFeelTemperature": metric_temp(feels),
            "RealFeelTemperatureShade": metric_temp(feels),
            "ApparentTemperature": metric_temp(feels),
            "WindChillTemperature": metric_temp(feels),
            "WetBulbTemperature": metric_temp(temp),
            "DewPoint": metric_temp(safe_float(main.get("dew_point"), temp - 8)),
            "RelativeHumidity": humidity,
            "IndoorRelativeHumidity": humidity,
            "Wind": {"Direction": direction_from_degrees(safe_float(wind.get("deg"), 0)), "Speed": metric_speed_kmh(wind_kmh)},
            "WindGust": {"Speed": metric_speed_kmh(gust_kmh)},
            "UVIndex": 0,
            "UVIndexText": "Low",
            "Visibility": {
                "Metric": {"Value": round(safe_float(data.get("visibility"), 10000) / 1000, 1), "Unit": "km", "UnitType": 6},
                "Imperial": {"Value": 6.2, "Unit": "mi", "UnitType": 2},
            },
            "ObstructionsToVisibility": "",
            "CloudCover": safe_int(clouds.get("all"), 0),
            "Ceiling": {
                "Metric": {"Value": 0, "Unit": "m", "UnitType": 5},
                "Imperial": {"Value": 0, "Unit": "ft", "UnitType": 0},
            },
            "Pressure": {
                "Metric": {"Value": pressure, "Unit": "mb", "UnitType": 14},
                "Imperial": {"Value": mb_to_inhg(pressure), "Unit": "inHg", "UnitType": 12},
            },
            "PressureTendency": {"LocalizedText": "Steady", "Code": "S"},
            "Precip1hr": metric_length_mm(precip_1h),
            "PrecipitationSummary": {
                "Precipitation": metric_length_mm(precip_1h),
                "PastHour": metric_length_mm(precip_1h),
                "Past3Hours": metric_length_mm(precip_1h),
                "Past6Hours": metric_length_mm(precip_1h),
                "Past9Hours": metric_length_mm(precip_1h),
                "Past12Hours": metric_length_mm(precip_1h),
                "Past18Hours": metric_length_mm(precip_1h),
                "Past24Hours": metric_length_mm(precip_1h),
            },
            "TemperatureSummary": {
                "Past6HourRange": {"Minimum": metric_temp(temp), "Maximum": metric_temp(temp)},
                "Past12HourRange": {"Minimum": metric_temp(temp), "Maximum": metric_temp(temp)},
                "Past24HourRange": {"Minimum": metric_temp(temp), "Maximum": metric_temp(temp)},
            },
            "MobileLink": "",
            "Link": "",
        }]

        return jsonify(payload)
    except Exception as e:
        return proxy_error(e)


@app.route("/forecasts/v1/daily/5day/<path:key>")
def daily_5day(key):
    try:
        return jsonify(build_daily_forecast(key, 5))
    except Exception as e:
        # В v15 daily не должен падать ProxyError из-за Open-Meteo 429.
        return jsonify(build_daily_forecast_fallback(key, 5, reason=e))


@app.route("/forecasts/v1/daily/10day/<path:key>")
def daily_10day(key):
    try:
        return jsonify(build_daily_forecast(key, 10))
    except Exception as e:
        # В v15 daily не должен падать ProxyError из-за Open-Meteo 429.
        return jsonify(build_daily_forecast_fallback(key, 10, reason=e))


@app.route("/forecasts/v1/hourly/12hour/<path:key>")
def hourly_12hour(key):
    try:
        cache_key = f"hourly:{key}:12"
        cached = cache_get(cache_key)
        if cached:
            return jsonify(cached)
        return jsonify(cache_set(cache_key, build_hourly_forecast(key, 12), HOURLY_CACHE_TTL_SECONDS))
    except Exception as e:
        stale = cache_get_any(f"hourly:{key}:12")
        if stale:
            return jsonify(stale)
        return proxy_error(e)


@app.route("/widget/htc2/city-find.asp")
def htc_city_find():
    loc = location_payload()
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<adc_database>
  <city>
    <location>{loc["LocalizedName"]}</location>
    <location_key>{loc["Key"]}</location_key>
    <country>{loc["Country"]["LocalizedName"]}</country>
    <timezone>{loc["TimeZone"]["Name"]}</timezone>
    <latitude>{loc["GeoPosition"]["Latitude"]}</latitude>
    <longitude>{loc["GeoPosition"]["Longitude"]}</longitude>
  </city>
</adc_database>'''
    return Response(xml, mimetype="application/xml; charset=utf-8")


@app.errorhandler(404)
def not_found(_):
    return jsonify({"ok": False, "ProxyError": "Route not found", "path": request.path, "version": VERSION}), 404


@app.errorhandler(500)
def internal_error(e):
    return proxy_error(e, 500)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
