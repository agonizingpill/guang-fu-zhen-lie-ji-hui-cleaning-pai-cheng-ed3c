"""Deterministic generator for the weighbridge reference fixture.

Run from backend/: python -m scripts.generate_weigh_fixture
The fixture is read-only at runtime; every estimate records its SHA256.
"""
import json
import random
from pathlib import Path

VEHICLES = 24
TRIPS = 12
# Two trucks only recently joined the route and have little history.
SHORT_HISTORY = {"甘A·W2307": 3, "甘A·W2318": 4}


def generate():
    rng = random.Random(2026)
    rows = []
    for index in range(VEHICLES):
        plate = f"甘A·W{2301 + index}"
        tare = round(rng.uniform(4200, 7000), 1)
        tank = round(rng.uniform(3000, 6000), 0)
        base_loss = rng.uniform(0.004, 0.013)
        noise = rng.uniform(0.0005, 0.0042)
        trips = SHORT_HISTORY.get(plate, TRIPS)
        for _ in range(trips):
            ambient = round(rng.uniform(5, 36), 2)
            haul = round(rng.uniform(6, 52), 2)
            loaded = round(rng.uniform(0.45, 0.95) * tank, 1)
            density = 1 - 0.00032 * (ambient - 20)
            loss = base_loss + 0.00019 * haul + 0.00022 * max(0.0, ambient - 27)
            loss = min(0.05, max(0.002, loss + rng.gauss(0, noise)))
            received = max(0.0, round(loaded * (1 - loss) + rng.gauss(0, 4.0), 1))
            gross = round(tare + loaded * density + rng.gauss(0, 4.0), 1)
            rows.append({
                "vehicle_code": plate,
                "station": "北岭接收站" if (2301 + index) % 2 == 0 else "西坡接收站",
                "gross_kg": gross,
                "tare_kg": tare,
                "ambient_temp_c": ambient,
                "haul_km": haul,
                "tank_capacity_l": tank,
                "loaded_liters": loaded,
                "received_liters": received,
            })
    return rows


if __name__ == "__main__":
    rows = generate()
    target = Path(__file__).resolve().parents[1] / "fixtures" / "weigh_reference.json"
    target.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} rows to {target}")
