from __future__ import annotations

from typing import Any

import matplotlib
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import networkx as nx

matplotlib.use("Agg")

# ---------------------------------------------------------------------------
# Node definitions
# ---------------------------------------------------------------------------

_NODES: list[dict[str, Any]] = [
    # Core routers
    {
        "node_id": "CR1", "node_type": "core", "region": "east",
        "capacity_gbps": 400, "cpu_baseline": 55, "temp_baseline": 42,
        "memory_baseline": 50, "customers": 0,
    },
    {
        "node_id": "CR2", "node_type": "core", "region": "west",
        "capacity_gbps": 400, "cpu_baseline": 53, "temp_baseline": 41,
        "memory_baseline": 48, "customers": 0,
    },
    # Aggregation routers
    {
        "node_id": "AGG1", "node_type": "aggregation", "region": "east",
        "capacity_gbps": 100, "cpu_baseline": 60, "temp_baseline": 38,
        "memory_baseline": 45, "customers": 0,
    },
    {
        "node_id": "AGG2", "node_type": "aggregation", "region": "east",
        "capacity_gbps": 100, "cpu_baseline": 58, "temp_baseline": 37,
        "memory_baseline": 43, "customers": 0,
    },
    {
        "node_id": "AGG3", "node_type": "aggregation", "region": "west",
        "capacity_gbps": 100, "cpu_baseline": 62, "temp_baseline": 39,
        "memory_baseline": 47, "customers": 0,
    },
    {
        "node_id": "AGG4", "node_type": "aggregation", "region": "west",
        "capacity_gbps": 100, "cpu_baseline": 59, "temp_baseline": 38,
        "memory_baseline": 44, "customers": 0,
    },
    # Edge routers
    {
        "node_id": "EDGE1", "node_type": "edge", "region": "east",
        "capacity_gbps": 40, "cpu_baseline": 65, "temp_baseline": 35,
        "memory_baseline": 55, "customers": 120000,
    },
    {
        "node_id": "EDGE2", "node_type": "edge", "region": "east",
        "capacity_gbps": 40, "cpu_baseline": 63, "temp_baseline": 36,
        "memory_baseline": 52, "customers": 85000,
    },
    {
        "node_id": "EDGE3", "node_type": "edge", "region": "west",
        "capacity_gbps": 40, "cpu_baseline": 64, "temp_baseline": 35,
        "memory_baseline": 54, "customers": 200000,
    },
    {
        "node_id": "EDGE4", "node_type": "edge", "region": "west",
        "capacity_gbps": 40, "cpu_baseline": 62, "temp_baseline": 36,
        "memory_baseline": 51, "customers": 50000,
    },
    # Peering points
    {
        "node_id": "PEER1", "node_type": "peering", "region": "east",
        "capacity_gbps": 100, "cpu_baseline": 50, "temp_baseline": 40,
        "memory_baseline": 40, "customers": 0,
    },
    {
        "node_id": "PEER2", "node_type": "peering", "region": "west",
        "capacity_gbps": 100, "cpu_baseline": 51, "temp_baseline": 40,
        "memory_baseline": 41, "customers": 0,
    },
]

# ---------------------------------------------------------------------------
# Link definitions — (source, target, capacity_gbps, latency_baseline_ms)
# ---------------------------------------------------------------------------

_LINKS: list[tuple[str, str, float, float]] = [
    # Core interconnect
    ("CR1", "CR2", 200.0, 5.0),
    # Core → Aggregation
    ("CR1", "AGG1", 100.0, 2.0),
    ("CR1", "AGG2", 100.0, 2.0),
    ("CR2", "AGG3", 100.0, 2.0),
    ("CR2", "AGG4", 100.0, 2.0),
    # Aggregation → Edge
    ("AGG1", "EDGE1", 40.0, 1.0),
    ("AGG2", "EDGE2", 40.0, 1.0),
    ("AGG3", "EDGE3", 40.0, 1.0),
    ("AGG4", "EDGE4", 40.0, 1.0),
    # Peering connections
    ("PEER1", "CR1", 100.0, 3.0),
    ("PEER2", "CR2", 100.0, 3.0),
    # Cross-connections for redundancy
    ("AGG1", "AGG2", 40.0, 1.0),
    ("AGG3", "AGG4", 40.0, 1.0),
    ("PEER1", "AGG1", 40.0, 2.0),
    ("PEER2", "AGG3", 40.0, 2.0),
]

# Visual style per node type
_NODE_COLORS = {
    "core": "#e74c3c",
    "aggregation": "#3498db",
    "edge": "#2ecc71",
    "peering": "#f39c12",
}
_NODE_SIZES = {
    "core": 2000,
    "aggregation": 1200,
    "edge": 700,
    "peering": 1000,
}


