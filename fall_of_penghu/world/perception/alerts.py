from __future__ import annotations

from dataclasses import dataclass, field
from math import hypot

from fall_of_penghu.world.entities.kinds import kind_label
from fall_of_penghu.world.events import ContactNotice
from fall_of_penghu.world.notices import CONTACT
from fall_of_penghu.world.perception.catalog import DetectionCatalog


@dataclass
class _Cluster:
    faction: str
    seed_x: float
    seed_y: float
    opened_sim: float
    ids: set[str] = field(default_factory=set)
    kinds: list[str] = field(default_factory=list)
    slow_time: bool = False


def _label(kinds: list[str]) -> str:
    from fall_of_penghu.shell.i18n import t

    if not kinds:
        return t("notice.contact.any")
    if all(k == kinds[0] for k in kinds):
        name = kind_label(kinds[0])
        n = len(kinds)
        if n == 1:
            return t("notice.contact.one", name=name)
        return t("notice.contact.many", name=name, n=n)
    return t("notice.contact.mixed", n=len(kinds))


class AlertTracker:
    """Hold enters until the cluster window ends, then one notice."""

    def __init__(self, catalog: DetectionCatalog) -> None:
        self._catalog = catalog
        self._open: list[_Cluster] = []

    def on_enter(
        self,
        *,
        faction: str,
        object_id: str,
        kind: str,
        x: float,
        y: float,
        now_sim: float,
    ) -> None:
        policy = self._catalog.alert_policy(kind)
        if not policy["notify"]:
            return
        radius = self._catalog.cluster_radius_m
        if policy["cluster"]:
            for cluster in self._open:
                if cluster.faction != faction:
                    continue
                if hypot(x - cluster.seed_x, y - cluster.seed_y) <= radius:
                    cluster.ids.add(object_id)
                    cluster.kinds.append(kind)
                    cluster.slow_time = cluster.slow_time or policy["slow_time"]
                    return
        self._open.append(
            _Cluster(
                faction=faction,
                seed_x=x,
                seed_y=y,
                opened_sim=now_sim,
                ids={object_id},
                kinds=[kind],
                slow_time=policy["slow_time"],
            )
        )

    def flush(
        self,
        now_sim: float,
        calendar_time: float = 0.0,
        world=None,
    ) -> list[ContactNotice]:
        window = self._catalog.cluster_window_sim_s
        keep: list[_Cluster] = []
        out: list[ContactNotice] = []
        for cluster in self._open:
            if now_sim - cluster.opened_sim < window:
                keep.append(cluster)
                continue
            ids = tuple(sorted(cluster.ids))
            kinds = tuple(cluster.kinds)
            same = bool(kinds) and all(k == kinds[0] for k in kinds)
            icons = _icon_kinds(cluster.kinds, ids, world)
            out.append(
                ContactNotice(
                    faction=cluster.faction,
                    object_ids=ids,
                    x=cluster.seed_x,
                    y=cluster.seed_y,
                    text=_label(cluster.kinds),
                    slow_time=cluster.slow_time,
                    category=CONTACT,
                    filter_kind=kinds[0] if same else None,
                    icon_kinds=icons,
                    calendar_time=calendar_time,
                )
            )
        self._open = keep
        return out


def _icon_kinds(kinds: list[str], ids: tuple[str, ...], world) -> tuple[str, ...]:
    icons = list(dict.fromkeys(kinds))
    if world is None:
        return tuple(icons)
    extra: list[str] = []
    for oid in ids:
        obj = world.entities.get(oid)
        if obj is None or obj.kind != "ferry":
            continue
        cargo_id = getattr(obj, "cargo_id", None)
        cargo = world.entities.get(cargo_id) if cargo_id else None
        if cargo is not None and cargo.kind not in icons and cargo.kind not in extra:
            extra.append(cargo.kind)
    return tuple(icons + extra)
