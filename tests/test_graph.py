from shared.graph import RoadGraph, generate_city_graph


class TestRoadGraph:
    def test_add_node(self):
        graph = RoadGraph()
        graph.add_node(1, 10.0, 20.0)

        assert 1 in graph.nodes
        assert graph.nodes[1].x == 10.0
        assert graph.nodes[1].y == 20.0

    def test_add_edge(self):
        graph = RoadGraph()
        graph.add_node(1, 0.0, 0.0)
        graph.add_node(2, 10.0, 0.0)
        graph.add_edge(1, 2, 10.0)

        assert len(graph.edges[1]) == 1
        assert graph.edges[1][0].to_node == 2
        assert len(graph.edges[2]) == 1

    def test_heuristic(self):
        graph = RoadGraph()
        graph.add_node(1, 0.0, 0.0)
        graph.add_node(2, 3.0, 4.0)

        h = graph.heuristic(1, 2)

        assert abs(h - 5.0) < 0.001

    def test_astar_simple_path(self):
        graph = RoadGraph()
        graph.add_node(1, 0.0, 0.0)
        graph.add_node(2, 10.0, 0.0)
        graph.add_node(3, 20.0, 0.0)

        graph.add_edge(1, 2, 10.0)
        graph.add_edge(2, 3, 10.0)

        path, distance = graph.astar(1, 3)
        assert path == [1, 2, 3]
        assert abs(distance - 20.0) < 0.001

    def test_astar_no_path(self):
        graph = RoadGraph()
        graph.add_node(1, 0.0, 0.0)
        graph.add_node(2, 100.0, 100.0)

        path, _ = graph.astar(1, 2)
        assert path is None

    def test_astar_shortest_path(self):
        graph = RoadGraph()
        graph.add_node(1, 0.0, 0.0)
        graph.add_node(2, 10.0, 0.0)
        graph.add_node(3, 5.0, 10.0)
        graph.add_node(4, 20.0, 0.0)

        graph.add_edge(1, 2, 10.0)
        graph.add_edge(1, 3, 15.0)
        graph.add_edge(2, 4, 10.0)
        graph.add_edge(3, 4, 20.0)

        path, distance = graph.astar(1, 4)
        assert path == [1, 2, 4]
        assert abs(distance - 20.0) < 0.001

    def test_traffic_factor(self):
        graph = RoadGraph()
        graph.add_node(1, 0.0, 0.0)
        graph.add_node(2, 10.0, 0.0)
        graph.add_edge(1, 2, 10.0)

        graph.set_traffic(1, 2, 2.0)
        assert graph.get_traffic_factor(1, 2) == 2.0

    def test_astar_with_traffic(self):
        graph = RoadGraph()
        graph.add_node(1, 0.0, 0.0)
        graph.add_node(2, 10.0, 0.0)
        graph.add_node(3, 20.0, 0.0)

        graph.add_edge(1, 2, 10.0)
        graph.add_edge(2, 3, 10.0)

        graph.set_traffic(1, 2, 2.0)

        path, distance = graph.astar(1, 3)
        assert path == [1, 2, 3]
        assert distance > 20.0


class TestGenerateCityGraph:
    def test_generate_graph_size(self):
        graph = generate_city_graph(30)
        assert len(graph.nodes) == 30

    def test_generate_graph_connectivity(self):
        graph = generate_city_graph(20)
        connected_nodes = 0
        for node_id in graph.edges:
            if len(graph.edges[node_id]) > 0:
                connected_nodes += 1
        assert connected_nodes > 15

    def test_generate_graph_no_isolated(self):
        graph = generate_city_graph(10)
        for node_id in graph.nodes:
            assert len(graph.edges[node_id]) > 0


class TestPerformance:
    def test_astar_performance_small(self):
        graph = generate_city_graph(50)
        import time

        start = time.time()
        for _ in range(100):
            path, _ = graph.astar(0, 25)
        elapsed = time.time() - start
        assert elapsed < 1.0

    def test_astar_performance_medium(self):
        graph = generate_city_graph(100)
        import time

        start = time.time()
        for _ in range(50):
            path, _ = graph.astar(0, 50)
        elapsed = time.time() - start
        assert elapsed < 2.0
