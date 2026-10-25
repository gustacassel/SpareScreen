"""Shapes of the data SpareScreen passes around, for type checking (plain dicts at runtime).

Most readings go to the page as JSON, so they stay dicts; the ones several modules share
are described here. `Json` is for the looser ones.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, TypedDict

Json = Dict[str, Any]  # a JSON-like dict: what the sources send to the page


class Source(Protocol):
    """Anything the sampler reads once a second (see server.start_sampler)."""

    name: str

    def read(self) -> Any: ...


class Art(TypedDict):
    """URLs of a game's art and icon (images.put), and the store's name for it."""

    art: Optional[str]
    icon: Optional[str]
    name: Optional[str]


class Game(TypedDict, total=False):
    """The running game, as the page gets it (activity.game)."""

    name: str
    source: str  # "library", "mine" or "auto"
    pid: int
    cpu: float
    mem: int
    since: Optional[float]
    art: Optional[str]
    icon: Optional[str]


class Check(TypedDict):
    """One line of the PC window's Status tab."""

    id: str
    status: str  # "ok", "warn", "error" or "info"
    title: str
    detail: str
    action: Optional[Dict[str, str]]  # {"id", "label"} of the button, if any


class FrameSummary(TypedDict):
    """Game FPS over the last seconds (fps.FrameStats)."""

    fps: int
    low1: int
    frametime: float