class NetworkTopology:
    """NetworkX-backed ISP topology with 12 nodes."""

    def __init__(self) -> None:
        self._graph: nx.DiGraph = nx.DiGraph()
        self._build()

    # ------------------------------------------------------------------
    # Internal builders
    # ------------------------------------------------------------------

    def _build(self) -> None:
        for node in _NODES:
            nid = node["node_id"]
            self._graph.add_node(nid, **{k: v for k, v in node.items() if k != "node_id"})

        for src, tgt, cap, lat in _LINKS:
            attrs = {
                "capacity_gbps": cap,
                "latency_baseline_ms": lat,
                "distance_km": lat * 100,  # rough approximation: 1ms ≈ 100km
                "weight": 1.0,
            }
            self._graph.add_edge(src, tgt, **attrs)
            self._graph.add_edge(tgt, src, **attrs)

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_graph(self) -> nx.DiGraph:
        return self._graph

    def get_node(self, node_id: str) -> dict[str, Any]:
        if node_id not in self._graph:
            raise KeyError(f"Node '{node_id}' not in topology")
        return {"node_id": node_id, **self._graph.nodes[node_id]}

    def get_link(self, source: str, target: str) -> dict[str, Any]:
        if not self._graph.has_edge(source, target):
            raise KeyError(f"Link '{source}→{target}' not in topology")
        return {
            "link_id": self.get_link_id(source, target),
            "source": source,
            "target": target,
            **self._graph.edges[source, target],
        }

    def get_all_nodes(self) -> list[dict[str, Any]]:
        return [self.get_node(nid) for nid in self._graph.nodes]

    def get_all_links(self) -> list[dict[str, Any]]:
        seen: set[str] = set()
        links = []
        for src, tgt in self._graph.edges:
            lid = self.get_link_id(src, tgt)
            if lid not in seen:
                seen.add(lid)
                links.append(self.get_link(src, tgt))
        return links

    def get_neighbors(self, node_id: str) -> list[str]:
        if node_id not in self._graph:
            raise KeyError(f"Node '{node_id}' not in topology")
        return list(self._graph.neighbors(node_id))

    def get_shortest_path(self, source: str, target: str) -> list[str]:
        try:
            return nx.shortest_path(self._graph, source, target, weight="weight")
        except nx.NetworkXNoPath:
            return []

    def get_all_paths(self, source: str, target: str, max_length: int = 5) -> list[list[str]]:
        try:
            return [
                p
                for p in nx.all_simple_paths(self._graph, source, target, cutoff=max_length)
            ]
        except nx.NetworkXError:
            return []

    def get_link_id(self, source: str, target: str) -> str:
        a, b = sorted([source, target])
        return f"{a}-{b}"

    # ------------------------------------------------------------------
    # Mutators
    # ------------------------------------------------------------------

    def update_link_weight(self, source: str, target: str, weight: float) -> None:
        """Update routing weight on both directions of a link."""
        if not self._graph.has_edge(source, target):
            raise KeyError(f"Link '{source}→{target}' not in topology")
        self._graph.edges[source, target]["weight"] = weight
        self._graph.edges[target, source]["weight"] = weight

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": self.get_all_nodes(),
            "links": self.get_all_links(),
        }

    # ------------------------------------------------------------------
    # Visualization
    # ------------------------------------------------------------------

    def visualize(self, filename: str = "topology.png") -> None:
        fig, ax = plt.subplots(figsize=(16, 10))

        pos = {
            "CR1": (3, 5), "CR2": (9, 5),
            "AGG1": (1, 3), "AGG2": (4, 3), "AGG3": (8, 3), "AGG4": (11, 3),
            "EDGE1": (0.5, 1), "EDGE2": (3.5, 1), "EDGE3": (7.5, 1), "EDGE4": (10.5, 1),
            "PEER1": (2, 7), "PEER2": (10, 7),
        }

        node_colors = [
            _NODE_COLORS[self._graph.nodes[n]["node_type"]] for n in self._graph.nodes
        ]
        node_sizes = [
            _NODE_SIZES[self._graph.nodes[n]["node_type"]] for n in self._graph.nodes
        ]

        # Draw undirected view to avoid doubled arrows
        undirected = self._graph.to_undirected()
        nx.draw_networkx_nodes(undirected, pos, ax=ax, node_color=node_colors, node_size=node_sizes, alpha=0.9)
        nx.draw_networkx_labels(undirected, pos, ax=ax, font_size=8, font_weight="bold")
        nx.draw_networkx_edges(
            undirected, pos, ax=ax,
            edge_color="#555555", width=1.5, alpha=0.6,
            arrows=False,
        )
        edge_labels = {
            (u, v): f"{d['capacity_gbps']:.0f}G / {d['latency_baseline_ms']:.0f}ms"
            for u, v, d in undirected.edges(data=True)
        }
        nx.draw_networkx_edge_labels(undirected, pos, edge_labels=edge_labels, ax=ax, font_size=6)

        legend = [
            mpatches.Patch(color=color, label=ntype.capitalize())
            for ntype, color in _NODE_COLORS.items()
        ]
        ax.legend(handles=legend, loc="upper right", fontsize=9)
        ax.set_title("ISP Network Topology — Ballmer Agentic Conception - BAC", fontsize=14, fontweight="bold")
        ax.axis("off")

        plt.tight_layout()
        plt.savefig(filename, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"Topology visualization saved to: {filename}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    topo = NetworkTopology()
    g = topo.get_graph()

    total_capacity = sum(
        d["capacity_gbps"] for _, _, d in g.edges(data=True)
    ) / 2  # bidirectional, count once

    print(f"Nodes : {g.number_of_nodes()}")
    print(f"Links : {g.number_of_edges() // 2} (bidirectional, {g.number_of_edges()} directed edges)")
    print(f"Total link capacity : {total_capacity:.0f} Gbps")

    print("\nNode summary:")
    for node in topo.get_all_nodes():
        print(f"  {node['node_id']:6s}  type={node['node_type']:12s}  region={node['region']:4s}  "
              f"capacity={node['capacity_gbps']:4d}G  customers={node['customers']:>7}")

    print("\nShortest path CR1 → EDGE3:", topo.get_shortest_path("CR1", "EDGE3"))

    topo.visualize("topology.png")
