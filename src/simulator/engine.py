from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import numpy as np

from src.models.schemas import LinkState, NetworkState, NodeState
from src.simulator.anomaly_injector import AnomalyInjector, ScenarioLabel, ScenarioType
from src.simulator.telemetry import TelemetryGenerator
from src.simulator.topology import NetworkTopology

# ---------------------------------------------------------------------------
# Internal data structures
# ---------------------------------------------------------------------------

@dataclass
class ActiveAnomaly:
    label: ScenarioLabel
    rng: np.random.Generator


@dataclass
class ScheduledAnomaly:
    fire_at: datetime          # simulation time
    scenario_type: ScenarioType
    target: str                # node_id or link_id depending on scenario
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class AppliedAction:
    rollback_token: str
    action_type: str
    pre_state: dict[str, Any]
    parameters: dict[str, Any]
    applied_at: datetime


# ---------------------------------------------------------------------------
# Status classifiers
# ---------------------------------------------------------------------------

def _node_status(
    cpu: float, temp: float, memory: float
) -> Literal["healthy", "degraded", "critical", "down"]:
    if cpu >= 95 or temp >= 82:
        return "critical"
    if cpu >= 75 or temp >= 70 or memory >= 90:
        return "degraded"
    return "healthy"


def _link_status(
    util: float, loss: float, latency: float, lat_base: float
) -> Literal["healthy", "degraded", "congested", "down"]:
    if util == 0.0 and loss >= 99.0:
        return "down"
    if util >= 90 or loss >= 5.0:
        return "congested"
    if util >= 70 or loss >= 1.0 or latency > lat_base * 2.5:
        return "degraded"
    return "healthy"


# ---------------------------------------------------------------------------
# SimulationEngine
# ---------------------------------------------------------------------------

