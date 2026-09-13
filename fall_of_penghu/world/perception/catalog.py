from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fall_of_penghu.world.entities.game_object import GameObject
from fall_of_penghu.world.entities.kinds import SHOT_KINDS, is_static_kind

DATA_NAME = "detection.json"
PACKAGE_DATA = Path(__file__).resolve().parents[2] / "data" / DATA_NAME

CHANNELS = ("radar", "visual_primitive", "visual_advanced", "satellite", "lookout")


class DetectionCatalog:
    """Ranges, cover, alerts, and emitters from one JSON table."""

    def __init__(self, data: dict[str, Any]) -> None:
        if data.get("format") != "fall-of-penghu-detection":
            raise ValueError("unexpected detection table format")
        self.raw = data
        cluster = data.get("cluster") or {}
        self.cluster_radius_m = float(cluster.get("radius_m") or 1000.0)
        self.cluster_window_sim_s = float(cluster.get("window_sim_s") or 120.0)
        imprint = data.get("imprint") or {}
        self._fade_default = float(imprint.get("default_fade_sim_s") or 40.0)
        self._fade = {
            str(k): float(v) for k, v in (imprint.get("fade_sim_s") or {}).items()
        }
        self._alerts = data.get("alerts") or {}
        self._detectable = {
            str(k): frozenset(str(c) for c in v)
            for k, v in (data.get("detectable_by") or {}).items()
        }
        self._roles = {str(k): str(v) for k, v in (data.get("cover_role") or {}).items()}
        self._emitters = {
            str(k): tuple(str(c) for c in v)
            for k, v in (data.get("emitters") or {}).items()
        }
        self._emitter_exceptions: dict[str, dict[str, float]] = {}
        for channel, row in (data.get("emitter_exceptions") or {}).items():
            self._emitter_exceptions[str(channel)] = {
                str(k): float(v) for k, v in (row or {}).items()
            }
        self._weapons = data.get("weapons") or {}
        self._channels = data.get("channels") or {}
        self._cover = data.get("cover") or {}
        for channel, rec in self._channels.items():
            row = rec.get("emitter_exceptions") or {}
            if not row:
                continue
            merged = dict(self._emitter_exceptions.get(str(channel)) or {})
            merged.update({str(k): float(v) for k, v in row.items()})
            self._emitter_exceptions[str(channel)] = merged
        self._threat = data.get("threat") or {}
        heat = data.get("heatmap") or {}
        self.heat_cell_m = float(heat.get("cell_m") or 500.0)
        self.heat_half_life_sim_s = float(heat.get("half_life_sim_s") or 180.0)
        self.landing_hot_threshold = float(heat.get("landing_hot_threshold") or 6.0)
        self.landing_cold_weight = float(heat.get("landing_cold_weight") or 0.65)
        self.landing_far_weight = float(heat.get("landing_far_weight") or 0.35)
        self.radar_aa_factor = float(heat.get("radar_aa_factor") or 0.35)
        self.scout_standoff_m = float(heat.get("scout_standoff_m") or 400.0)
        self.scout_reassign_sim_s = float(heat.get("scout_reassign_sim_s") or 180.0)
        self.scout_count = max(1, int(heat.get("scout_count") or 6))
        self.scout_per_day = max(0, int(heat.get("scout_per_day") or 4))
        self.scout_patrol_count = max(0, int(heat.get("scout_patrol_count") or 2))
        self.scout_dusk_tod = float(heat.get("scout_dusk_tod") or (17.0 / 24.0))
        self.drone_lost_sim_s = float(heat.get("drone_lost_sim_s") or 90.0)
        self._heat_splat = heat.get("splat") or {}
        self._landing_weight = heat.get("landing_weight") or {}
        lookout = data.get("lookout") or {}
        self.lookout_simplify_m = float(lookout.get("simplify_m") or 20.0)
        sat = data.get("satellite_windows") or {}
        self.sat_faction = str(sat.get("faction") or "C")
        self.sat_always_day = bool(sat.get("always_day"))
        self.sat_period_s = float(sat.get("period_calendar_s") or 21600.0)
        self.sat_duration_s = float(sat.get("duration_calendar_s") or 3000.0)
        self.sat_offset_s = float(sat.get("offset_calendar_s") or 0.0)
        health = data.get("health") or {}
        self._hp_default = float(health.get("default") or 100.0)
        self._hp_kinds = {
            str(k): float(v) for k, v in (health.get("kinds") or {}).items()
        }
        self.rest_idle_sim_s = float(health.get("rest_idle_sim_s") or 90.0)
        self.heal_full_sim_s = float(health.get("heal_full_sim_s") or 57600.0)
        self.ammo_full_sim_s = float(health.get("ammo_full_sim_s") or 0.0)
        movement = data.get("movement") or {}
        self._move_defaults = movement.get("defaults") or {}
        self._move_kinds = movement.get("kinds") or {}
        offroad = self._move_defaults.get("offroad") or {}
        self._offroad_default = {
            "forest": float(offroad.get("forest") if offroad.get("forest") is not None else 0.3),
            "grass": float(offroad.get("grass") if offroad.get("grass") is not None else 0.7),
            "open": float(offroad.get("open") if offroad.get("open") is not None else 0.9),
        }

    @classmethod
    def load(cls, path: Path | None = None) -> DetectionCatalog:
        src = Path(path) if path is not None else PACKAGE_DATA
        with src.open("r", encoding="utf-8") as fh:
            return cls(json.load(fh))

    def scout_cap(self, day: int) -> int:
        """Day 0 (opening noon) is six scouts; four more each calendar midnight."""
        return max(1, self.scout_count + self.scout_per_day * max(0, int(day)))

    def listed_kinds(self) -> tuple[str, ...]:
        kinds: set[str] = set(self._detectable)
        kinds.update(self._roles)
        kinds.update(self._emitters)
        kinds.update(self._weapons)
        kinds.update(self._move_kinds)
        kinds.update(self._hp_kinds)
        return tuple(sorted(kinds))

    def fade_sim_s(self, kind: str) -> float:
        return float(self._fade.get(kind, self._fade_default))

    def alert_policy(self, kind: str) -> dict[str, bool]:
        rec = self._alerts.get(kind) or self._alerts.get("default") or {}
        return {
            "notify": bool(rec.get("notify")),
            "cluster": bool(rec.get("cluster")),
            "slow_time": bool(rec.get("slow_time")),
        }

    def detectable_by(self, kind: str) -> frozenset[str]:
        return self._detectable.get(
            kind, frozenset(("visual_advanced", "satellite"))
        )

    def cover_role(self, kind: str) -> str:
        return self._roles.get(kind, "ground")

    def emitters(self, kind: str) -> tuple[str, ...]:
        return self._emitters.get(kind, ())

    def engagement_m(self, kind: str) -> float | None:
        rec = self._weapons.get(kind)
        if not rec:
            return None
        return float(rec.get("engagement_m") or 0.0) or None

    def min_engagement_m(self, kind: str) -> float:
        rec = self._weapons.get(kind) or {}
        return max(0.0, float(rec.get("min_engagement_m") or 0.0))

    def must_halt(self, kind: str) -> bool:
        rec = self._weapons.get(kind) or {}
        if rec.get("must_halt") is not None:
            return bool(rec.get("must_halt"))
        return self.min_engagement_m(kind) > 0.0

    def default_doctrine(self, kind: str) -> str:
        rec = self._weapons.get(kind) or {}
        return str(rec.get("doctrine") or "hold")

    def weapon(self, kind: str) -> dict[str, Any]:
        return self._weapons.get(kind) or {}

    def cooldown_sim_s(self, kind: str) -> float:
        return float(self.weapon(kind).get("cooldown_sim_s") or 5.0)

    def clip_size(self, kind: str) -> int:
        return max(0, int(self.weapon(kind).get("clip") or 0))

    def reserve_size(self, kind: str) -> int:
        return max(0, int(self.weapon(kind).get("reserve") or 0))

    def reload_sim_s(self, kind: str) -> float:
        return float(self.weapon(kind).get("reload_sim_s") or 0.0)

    def limited_ammo(self, kind: str) -> bool:
        return self.clip_size(kind) > 0

    def ammo_caption(self, obj: GameObject, now: float) -> str | None:
        """Magazine / reserve, plus reload countdown. None if the kind is unlimited."""
        if not self.limited_ammo(obj.kind):
            return None
        clip = int(getattr(obj, "clip", 0) or 0)
        reserve = int(getattr(obj, "reserve", 0) or 0)
        text = f"{clip}/{reserve}"
        if getattr(obj, "reloading", False):
            left = max(0.0, float(getattr(obj, "weapon_ready_sim", 0.0) or 0.0) - now)
            return f"{text} RLD {left:.0f}s"
        if clip <= 0 and reserve <= 0:
            return f"{text} EMPTY"
        return text

    def max_in_flight(self, kind: str) -> int:
        return int(self.weapon(kind).get("max_in_flight") or 1)

    def engage_mobility(self, kind: str) -> frozenset[str] | None:
        raw = self.weapon(kind).get("engage_mobility")
        if raw is None:
            return None
        return frozenset(str(item) for item in raw)

    def target_branch(self, kind: str) -> str:
        if is_static_kind(kind):
            return "static"
        role = self.cover_role(kind)
        if role == "ground":
            return "land"
        if role in ("air", "sea"):
            return role
        return "land"

    def target_mobility(self, target: GameObject) -> str:
        raw = str(getattr(target, "mobility", "") or "")
        if raw in ("air", "land", "sea"):
            return raw
        if is_static_kind(target.kind):
            return "land"
        branch = self.target_branch(target.kind)
        if branch == "static":
            return "land"
        return branch

    def kind_mobility(self, kind: str) -> str:
        if is_static_kind(kind):
            return "land"
        role = self.cover_role(kind)
        if role == "ground":
            return "land"
        if role in ("air", "sea"):
            return role
        return "land"

    def target_kinds(self) -> tuple[str, ...]:
        kinds = set(self._roles)
        kinds.update(self._detectable)
        kinds -= SHOT_KINDS
        kinds.discard("embark")
        return tuple(sorted(kinds))

    def scatter_m(self, kind: str, dist_m: float) -> float:
        rec = self.weapon(kind)
        lo = float(rec.get("scatter_min_m") or 0.0)
        hi = float(rec.get("scatter_max_m") or 0.0)
        if hi <= 0.0 and lo <= 0.0:
            return 0.0
        min_r = self.min_engagement_m(kind)
        max_r = self.engagement_m(kind) or min_r
        span = max(max_r - min_r, 1.0)
        t = min(1.0, max(0.0, (float(dist_m) - min_r) / span))
        return lo + (hi - lo) * t

    def engage_kinds_for(self, shooter_kind: str) -> frozenset[str]:
        allowed = self.engage_mobility(shooter_kind)
        out: set[str] = set()
        for kind in self.target_kinds():
            mob = self.kind_mobility(kind)
            if allowed is None or mob in allowed:
                out.add(kind)
        return frozenset(out)

    def can_engage(self, shooter_kind: str, target: GameObject) -> bool:
        allowed = self.engage_mobility(shooter_kind)
        if allowed is None:
            return True
        return self.target_mobility(target) in allowed

    def wants_target(self, shooter: GameObject, target: GameObject) -> bool:
        if not self.can_engage(shooter.kind, target):
            return False
        selected = getattr(shooter, "engage_kinds", None)
        if selected is None:
            return True
        return target.kind in selected

    def intercept_speed_mps(self) -> float:
        rec = self._move_kinds.get("intercept") or {}
        if rec.get("speed_mps") is not None:
            return float(rec["speed_mps"])
        return float(self.weapon("intercept").get("speed_mps") or 220.0)

    def speed_mps(self, kind: str) -> float:
        rec = self._move_kinds.get(kind) or {}
        if rec.get("speed_mps") is not None:
            return float(rec["speed_mps"])
        if kind == "intercept":
            return self.intercept_speed_mps()
        return float(self._move_defaults.get("speed_mps") or 10.0)

    def offroad_factor(self, kind: str, cover: str) -> float:
        rec = self._move_kinds.get(kind) or {}
        row = rec.get("offroad") or {}
        if cover in row:
            return float(row[cover])
        if cover in self._offroad_default:
            return float(self._offroad_default[cover])
        return float(self._offroad_default["open"])

    def intercept_kill_m(self) -> float:
        return float(self.weapon("intercept").get("kill_m") or 28.0)

    def intercept_life_sim_s(self) -> float:
        return float(self.weapon("intercept").get("life_sim_s") or 45.0)

    def max_hp(self, kind: str) -> float:
        if kind in self._hp_kinds:
            return float(self._hp_kinds[kind])
        return self._hp_default

    def weapon_ammo(self, kind: str) -> str:
        return str(self.weapon(kind).get("ammo") or "intercept")

    def weapon_damage(self, kind: str) -> float:
        rec = self.weapon(kind)
        if rec.get("damage") is not None:
            return float(rec["damage"])
        if kind == "intercept":
            return 100.0
        return 25.0

    def hit_p0(self, kind: str) -> float:
        return float(self.weapon(kind).get("hit_p0") or 1.0)

    def hit_chance(self, kind: str, dist_m: float) -> float:
        reach = self.engagement_m(kind)
        if reach is None or reach <= 0.0:
            return 0.0
        t = min(1.0, max(0.0, float(dist_m) / reach))
        return max(0.0, self.hit_p0(kind) * (1.0 - t * t))

    def splat(self, kind: str) -> tuple[float, float]:
        row = self._heat_splat.get(kind) or self._heat_splat.get("default") or {}
        weight = float(row.get("weight") if row.get("weight") is not None else 1.0)
        sigma = float(row.get("sigma_m") if row.get("sigma_m") is not None else 400.0)
        return weight, sigma

    def landing_weight(self, kind: str) -> float:
        row = self._landing_weight
        if kind in row:
            return float(row[kind])
        return float(row.get("default") or 1.0)

    def threat(self, shooter_kind: str, target_kind: str) -> float:
        if is_static_kind(target_kind):
            row = self._threat.get(shooter_kind) or {}
            if row.get(target_kind) is not None:
                return float(row[target_kind])
            if row.get("static") is not None:
                return float(row["static"])
            if self._threat.get("static") is not None:
                return float(self._threat["static"])
            return 0.05
        row = self._threat.get(shooter_kind) or {}
        if target_kind in row:
            return float(row[target_kind])
        base = self._threat.get("default") or {}
        if target_kind in base:
            return float(base[target_kind])
        if "default" in row:
            return float(row["default"])
        return float(base.get("default") or 1.0)

    def tracer_speed_mps(self) -> float:
        rec = self._move_kinds.get("tracer") or {}
        if rec.get("speed_mps") is not None:
            return float(rec["speed_mps"])
        return float(self.weapon("tracer").get("speed_mps") or 420.0)

    def tracer_life_sim_s(self) -> float:
        return float(self.weapon("tracer").get("life_sim_s") or 8.0)

    def ammo_speed_mps(self, shooter_kind: str) -> float:
        rec = self.weapon(shooter_kind)
        if rec.get("speed_mps") is not None:
            return float(rec["speed_mps"])
        ammo = self.weapon_ammo(shooter_kind)
        rec_ammo = self.weapon(ammo)
        if rec_ammo.get("speed_mps") is not None:
            return float(rec_ammo["speed_mps"])
        if ammo == "tracer":
            return self.tracer_speed_mps()
        if ammo == "shell":
            return 350.0
        return self.intercept_speed_mps()

    def ammo_life_sim_s(self, shooter_kind: str) -> float:
        rec = self.weapon(shooter_kind)
        if rec.get("life_sim_s") is not None:
            return float(rec["life_sim_s"])
        ammo = self.weapon_ammo(shooter_kind)
        rec_ammo = self.weapon(ammo)
        if rec_ammo.get("life_sim_s") is not None:
            return float(rec_ammo["life_sim_s"])
        if ammo == "tracer":
            return self.tracer_life_sim_s()
        if ammo == "shell":
            return 40.0
        return self.intercept_life_sim_s()

    def blast_m(self, kind: str) -> float:
        return float(self.weapon(kind).get("blast_m") or 0.0)

    def channel(self, name: str) -> dict[str, Any]:
        return self._channels.get(name) or {}

    def day_only(self, channel: str) -> bool:
        return bool(self.channel(channel).get("day_only"))

    def is_global(self, channel: str) -> bool:
        return bool(self.channel(channel).get("global"))

    def range_m(self, channel: str, kind: str) -> float | None:
        rec = self.channel(channel)
        if rec.get("global"):
            return None
        exceptions = rec.get("exceptions") or {}
        if kind in exceptions:
            return float(exceptions[kind])
        raw = rec.get("default_range_m")
        if raw is None:
            return None
        return float(raw)

    def default_range_m(self, channel: str) -> float | None:
        rec = self.channel(channel)
        if rec.get("global"):
            return None
        raw = rec.get("default_range_m")
        if raw is None:
            return None
        return float(raw)

    def emitter_range_m(self, channel: str, emitter_kind: str) -> float | None:
        rec = self.channel(channel)
        if rec.get("global"):
            return None
        row = self._emitter_exceptions.get(channel) or {}
        if emitter_kind in row:
            return float(row[emitter_kind])
        return self.default_range_m(channel)

    def night_factor(self, channel: str, kind: str | None = None) -> float:
        rec = self.channel(channel)
        if kind is not None:
            row = rec.get("night_factor_exceptions") or {}
            if kind in row:
                return max(0.0, float(row[kind]))
        if rec.get("night_factor") is not None:
            return max(0.0, float(rec["night_factor"]))
        return 1.0 if rec.get("day_only") else 0.0

    def darkness_scale(
        self, channel: str, darkness: float, kind: str | None = None
    ) -> float:
        return max(0.0, 1.0 - float(darkness) * self.night_factor(channel, kind))

    def scaled_range_m(
        self,
        channel: str,
        kind: str,
        darkness: float,
        *,
        emitter_kind: str | None = None,
    ) -> float | None:
        target_r = self.range_m(channel, kind)
        if emitter_kind is not None:
            emit_r = self.emitter_range_m(channel, emitter_kind)
            if emit_r is None:
                base = target_r
            elif target_r is None:
                base = emit_r
            else:
                base = min(emit_r, target_r)
        else:
            base = target_r
        if base is None:
            return None
        return base * self.darkness_scale(channel, darkness, kind=kind)

    def cover_factor(self, channel: str, cover: str) -> float:
        row = self._cover.get(channel) or {}
        if cover in row:
            return float(row[cover])
        return float(row.get("open") or 1.0)
