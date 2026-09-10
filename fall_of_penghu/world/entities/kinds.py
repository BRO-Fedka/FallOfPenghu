from __future__ import annotations

STATIC_KINDS = {"port", "airfield", "bridge", "seaport", "airport"}
SHOT_KINDS = frozenset({"intercept", "tracer", "shell"})
SKIP_PLACE = frozenset({*SHOT_KINDS, "seaport", "airport", "embark", "small_arms", "cannon"})

KIND_LABELS: dict[str, str] = {
    "port": "Port",
    "airfield": "Airfield",
    "bridge": "Bridge",
    "aaw": "AAW",
    "aa_pickup": "AA pickup",
    "ship": "Ship",
    "drone": "Drone",
    "scout": "Scout",
    "truck": "Truck",
    "ferry": "Ferry",
    "drone_carrier": "Drone carrier",
    "landing_ship": "Landing ship",
    "infantry": "Infantry",
    "artillery": "Artillery",
    "tank": "Tank",
    "shell": "Shell",
}


def kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, kind.replace("_", " ").title())


def mark_static(kind: str) -> None:
    if kind and kind not in SKIP_PLACE:
        STATIC_KINDS.add(kind)


def is_static_kind(kind: str) -> bool:
    return kind in STATIC_KINDS