class SimulationEngine:
    """
    Real-time (or accelerated) simulation engine.

    ``speed_multiplier=60`` means 1 real second = 1 simulated minute.
    ``speed_multiplier=120`` means 1 real second = 2 simulated minutes.
    """

    def __init__(
        self,
        topology: NetworkTopology,
        speed_multiplier: float = 60.0,
        seed: int = 42,
    ) -> None:
        self._topology = topology
        self._speed = speed_multiplier
        self._seed = seed

        self._telemetry = TelemetryGenerator(topology, seed=seed)
        self._injector = AnomalyInjector(topology, seed=seed + 1)

        # Simulation state
        self._current_state: dict[str, Any] = {}
        self._tick_count: int = 0

        # Control flags
        self._running: bool = False
        self._paused: bool = False
        self._task: asyncio.Task[None] | None = None

        # Subscribers: async callbacks(timestamp: str, state: dict)
        self._subscribers: list[Callable[..., Any]] = []

        # Anomaly tracking
        self._active_anomalies: list[ActiveAnomaly] = []
        self._anomaly_history: list[ScenarioLabel] = []
        self._scheduled_anomalies: list[ScheduledAnomaly] = []

        # Action tracking
        self._applied_actions: list[AppliedAction] = []
        self._rollback_store: dict[str, AppliedAction] = {}

        # Per-link overrides set by actions: link_id → {rate_limit_pct, capacity_boost}
        self._link_overrides: dict[str, dict[str, float]] = {}

        self._rng = np.random.default_rng(seed + 2)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the simulation loop as a background asyncio task."""
        if self._running:
            return
        self._running = True
        self._paused = False
        self._task = asyncio.create_task(self._loop(), name="simulation-engine")

    async def stop(self) -> None:
        """Stop the engine gracefully and await task completion."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    # ------------------------------------------------------------------
    # Core loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        sleep_seconds = 60.0 / self._speed

        while self._running:
            if self._paused:
                await asyncio.sleep(0.05)
                continue

            # 1. Advance telemetry by one minute
            snapshot = self._telemetry.step()
            self._tick_count += 1

            # 2. Fire any scheduled anomalies whose sim-time has arrived
            self._fire_scheduled(self._telemetry.get_time())

            # 3. Apply active anomaly effects to the snapshot
            snapshot = self._apply_anomaly_effects(snapshot)

            # 4. Apply active action effects (rate limits, capacity overrides)
            snapshot = self._apply_action_effects(snapshot)

            # 5. Expire finished anomalies
            sim_now = self._telemetry.get_time()
            self._active_anomalies = [
                a for a in self._active_anomalies if a.label.end_time > sim_now
            ]

            # 6. Update current state
            self._current_state = snapshot

            # 7. Notify subscribers
            await self._notify(snapshot["timestamp"], snapshot)

            await asyncio.sleep(sleep_seconds)

    # ------------------------------------------------------------------
    # Anomaly effects (per-step, real-time)
    # ------------------------------------------------------------------

    def _fire_scheduled(self, sim_now: datetime) -> None:
        remaining: list[ScheduledAnomaly] = []
        for s in self._scheduled_anomalies:
            if sim_now >= s.fire_at:
                self.inject_anomaly_now(s.scenario_type, s.target, **s.kwargs)
            else:
                remaining.append(s)
        self._scheduled_anomalies = remaining

    def _apply_anomaly_effects(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Return a new snapshot with all active anomaly overlays applied."""
        if not self._active_anomalies:
            return snapshot

        nodes = dict(snapshot["nodes"])
        links = dict(snapshot["links"])

        for aa in self._active_anomalies:
            lbl = aa.label
            rng = aa.rng
            stype = lbl.scenario_type

            if stype == "congestion_cascade":
                root = lbl.root_cause_link
                if root and root in links:
                    links = {**links, root: _spike_link(links[root], rng, util_boost=45, loss_boost=2.5)}
                for lid in lbl.affected_links:
                    if lid != root and lid in links:
                        links = {**links, lid: _boost_link(links[lid], rng, util_boost=15)}

            elif stype == "hardware_degradation":
                nid = lbl.root_cause_node
                if nid and nid in nodes:
                    nodes = {**nodes, nid: _degrade_node(nodes[nid], rng)}
                for lid in lbl.affected_links:
                    if lid in links:
                        links = {**links, lid: _latency_boost(links[lid], rng, factor=1.4)}

            elif stype == "ddos_surge":
                nid = lbl.root_cause_node
                if nid and nid in nodes:
                    nodes = {**nodes, nid: _saturate_node(nodes[nid], rng)}
                for lid in lbl.affected_links:
                    if lid in links:
                        links = {**links, lid: _spike_link(links[lid], rng, util_boost=50, loss_boost=8.0)}

            elif stype == "misconfiguration":
                lid = lbl.root_cause_link
                if lid and lid in links:
                    links = {**links, lid: _erratic_link(links[lid], rng)}

            elif stype == "fiber_cut":
                lid = lbl.root_cause_link
                if lid and lid in links:
                    links = {**links, lid: _kill_link(links[lid])}
                for slid in lbl.affected_links:
                    if slid != lid and slid in links:
                        links = {**links, slid: _boost_link(links[slid], rng, util_boost=25)}

        return {**snapshot, "nodes": nodes, "links": links}

    def _apply_action_effects(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Apply persistent action overrides (rate limits, capacity boosts)."""
        if not self._link_overrides:
            return snapshot

        links = dict(snapshot["links"])
        for lid, overrides in self._link_overrides.items():
            if lid not in links:
                continue
            link = dict(links[lid])
            cap = link.get("capacity_gbps", 1.0)

            if "rate_limit_pct" in overrides:
                # Clamp throughput to rate_limit_pct of capacity
                limit_gbps = cap * overrides["rate_limit_pct"] / 100.0
                if link["throughput_gbps"] > limit_gbps:
                    link = {**link,
                            "throughput_gbps": round(limit_gbps, 4),
                            "utilization_pct": round(overrides["rate_limit_pct"], 4)}

            if "capacity_gbps" in overrides:
                new_cap = overrides["capacity_gbps"]
                link = {**link,
                        "capacity_gbps": new_cap,
                        "utilization_pct": round(
                            min(link["throughput_gbps"] / new_cap * 100.0, 100.0), 4
                        )}
            links[lid] = link
        return {**snapshot, "links": links}

    # ------------------------------------------------------------------
    # Subscriber pattern
    # ------------------------------------------------------------------

    def subscribe(self, callback: Callable[..., Any]) -> None:
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[..., Any]) -> None:
        self._subscribers = [s for s in self._subscribers if s is not callback]

    async def _notify(self, timestamp: str, state: dict[str, Any]) -> None:
        for cb in list(self._subscribers):
            try:
                result = cb(timestamp, state)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass  # never let a bad subscriber crash the loop

    # ------------------------------------------------------------------
    # State inspection
    # ------------------------------------------------------------------

    def get_current_state(self) -> NetworkState:
        """Build a validated NetworkState from the latest raw snapshot."""
        snap = self._current_state
        if not snap:
            snap = self._telemetry.get_current_state()

        ts = datetime.fromisoformat(snap["timestamp"])

        node_states: dict[str, NodeState] = {}
        for nid, m in snap["nodes"].items():
            node_meta = self._topology.get_node(nid)
            node_states[nid] = NodeState(
                node_id=nid,
                node_type=node_meta["node_type"],
                region=node_meta["region"],
                cpu_pct=m["cpu_pct"],
                memory_pct=m["memory_pct"],
                temperature_c=m["temperature_c"],
                buffer_drops=m["buffer_drops"],
                status=_node_status(m["cpu_pct"], m["temperature_c"], m["memory_pct"]),
            )

        link_states: dict[str, LinkState] = {}
        for lid, m in snap["links"].items():
            parts = lid.split("-")
            src, tgt = parts[0], parts[1]
            lat_base = self._topology.get_link(src, tgt)["latency_baseline_ms"]
            link_states[lid] = LinkState(
                link_id=lid,
                source=src,
                target=tgt,
                latency_ms=m["latency_ms"],
                packet_loss_pct=m["packet_loss_pct"],
                utilization_pct=m["utilization_pct"],
                throughput_gbps=m["throughput_gbps"],
                capacity_gbps=m["capacity_gbps"],
                status=_link_status(
                    m["utilization_pct"], m["packet_loss_pct"],
                    m["latency_ms"], lat_base,
                ),
            )

        return NetworkState(timestamp=ts, nodes=node_states, links=link_states)

    def get_current_state_dict(self) -> dict[str, Any]:
        return self._current_state or self._telemetry.get_current_state()

    def get_simulation_time(self) -> datetime:
        return self._telemetry.get_time()

    def get_speed(self) -> float:
        return self._speed

    def set_speed(self, multiplier: float) -> None:
        self._speed = max(0.1, multiplier)

    def is_running(self) -> bool:
        return self._running and not self._paused

    def get_tick_count(self) -> int:
        return self._tick_count

    # ------------------------------------------------------------------
    # Anomaly API
    # ------------------------------------------------------------------

    def schedule_anomaly(
        self,
        delay_seconds: float,
        scenario_type: ScenarioType,
        target: str,
        **kwargs: Any,
    ) -> None:
        """Schedule an anomaly to fire after ``delay_seconds`` of real time."""
        real_minutes = delay_seconds * self._speed / 60.0
        fire_at = self._telemetry.get_time() + timedelta(minutes=real_minutes)
        self._scheduled_anomalies.append(
            ScheduledAnomaly(
                fire_at=fire_at,
                scenario_type=scenario_type,
                target=target,
                kwargs=kwargs,
            )
        )

    def inject_anomaly_now(
        self, scenario_type: ScenarioType, target: str, duration_minutes: int = 45, **kwargs: Any
    ) -> ScenarioLabel:
        """Inject a scenario immediately into the live simulation."""
        sim_now = self._telemetry.get_time()
        end_time = sim_now + timedelta(minutes=duration_minutes)

        # Build a ScenarioLabel without going through the batch DataFrame path
        affected_links, affected_nodes, root_node, root_link = \
            self._resolve_targets(scenario_type, target)

        severity_map: dict[ScenarioType, str] = {
            "congestion_cascade": "high",
            "hardware_degradation": "medium",
            "ddos_surge": "critical",
            "misconfiguration": "medium",
            "fiber_cut": "critical",
        }

        label = ScenarioLabel(
            scenario_id=str(uuid.uuid4()),
            scenario_type=scenario_type,
            start_time=sim_now,
            end_time=end_time,
            root_cause=f"{scenario_type} on {target}",
            root_cause_node=root_node,
            root_cause_link=root_link,
            affected_nodes=affected_nodes,
            affected_links=affected_links,
            severity=severity_map[scenario_type],  # type: ignore[arg-type]
            description=f"{scenario_type} @ {target} for {duration_minutes} min",
        )

        aa = ActiveAnomaly(label=label, rng=np.random.default_rng(self._rng.integers(1 << 31)))
        self._active_anomalies.append(aa)
        self._anomaly_history.append(label)
        self._injector._labels.append(label)
        return label

    def _resolve_targets(
        self, scenario_type: ScenarioType, target: str
    ) -> tuple[list[str], list[str], str | None, str | None]:
        """Return (affected_links, affected_nodes, root_node, root_link)."""
        topo = self._topology

        if scenario_type == "congestion_cascade":
            root_link = topo.get_link_id(*target.split("-")[:2]) if "-" in target else target
            secondary = [
                topo.get_link_id("CR1", "AGG1"),
                topo.get_link_id("CR1", "AGG2"),
                topo.get_link_id("CR2", "AGG3"),
                topo.get_link_id("CR2", "AGG4"),
            ]
            return [root_link] + secondary, ["CR1", "CR2"], None, root_link

        if scenario_type == "hardware_degradation":
            neighbors = topo.get_neighbors(target)
            links = [topo.get_link_id(target, nb) for nb in neighbors]
            return links, [target], target, None

        if scenario_type == "ddos_surge":
            neighbors = topo.get_neighbors(target)
            links = [topo.get_link_id(target, nb) for nb in neighbors]
            return links, [target], target, None

        if scenario_type == "misconfiguration":
            parts = target.split("-")
            return [target], [parts[0], parts[1]], None, target

        if scenario_type == "fiber_cut":
            parts = target.split("-")
            node_a, node_b = parts[0], parts[1]
            sibling_links: list[str] = []
            for nb in topo.get_neighbors(node_a):
                if nb != node_b:
                    sibling_links.append(topo.get_link_id(node_a, nb))
            for nb in topo.get_neighbors(node_b):
                if nb != node_a:
                    sibling_links.append(topo.get_link_id(node_b, nb))
            return [target] + sibling_links, [node_a, node_b], None, target

        return [], [], None, None

    def get_active_anomalies(self) -> list[ScenarioLabel]:
        return [a.label for a in self._active_anomalies]

    def get_anomaly_history(self) -> list[ScenarioLabel]:
        return list(self._anomaly_history)

    # ------------------------------------------------------------------
    # Action API
    # ------------------------------------------------------------------

    def apply_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """
        Apply a network action.  Supported action_type values:
        ``reroute``, ``rate_limit``, ``scale_capacity``, ``rollback``.

        Returns ``{"success": bool, "pre_state": dict, "rollback_token": str}``.
        """
        action_type: str = action.get("action_type", "")

        if action_type == "rollback":
            token = action.get("rollback_token", "")
            success = self.rollback_action(token)
            return {"success": success, "pre_state": {}, "rollback_token": token}

        token = str(uuid.uuid4())
        pre_state = self._snapshot_pre_state(action)

        try:
            if action_type == "reroute":
                self._do_reroute(action)
            elif action_type == "rate_limit":
                self._do_rate_limit(action)
            elif action_type == "scale_capacity":
                self._do_scale_capacity(action)
            else:
                return {"success": False, "pre_state": {}, "rollback_token": ""}

            applied = AppliedAction(
                rollback_token=token,
                action_type=action_type,
                pre_state=pre_state,
                parameters=dict(action),
                applied_at=self._telemetry.get_time(),
            )
            self._applied_actions.append(applied)
            self._rollback_store[token] = applied
            return {"success": True, "pre_state": pre_state, "rollback_token": token}

        except Exception as exc:
            return {"success": False, "pre_state": pre_state, "rollback_token": "", "error": str(exc)}

    def rollback_action(self, rollback_token: str) -> bool:
        """Restore pre-action state for a given rollback token."""
        applied = self._rollback_store.get(rollback_token)
        if not applied:
            return False

        pre = applied.pre_state
        atype = applied.action_type
        params = applied.parameters

        if atype == "reroute":
            src = params.get("source_node", "")
            tgt = params.get("target_node", "")
            if src and tgt:
                old_weight = pre.get("weight", 1.0)
                self._topology.update_link_weight(src, tgt, old_weight)

        elif atype == "rate_limit":
            lid = params.get("target_link", "")
            if lid in self._link_overrides:
                del self._link_overrides[lid]

        elif atype == "scale_capacity":
            lid = params.get("target_link", "")
            if lid in self._link_overrides:
                self._link_overrides[lid].pop("capacity_gbps", None)
                if not self._link_overrides[lid]:
                    del self._link_overrides[lid]

        del self._rollback_store[rollback_token]
        return True

    def get_action_history(self) -> list[AppliedAction]:
        return list(self._applied_actions)

    # ------------------------------------------------------------------
    # Action helpers
    # ------------------------------------------------------------------

    def _snapshot_pre_state(self, action: dict[str, Any]) -> dict[str, Any]:
        atype = action.get("action_type", "")
        if atype == "reroute":
            src = action.get("source_node", "")
            tgt = action.get("target_node", "")
            try:
                link = self._topology.get_link(src, tgt)
                return {"weight": link.get("weight", 1.0)}
            except KeyError:
                return {}
        if atype in ("rate_limit", "scale_capacity"):
            lid = action.get("target_link", "")
            return dict(self._link_overrides.get(lid, {}))
        return {}

    def _do_reroute(self, action: dict[str, Any]) -> None:
        src = action["source_node"]
        tgt = action["target_node"]
        new_weight = float(action.get("new_weight", 10.0))
        self._topology.update_link_weight(src, tgt, new_weight)

    def _do_rate_limit(self, action: dict[str, Any]) -> None:
        lid = action["target_link"]
        pct = float(action.get("limit_pct", 50.0))
        self._link_overrides.setdefault(lid, {})["rate_limit_pct"] = pct

    def _do_scale_capacity(self, action: dict[str, Any]) -> None:
        lid = action["target_link"]
        new_cap = float(action["new_capacity_gbps"])
        self._link_overrides.setdefault(lid, {})["capacity_gbps"] = new_cap


