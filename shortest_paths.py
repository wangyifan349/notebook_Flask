# shortest_paths.py
# 集合：Dijkstra, A*, Bellman-Ford, Floyd-Warshall, BFS（网格/无权图）
# 每个函数为独立顶层函数，返回值与注释说明在函数签名下方给出。

import heapq
from collections import deque
from typing import Dict, List, Tuple, Callable, Any

# ---------------------------------------------------------------------
# Dijkstra
# 适用：非负权图（有向或无向）
# 参数：
#   adj: dict node -> list of (neighbor, weight)
#   start: 起点
# 返回：
#   (dist, prev)
#   dist: dict node->最短距离（未到达节点无条目或为 inf）
#   prev: dict node->前驱节点（用于重建路径）
# 备注：使用最小堆（优先队列）
def dijkstra(adj: Dict[Any, List[Tuple[Any, float]]], start: Any) -> Tuple[Dict[Any, float], Dict[Any, Any]]:
    dist: Dict[Any, float] = {start: 0.0}
    prev: Dict[Any, Any] = {}
    pq: List[Tuple[float, Any]] = [(0.0, start)]
    while pq:
        d, u = heapq.heappop(pq)
        if d != dist.get(u, float('inf')):
            continue
        for v, w in adj.get(u, ()):
            nd = d + w
            if nd < dist.get(v, float('inf')):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))
    return dist, prev

# ---------------------------------------------------------------------
# A*
# 适用：有启发式信息（h）且可计算 neighbors 的情形（如网格或带坐标图）
# 参数：
#   start, goal: 起点与终点
#   neighbors: 函数 node -> list of (neighbor, weight)
#   h: 启发式函数 h(node, goal)，应为可接受的（admissible）
# 返回：
#   (path_list, total_cost) 或 ([], inf) 若无路径
def astar(start: Any, goal: Any,
          neighbors: Callable[[Any], List[Tuple[Any, float]]],
          h: Callable[[Any, Any], float]) -> Tuple[List[Any], float]:
    g: Dict[Any, float] = {start: 0.0}
    f: Dict[Any, float] = {start: h(start, goal)}
    prev: Dict[Any, Any] = {}
    open_heap: List[Tuple[float, Any]] = [(f[start], start)]
    closed: set = set()
    while open_heap:
        _, current = heapq.heappop(open_heap)
        if current == goal:
            path = _reconstruct_path(prev, start, goal)
            return path, g[goal]
        if current in closed:
            continue
        closed.add(current)
        for nbr, w in neighbors(current):
            tentative_g = g[current] + w
            if tentative_g < g.get(nbr, float('inf')):
                prev[nbr] = current
                g[nbr] = tentative_g
                f[nbr] = tentative_g + h(nbr, goal)
                heapq.heappush(open_heap, (f[nbr], nbr))
    return [], float('inf')

# 辅助：A* 路径重建（独立顶层函数）
def _reconstruct_path(prev: Dict[Any, Any], start: Any, goal: Any) -> List[Any]:
    path: List[Any] = []
    u = goal
    while u != start:
        path.append(u)
        u = prev.get(u)
        if u is None:
            return []
    path.append(start)
    path.reverse()
    return path

# ---------------------------------------------------------------------
# Bellman-Ford
# 适用：含负权边的图，可检测负权环
# 参数：
#   edges: list of (u, v, w)
#   nodes: 所有节点的列表示例（用于初始化）
#   start: 起点
# 返回：
#   (dist, prev)
# 抛出：
#   ValueError 当存在负权回路时
def bellman_ford(edges: List[Tuple[Any, Any, float]], nodes: List[Any], start: Any) -> Tuple[Dict[Any, float], Dict[Any, Any]]:
    dist: Dict[Any, float] = {node: float('inf') for node in nodes}
    prev: Dict[Any, Any] = {node: None for node in nodes}
    dist[start] = 0.0
    n = len(nodes)
    for _ in range(n - 1):
        updated = False
        for u, v, w in edges:
            if dist[u] + w < dist[v]:
                dist[v] = dist[u] + w
                prev[v] = u
                updated = True
        if not updated:
            break
    # 检测负权回路
    for u, v, w in edges:
        if dist[u] + w < dist[v]:
            raise ValueError("Graph contains a negative-weight cycle")
    return dist, prev

