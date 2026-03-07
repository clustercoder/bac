from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TelemetryReading(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timestamp: datetime
    node_id: str
    link_id: Optional[str] = None  # format: "NODE1-NODE2"
    metrics: dict[str, float] = Field(
        default_factory=dict,
        description="Keys: latency_ms, packet_loss_pct, utilization_pct, throughput_gbps",
    )

    @field_validator("link_id")
    @classmethod
    def validate_link_id_format(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and "-" not in v:
            raise ValueError("link_id must follow format 'NODE1-NODE2'")
        return v

    @field_validator("metrics")
    @classmethod
    def validate_metric_values(cls, v: dict[str, float]) -> dict[str, float]:
        pct_keys = {"packet_loss_pct", "utilization_pct"}
        for key in pct_keys:
            if key in v and not (0.0 <= v[key] <= 100.0):
                raise ValueError(f"{key} must be between 0 and 100, got {v[key]}")
        for key, val in v.items():
            if val < 0:
                raise ValueError(f"Metric '{key}' cannot be negative, got {val}")
        return v


class NodeState(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    node_id: str
    node_type: Literal["core", "aggregation", "edge", "peering"]
    region: str
    cpu_pct: float = Field(ge=0.0, le=100.0)
    memory_pct: float = Field(ge=0.0, le=100.0)
    temperature_c: float = Field(ge=-10.0, le=200.0)
    buffer_drops: int = Field(ge=0)
    status: Literal["healthy", "degraded", "critical", "down"]


class LinkState(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    link_id: str  # format: "NODE1-NODE2"
    source: str
    target: str
    latency_ms: float = Field(ge=0.0)
    packet_loss_pct: float = Field(ge=0.0, le=100.0)
    utilization_pct: float = Field(ge=0.0, le=100.0)
    throughput_gbps: float = Field(ge=0.0)
    capacity_gbps: float = Field(gt=0.0)
    status: Literal["healthy", "degraded", "congested", "down"]

    @field_validator("link_id")
    @classmethod
    def validate_link_id_format(cls, v: str) -> str:
        if "-" not in v:
            raise ValueError("link_id must follow format 'NODE1-NODE2'")
        return v

    @model_validator(mode="after")
    def validate_throughput_vs_capacity(self) -> LinkState:
        if self.throughput_gbps > self.capacity_gbps:
            raise ValueError(
                f"throughput_gbps ({self.throughput_gbps}) cannot exceed capacity_gbps ({self.capacity_gbps})"
            )
        return self

    @model_validator(mode="after")
    def validate_link_id_matches_endpoints(self) -> LinkState:
        expected = f"{self.source}-{self.target}"
        reverse = f"{self.target}-{self.source}"
        if self.link_id not in (expected, reverse):
            raise ValueError(
                f"link_id '{self.link_id}' does not match source '{self.source}' and target '{self.target}'"
            )
        return self


class NetworkState(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timestamp: datetime
    nodes: dict[str, NodeState] = Field(default_factory=dict)
    links: dict[str, LinkState] = Field(default_factory=dict)


class Anomaly(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime
    metric_name: str
    node_id: Optional[str] = None
    link_id: Optional[str] = None
    observed_value: float
    expected_value: float
    severity: Literal["low", "medium", "high", "critical"]
    confidence: float = Field(ge=0.0, le=1.0)
    detector_type: str

    @model_validator(mode="after")
    def validate_at_least_one_target(self) -> Anomaly:
        if self.node_id is None and self.link_id is None:
            raise ValueError("At least one of node_id or link_id must be set")
        return self


class Hypothesis(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    root_cause: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    affected_nodes: list[str] = Field(default_factory=list)
    affected_links: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)


class ProposedAction(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    action_type: Literal[
        "reroute", "rate_limit", "scale_capacity", "config_rollback", "create_ticket", "escalate"
    ]
    target_node: Optional[str] = None
    target_link: Optional[str] = None
    parameters: dict = Field(default_factory=dict)
    expected_impact: str
    risk_level: float = Field(ge=0.0, le=1.0)
    requires_approval: bool
    utility_score: float
    z3_verified: bool = False
    z3_proof: Optional[str] = None

    @model_validator(mode="after")
    def validate_has_target(self) -> ProposedAction:
        passive_actions = {"create_ticket", "escalate"}
        if self.action_type not in passive_actions:
            if self.target_node is None and self.target_link is None:
                raise ValueError(
                    f"action_type '{self.action_type}' requires target_node or target_link"
                )
        return self


class ActionResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    action_id: str
    success: bool
    pre_metrics: dict[str, float] = Field(default_factory=dict)
    post_metrics: dict[str, float] = Field(default_factory=dict)
    rollback_available: bool
    rollback_token: Optional[str] = None
    outcome: Literal["effective", "partially_effective", "ineffective", "harmful"]

    @model_validator(mode="after")
    def validate_rollback_token_present_when_available(self) -> ActionResult:
        if self.rollback_available and self.rollback_token is None:
            raise ValueError("rollback_token must be set when rollback_available is True")
        return self


class AuditEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timestamp: datetime
    decision_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    phase: Literal["observe", "reason", "decide", "debate", "verify", "act", "learn"]
    anomalies: list[Anomaly] = Field(default_factory=list)
    hypothesis: Optional[Hypothesis] = None
    proposed_action: Optional[ProposedAction] = None
    rationale: str
    operator_approved: Optional[bool] = None
    debate_transcript: Optional[list[dict]] = None
    outcome: Optional[str] = None


class DebateEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    agent_role: Literal["reliability", "performance", "cost_sla", "judge"]
    position: Literal["support", "oppose", "conditional"]
    argument: str
    confidence: float = Field(ge=0.0, le=1.0)
    conditions: Optional[list[str]] = None


class DebateResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    proposed_action: ProposedAction
    entries: list[DebateEntry] = Field(default_factory=list)
    final_decision: Literal["approve", "reject", "modify"]
    judge_rationale: str
    consensus_score: float = Field(ge=0.0, le=1.0)
