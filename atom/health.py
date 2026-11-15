"""Apple Health data: store, import and summaries.

Apple Health has no cloud API; the data leaves the phone in one of two ways:
  * the Health app's "Export All Health Data" file (export.zip / export.xml), uploaded on the Health page, or
  * pushes to POST /api/health/ingest (iOS Shortcuts or a Health-export app), authenticated by a bearer token.

Cumulative metrics (energy, steps, ...) are stored as one value per (day, type, source). Several sources (iPhone, Watch,
other apps) measure the same walk, so summaries take the largest source for a day instead of adding them up.
Point metrics (weight, resting heart rate, ...) keep every reading. Re-importing is idempotent.
"""
from __future__ import annotations

import secrets
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO, Iterable
from xml.etree import ElementTree as ET

from .db import Database

# HealthKit identifier -> (our type, unit, factor). Cumulative types are summed per day.
CUMULATIVE = {
    "HKQuantityTypeIdentifierActiveEnergyBurned": ("active_energy", "kcal"),
    "HKQuantityTypeIdentifierBasalEnergyBurned": ("basal_energy", "kcal"),
    "HKQuantityTypeIdentifierStepCount": ("steps", "count"),
    "HKQuantityTypeIdentifierDistanceWalkingRunning": ("distance", "km"),
    "HKQuantityTypeIdentifierAppleExerciseTime": ("exercise", "min"),
    "HKQuantityTypeIdentifierDietaryEnergyConsumed": ("dietary_energy", "kcal"),
}
POINTS = {
    "HKQuantityTypeIdentifierBodyMass": ("weight", "kg"),
    "HKQuantityTypeIdentifierBodyFatPercentage": ("body_fat", "%"),
    "HKQuantityTypeIdentifierRestingHeartRate": ("resting_hr", "bpm"),
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": ("hrv", "ms"),
}
CUM_TYPES = {v[0] for v in CUMULATIVE.values()}
POINT_TYPES = {v[0] for v in POINTS.values()}
TOKEN_KEY = "health_ingest_token"


def _to_kcal(value: float, unit: str) -> float:
    return value * 4.184 if unit.lower() == "kj" else value


def _to_km(value: float, unit: str) -> float:
    return {"mi": value * 1.609344, "m": value / 1000, "km": value}.get(unit.lower(), value)


def _to_kg(value: float, unit: str) -> float:
    return {"lb": value * 0.45359237, "g": value / 1000, "kg": value}.get(unit.lower(), value)


def _to_min(value: float, unit: str) -> float:
    return {"s": value / 60, "sec": value / 60, "hr": value * 60, "h": value * 60, "min": value}.get(unit.lower(), value)


def parse_ts(s: str) -> float:
    """'2026-11-13 08:15:02 +0100' (Health export) or ISO 8601 -> epoch seconds."""
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).timestamp()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError as e:
        raise ValueError(f"bad date '{s}'") from e


def day_of(s: str) -> str:
    """Calendar day as written in the source date string (the phone's local day)."""
    return s.strip()[:10]


def normalize(kind: str, value: float, unit: str) -> float:
    if kind in ("active_energy", "basal_energy", "dietary_energy"):
        return _to_kcal(value, unit)
    if kind == "distance":
        return _to_km(value, unit)
    if kind == "weight":
        return _to_kg(value, unit)
    if kind == "exercise":
        return _to_min(value, unit)
    if kind == "body_fat" and unit in ("", "count") and value <= 1:
        return value * 100
    return value