# ---------------------------------------------------------------------------
# Per-metric overlay helpers (pure functions → new dict each time)
# ---------------------------------------------------------------------------

def _spike_link(
    m: dict[str, Any], rng: np.random.Generator, util_boost: float, loss_boost: float
) -> dict[str, Any]:
    cap = m["capacity_gbps"]
    new_util = float(np.clip(m["utilization_pct"] + rng.uniform(util_boost * 0.7, util_boost * 1.3), 0, 100))
    new_loss = float(np.clip(m["packet_loss_pct"] + rng.uniform(loss_boost * 0.8, loss_boost * 1.2), 0, 100))
    new_lat = m["latency_ms"] * float(rng.uniform(2.5, 4.0))
    new_tp = float(np.clip(new_util / 100.0 * cap, 0, cap))
    return {**m,
            "utilization_pct": round(new_util, 4),
            "throughput_gbps": round(new_tp, 4),
            "latency_ms": round(new_lat, 4),
            "packet_loss_pct": round(new_loss, 6)}


def _boost_link(
    m: dict[str, Any], rng: np.random.Generator, util_boost: float
) -> dict[str, Any]:
    cap = m["capacity_gbps"]
    new_util = float(np.clip(m["utilization_pct"] + rng.uniform(util_boost * 0.6, util_boost * 1.4), 0, 100))
    new_lat = m["latency_ms"] * float(rng.uniform(1.3, 1.8))
    new_tp = float(np.clip(new_util / 100.0 * cap, 0, cap))
    return {**m,
            "utilization_pct": round(new_util, 4),
            "throughput_gbps": round(new_tp, 4),
            "latency_ms": round(new_lat, 4)}


