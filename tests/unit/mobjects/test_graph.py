"""A graph is its vertices and edges, edited through its public methods, beside a model of them.

- Its vertices and edges are those added and not removed, in the order added; a vertex
  removed takes its edges with it, and a key removed and added again is a fresh vertex, made
  with the graph's vertex keywords under the ones given, without the label it had.
- Each method returns what it added or removed: a new vertex, an edge's new vertices then
  the edge, a vertex's edges then the vertex.
- Every edge joins its vertices once the graph's updater runs: center to center, or outline
  to outline for a directed graph's, wherever the vertices were moved or laid out.
- A layout by positions puts each vertex at its own; a layout function is handed a fresh
  graph of the current vertices and edges, the scale, and the layout keywords (over the
  partitions and root vertex given), and what it does to that graph stays there; a layout by
  name lays the vertices out as a graph made afresh with that layout would.
- A copy goes on apart: what is done to it leaves the graph it was copied from.
"""

import networkx as nx
import numpy as np
import pytest
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    invariant,
    precondition,
    rule,
)

import manimgx as m
from manimgx.mobjects.graph import GenericGraph

KEYS = range(6)
SPOTS = [
    np.array([x, y, 0.0]) for x in (-3.0, -1.5, 0.0, 1.5, 3.0) for y in (-2.0, 0, 2)
]
TOKEN = object()  # (a layout keyword handed on as it is)
# what a layout function was handed: its scale, keywords, nodes and edges, and the graph's
# and the nodes' attributes
type Seen = tuple[
    float,
    dict[str, object],
    list[int],
    set[tuple[int, int]],
    dict[str, object],
    list[dict[str, object]],
]


