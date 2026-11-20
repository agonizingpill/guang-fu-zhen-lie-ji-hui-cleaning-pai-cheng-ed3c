"""Net received water estimator for mixed-load wastewater trucks.

Receiving stations only issue a whole-truck weigh ticket. Historical tickets
(gross/tare, ambient, haul distance, tank size) are paired with the station's
actual received litres and used to estimate the net received water of a new
trip. Generalisation is validated by leaving one vehicle out at a time: every
vehicle's rows are predicted by a forest trained on all other vehicles, so a
truck that the model cannot represent shows a large per-vehicle error instead
of a deceptively good training score.

When a vehicle has too little history or its leave-one-vehicle-out MAPE is over
the threshold, the estimate is not trusted and the trip requires a measured net
volume before any receipt can be allocated.
"""
import hashlib
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error

FEATURES = ['gross_kg', 'tare_kg', 'ambient_temp_c', 'haul_km', 'tank_capacity_l']
MIN_HISTORY_TRIPS = 5
MAX_HOLDOUT_MAPE_PCT = 8.0
FIXTURE = Path(__file__).resolve().parents[1] / 'fixtures/weigh_reference.json'


def _forest():
    return RandomForestRegressor(n_estimators=120, max_depth=12, min_samples_leaf=2, random_state=42, n_jobs=1)


@lru_cache(maxsize=1)
def train_reference():
    raw = FIXTURE.read_bytes()
    rows = json.loads(raw)
    x = np.array([[r[k] for k in FEATURES] for r in rows], dtype=float)
    y = np.array([r['received_liters'] for r in rows], dtype=float)
    groups = np.array([r['vehicle_code'] for r in rows])
    vehicles = sorted(set(groups.tolist()))
    per_vehicle = {}
    for vehicle in vehicles:
        held = groups == vehicle
        train = ~held
        model = _forest().fit(x[train], y[train])
        pred = model.predict(x[held])
        per_vehicle[vehicle] = {
            'trips': int(held.sum()),
            'holdout_mae_l': round(float(mean_absolute_error(y[held], pred)), 3),
            'holdout_mape_pct': round(float(np.mean(np.abs((y[held] - pred) / y[held])) * 100), 3),
            'mean_received_l': round(float(y[held].mean()), 3),
        }
    model = _forest().fit(x, y)
    global_mape = float(np.mean([v['holdout_mape_pct'] for v in per_vehicle.values()]))
    evidence = {
        'reference_rows': len(rows),
        'vehicle_count': len(vehicles),
        'global_holdout_mape_pct': round(global_mape, 3),
        'max_holdout_mape_pct': MAX_HOLDOUT_MAPE_PCT,
        'min_history_trips': MIN_HISTORY_TRIPS,
        'per_vehicle': per_vehicle,
        'features': FEATURES,
        'target': 'received_liters',
        'random_state': 42,
        'method': 'RandomForestRegressor / 120 trees / max_depth 12 / leave-one-vehicle-out',
        'sha256': hashlib.sha256(raw).hexdigest(),
    }
    return model, evidence


def estimate(fields):
    """Estimate net litres for one weigh ticket and explain whether it is usable."""
    model, evidence = train_reference()
    vehicle = fields['vehicle_code']
    history = evidence['per_vehicle'].get(vehicle)
    reasons = []
    if not history:
        reasons.append('该车无历史磅单，净收水量须现场实测')
    else:
        if history['trips'] < MIN_HISTORY_TRIPS:
            reasons.append(f"该车仅{history['trips']}张历史磅单，少于{MIN_HISTORY_TRIPS}张，须现场实测")
        if history['holdout_mape_pct'] > MAX_HOLDOUT_MAPE_PCT:
            reasons.append(f"按车辆留出误差{history['holdout_mape_pct']}%超过{MAX_HOLDOUT_MAPE_PCT}%，须现场实测")
    predicted = float(model.predict([[float(fields[k]) for k in FEATURES]])[0])
    predicted = max(0.0, round(predicted, 1))
    if fields.get('tank_capacity_l'):
        predicted = min(predicted, float(fields['tank_capacity_l']))
    return predicted, {
        'vehicle_code': vehicle,
        'estimated_net_liters': predicted,
        'history_trips': history['trips'] if history else 0,
        'holdout_mae_l': history['holdout_mae_l'] if history else None,
        'holdout_mape_pct': history['holdout_mape_pct'] if history else None,
        'threshold_pct': MAX_HOLDOUT_MAPE_PCT,
        'min_history_trips': MIN_HISTORY_TRIPS,
        'measured_required': bool(reasons),
        'reason': '；'.join(reasons) if reasons else '按车辆留出误差在阈值内，采用估算净收',
        'features': {k: float(fields[k]) for k in FEATURES},
        'model_sha256': evidence['sha256'],
        'global_holdout_mape_pct': evidence['global_holdout_mape_pct'],
    }
