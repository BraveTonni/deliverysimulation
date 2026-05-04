import random
import heapq
import math

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Node:
    id: int
    x: float
    y: float


@dataclass
class Edge:
    from_node: int
    to_node: int
    distance: float
    traffic_factor: float = 1.0


@dataclass(order=True)
class PathNode:
    f_score: float
    g_score: float = field(compare=False)
    node_id: int = field(compare=False)
    came_from: Optional[int] = field(default=None, compare=False)


class RoadGraph:
    def __init__(self):
        self.nodes: dict[int, Node] = {}
        self.edges: dict[int, list[Edge]] = {}

    def add_node(self, node_id: int, x: float, y: float) -> None:
        self.nodes[node_id] = Node(node_id, x, y)
        if node_id not in self.edges:
            self.edges[node_id] = []

    def add_edge(self, from_node: int, to_node: int, distance: float) -> None:
        edge = Edge(from_node, to_node, distance)
        self.edges[from_node].append(edge)
        self.edges[to_node].append(Edge(to_node, from_node, distance))

    def get_neighbors(self, node_id: int) -> list[Edge]:
        return self.edges.get(node_id, [])

    def heuristic(self, node_id: int, goal: int) -> float:
        node = self.nodes[node_id]
        goal_node = self.nodes[goal]
        return math.sqrt((node.x - goal_node.x) ** 2 + (node.y - goal_node.y) ** 2)

    def get_traffic_factor(self, from_node: int, to_node: int) -> float:
        for edge in self.edges.get(from_node, []):
            if edge.to_node == to_node:
                return edge.traffic_factor
        return 1.0

    def set_traffic(self, from_node: int, to_node: int, factor: float) -> None:
        for edge in self.edges.get(from_node, []):
            if edge.to_node == to_node:
                edge.traffic_factor = factor

    def astar(self, start: int, goal: int) -> tuple[Optional[list[int]], float]:
        if start not in self.nodes or goal not in self.nodes:
            return None, float("inf")

        open_set: list[PathNode] = []
        closed_set: set[int] = set()
        came_from: dict[int, int] = {}

        initial_f = self.heuristic(start, goal)
        heapq.heappush(open_set, PathNode(initial_f, 0, start))

        g_scores: dict[int, float] = {start: 0}

        while open_set:
            current = heapq.heappop(open_set)

            if current.node_id == goal:
                path = self.reconstruct_path(came_from, current.node_id)
                return path, current.g_score

            if current.node_id in closed_set:
                continue
            closed_set.add(current.node_id)

            for edge in self.get_neighbors(current.node_id):
                if edge.to_node in closed_set:
                    continue

                traffic = self.get_traffic_factor(current.node_id, edge.to_node)
                tentative_g = current.g_score + edge.distance * traffic

                if edge.to_node not in g_scores or tentative_g < g_scores[edge.to_node]:
                    g_scores[edge.to_node] = tentative_g
                    came_from[edge.to_node] = current.node_id
                    f = tentative_g + self.heuristic(edge.to_node, goal)
                    heapq.heappush(open_set, PathNode(f, tentative_g, edge.to_node, current.node_id))

        return None, float("inf")

    def reconstruct_path(self, came_from: dict[int, int], current: int) -> list[int]:
        path = [current]
        while current in came_from:
            current = came_from[current]
            path.append(current)
        path.reverse()
        return path


def generate_city_graph(num_nodes: int = 50, seed: int = 42) -> RoadGraph:
    random.seed(seed)

    graph = RoadGraph()

    for i in range(num_nodes):
        x = random.uniform(0, 1000)
        y = random.uniform(0, 1000)
        graph.add_node(i, x, y)

    for i in range(num_nodes):
        for j in range(i + 1, num_nodes):
            dist = math.sqrt((graph.nodes[i].x - graph.nodes[j].x) ** 2 + (graph.nodes[i].y - graph.nodes[j].y) ** 2)
            if dist < 200:
                graph.add_edge(i, j, dist)

    for i in range(num_nodes):
        if len(graph.edges[i]) == 0:
            nearest = min(
                range(num_nodes),
                key=lambda j: (
                    math.sqrt((graph.nodes[i].x - graph.nodes[j].x) ** 2 + (graph.nodes[i].y - graph.nodes[j].y) ** 2)
                    if j != i
                    else float("inf")
                ),
            )
            dist = math.sqrt(
                (graph.nodes[i].x - graph.nodes[nearest].x) ** 2 + (graph.nodes[i].y - graph.nodes[nearest].y) ** 2
            )
            graph.add_edge(i, nearest, dist)

    return graph