# ---------------------------------------------------------------------
# Floyd–Warshall
# 适用：计算任意两点之间最短路径（全对全）
# 参数：
#   nodes: 节点列表
#   weight_fn: 函数 weight_fn(u, v) 返回直接边权（无边时返回 float('inf')），对角应为 0
# 返回：
#   (dist, next_node)
#   dist: dict-of-dicts，dist[u][v] 为最短距离
#   next_node: dict-of-dicts，next_node[u][v] 为从 u 到 v 路径上的下一个节点（用于重建路径）
def floyd_warshall(nodes: List[Any], weight_fn: Callable[[Any, Any], float]) -> Tuple[Dict[Any, Dict[Any, float]], Dict[Any, Dict[Any, Any]]]:
    dist: Dict[Any, Dict[Any, float]] = {u: {v: weight_fn(u, v) for v in nodes} for u in nodes}
    next_node: Dict[Any, Dict[Any, Any]] = {u: {v: (v if dist[u][v] < float('inf') and u != v else None) for v in nodes} for u in nodes}
    for k in nodes:
        for i in nodes:
            for j in nodes:
                if dist[i][k] + dist[k][j] < dist[i][j]:
                    dist[i][j] = dist[i][k] + dist[k][j]
                    next_node[i][j] = next_node[i][k]
    return dist, next_node

# 独立的路径重建函数（Floyd–Warshall）
def reconstruct_fw_path(next_node: Dict[Any, Dict[Any, Any]], u: Any, v: Any) -> List[Any]:
    if next_node.get(u, {}).get(v) is None:
        return []
    path: List[Any] = [u]
    while u != v:
        u = next_node[u][v]
        path.append(u)
    return path

# ---------------------------------------------------------------------
# BFS（无权图或网格最短路径）
# 适用：无权图或等权网格（每步代价相等）
# 参数：
#   start, goal: 起点与终点
#   neighbors: 函数 node -> list of neighbor nodes（不带权重）
# 返回：
#   (path_list, steps) 或 ([], -1) 若无路径
def bfs(start: Any, goal: Any, neighbors: Callable[[Any], List[Any]]) -> Tuple[List[Any], int]:
    q: deque = deque([start])
    prev: Dict[Any, Any] = {start: None}
    while q:
        u = q.popleft()
        if u == goal:
            break
        for v in neighbors(u):
            if v not in prev:
                prev[v] = u
                q.append(v)
    if goal not in prev:
        return [], -1
    path: List[Any] = []
    u = goal
    while u is not None:
        path.append(u)
        u = prev[u]
    path.reverse()
    return path, len(path) - 1




# ---------------------------------------------------------------------
# Dijkstra
# 适用：非负权图（有向或无向）
# 参数：
#   adj: dict node -> list of (neighbor, weight)
#   start: 起点
# 返回：
#   (dist, prev)
def dijkstra(adj: Dict[Any, List[Tuple[Any, float]]], start: Any) -> Tuple[Dict[Any, float], Dict[Any, Any]]:
    dist: Dict[Any, float] = {start: 0.0}
    prev: Dict[Any, Any] = {}
    pq: List[Tuple[float, Any]] = [(0.0, start)]
    while pq:
        d, u = heapq.heappop(pq)
        if d != dist.get(u, float('inf')):
            continue
        for v, w in adj.get(u, ()):
            nd = d + w
            if nd < dist.get(v, float('inf')):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))
    return dist, prev

