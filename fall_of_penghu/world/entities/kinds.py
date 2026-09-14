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
    from fall_of_penghu.shell.i18n import t

    fallback = KIND_LABELS.get(kind, kind.replace("_", " ").title())
    return t(f"kind.{kind}", default=fallback)


def localized_name(kind: str, name: str) -> str:
    """Swap the English kind word in a stored name for the current language."""
    en = KIND_LABELS.get(kind)
    if not en:
        return name
    label = kind_label(kind)
    if name == en:
        return label
    prefix = f"{en} "
    if name.startswith(prefix):
        return label + name[len(en) :]
    return name


def mark_static(kind: str) -> None:
    if kind and kind not in SKIP_PLACE:
        STATIC_KINDS.add(kind)


def is_static_kind(kind: str) -> bool:
    return kind in STATIC_KINDS
