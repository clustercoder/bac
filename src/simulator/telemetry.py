from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from src.simulator.topology import NetworkTopology


def _diurnal_factor(hour: float) -> float:
    """Smooth sine curve: low ~0.3 at 4am, peak ~1.0 at 8pm."""
    raw = 0.3 + 0.7 * (0.5 * (1 + math.sin((hour - 16) * math.pi / 12)))
    return float(np.clip(raw, 0.3, 1.0))


class TelemetryGenerator:
    """Produces realistic per-minute ISP telemetry for all nodes and links."""

    def __init__(
        self,
        topology: NetworkTopology,
        seed: int = 42,
        start_time: datetime | None = None,
    ) -> None:
        self._topology = topology
        self._seed = seed
        self._rng = np.random.default_rng(seed)

        if start_time is None:
            today = datetime.now(timezone.utc).date()
            start_time = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
        self._current_time: datetime = start_time

        # Running state — populated by _init_state()
        self._link_state: dict[str, dict[str, float]] = {}
        self._node_state: dict[str, dict[str, float]] = {}
        self._init_state()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _init_state(self) -> None:
        hour = self._current_time.hour + self._current_time.minute / 60.0
        factor = _diurnal_factor(hour)

        for link in self._topology.get_all_links():
            cap = link["capacity_gbps"]
            lat = link["latency_baseline_ms"]
            util = float(np.clip(cap * factor * self._rng.uniform(0.4, 0.7), 0, cap))
            util_pct = (util / cap) * 100.0
            self._link_state[link["link_id"]] = {
                "current_utilization": util_pct,
                "current_throughput": util,
                "current_latency": lat,
                "current_loss": 0.0,
            }

        for node in self._topology.get_all_nodes():
            nid = node["node_id"]
            self._node_state[nid] = {
                "current_cpu": float(np.clip(
                    node["cpu_baseline"] * factor + self._rng.normal(0, 3), 0, 100
                )),
                "current_memory": float(np.clip(
                    node["memory_baseline"] + self._rng.normal(0, 2), 0, 100
                )),
                "current_temp": float(np.clip(
                    node["temp_baseline"] + self._rng.normal(0, 1), 20, 90
                )),
                "current_buffer_drops": 0,
                # slow random walk accumulator for temperature
                "_temp_walk": 0.0,
            }

    # ------------------------------------------------------------------
    # Per-step generators
    # ------------------------------------------------------------------

    def _generate_link_metrics(
        self, link: dict[str, Any], factor: float
    ) -> dict[str, float]:
        cap = link["capacity_gbps"]
        lat_base = link["latency_baseline_ms"]
        prev = self._link_state[link["link_id"]]

        # Utilization: blend previous state with new target for smoothness
        target_util = cap * factor * self._rng.uniform(0.4, 0.7)
        smoothed_throughput = 0.7 * prev["current_throughput"] + 0.3 * target_util
        smoothed_throughput = float(np.clip(smoothed_throughput, 0.0, cap))
        util_pct = (smoothed_throughput / cap) * 100.0

        # Latency: baseline + quadratic congestion term + noise
        latency = (
            lat_base
            + (util_pct / 100.0) ** 2 * lat_base * 0.5
            + float(self._rng.normal(0, lat_base * 0.05))
        )
        latency = float(np.clip(latency, 0.1, 200.0))

        # Packet loss: negligible until >80% utilisation, then rises sharply
        if util_pct > 80.0:
            loss = max(0.0, 0.01 + (util_pct - 80.0) * 0.02 + float(self._rng.normal(0, 0.005)))
        else:
            loss = max(0.0, float(self._rng.normal(0.01, 0.005)))
        loss = float(np.clip(loss, 0.0, 100.0))

        return {
            "utilization_pct": round(util_pct, 4),
            "throughput_gbps": round(smoothed_throughput, 4),
            "latency_ms": round(latency, 4),
            "packet_loss_pct": round(loss, 6),
            "capacity_gbps": cap,
            "latency_baseline_ms": lat_base,
        }

    def _generate_node_metrics(
        self, node: dict[str, Any], factor: float, neighbor_util_mean: float
    ) -> dict[str, float]:
        nid = node["node_id"]
        prev = self._node_state[nid]

        # CPU: baseline scaled by diurnal factor + noise
        cpu = float(np.clip(
            node["cpu_baseline"] * factor + float(self._rng.normal(0, 3)), 0.0, 100.0
        ))

        # Memory: loosely tracks CPU
        memory = float(np.clip(
            node["memory_baseline"] + (cpu - node["cpu_baseline"]) * 0.3
            + float(self._rng.normal(0, 2)),
            0.0, 100.0,
        ))

        # Temperature: slow random walk on top of CPU-correlated baseline
        walk_delta = float(self._rng.normal(0, 0.1))
        new_walk = prev["_temp_walk"] + walk_delta
        # Dampen walk toward 0 to prevent unbounded drift
        new_walk = new_walk * 0.98
        temp = float(np.clip(
            node["temp_baseline"] + (cpu - node["cpu_baseline"]) * 0.15 + new_walk,
            20.0, 90.0,
        ))

        # Buffer drops: Poisson(1) normally; higher when links are congested
        congestion_boost = max(0.0, (neighbor_util_mean - 70.0) * 0.5)
        buffer_drops = max(0, int(self._rng.poisson(max(0.1, 1.0 + congestion_boost))))

        # Persist walk state
        self._node_state[nid]["_temp_walk"] = new_walk

        return {
            "cpu_pct": round(cpu, 4),
            "memory_pct": round(memory, 4),
            "temperature_c": round(temp, 4),
            "buffer_drops": buffer_drops,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def step(self) -> dict[str, Any]:
        """Advance simulation by 1 minute and return all readings."""
        self._current_time += timedelta(minutes=1)
        hour = self._current_time.hour + self._current_time.minute / 60.0
        factor = _diurnal_factor(hour)

        # Generate link metrics first so node congestion can reference them
        link_readings: dict[str, dict[str, float]] = {}
        for link in self._topology.get_all_links():
            lid = link["link_id"]
            metrics = self._generate_link_metrics(link, factor)
            link_readings[lid] = metrics
            # Update running state
            self._link_state[lid]["current_utilization"] = metrics["utilization_pct"]
            self._link_state[lid]["current_throughput"] = metrics["throughput_gbps"]
            self._link_state[lid]["current_latency"] = metrics["latency_ms"]
            self._link_state[lid]["current_loss"] = metrics["packet_loss_pct"]

        # Compute mean utilization on links adjacent to each node
        node_readings: dict[str, dict[str, float]] = {}
        for node in self._topology.get_all_nodes():
            nid = node["node_id"]
            neighbor_utils = []
            for nb in self._topology.get_neighbors(nid):
                lid = self._topology.get_link_id(nid, nb)
                if lid in link_readings:
                    neighbor_utils.append(link_readings[lid]["utilization_pct"])
            mean_util = float(np.mean(neighbor_utils)) if neighbor_utils else 50.0
            metrics = self._generate_node_metrics(node, factor, mean_util)
            node_readings[nid] = metrics
            self._node_state[nid].update({
                "current_cpu": metrics["cpu_pct"],
                "current_memory": metrics["memory_pct"],
                "current_temp": metrics["temperature_c"],
                "current_buffer_drops": metrics["buffer_drops"],
            })

        return {
            "timestamp": self._current_time.isoformat(),
            "nodes": node_readings,
            "links": link_readings,
        }

    def generate_baseline(self, duration_hours: int = 24) -> pd.DataFrame:
        """Generate `duration_hours` of 1-minute telemetry. Returns a flat DataFrame."""
        self.reset()
        rows: list[dict[str, Any]] = []
        steps = duration_hours * 60

        for _ in range(steps):
            snapshot = self.step()
            ts = snapshot["timestamp"]

            for nid, metrics in snapshot["nodes"].items():
                rows.append({"timestamp": ts, "entity_id": nid, "entity_type": "node", **metrics})

            for lid, metrics in snapshot["links"].items():
                rows.append({"timestamp": ts, "entity_id": lid, "entity_type": "link", **metrics})

        return pd.DataFrame(rows)

    def get_current_state(self) -> dict[str, Any]:
        """Return latest readings without advancing time."""
        links = {
            link["link_id"]: {
                "utilization_pct": self._link_state[link["link_id"]]["current_utilization"],
                "throughput_gbps": self._link_state[link["link_id"]]["current_throughput"],
                "latency_ms": self._link_state[link["link_id"]]["current_latency"],
                "packet_loss_pct": self._link_state[link["link_id"]]["current_loss"],
                "capacity_gbps": link["capacity_gbps"],
            }
            for link in self._topology.get_all_links()
        }
        nodes = {
            nid: {
                "cpu_pct": s["current_cpu"],
                "memory_pct": s["current_memory"],
                "temperature_c": s["current_temp"],
                "buffer_drops": s["current_buffer_drops"],
            }
            for nid, s in self._node_state.items()
        }
        return {"timestamp": self._current_time.isoformat(), "nodes": nodes, "links": links}

    def reset(self, seed: int | None = None) -> None:
        """Reset to initial conditions, optionally with a new seed."""
        if seed is not None:
            self._seed = seed
        self._rng = np.random.default_rng(self._seed)
        today = datetime.now(timezone.utc).date()
        self._current_time = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
        self._link_state.clear()
        self._node_state.clear()
        self._init_state()

    def get_time(self) -> datetime:
        return self._current_time


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from src.simulator.topology import NetworkTopology

    topo = NetworkTopology()
    gen = TelemetryGenerator(topo, seed=42)

    print("Generating 2 hours of telemetry...")
    df = gen.generate_baseline(duration_hours=2)
    print(f"Rows generated: {len(df):,}  (timesteps × entities)\n")

    # Sample: one link
    link_df = df[(df["entity_type"] == "link") & (df["entity_id"] == "CR1-CR2")]
    print("=== Link CR1-CR2 (first 5 rows) ===")
    print(link_df[["timestamp", "latency_ms", "utilization_pct", "packet_loss_pct", "throughput_gbps"]].head().to_string(index=False))

    print("\n=== Link CR1-CR2 stats (2h) ===")
    numeric_link = link_df[["latency_ms", "utilization_pct", "packet_loss_pct", "throughput_gbps"]]
    print(numeric_link.agg(["min", "max", "mean"]).round(4).to_string())

    # Sample: one node
    node_df = df[(df["entity_type"] == "node") & (df["entity_id"] == "EDGE3")]
    print("\n=== Node EDGE3 (first 5 rows) ===")
    print(node_df[["timestamp", "cpu_pct", "memory_pct", "temperature_c", "buffer_drops"]].head().to_string(index=False))

    print("\n=== Node EDGE3 stats (2h) ===")
    numeric_node = node_df[["cpu_pct", "memory_pct", "temperature_c", "buffer_drops"]]
    print(numeric_node.agg(["min", "max", "mean"]).round(4).to_string())