# ---------------------------------------------------------------------
# A*
# 适用：有启发式信息（h）且可计算 neighbors 的情形（如网格或带坐标图）
# 参数：
#   start, goal: 起点与终点
#   neighbors: 函数 node -> list of (neighbor, weight)
#   h: 启发式函数 h(node, goal)
# 返回：
#   (path_list, total_cost) 或 ([], inf) 若无路径
def astar(start: Any, goal: Any,
          neighbors: Callable[[Any], List[Tuple[Any, float]]],
          h: Callable[[Any, Any], float]) -> Tuple[List[Any], float]:
    g: Dict[Any, float] = {start: 0.0}
    f: Dict[Any, float] = {start: h(start, goal)}
    prev: Dict[Any, Any] = {}
    open_heap: List[Tuple[float, Any]] = [(f[start], start)]
    closed: set = set()
    while open_heap:
        _, current = heapq.heappop(open_heap)
        if current == goal:
            path = reconstruct_path(prev, start, goal)
            return path, g[goal]
        if current in closed:
            continue
        closed.add(current)
        for nbr, w in neighbors(current):
            tentative_g = g[current] + w
            if tentative_g < g.get(nbr, float('inf')):
                prev[nbr] = current
                g[nbr] = tentative_g
                f[nbr] = tentative_g + h(nbr, goal)
                heapq.heappush(open_heap, (f[nbr], nbr))
    return [], float('inf')

# 通用路径重建（用于 A*、Dijkstra 等 prev 字典）
def reconstruct_path(prev: Dict[Any, Any], start: Any, goal: Any) -> List[Any]:
    path: List[Any] = []
    u = goal
    while u != start:
        path.append(u)
        u = prev.get(u)
        if u is None:
            return []
    path.append(start)
    path.reverse()
    return path

# ---------------------------------------------------------------------
# Bellman-Ford
# 适用：含负权边的图，可检测负权环
# 参数：
#   edges: list of (u, v, w)
#   nodes: 所有节点列表
#   start: 起点
# 返回：
#   (dist, prev)
def bellman_ford(edges: List[Tuple[Any, Any, float]], nodes: List[Any], start: Any) -> Tuple[Dict[Any, float], Dict[Any, Any]]:
    dist: Dict[Any, float] = {node: float('inf') for node in nodes}
    prev: Dict[Any, Any] = {node: None for node in nodes}
    dist[start] = 0.0
    n = len(nodes)
    for _ in range(n - 1):
        updated = False
        for u, v, w in edges:
            if dist[u] + w < dist[v]:
                dist[v] = dist[u] + w
                prev[v] = u
                updated = True
        if not updated:
            break
    for u, v, w in edges:
        if dist[u] + w < dist[v]:
            raise ValueError("Graph contains a negative-weight cycle")
    return dist, prev

# ---------------------------------------------------------------------
# Floyd–Warshall
# 适用：计算任意两点之间最短路径（全对全）
# 参数：
#   nodes: 节点列表
#   weight_fn: 函数 weight_fn(u, v) 返回直接边权（无边返回 float('inf')）
# 返回：
#   (dist, next_node)
def floyd_warshall(nodes: List[Any], weight_fn: Callable[[Any, Any], float]) -> Tuple[Dict[Any, Dict[Any, float]], Dict[Any, Dict[Any, Any]]]:
    dist: Dict[Any, Dict[Any, float]] = {u: {v: weight_fn(u, v) for v in nodes} for u in nodes}
    next_node: Dict[Any, Dict[Any, Any]] = {u: {v: (v if dist[u][v] < float('inf') and u != v else None) for v in nodes} for u in nodes}
    for k in nodes:
        for i in nodes:
            for j in nodes:
                if dist[i][k] + dist[k][j] < dist[i][j]:
                    dist[i][j] = dist[i][k] + dist[k][j]
                    next_node[i][j] = next_node[i][k]
    return dist, next_node

