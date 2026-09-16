from __future__ import annotations

import math

Point = tuple[float, float]  # (lat, lon)

EARTH_R = 6_371_000.0


def haversine(a: Point, b: Point) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(h))


def point_in_ring(p: Point, ring: list[Point]) -> bool:
    lat, lon = p
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        yi, xi = ring[i]
        yj, xj = ring[j]
        if (yi > lat) != (yj > lat):
            x_cross = (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
            if lon < x_cross:
                inside = not inside
        j = i
    return inside


def _seg_distance(p: Point, a: Point, b: Point) -> float:
    # Локальная равнопромежуточная проекция, достаточно точна на масштабе кампуса
    k = math.cos(math.radians(p[0]))
    px, py = p[1] * k, p[0]
    ax, ay = a[1] * k, a[0]
    bx, by = b[1] * k, b[0]
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    cx, cy = ax + t * dx, ay + t * dy
    return haversine(p, (cy, cx / k))


def distance_to_rings(p: Point, rings: list[list[Point]]) -> float:
    """0, если точка внутри любого кольца, иначе расстояние до ближайшей границы в метрах."""
    if not rings:
        return float("inf")
    if any(point_in_ring(p, r) for r in rings if len(r) >= 3):
        return 0.0
    best = float("inf")
    for ring in rings:
        for i in range(len(ring) - 1):
            best = min(best, _seg_distance(p, ring[i], ring[i + 1]))
    return best


def stitch_ways(ways: list[list[Point]]) -> list[list[Point]]:
    """Склеивает внешние линии мультиполигона OSM в замкнутые кольца."""
    pending = [list(w) for w in ways if len(w) >= 2]
    rings: list[list[Point]] = []
    while pending:
        ring = pending.pop(0)
        changed = True
        while ring[0] != ring[-1] and changed:
            changed = False
            for i, w in enumerate(pending):
                if w[0] == ring[-1]:
                    ring += w[1:]
                elif w[-1] == ring[-1]:
                    ring += list(reversed(w))[1:]
                elif w[-1] == ring[0]:
                    ring = w[:-1] + ring
                elif w[0] == ring[0]:
                    ring = list(reversed(w))[:-1] + ring
                else:
                    continue
                pending.pop(i)
                changed = True
                break
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        if len(ring) >= 4:
            rings.append(ring)
    return rings


def bbox_diag(rings: list[list[Point]]) -> float:
    pts = [p for r in rings for p in r]
    if not pts:
        return 0.0
    lats = [p[0] for p in pts]
    lons = [p[1] for p in pts]
    return haversine((min(lats), min(lons)), (max(lats), max(lons)))


def centroid(rings: list[list[Point]]) -> Point | None:
    pts = [p for r in rings for p in r]
    if not pts:
        return None
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
