import math
from typing import Any

import pandas as pd
import pytest

from pitwall.config import BundleBudgets, load_regulations
from pitwall.export.bundle import OverBudget, export_bundle
from pitwall.export.contract import Replay, TelemetryLap
from pitwall.ingest.storage import RaceTables, write_race
from pitwall.ingest.traces import (
    align_distance,
    fastest_laps,
    fetch_traces,
    lap_trace,
    write_traces,
)
from tests.conftest import BUDGETS, CONFIG, DRIVERS

SPEED_KMH = 180.0  # 50 m/s
SAMPLE_S = 0.25


class TraceClient:
    """OpenF1 car data at a constant speed and a circular location trace, inside the window."""

    def __init__(self) -> None:
        self.windows: list[tuple[str, int]] = []

    def get(self, endpoint: str, **params: Any) -> list[dict[str, Any]]:
        if endpoint == "drivers":
            return [{"driver_number": n, "name_acronym": code} for n, (code, _) in DRIVERS.items()]
        start = pd.Timestamp(params["date>"])
        end = pd.Timestamp(params["date<"])
        self.windows.append((endpoint, params["driver_number"]))
        times = pd.date_range(start + pd.Timedelta(seconds=0.1), end, freq=f"{SAMPLE_S}s")
        if endpoint == "car_data":
            return [
                {
                    "date": t.isoformat(),
                    "speed": SPEED_KMH,
                    "throttle": 104,
                    "brake": 100 * (k % 2),
                    "n_gear": 7,
                }
                for k, t in enumerate(times)
            ]
        assert endpoint == "location"
        angles = [2 * math.pi * k / len(times) for k in range(len(times))]
        return [
            {"date": t.isoformat(), "x": round(1000 * math.cos(a)), "y": round(1000 * math.sin(a))}
            for t, a in zip(times, angles, strict=True)
        ]


def test_fastest_lap_is_the_quickest_lap_at_pace(race_tables: RaceTables) -> None:
    laps = race_tables.laps.copy()
    # A shortcut lap is an outlier however fast: it is not the driver's fastest lap.
    shortcut = (laps["driver"] == "VER") & (laps["lap"] == 10)
    laps.loc[shortcut, ["lap_time_s", "lap_class"]] = [50.0, "outlier"]
    best = fastest_laps(laps)
    assert sorted(best["driver"]) == ["LEC", "SAR", "VER"]
    assert best["lap_time_s"].is_monotonic_increasing
    ver = best[best["driver"] == "VER"].iloc[0]
    assert ver["lap"] != 10
    assert ver["lap_class"] in ("clean", "traffic")


def test_lap_trace_runs_line_to_line() -> None:
    start = pd.Timestamp("2024-03-02 15:00", tz="UTC")
    samples = TraceClient().get(
        "car_data",
        driver_number=1,
        **{"date>": start.isoformat(), "date<": (start + pd.Timedelta(seconds=10)).isoformat()},
    )
    trace = lap_trace(samples, start, 10.0)
    assert trace["time_s"].iloc[0] == 0
    assert trace["time_s"].iloc[-1] == 10
    assert trace["distance_m"].iloc[-1] == pytest.approx(500)
    assert trace["distance_m"].is_monotonic_increasing
    assert trace["throttle"].max() == 100
    assert set(trace["brake"]) == {True, False}


def test_laps_align_to_the_median_length() -> None:
    def lap(driver: str, length: float) -> pd.DataFrame:
        return pd.DataFrame({"driver": driver, "lap": 5, "distance_m": [0, length / 2, length]})

    aligned = align_distance(pd.concat([lap("A", 990), lap("B", 1000), lap("C", 1030)]))
    assert list(aligned.groupby("driver")["distance_m"].max()) == [1000, 1000, 1000]
    assert list(aligned[aligned["driver"] == "C"]["distance_m"]) == [0, 500, 1000]


def _export(race_tables: RaceTables, tmp_path, budgets: BundleBudgets = BUDGETS):
    data_dir, bundle_dir = tmp_path / "data", tmp_path / "bundle"
    write_race(data_dir, race_tables)
    client = TraceClient()
    write_traces(data_dir, race_tables, *fetch_traces(client, race_tables))
    manifest = export_bundle(data_dir, bundle_dir, "abc", CONFIG.sim, load_regulations(), budgets)
    return client, manifest, bundle_dir


def test_export_writes_the_replay_and_a_telemetry_lap_per_driver(
    race_tables: RaceTables, tmp_path
) -> None:
    client, manifest, bundle_dir = _export(race_tables, tmp_path)
    # One car-data window per driver, one location window for the reference lap.
    reference_number = client.windows[-1][1]
    assert sorted(client.windows) == [
        ("car_data", 1),
        ("car_data", 2),
        ("car_data", 16),
        ("location", reference_number),
    ]
    entry = manifest.races[0]
    assert entry.replay_path == "races/2024/01.replay.json"
    replay = Replay.model_validate_json((bundle_dir / entry.replay_path).read_text())

    assert [car.driver for car in replay.cars] == ["VER", "LEC", "SAR"]
    completed = race_tables.results.set_index("driver")["laps_completed"]
    for car in replay.cars:
        assert len(car.lap_end_s) == completed[car.driver]
        assert car.lap_end_s == sorted(car.lap_end_s)
    assert [(n.kind, n.start_lap, n.end_lap) for n in replay.neutralisations] == [("SC", 31, 33)]

    reference = replay.fastest_laps[0]
    assert (replay.track.driver, replay.track.lap) == (reference.driver, reference.lap)
    assert len(replay.track.x) == len(replay.track.y) == len(replay.track.t_ms)
    for fastest in replay.fastest_laps:
        lap = TelemetryLap.model_validate_json((bundle_dir / fastest.telemetry_path).read_text())
        assert (lap.driver, lap.lap) == (fastest.driver, fastest.lap)
        assert lap.time_ms[0] == 0
        assert lap.time_ms[-1] == round(fastest.lap_time_s * 1000)
        assert set(lap.brake) == {0, 1}


def test_a_file_over_budget_fails_the_export(race_tables: RaceTables, tmp_path) -> None:
    tight = BUDGETS.model_copy(update={"telemetry_lap_gz_bytes": 100})
    with pytest.raises(OverBudget, match=r"telemetry/\w+\.json"):
        _export(race_tables, tmp_path, tight)
    assert not (tmp_path / "bundle" / "manifest.json").exists()