def _latency_boost(
    m: dict[str, Any], rng: np.random.Generator, factor: float
) -> dict[str, Any]:
    return {**m, "latency_ms": round(m["latency_ms"] * float(rng.uniform(factor * 0.9, factor * 1.1)), 4)}


def _erratic_link(m: dict[str, Any], rng: np.random.Generator) -> dict[str, Any]:
    jitter = float(rng.choice([1.0, 1.5, 3.0, 5.0], p=[0.4, 0.3, 0.2, 0.1]))
    spike = float(rng.choice([0.0, 8.0, 15.0], p=[0.75, 0.2, 0.05]))
    new_loss = float(np.clip(m["packet_loss_pct"] + rng.uniform(0.5, 2.0) + spike, 0, 100))
    return {**m,
            "latency_ms": round(m["latency_ms"] * jitter, 4),
            "packet_loss_pct": round(new_loss, 6)}


def _kill_link(m: dict[str, Any]) -> dict[str, Any]:
    return {**m, "utilization_pct": 0.0, "throughput_gbps": 0.0,
            "packet_loss_pct": 100.0, "latency_ms": 0.0}


def _degrade_node(m: dict[str, Any], rng: np.random.Generator) -> dict[str, Any]:
    new_cpu = float(np.clip(m["cpu_pct"] + rng.uniform(20, 40), 0, 100))
    new_temp = float(np.clip(m["temperature_c"] + rng.uniform(8, 20), 20, 90))
    new_mem = float(np.clip(m["memory_pct"] + rng.uniform(10, 25), 0, 100))
    return {**m,
            "cpu_pct": round(new_cpu, 4),
            "temperature_c": round(new_temp, 4),
            "memory_pct": round(new_mem, 4),
            "buffer_drops": m["buffer_drops"] + int(rng.integers(10, 50))}


