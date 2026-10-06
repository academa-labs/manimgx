"""Spectral coordinates belong to Laplacian eigenspaces, not an eigensolver's choice of basis."""

import networkx as nx
import numpy as np
import pytest

from manimgx.mobjects.graph import _spectral_layout


@pytest.mark.parametrize(
    ("graph", "groups"),
    [
        (nx.empty_graph(6), [(0, 6)]),
        (nx.complete_graph(6), [(0, 1), (1, 6)]),
        (nx.cycle_graph(6), [(0, 1), (1, 3), (3, 5), (5, 6)]),
        (
            nx.disjoint_union(nx.path_graph(3), nx.path_graph(3)),
            [(0, 2), (2, 4), (4, 6)],
        ),
        (
            nx.Graph(
                [(1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 1), (5, 1), (1, 3), (3, 5)]
            ),
            [(0, 1), (1, 3), (3, 4), (4, 6)],
        ),
    ],
    ids=["isolated", "complete", "cycle", "disconnected", "corpus"],
)
def test_axes_do_not_depend_on_the_eigensolvers_basis(
    graph: nx.Graph, groups: list[tuple[int, int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = np.array(list(_spectral_layout(graph).values()))
    solve = np.linalg.eigh
    rng = np.random.default_rng(2026)

    def other_basis(matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        values, vectors = solve(matrix)
        for start, end in groups:
            rotation, _ = np.linalg.qr(rng.normal(size=(end - start, end - start)))
            vectors[:, start:end] = vectors[:, start:end] @ rotation
        return values, vectors

    monkeypatch.setattr(np.linalg, "eigh", other_basis)
    for _ in range(20):
        found = np.array(list(_spectral_layout(graph).values()))
        np.testing.assert_allclose(found, expected, rtol=0, atol=1e-13)


@pytest.mark.parametrize(
    "graph",
    [nx.path_graph(8), nx.complete_graph(8), nx.cycle_graph(8), nx.empty_graph(8)],
)
def test_coordinates_are_centered_orthogonal_lowest_laplacian_directions(
    graph: nx.Graph,
) -> None:
    adjacency = nx.to_numpy_array(graph)
    laplacian = np.diag(adjacency.sum(axis=1)) - adjacency
    expected = np.linalg.eigvalsh(laplacian)[1:4]
    points = np.array(list(_spectral_layout(graph, dim=3).values()))
    directions = points / np.linalg.norm(points, axis=0)
    np.testing.assert_allclose(directions.mean(axis=0), 0, atol=1e-13)
    np.testing.assert_allclose(directions.T @ directions, np.eye(3), atol=1e-13)
    np.testing.assert_allclose(
        laplacian @ directions, directions * expected, atol=1e-13
    )


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_small_graphs_honor_dimensions_scale_and_center(count: int) -> None:
    graph = nx.path_graph(count)
    center = np.array([2.0, 3.0, 4.0])
    positions = _spectral_layout(
        graph, dim=3, scale=2, center=center, store_pos_as="position"
    )
    assert list(positions) == list(graph)
    for node, position in positions.items():
        assert position.shape == (3,)
        np.testing.assert_array_equal(graph.nodes[node]["position"], position)
    if count:
        points = np.array(list(positions.values()))
        np.testing.assert_allclose(points.mean(axis=0), center, atol=1e-13)
        assert np.abs(points - center).max() == pytest.approx(0 if count == 1 else 2)


def test_directed_edges_define_the_same_symmetric_laplacian() -> None:
    directed = nx.DiGraph([(0, 1), (1, 2), (2, 3)])
    expected = _spectral_layout(directed.to_undirected())
    found = _spectral_layout(directed)
    np.testing.assert_array_equal(list(found.values()), list(expected.values()))


@pytest.mark.parametrize("separation", [2.0**-20, 2.0**-47])
def test_unresolved_orientation_neither_flips_nor_drops_a_low_mode(
    separation: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Backward-stable solves can disagree at a zero component near another mode."""
    s = 2**-0.5
    q = np.array(
        [[0.5, 0, s, 0.5], [0.5, s, 0, -0.5], [0.5, -s, 0, -0.5], [0.5, 0, -s, 0.5]]
    )
    first = np.outer([0, 1, -1, 0], [0, 1, -1, 0])
    second = np.outer([1, 0, 0, -1], [1, 0, 0, -1])
    last = np.outer([1, -1, -1, 1], [1, -1, -1, 1])
    adjacency = -0.5 * first - 0.5 * (1 + separation) * second - 0.375 * last
    np.fill_diagonal(adjacency, 0)
    graph = nx.from_numpy_array(adjacency)
    found: list[np.ndarray] = []
    for angle in (-1e-10, 1e-10):

        def solve(
            matrix: np.ndarray, angle: float = angle
        ) -> tuple[np.ndarray, np.ndarray]:
            values = np.diag(q.T @ matrix @ q).copy()
            vectors = q.copy()
            c, s = np.cos(angle), np.sin(angle)
            vectors[:, 1:3] = vectors[:, 1:3] @ np.array([[c, -s], [s, c]])
            assert np.linalg.norm(matrix @ vectors - vectors * values) < 1e-14
            return values, vectors

        monkeypatch.setattr(np.linalg, "eigh", solve)
        points = np.array(list(_spectral_layout(graph).values()))
        directions = points / np.linalg.norm(points, axis=0)
        np.testing.assert_allclose(directions.T @ directions, np.eye(2), atol=1e-13)
        np.testing.assert_allclose(
            directions @ directions.T, q[:, 1:3] @ q[:, 1:3].T, atol=1e-13
        )
        found.append(points)
    np.testing.assert_allclose(found[0], found[1], atol=1e-8)


@pytest.mark.parametrize("scale", [1e-200, 1e200])
def test_uniform_weight_scale_does_not_change_the_coordinates(scale: float) -> None:
    graph = nx.cycle_graph(6)
    expected = _spectral_layout(graph)
    nx.set_edge_attributes(graph, scale, "weight")
    found = _spectral_layout(graph)
    np.testing.assert_allclose(
        list(found.values()), list(expected.values()), atol=1e-13
    )


def test_a_nearly_zero_node_projection_does_not_amplify_solver_rounding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constant = np.ones(6) / np.sqrt(6)
    first = np.array([0, 1, -1, 0, 0, 0]) / np.sqrt(2)
    second = np.array([0, 1, 1, -2, 0, 0]) / np.sqrt(6)
    high = np.array([5, -1, -1, -1, -1, -1]) / np.sqrt(30)
    q, _ = np.linalg.qr(
        np.column_stack([constant, first, second, high]), mode="complete"
    )

    def rotate(q: np.ndarray, left: int, right: int, angle: float) -> np.ndarray:
        q = q.copy()
        c, s = np.cos(angle), np.sin(angle)
        q[:, [left, right]] = q[:, [left, right]] @ np.array([[c, -s], [s, c]])
        return q

    q = rotate(q, 1, 3, 1e-13)
    adjacency = -(q @ np.diag([0, 4, 4, 5, 5, 5]) @ q.T)
    np.fill_diagonal(adjacency, 0)
    assert (adjacency >= 0).all()
    graph = nx.from_numpy_array(adjacency)
    found: list[np.ndarray] = []
    for noise in (-2e-15, 2e-15):

        def solve(
            matrix: np.ndarray, noise: float = noise
        ) -> tuple[np.ndarray, np.ndarray]:
            values = np.diag(q.T @ matrix @ q).copy()
            vectors = rotate(q, 2, 3, noise)
            assert np.linalg.norm(matrix @ vectors - vectors * values) < 1e-14
            return values, vectors

        monkeypatch.setattr(np.linalg, "eigh", solve)
        found.append(np.array(list(_spectral_layout(graph).values())))
    np.testing.assert_allclose(found[0], found[1], rtol=0, atol=1e-13)
