"""The last few minutes of a few readings, for the page's small charts.

The page draws CPU, GPU and RAM usage, the CPU and GPU temperatures and the network
speed over the last WINDOW seconds. It adds a point itself every STEP seconds from the
live data; this keeps the same points on the PC so a page that was just opened (or
reloaded) starts with the whole chart instead of an empty one (GET /history). Each point
is the average of the readings since the previous one, so a one-second blip doesn't
make the line jump.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Any, Deque, List, Optional

from .shapes import Json

WINDOW = 5 * 60  # seconds shown
STEP = 2         # seconds between points
# name -> where it is in a snapshot
SERIES = (
    ("cpu", ("system", "cpu", "percent")),
    ("cpu_temp", ("system", "cpu", "temp")),
    ("gpu", ("system", "gpu", "percent")),
    ("gpu_temp", ("system", "gpu", "temp")),
    ("ram", ("system", "ram", "percent")),
    ("net_down", ("system", "net", "down")),
    ("net_up", ("system", "net", "up")),
)


def _value(snapshot: Json, path: tuple[str, ...]) -> Optional[float]:
    node: Any = snapshot
    for key in path:
        node = node.get(key) if isinstance(node, dict) else None
    if isinstance(node, bool) or not isinstance(node, (int, float)):
        return None
    return round(float(node), 1)


class History:
    def __init__(self) -> None:
        self._points: Deque[List[Optional[float]]] = deque()  # [time, value per series]
        self._sums = [0.0] * len(SERIES)  # readings since the last point, to average
        self._counts = [0] * len(SERIES)
        self._lock = threading.Lock()

    def add(self, snapshot: Json) -> None:
        stamp = snapshot.get("time")
        if not isinstance(stamp, (int, float)):
            return
        with self._lock:
            for i, (_, path) in enumerate(SERIES):
                value = _value(snapshot, path)
                if value is not None:
                    self._sums[i] += value
                    self._counts[i] += 1
            if self._points and stamp - (self._points[-1][0] or 0) < STEP:
                return
            point: List[Optional[float]] = [round(stamp, 1)]
            point += [round(total / count, 1) if count else None for total, count in zip(self._sums, self._counts)]
            self._sums, self._counts = [0.0] * len(SERIES), [0] * len(SERIES)
            self._points.append(point)
            while self._points and (self._points[0][0] or 0) < stamp - WINDOW:
                self._points.popleft()

    def read(self) -> Json:
        with self._lock:
            return {"window": WINDOW, "step": STEP, "series": [name for name, _ in SERIES],
                    "points": [list(p) for p in self._points]}