def _saturate_node(m: dict[str, Any], rng: np.random.Generator) -> dict[str, Any]:
    new_cpu = float(np.clip(rng.uniform(88, 100), 0, 100))
    return {**m,
            "cpu_pct": round(new_cpu, 4),
            "buffer_drops": m["buffer_drops"] + int(rng.integers(200, 800))}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio
    from src.simulator.topology import NetworkTopology

    async def main() -> None:
        topo = NetworkTopology()
        engine = SimulationEngine(topo, speed_multiplier=120.0, seed=42)

        tick_counter = {"n": 0}
        anomaly_detected: list[str] = []

        # ── Subscriber: print every 5th tick ──────────────────────────────
        def printer(timestamp: str, state: dict[str, Any]) -> None:
            tick_counter["n"] += 1
            if tick_counter["n"] % 5 != 0:
                return
            sim_time = timestamp[11:16]  # HH:MM
            # Pick headline metrics
            cr1_cr2 = state["links"].get("CR1-CR2", {})
            util = cr1_cr2.get("utilization_pct", 0.0)
            lat  = cr1_cr2.get("latency_ms", 0.0)
            loss = cr1_cr2.get("packet_loss_pct", 0.0)
            print(
                f"  [tick {tick_counter['n']:>4}  sim={sim_time}]  "
                f"CR1-CR2  util={util:>6.2f}%  lat={lat:>6.2f}ms  loss={loss:.4f}%"
            )

        engine.subscribe(printer)

        # ── Start at 120x speed ──────────────────────────────────────────
        print(f"Starting engine at {engine.get_speed()}x speed  "
              f"(1 real second = {engine.get_speed()/60:.0f} sim minutes)\n")
        await engine.start()

        # ── Run 10 seconds, then inject congestion cascade ───────────────
        print("Running for 10 seconds before injecting anomaly…")
        await asyncio.sleep(10)

        print("\n>>> Injecting congestion_cascade on CR1-CR2")
        label = engine.inject_anomaly_now(
            "congestion_cascade", "CR1-CR2", duration_minutes=30
        )
        print(f"    scenario_id : {label.scenario_id[:8]}…")
        print(f"    severity    : {label.severity}")
        print(f"    end_sim_time: {label.end_time.strftime('%H:%M')} UTC\n")

        # ── Run 20 more seconds showing the anomaly unfold ───────────────
        print("Running 20 more seconds (anomaly unfolding)…")
        await asyncio.sleep(20)

        # ── Stop ──────────────────────────────────────────────────────────
        await engine.stop()

        # ── Summary ───────────────────────────────────────────────────────
        print("\n" + "=" * 55)
        print("SIMULATION SUMMARY")
        print("=" * 55)
        print(f"  Total ticks       : {engine.get_tick_count()}")
        print(f"  Anomalies injected: {len(engine.get_anomaly_history())}")
        print(f"  Actions applied   : {len(engine.get_action_history())}")
        print(f"  Final sim time    : {engine.get_simulation_time().strftime('%Y-%m-%d %H:%M')} UTC")
        if engine.get_anomaly_history():
            lbl = engine.get_anomaly_history()[0]
            print(f"\n  Anomaly injected  : {lbl.scenario_type}")
            print(f"  Affected links    : {lbl.affected_links}")
            print(f"  Severity          : {lbl.severity}")

    asyncio.run(main())
