"""Apple Health import, ingest and summary."""
import zipfile

from atom.db import Database
from atom.health import HealthStore

XML = """<?xml version="1.0" encoding="UTF-8"?>
<HealthData>
 <Record type="HKQuantityTypeIdentifierActiveEnergyBurned" sourceName="Watch" unit="kcal" startDate="2026-11-10 08:00:00 +0100" endDate="2026-11-10 08:30:00 +0100" value="100"/>
 <Record type="HKQuantityTypeIdentifierActiveEnergyBurned" sourceName="Watch" unit="kcal" startDate="2026-11-10 18:00:00 +0100" endDate="2026-11-10 18:30:00 +0100" value="250.5"/>
 <Record type="HKQuantityTypeIdentifierBasalEnergyBurned" sourceName="Watch" unit="kcal" startDate="2026-11-10 00:00:00 +0100" endDate="2026-11-10 23:00:00 +0100" value="1700"/>
 <Record type="HKQuantityTypeIdentifierStepCount" sourceName="iPhone" unit="count" startDate="2026-11-10 09:00:00 +0100" endDate="2026-11-10 09:10:00 +0100" value="3000"/>
 <Record type="HKQuantityTypeIdentifierStepCount" sourceName="Watch" unit="count" startDate="2026-11-10 09:00:00 +0100" endDate="2026-11-10 09:10:00 +0100" value="3100"/>
 <Record type="HKQuantityTypeIdentifierBodyMass" sourceName="Scale" unit="lb" startDate="2026-11-10 07:00:00 +0100" endDate="2026-11-10 07:00:00 +0100" value="176"/>
 <Workout workoutActivityType="HKWorkoutActivityTypeRunning" duration="30" durationUnit="min" totalDistance="5" totalDistanceUnit="km" totalEnergyBurned="300" totalEnergyBurnedUnit="kcal" sourceName="Watch" startDate="2026-11-10 18:00:00 +0100" endDate="2026-11-10 18:30:00 +0100"/>
</HealthData>"""


def test_import_summary_and_idempotent(tmp_path):
    store = HealthStore(Database(":memory:"))
    z = tmp_path / "export.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("apple_health_export/export.xml", XML)
    for _ in range(2):                                      # re-import must not double anything
        r = store.import_export(z)
    assert r["workouts"] == 1 and r["points"] == 1
    s = store.summary(30, today="2026-11-12")
    day = next(x for x in s["series"] if x["day"] == "2026-11-10")
    assert day["active_energy"] == 350.5 and day["basal_energy"] == 1700 and day["total_energy"] == 2050.5
    assert day["steps"] == 3100                             # largest source, not iPhone + Watch
    assert abs(s["weight"][0]["value"] - 79.83) < 0.01      # lb -> kg
    assert s["workouts"][0]["kind"] == "Running" and s["workouts"][0]["kcal"] == 300
    assert s["has_data"]


def test_ingest_and_api(client):
    r = client.get("/api/health/summary?days=7")
    assert r.status_code == 200 and r.json()["has_data"] is False
    body = {"samples": [{"type": "active_energy", "date": "2026-11-13", "value": 640, "unit": "kcal"},
                        {"type": "bogus", "date": "2026-11-13", "value": 1}]}
    assert client.post("/api/health/ingest", json=body).status_code == 401
    tok = client.get("/api/health/token").json()["token"]
    r = client.post("/api/health/ingest", json=body, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200 and r.json()["stored"] == 1 and r.json()["error_count"] == 1
    r = client.post("/api/health/import", content=b"not xml")
    assert r.status_code == 422