class Graphs(RuleBasedStateMachine):
    """A graph or a directed one, its vertices added, removed, moved and laid out, its edges
    added and removed, and copied, beside a model of where each vertex is and its color."""

    graph: m.Graph[int] | m.DiGraph[int]

    @initialize(directed=st.booleans(), drawn=st.booleans())
    def made(self, directed: bool, drawn: bool) -> None:
        self.kind = m.DiGraph if directed else m.Graph
        style = {"radius": 0.15, "color": m.BLUE}
        if drawn:  # (a vertex given as its mobject, named only by it and by an edge)
            dot = m.Dot(radius=0.15, color=m.YELLOW)
            self.graph = self.kind(
                [0],
                [(0, 1)],
                vertex_mobjects={1: dot},
                layout="circular",
                vertex_config=style,
            )
        else:
            self.graph = self.kind(
                [0, 1], [(0, 1)], layout="circular", vertex_config=style
            )
        fresh = self.kind([0, 1], [(0, 1)], layout="circular")
        self.where = {v: fresh[v].get_center() for v in (0, 1)}
        self.colors = {0: m.BLUE, 1: m.YELLOW if drawn else m.BLUE}
        self.edges: list[tuple[int, int]] = [(0, 1)]
        self.gone: list[m.Mobject] = []  # removed: never in the family again
        self.copied: list[
            tuple[GenericGraph[int], list[np.ndarray], list[int], list[object]]
        ] = []

    def free(self) -> list[np.ndarray]:
        return [
            s
            for s in SPOTS
            if all(np.linalg.norm(s - p) > 0.5 for p in self.where.values())
        ]

    @precondition(lambda self: len(self.where) < len(KEYS))
    @rule(data=st.data(), red=st.booleans(), labeled=st.booleans())
    def add_vertex(self, data: st.DataObject, red: bool, labeled: bool) -> None:
        v = data.draw(st.sampled_from([v for v in KEYS if v not in self.where]))
        spot = data.draw(st.sampled_from(self.free()))
        label = m.Square(0.1)
        added = self.graph.add_vertices(
            v,
            positions={v: spot},
            labels={v: label} if labeled else False,
            vertex_config={"color": m.RED} if red else None,
        )
        assert added.submobjects == [self.graph[v]]
        if labeled:
            assert label in self.graph[v].get_family()
        else:  # (a fresh vertex: no label left from a vertex of that key before)
            assert self.graph[v].submobjects == []
        self.where[v] = spot
        self.colors[v] = m.RED if red else m.BLUE

    @precondition(lambda self: self.where)
    @rule(data=st.data())
    def add_a_present_vertex(self, data: st.DataObject) -> None:
        v = data.draw(st.sampled_from(sorted(self.where)))
        with pytest.raises(ValueError, match="already used"):
            self.graph.add_vertices(v)

    @rule(data=st.data(), green=st.booleans())
    def add_edge(self, data: st.DataObject, green: bool) -> None:
        pairs = [
            (u, v) for u in KEYS for v in KEYS if u != v and (u, v) not in self.edges
        ]
        # (an edge's reverse, often: see remove_edge)
        reverses = [e for e in pairs if e[::-1] in self.edges]
        u, v = data.draw(
            st.sampled_from(reverses) | st.sampled_from(pairs)
            if reverses
            else st.sampled_from(pairs)
        )
        new = [w for w in (u, v) if w not in self.where]
        spots = dict(zip(new, data.draw(st.permutations(self.free())), strict=False))
        added = self.graph.add_edges(
            (u, v),
            positions=spots,
            vertex_config={"color": m.GREEN} if green else None,
        )
        assert added.submobjects == [
            *(self.graph[w] for w in new),
            self.graph.edges[u, v],
        ]
        for w in new:
            self.where[w] = spots[w]
            self.colors[w] = m.GREEN if green else m.BLUE
        self.edges.append((u, v))

    @precondition(lambda self: self.where)
    @rule(data=st.data())
    def remove_vertex(self, data: st.DataObject) -> None:
        v = data.draw(st.sampled_from(sorted(self.where)))
        touching = [e for e in self.edges if v in e]
        expected = [*(self.graph.edges[e] for e in touching), self.graph[v]]
        assert self.graph.remove_vertices(v).submobjects == expected
        self.gone += [mob for part in expected for mob in part.get_family()]
        del self.where[v], self.colors[v]
        self.edges = [e for e in self.edges if v not in e]

    @precondition(lambda self: self.edges)
    @rule(data=st.data())
    def remove_edge(self, data: st.DataObject) -> None:
        # (an undirected graph's (u, v) and (v, u) are two edges, and one connection
        # until both are gone: the layout functions see it)
        e = data.draw(st.sampled_from(self.edges))
        edge = self.graph.edges[e]
        assert self.graph.remove_edges(e).submobjects == [edge]
        self.gone += edge.get_family()
        self.edges.remove(e)

    @precondition(lambda self: self.where)
    @rule(data=st.data())
    def move_vertex(self, data: st.DataObject) -> None:
        v = data.draw(st.sampled_from(sorted(self.where)))
        spot = data.draw(st.sampled_from(self.free()))
        self.graph[v].move_to(spot)
        self.where[v] = spot

    @precondition(lambda self: self.where)
    @rule(data=st.data(), flat=st.booleans())
    def lay_out_by_hand(self, data: st.DataObject, flat: bool) -> None:
        spots = data.draw(st.permutations(SPOTS))
        positions = dict(zip(self.where, spots, strict=False))
        self.graph.change_layout(
            {v: list(p[:2]) if flat else p for v, p in positions.items()}
        )
        self.where.update(positions)

    @precondition(lambda self: self.where)
    @rule(
        scale=st.sampled_from([1.0, 3.0]),
        config=st.sampled_from(
            [None, {"token": TOKEN}, {"root_vertex": 7, "partitions": [[0]]}]
        ),
        partitions=st.sampled_from([None, [[5]]]),
        root=st.sampled_from([None, 0]),
    )
    def lay_out_by_a_function(
        self,
        scale: float,
        config: dict[str, object] | None,
        partitions: list[list[int]] | None,
        root: int | None,
    ) -> None:
        seen: list[Seen] = []

        def layout(
            topology: nx.Graph, scale: float = 2.0, **kwargs: object
        ) -> dict[int, list[float]]:
            nodes = list(topology)
            seen.append(
                (
                    scale,
                    kwargs,
                    nodes,
                    set(topology.edges),
                    dict(topology.graph),
                    [dict(topology.nodes[v]) for v in nodes],
                )
            )
            topology.graph["stale"] = True  # (what it does stays in this call)
            topology.add_edge(98, 99)
            for v in nodes:
                topology.nodes[v]["weight"] = 1
            return {v: [scale * i, 0.5 * i] for i, v in enumerate(nodes)}

        self.graph.change_layout(
            layout,
            layout_scale=scale,
            layout_config=config,
            partitions=partitions,
            root_vertex=root,
        )
        keywords = dict(config or {})
        if partitions is not None:
            keywords.setdefault("partitions", partitions)
        if root is not None:
            keywords.setdefault("root_vertex", root)
        nodes = list(self.where)
        [(seen_scale, seen_keywords, seen_nodes, seen_edges, *fresh)] = seen
        assert (seen_scale, seen_keywords, seen_nodes) == (scale, keywords, nodes)
        if self.kind is m.DiGraph:
            assert seen_edges == set(self.edges)
        else:  # (an undirected pair is one connection, either way round)
            assert {frozenset(e) for e in seen_edges} == {
                frozenset(e) for e in self.edges
            }
        assert fresh == [{}, [{}] * len(nodes)]
        for i, v in enumerate(nodes):
            self.where[v] = np.array([scale * i, 0.5 * i, 0])

    @precondition(lambda self: self.where)
    @rule(data=st.data(), name=st.sampled_from(["circular", "partite"]))
    def lay_out_by_name(self, data: st.DataObject, name: str) -> None:
        vertices = list(self.where)
        partitions = None
        if name == "partite":
            order = data.draw(st.permutations(vertices))
            cut = data.draw(st.integers(1, len(order)))
            partitions = [order[:cut][::2], order[:cut][1::2]]
            partitions = [p for p in partitions if p]
        fresh = self.kind(vertices, self.edges, layout=name, partitions=partitions)
        self.graph.change_layout(name, partitions=partitions)
        for v in vertices:
            self.where[v] = fresh[v].get_center()

    @rule()
    def copy(self) -> None:
        graph = self.graph
        points = [mob.points.copy() for mob in graph.get_family()]
        self.copied.append((graph, points, list(graph.vertices), list(graph.edges)))
        self.graph = graph.copy()
        assert not {id(mob) for mob in self.graph.get_family()} & {
            id(mob) for mob in graph.get_family()
        }
        self.gone = []

    @invariant()
    def edges_join_their_vertices(self) -> None:
        graph = self.graph
        assert list(graph.vertices) == list(self.where)
        assert list(graph.edges) == self.edges
        family = {id(mob) for mob in graph.get_family()}
        assert not any(id(mob) in family for mob in self.gone)
        graph.update(0)
        for v, spot in self.where.items():
            np.testing.assert_allclose(graph[v].get_center(), spot, atol=1e-9)
            assert graph[v].get_color() == self.colors[v]
            assert graph[v].width == pytest.approx(0.3)
        for (u, v), edge in graph.edges.items():
            start, end = graph[u].get_center(), graph[v].get_center()
            if isinstance(graph, m.DiGraph):
                direction = end - start
                start = graph[u].get_boundary_point(direction)
                end = graph[v].get_boundary_point(-direction)
            np.testing.assert_allclose(
                edge.get_start_and_end(), [start, end], atol=1e-9
            )

    @invariant()
    def copies_go_on_apart(self) -> None:
        for graph, points, vertices, edges in self.copied:
            graph.update(0)
            assert (list(graph.vertices), list(graph.edges)) == (vertices, edges)
            for mob, before in zip(graph.get_family(), points, strict=True):
                np.testing.assert_allclose(mob.points, before, atol=1e-9)


TestGraphs = Graphs.TestCase
TestGraphs.settings = settings(stateful_step_count=20, max_examples=60)
