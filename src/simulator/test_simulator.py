"""Integration test — verifies the full simulator stack end-to-end."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from src.simulator.anomaly_injector import AnomalyInjector
from src.simulator.engine import SimulationEngine
from src.simulator.telemetry import TelemetryGenerator
from src.simulator.topology import NetworkTopology


def test_topology() -> NetworkTopology:
    topo = NetworkTopology()
    g = topo.get_graph()
    num_nodes = g.number_of_nodes()
    num_links = g.number_of_edges() // 2  # bidirectional → count once
    print(f"✅ Topology: {num_nodes} nodes, {num_links} links")
    return topo


def test_baseline(topo: NetworkTopology):
    gen = TelemetryGenerator(topo, seed=42)
    df = gen.generate_baseline(duration_hours=4)
    print(f"✅ Baseline telemetry: {len(df):,} readings")
    return df


def test_anomalies(topo: NetworkTopology, df):
    injector = AnomalyInjector(topo, seed=7)
    anomalous_df, labels = injector.inject_random_scenarios(
        df, n_scenarios=3, min_gap_minutes=30
    )

    summaries = [f"{lbl.scenario_type}({lbl.severity})" for lbl in labels]
    print(f"✅ Anomalies injected: {', '.join(summaries)}")

    # Label breakdown: timestamps that fall inside any anomaly window vs normal
    import pandas as pd
    ts_col = pd.to_datetime(anomalous_df["timestamp"], utc=True)
    anomalous_mask = ts_col.apply(lambda t: any(
        lbl.start_time <= t <= lbl.end_time for lbl in labels
    ))
    n_anomalous = anomalous_mask.sum()
    n_normal = (~anomalous_mask).sum()
    pct = n_anomalous / len(anomalous_df) * 100
    print(f"   Label breakdown  : {n_anomalous:,} anomalous timestamps "
          f"({pct:.1f}%)  |  {n_normal:,} normal")

    for lbl in labels:
        dur = int((lbl.end_time - lbl.start_time).total_seconds() // 60)
        print(f"   • [{lbl.severity:8s}] {lbl.scenario_type:22s}  "
              f"start={lbl.start_time.strftime('%H:%M')}  "
              f"duration={dur:>3}min  "
              f"links={len(lbl.affected_links)}")

    return labels


async def test_engine(topo: NetworkTopology) -> None:
    engine = SimulationEngine(topo, speed_multiplier=120.0, seed=42)

    ticks: list[int] = []

    def counter(_ts: str, _state: dict) -> None:
        ticks.append(1)

    engine.subscribe(counter)
    await engine.start()
    await asyncio.sleep(10)
    await engine.stop()

    assert engine.get_tick_count() > 0, "Engine produced no ticks"
    assert not engine.is_running(), "Engine did not stop cleanly"
    print(f"✅ Engine: {engine.get_tick_count()} ticks in 10 seconds  "
          f"(sim time advanced {engine.get_tick_count()} minutes)")


async def main() -> None:
    print("\n── Phase 2 Integration Test ─────────────────────────\n")

    topo   = test_topology()
    df     = test_baseline(topo)
    _      = test_anomalies(topo, df)
    await test_engine(topo)

    print("\n🎉 Phase 2 Complete — Simulator fully operational\n")


if __name__ == "__main__":
    asyncio.run(main())
