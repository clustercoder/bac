from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import numpy as np
import pandas as pd

from src.simulator.telemetry import TelemetryGenerator
from src.simulator.topology import NetworkTopology

ScenarioType = Literal[
    "congestion_cascade",
    "hardware_degradation",
    "ddos_surge",
    "misconfiguration",
    "fiber_cut",
]


@dataclass
class ScenarioLabel:
    scenario_id: str
    scenario_type: ScenarioType
    start_time: datetime
    end_time: datetime
    root_cause: str
    root_cause_node: str | None
    root_cause_link: str | None
    affected_nodes: list[str]
    affected_links: list[str]
    severity: Literal["low", "medium", "high", "critical"]
    description: str


class AnomalyInjector:
    """
    Wraps a TelemetryGenerator and overlays labeled failure scenarios onto
    generated telemetry.  Each inject_* method modifies the in-memory
    telemetry DataFrame produced by generate_baseline() in-place — but
    following the immutability guideline the helper returns a *new* copy.
    """

    def __init__(self, topology: NetworkTopology, seed: int = 0) -> None:
        self._topology = topology
        self._rng = np.random.default_rng(seed)
        self._labels: list[ScenarioLabel] = []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_mask(
        df: pd.DataFrame,
        entity_id: str,
        start: datetime,
        end: datetime,
        entity_type: str,
    ) -> pd.Series:
        ts = pd.to_datetime(df["timestamp"], utc=True)
        return (
            (df["entity_id"] == entity_id)
            & (df["entity_type"] == entity_type)
            & (ts >= start)
            & (ts <= end)
        )

    @staticmethod
    def _clamp(series: pd.Series | np.ndarray, lo: float, hi: float) -> np.ndarray:
        return np.clip(series, lo, hi)

    # ------------------------------------------------------------------
    # Scenario implementations
    # ------------------------------------------------------------------

    def inject_congestion_cascade(
        self,
        df: pd.DataFrame,
        start_time: datetime,
        duration_minutes: int = 45,
        root_link: str = "CR1-CR2",
    ) -> tuple[pd.DataFrame, ScenarioLabel]:
        """
        Simulate a traffic surge on the core interconnect that cascades to
        adjacent aggregation links.  Utilization on root link spikes to
        85-98%, latency and packet loss rise; neighbouring links see a
        secondary elevation of 10-20 pp.
        """
        end_time = start_time + timedelta(minutes=duration_minutes)
        out = df.copy()

        # Root link — heavy congestion
        mask_root = self._row_mask(out, root_link, start_time, end_time, "link")
        n_root = mask_root.sum()
        if n_root > 0:
            out.loc[mask_root, "utilization_pct"] = self._clamp(
                out.loc[mask_root, "utilization_pct"]
                + self._rng.uniform(40, 55, size=n_root),
                0, 100,
            )
            out.loc[mask_root, "latency_ms"] = (
                out.loc[mask_root, "latency_ms"] * self._rng.uniform(2.5, 4.0, size=n_root)
            )
            out.loc[mask_root, "packet_loss_pct"] = self._clamp(
                out.loc[mask_root, "packet_loss_pct"]
                + self._rng.uniform(1.5, 4.0, size=n_root),
                0, 100,
            )
            cap = out.loc[mask_root, "capacity_gbps"].values
            out.loc[mask_root, "throughput_gbps"] = self._clamp(
                out.loc[mask_root, "utilization_pct"] / 100.0 * cap,
                0, cap.max(),
            )

        # Secondary links adjacent to CR1 and CR2 (use canonical sorted IDs)
        secondary_links = [
            self._topology.get_link_id("CR1", "AGG1"),
            self._topology.get_link_id("CR1", "AGG2"),
            self._topology.get_link_id("CR2", "AGG3"),
            self._topology.get_link_id("CR2", "AGG4"),
        ]
        for lid in secondary_links:
            mask = self._row_mask(out, lid, start_time, end_time, "link")
            n = mask.sum()
            if n > 0:
                boost = self._rng.uniform(10, 22, size=n)
                out.loc[mask, "utilization_pct"] = self._clamp(
                    out.loc[mask, "utilization_pct"] + boost, 0, 100
                )
                out.loc[mask, "latency_ms"] = (
                    out.loc[mask, "latency_ms"] * self._rng.uniform(1.3, 1.8, size=n)
                )

        label = ScenarioLabel(
            scenario_id=str(uuid.uuid4()),
            scenario_type="congestion_cascade",
            start_time=start_time,
            end_time=end_time,
            root_cause="Traffic surge on core interconnect causing cascade to aggregation layer",
            root_cause_node=None,
            root_cause_link=root_link,
            affected_nodes=["CR1", "CR2"],
            affected_links=[root_link] + secondary_links,
            severity="high",
            description=(
                f"Core link {root_link} congestion cascade "
                f"({duration_minutes} min) affecting aggregation links"
            ),
        )
        self._labels.append(label)
        return out, label

    def inject_hardware_degradation(
        self,
        df: pd.DataFrame,
        start_time: datetime,
        duration_minutes: int = 120,
        root_node: str = "AGG1",
    ) -> tuple[pd.DataFrame, ScenarioLabel]:
        """
        Gradual hardware degradation: CPU and temperature steadily climb on
        the affected node; attached link latency increases proportionally.
        """
        end_time = start_time + timedelta(minutes=duration_minutes)
        out = df.copy()

        mask_node = self._row_mask(out, root_node, start_time, end_time, "node")
        n = mask_node.sum()
        if n > 0:
            ramp = np.linspace(0.0, 1.0, n)
            out.loc[mask_node, "cpu_pct"] = self._clamp(
                out.loc[mask_node, "cpu_pct"] + ramp * 35, 0, 100
            )
            out.loc[mask_node, "temperature_c"] = self._clamp(
                out.loc[mask_node, "temperature_c"] + ramp * 18, 20, 90
            )
            out.loc[mask_node, "memory_pct"] = self._clamp(
                out.loc[mask_node, "memory_pct"] + ramp * 20, 0, 100
            )
            out.loc[mask_node, "buffer_drops"] = (
                out.loc[mask_node, "buffer_drops"] + (ramp * 15).astype(int)
            )

        # Attached links degrade as the node struggles
        neighbors = self._topology.get_neighbors(root_node)
        affected_links = [self._topology.get_link_id(root_node, nb) for nb in neighbors]
        for lid in affected_links:
            mask_link = self._row_mask(out, lid, start_time, end_time, "link")
            n_l = mask_link.sum()
            if n_l > 0:
                ramp_l = np.linspace(0.0, 1.0, n_l)
                out.loc[mask_link, "latency_ms"] = (
                    out.loc[mask_link, "latency_ms"] * (1 + ramp_l * 0.6)
                )
                out.loc[mask_link, "packet_loss_pct"] = self._clamp(
                    out.loc[mask_link, "packet_loss_pct"] + ramp_l * 0.8, 0, 100
                )

        label = ScenarioLabel(
            scenario_id=str(uuid.uuid4()),
            scenario_type="hardware_degradation",
            start_time=start_time,
            end_time=end_time,
            root_cause=f"Gradual hardware failure on node {root_node} (CPU/thermal runaway)",
            root_cause_node=root_node,
            root_cause_link=None,
            affected_nodes=[root_node],
            affected_links=affected_links,
            severity="medium",
            description=(
                f"Node {root_node} hardware degradation ({duration_minutes} min) "
                "with ramp-up in CPU, temperature, and link latency"
            ),
        )
        self._labels.append(label)
        return out, label

    def inject_ddos_surge(
        self,
        df: pd.DataFrame,
        start_time: datetime,
        duration_minutes: int = 30,
        target_node: str = "EDGE3",
    ) -> tuple[pd.DataFrame, ScenarioLabel]:
        """
        DDoS traffic surge hits an edge node: sudden, near-instantaneous
        utilization spike + high packet loss and CPU saturation.
        """
        end_time = start_time + timedelta(minutes=duration_minutes)
        out = df.copy()

        # Incoming link fully saturated
        neighbors = self._topology.get_neighbors(target_node)
        affected_links = [self._topology.get_link_id(target_node, nb) for nb in neighbors]
        for lid in affected_links:
            mask = self._row_mask(out, lid, start_time, end_time, "link")
            n = mask.sum()
            if n > 0:
                out.loc[mask, "utilization_pct"] = self._clamp(
                    self._rng.uniform(92, 100, size=n), 0, 100
                )
                out.loc[mask, "packet_loss_pct"] = self._clamp(
                    self._rng.uniform(5, 18, size=n), 0, 100
                )
                out.loc[mask, "latency_ms"] = (
                    out.loc[mask, "latency_ms"] * self._rng.uniform(3, 6, size=n)
                )
                cap = out.loc[mask, "capacity_gbps"].values
                out.loc[mask, "throughput_gbps"] = self._clamp(
                    out.loc[mask, "utilization_pct"] / 100.0 * cap, 0, cap.max()
                )

        # Target node CPU maxed
        mask_node = self._row_mask(out, target_node, start_time, end_time, "node")
        n_node = mask_node.sum()
        if n_node > 0:
            out.loc[mask_node, "cpu_pct"] = self._clamp(
                self._rng.uniform(88, 100, size=n_node), 0, 100
            )
            out.loc[mask_node, "buffer_drops"] = (
                out.loc[mask_node, "buffer_drops"]
                + self._rng.integers(200, 800, size=n_node)
            )

        label = ScenarioLabel(
            scenario_id=str(uuid.uuid4()),
            scenario_type="ddos_surge",
            start_time=start_time,
            end_time=end_time,
            root_cause=f"Volumetric DDoS attack targeting edge node {target_node}",
            root_cause_node=target_node,
            root_cause_link=None,
            affected_nodes=[target_node],
            affected_links=affected_links,
            severity="critical",
            description=(
                f"DDoS surge at {target_node} ({duration_minutes} min): "
                "link saturation, high packet loss, CPU spike"
            ),
        )
        self._labels.append(label)
        return out, label

    def inject_misconfiguration(
        self,
        df: pd.DataFrame,
        start_time: datetime,
        duration_minutes: int = 60,
        target_link: str = "AGG2-EDGE2",
    ) -> tuple[pd.DataFrame, ScenarioLabel]:
        """
        BGP/routing misconfiguration causes a link to carry excess traffic
        (sub-optimal routing black-holes traffic intermittently).
        Latency becomes erratic and packet loss rises with spikes.
        """
        end_time = start_time + timedelta(minutes=duration_minutes)
        out = df.copy()

        mask = self._row_mask(out, target_link, start_time, end_time, "link")
        n = mask.sum()
        if n > 0:
            # Erratic latency — base * random jitter multiplier
            jitter = self._rng.choice(
                [1.0, 1.5, 3.0, 5.0, 1.2], size=n, p=[0.4, 0.3, 0.15, 0.05, 0.1]
            )
            out.loc[mask, "latency_ms"] = (
                out.loc[mask, "latency_ms"] * jitter
            )
            # Intermittent packet loss spikes
            loss_base = self._rng.uniform(0.5, 2.0, size=n)
            loss_spikes = self._rng.choice([0.0, 8.0, 15.0], size=n, p=[0.75, 0.2, 0.05])
            out.loc[mask, "packet_loss_pct"] = self._clamp(
                out.loc[mask, "packet_loss_pct"] + loss_base + loss_spikes, 0, 100
            )
            # Utilization slightly elevated due to re-transmitted packets
            out.loc[mask, "utilization_pct"] = self._clamp(
                out.loc[mask, "utilization_pct"] + self._rng.uniform(5, 15, size=n),
                0, 100,
            )

        # Parse node names from link_id
        parts = target_link.split("-")
        node_a, node_b = parts[0], parts[1]

        label = ScenarioLabel(
            scenario_id=str(uuid.uuid4()),
            scenario_type="misconfiguration",
            start_time=start_time,
            end_time=end_time,
            root_cause=f"BGP routing misconfiguration on link {target_link}",
            root_cause_node=None,
            root_cause_link=target_link,
            affected_nodes=[node_a, node_b],
            affected_links=[target_link],
            severity="medium",
            description=(
                f"Routing misconfiguration on {target_link} ({duration_minutes} min): "
                "erratic latency, intermittent packet loss spikes"
            ),
        )
        self._labels.append(label)
        return out, label

    def inject_fiber_cut(
        self,
        df: pd.DataFrame,
        start_time: datetime,
        duration_minutes: int = 90,
        cut_link: str = "AGG3-EDGE3",
    ) -> tuple[pd.DataFrame, ScenarioLabel]:
        """
        Physical fiber cut: link goes completely dark (utilization=0,
        throughput=0, packet_loss=100).  Adjacent links carry rerouted
        traffic and become congested.
        """
        end_time = start_time + timedelta(minutes=duration_minutes)
        out = df.copy()

        # Kill the cut link
        mask_cut = self._row_mask(out, cut_link, start_time, end_time, "link")
        out.loc[mask_cut, "utilization_pct"] = 0.0
        out.loc[mask_cut, "throughput_gbps"] = 0.0
        out.loc[mask_cut, "packet_loss_pct"] = 100.0
        out.loc[mask_cut, "latency_ms"] = 0.0

        # Rerouted traffic elevates sibling links
        parts = cut_link.split("-")
        node_a, node_b = parts[0], parts[1]
        sibling_links: list[str] = []
        for nb in self._topology.get_neighbors(node_a):
            if nb != node_b:
                sibling_links.append(self._topology.get_link_id(node_a, nb))
        for nb in self._topology.get_neighbors(node_b):
            if nb != node_a:
                sibling_links.append(self._topology.get_link_id(node_b, nb))

        for lid in sibling_links:
            mask = self._row_mask(out, lid, start_time, end_time, "link")
            n = mask.sum()
            if n > 0:
                out.loc[mask, "utilization_pct"] = self._clamp(
                    out.loc[mask, "utilization_pct"]
                    + self._rng.uniform(20, 35, size=n),
                    0, 100,
                )
                out.loc[mask, "latency_ms"] = (
                    out.loc[mask, "latency_ms"] * self._rng.uniform(1.5, 2.2, size=n)
                )

        label = ScenarioLabel(
            scenario_id=str(uuid.uuid4()),
            scenario_type="fiber_cut",
            start_time=start_time,
            end_time=end_time,
            root_cause=f"Physical fiber cut on link {cut_link}",
            root_cause_node=None,
            root_cause_link=cut_link,
            affected_nodes=[node_a, node_b],
            affected_links=[cut_link] + sibling_links,
            severity="critical",
            description=(
                f"Fiber cut on {cut_link} ({duration_minutes} min): "
                "link down, traffic rerouted to sibling links"
            ),
        )
        self._labels.append(label)
        return out, label

    # ------------------------------------------------------------------
    # High-level API
    # ------------------------------------------------------------------

    def inject_scenario(
        self,
        df: pd.DataFrame,
        scenario_type: ScenarioType,
        start_time: datetime,
        **kwargs: Any,
    ) -> tuple[pd.DataFrame, ScenarioLabel]:
        """Dispatch to the named scenario method."""
        dispatch = {
            "congestion_cascade": self.inject_congestion_cascade,
            "hardware_degradation": self.inject_hardware_degradation,
            "ddos_surge": self.inject_ddos_surge,
            "misconfiguration": self.inject_misconfiguration,
            "fiber_cut": self.inject_fiber_cut,
        }
        return dispatch[scenario_type](df, start_time, **kwargs)

    def inject_random_scenarios(
        self,
        df: pd.DataFrame,
        n_scenarios: int = 5,
        min_gap_minutes: int = 60,
    ) -> tuple[pd.DataFrame, list[ScenarioLabel]]:
        """
        Inject `n_scenarios` randomly chosen scenarios at random times
        spaced at least `min_gap_minutes` apart within the DataFrame's
        time range.
        """
        timestamps = pd.to_datetime(df["timestamp"], utc=True).unique()
        timestamps = sorted(timestamps)
        total_minutes = len(timestamps)

        scenario_types: list[ScenarioType] = [
            "congestion_cascade",
            "hardware_degradation",
            "ddos_surge",
            "misconfiguration",
            "fiber_cut",
        ]

        labels: list[ScenarioLabel] = []
        used_slots: list[int] = []
        out = df.copy()

        attempts = 0
        while len(labels) < n_scenarios and attempts < n_scenarios * 20:
            attempts += 1
            slot = int(self._rng.integers(0, max(1, total_minutes - 120)))
            if any(abs(slot - u) < min_gap_minutes for u in used_slots):
                continue
            used_slots.append(slot)
            chosen = scenario_types[len(labels) % len(scenario_types)]
            start = pd.Timestamp(timestamps[slot]).to_pydatetime()
            out, label = self.inject_scenario(out, chosen, start)
            labels.append(label)

        return out, labels

    def get_labels(self) -> list[ScenarioLabel]:
        """Return all injected scenario labels accumulated so far."""
        return list(self._labels)

    def get_labels_df(self) -> pd.DataFrame:
        """Return labels as a flat DataFrame for analysis."""
        rows = []
        for lbl in self._labels:
            rows.append({
                "scenario_id": lbl.scenario_id,
                "scenario_type": lbl.scenario_type,
                "start_time": lbl.start_time.isoformat(),
                "end_time": lbl.end_time.isoformat(),
                "duration_min": int(
                    (lbl.end_time - lbl.start_time).total_seconds() / 60
                ),
                "severity": lbl.severity,
                "root_cause_node": lbl.root_cause_node or "",
                "root_cause_link": lbl.root_cause_link or "",
                "n_affected_nodes": len(lbl.affected_nodes),
                "n_affected_links": len(lbl.affected_links),
                "description": lbl.description,
            })
        return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    topo = NetworkTopology()
    gen = TelemetryGenerator(topo, seed=42)

    print("Generating 24-hour baseline telemetry…")
    baseline = gen.generate_baseline(duration_hours=24)
    print(f"Baseline rows: {len(baseline):,}")

    injector = AnomalyInjector(topo, seed=7)

    # Build a time index: base = midnight UTC today
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # Inject one of each scenario at spread-out times
    scenarios: list[tuple[ScenarioType, datetime, dict[str, Any]]] = [
        ("congestion_cascade",   today + timedelta(hours=2),  {}),
        ("hardware_degradation", today + timedelta(hours=5),  {"root_node": "AGG1"}),
        ("ddos_surge",           today + timedelta(hours=10), {"target_node": "EDGE3"}),
        ("misconfiguration",     today + timedelta(hours=14), {"target_link": "AGG2-EDGE2"}),
        ("fiber_cut",            today + timedelta(hours=18), {"cut_link": "AGG3-EDGE3"}),
    ]

    df = baseline.copy()
    for stype, stime, kwargs in scenarios:
        df, lbl = injector.inject_scenario(df, stype, stime, **kwargs)
        print(f"  Injected [{lbl.severity:8s}] {lbl.scenario_type} @ {stime.strftime('%H:%M')} UTC")

    # Summary table
    print("\n=== Injected Scenario Summary ===")
    labels_df = injector.get_labels_df()
    print(
        labels_df[
            ["scenario_type", "start_time", "duration_min", "severity",
             "root_cause_node", "root_cause_link", "n_affected_links"]
        ].to_string(index=False)
    )

    # Before / after comparison for the fiber-cut scenario
    fiber_label = injector.get_labels()[-1]
    link_id = fiber_label.root_cause_link
    assert link_id is not None

    # "Before" window: 30 min before start
    before_start = fiber_label.start_time - timedelta(minutes=30)
    before_end = fiber_label.start_time - timedelta(minutes=1)

    ts_col = pd.to_datetime(df["timestamp"], utc=True)
    before_mask = (
        (df["entity_id"] == link_id)
        & (df["entity_type"] == "link")
        & (ts_col >= before_start)
        & (ts_col <= before_end)
    )
    during_mask = (
        (df["entity_id"] == link_id)
        & (df["entity_type"] == "link")
        & (ts_col >= fiber_label.start_time)
        & (ts_col <= fiber_label.end_time)
    )

    cols = ["utilization_pct", "throughput_gbps", "latency_ms", "packet_loss_pct"]
    before_stats = df.loc[before_mask, cols].mean().round(4)
    during_stats = df.loc[during_mask, cols].mean().round(4)

    print(f"\n=== Before/After: Fiber Cut on {link_id} ===")
    comparison = pd.DataFrame({"before": before_stats, "during": during_stats})
    print(comparison.to_string())