def reconstruct_fw_path(next_node: Dict[Any, Dict[Any, Any]], u: Any, v: Any) -> List[Any]:
    if next_node.get(u, {}).get(v) is None:
        return []
    path: List[Any] = [u]
    while u != v:
        u = next_node[u][v]
        path.append(u)
    return path

# ---------------------------------------------------------------------
# BFS（无权图或网格）
# 适用：无权图或等权网格（每步代价相等）
# 参数：
#   start, goal: 起点与终点
#   neighbors: 函数 node -> list of neighbor nodes（不带权重）
# 返回：
#   (path_list, steps) 或 ([], -1) 若无路径
def bfs(start: Any, goal: Any, neighbors: Callable[[Any], List[Any]]) -> Tuple[List[Any], int]:
    q: deque = deque([start])
    prev: Dict[Any, Any] = {start: None}
    while q:
        u = q.popleft()
        if u == goal:
            break
        for v in neighbors(u):
            if v not in prev:
                prev[v] = u
                q.append(v)
    if goal not in prev:
        return [], -1
    path: List[Any] = []
    u = goal
    while u is not None:
        path.append(u)
        u = prev[u]
    path.reverse()
    return path, len(path) - 1

# ---------------------------------------------------------------------
# 如果作为脚本直接运行，下面给出简短示例（可删去）
if __name__ == "__main__":
    # Dijkstra 示例
    adj = {
        'A': [('B', 2), ('C', 5)],
        'B': [('A', 2), ('C', 1), ('D', 4)],
        'C': [('A', 5), ('B', 1), ('D', 1)],
        'D': [('B', 4), ('C', 1)]
    }
    dist, prev = dijkstra(adj, 'A')
    path_AD = reconstruct_path(prev, 'A', 'D')
    print("Dijkstra A->D:", dist.get('D'), path_AD)

    # A*（网格）示例
    grid = [
        [0,0,0,0],
        [1,1,0,1],
        [0,0,0,0],
        [0,1,1,0]
    ]
    start = (0,0); goal = (3,3)
    def neighbors_grid(pos):
        x,y = pos; H,W = len(grid), len(grid[0])
        res = []
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            nx,ny = x+dx, y+dy
            if 0<=nx<H and 0<=ny<W and grid[nx][ny]==0:
                res.append(((nx,ny), 1.0))
        return res
    def manhattan(a,b):
        return abs(a[0]-b[0]) + abs(a[1]-b[1])
    path, cost = astar(start, goal, neighbors_grid, manhattan)
    print("A* cost, path:", cost, path)

    # Bellman-Ford 示例
    nodes = [0,1,2,3]
    edges = [
        (0,1,5),
        (0,2,3),
        (1,2,-2),
        (2,3,2),
        (1,3,6)
    ]
    dist_bf, prev_bf = bellman_ford(edges, nodes, 0)
    print("Bellman-Ford dist:", dist_bf)

    # Floyd-Warshall 示例
    nodes_fw = ['A','B','C']
    def weight_fn(u,v):
        if u==v: return 0.0
        weights = {('A','B'):3, ('B','C'):4, ('A','C'):10}
        return weights.get((u,v), float('inf'))
    dist_fw, next_node = floyd_warshall(nodes_fw, weight_fn)
    path_ac = reconstruct_fw_path(next_node, 'A', 'C')
    print("Floyd-Warshall A->C:", dist_fw['A']['C'], path_ac)

    # BFS 示例（无权网格）
    grid2 = [
        [0,0,0],
        [0,1,0],
        [0,0,0]
    ]
    start2 = (0,0); goal2 = (2,2)
    def neighbors_unweighted(pos):
        x,y = pos; H,W = len(grid2), len(grid2[0])
        res = []
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            nx,ny = x+dx, y+dy
            if 0<=nx<H and 0<=ny<W and grid2[nx][ny]==0:
                res.append((nx,ny))
        return res
    path2, steps2 = bfs(start2, goal2, neighbors_unweighted)
    print("BFS steps, path:", steps2, path2)


  