class HealthStore:
    def __init__(self, db: Database):
        self.db = db

    # -------------------------------------------------------------- token
    def token(self) -> str:
        row = self.db.one("SELECT value FROM settings WHERE key=?", (TOKEN_KEY,))
        if row and row["value"]:
            return row["value"]
        return self.rotate_token()

    def rotate_token(self) -> str:
        t = secrets.token_urlsafe(24)
        self.db.execute("INSERT INTO settings (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (TOKEN_KEY, t))
        return t

    def check_token(self, given: str) -> bool:
        return bool(given) and secrets.compare_digest(given, self.token())

    # -------------------------------------------------------------- writes
    def put_daily(self, day: str, kind: str, source: str, value: float, unit: str = "") -> None:
        self.db.execute(
            "INSERT INTO health_daily (day,type,source,value,unit,updated_at) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(day,type,source) DO UPDATE SET value=excluded.value, unit=excluded.unit, updated_at=excluded.updated_at",
            (day, kind, source, value, unit, time.time()))

    def put_point(self, source: str, kind: str, ts: float, day: str, value: float, unit: str = "") -> None:
        self.db.execute(
            "INSERT INTO health_points (source,type,ts,day,value,unit) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(source,type,ts) DO UPDATE SET value=excluded.value, unit=excluded.unit, day=excluded.day",
            (source, kind, ts, day, value, unit))

    def put_workout(self, source: str, kind: str, start_ts: float, end_ts: float | None, day: str, minutes: float, kcal: float, km: float) -> None:
        self.db.execute(
            "INSERT INTO health_workouts (source,kind,start_ts,end_ts,day,minutes,kcal,km) VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(source,kind,start_ts) DO UPDATE SET end_ts=excluded.end_ts, day=excluded.day, minutes=excluded.minutes, kcal=excluded.kcal, km=excluded.km",
            (source, kind, start_ts, end_ts, day, minutes, kcal, km))

    def ingest(self, items: Iterable[dict], default_source: str = "iphone") -> dict:
        """Push API. Each item: {type, value, unit?, date|start, source?}. Cumulative types are a day's total
        (`date`); point types are a reading (`start` or `date`). {type:'workout', kind, start, minutes, kcal, km}."""
        stored, errors = 0, []
        for i, it in enumerate(items):
            try:
                kind = str(it.get("type", "")).strip().lower()
                source = str(it.get("source") or default_source)[:60]
                when = str(it.get("start") or it.get("date") or "")
                if not when:
                    raise ValueError("missing date")
                day = day_of(when)
                unit = str(it.get("unit") or "")
                if kind == "workout":
                    st = parse_ts(when)
                    en = parse_ts(str(it["end"])) if it.get("end") else None
                    mins = float(it.get("minutes") or ((en - st) / 60 if en else 0))
                    self.put_workout(source, str(it.get("kind") or "workout")[:40], st, en, day, mins,
                                     float(it.get("kcal") or 0), float(it.get("km") or 0))
                elif kind in CUM_TYPES:
                    self.put_daily(day, kind, source, normalize(kind, float(it["value"]), unit), unit)
                elif kind in POINT_TYPES:
                    self.put_point(source, kind, parse_ts(when), day, normalize(kind, float(it["value"]), unit), unit)
                else:
                    raise ValueError(f"unknown type '{kind}'")
                stored += 1
            except (KeyError, ValueError, TypeError) as e:
                errors.append({"index": i, "error": str(e)})
        return {"stored": stored, "errors": errors[:20], "error_count": len(errors)}

    def import_export(self, path: Path) -> dict:
        """Import Apple Health's export.zip or export.xml (streamed; the file can be gigabytes)."""
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                names = [n for n in z.namelist() if n.endswith("export.xml") and "cda" not in n.lower()]
                if not names:
                    raise ValueError("no export.xml in the zip (is this the Health export?)")
                with z.open(names[0]) as f:
                    return self._import_xml(f)
        with open(path, "rb") as f:
            return self._import_xml(f)

    def _import_xml(self, f: BinaryIO) -> dict:
        daily: dict[tuple[str, str, str], list] = {}          # (day,type,source) -> [sum, unit]
        n_records = n_points = n_workouts = 0
        for _ev, el in ET.iterparse(f, events=("end",)):
            tag = el.tag
            if tag == "Record":
                hk = el.get("type", "")
                src = (el.get("sourceName") or "unknown")[:60]
                try:
                    if hk in CUMULATIVE:
                        kind, unit = CUMULATIVE[hk]
                        v = normalize(kind, float(el.get("value", "0")), el.get("unit", ""))
                        key = (day_of(el.get("startDate", "")), kind, src)
                        acc = daily.setdefault(key, [0.0, unit])
                        acc[0] += v
                        n_records += 1
                    elif hk in POINTS:
                        kind, unit = POINTS[hk]
                        sd = el.get("startDate", "")
                        self.put_point(src, kind, parse_ts(sd), day_of(sd), normalize(kind, float(el.get("value", "0")), el.get("unit", "")), unit)
                        n_points += 1
                except (ValueError, TypeError):
                    pass
            elif tag == "Workout":
                try:
                    sd = el.get("startDate", "")
                    kind = (el.get("workoutActivityType") or "").replace("HKWorkoutActivityType", "") or "Workout"
                    mins = _to_min(float(el.get("duration", "0")), el.get("durationUnit", "min"))
                    kcal = _to_kcal(float(el.get("totalEnergyBurned") or 0), el.get("totalEnergyBurnedUnit", "kcal"))
                    km = _to_km(float(el.get("totalDistance") or 0), el.get("totalDistanceUnit", "km"))
                    self.put_workout((el.get("sourceName") or "unknown")[:60], kind, parse_ts(sd),
                                     parse_ts(el.get("endDate")) if el.get("endDate") else None, day_of(sd), mins, kcal, km)
                    n_workouts += 1
                except (ValueError, TypeError):
                    pass
            if tag in ("Record", "Workout", "WorkoutEvent", "MetadataEntry", "ActivitySummary", "Correlation"):
                if tag != "MetadataEntry":
                    el.clear()
        with self.db.lock:
            self.db.conn.execute("BEGIN")
            try:
                for (day, kind, src), (total, unit) in daily.items():
                    self.put_daily(day, kind, src, total, unit)
                self.db.conn.execute("COMMIT")
            except Exception:
                self.db.conn.execute("ROLLBACK")
                raise
        return {"records": n_records, "points": n_points, "workouts": n_workouts, "days": len({k[0] for k in daily})}

    # -------------------------------------------------------------- reads
    def summary(self, days: int = 30, today: str | None = None) -> dict:
        today = today or datetime.now().strftime("%Y-%m-%d")
        start = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        series: dict[str, dict[str, Any]] = {}
        d = datetime.strptime(start, "%Y-%m-%d")
        for _ in range(days):
            series[d.strftime("%Y-%m-%d")] = {"day": d.strftime("%Y-%m-%d")}
            d += timedelta(days=1)
        for r in self.db.all("SELECT day,type,MAX(value) AS v FROM health_daily WHERE day>=? AND day<=? GROUP BY day,type", (start, today)):
            if r["day"] in series:
                series[r["day"]][r["type"]] = round(r["v"], 1)
        for row in series.values():
            if "active_energy" in row and "basal_energy" in row:
                row["total_energy"] = round(row["active_energy"] + row["basal_energy"], 1)
        weight = [{"day": r["day"], "ts": r["ts"], "value": round(r["value"], 2)} for r in self.db.all(
            "SELECT day,ts,value FROM health_points WHERE type='weight' AND day>=? AND day<=? ORDER BY ts", (start, today))]
        points = {t: [{"day": r["day"], "value": round(r["value"], 1)} for r in self.db.all(
            "SELECT day,AVG(value) AS value FROM health_points WHERE type=? AND day>=? AND day<=? GROUP BY day ORDER BY day", (t, start, today))]
            for t in ("resting_hr", "hrv", "body_fat")}
        workouts = [dict(r) for r in self.db.all(
            "SELECT kind,start_ts,day,minutes,kcal,km,source FROM health_workouts WHERE day>=? AND day<=? ORDER BY start_ts DESC LIMIT 100", (start, today))]
        rows = list(series.values())

        def avg(key: str) -> float | None:
            v = [r[key] for r in rows if key in r and r["day"] != today]       # today is still in progress
            return round(sum(v) / len(v), 1) if v else None

        todayrow = series.get(today, {})
        counts = self.db.one("SELECT (SELECT COUNT(*) FROM health_daily) AS daily, (SELECT COUNT(*) FROM health_points) AS points, "
                             "(SELECT COUNT(*) FROM health_workouts) AS workouts, (SELECT MAX(updated_at) FROM health_daily) AS last_daily")
        return {"days": days, "today": today, "series": rows, "weight": weight, "points": points, "workouts": workouts,
                "averages": {k: avg(k) for k in ("active_energy", "basal_energy", "total_energy", "steps", "exercise", "distance", "dietary_energy")},
                "today_values": todayrow,
                "has_data": bool(counts["daily"] or counts["points"] or counts["workouts"]),
                "last_update": counts["last_daily"]}
