from __future__ import annotations

from collections import deque
from typing import Any

from fall_of_penghu.ai.heatmap import BeachPick, Ember
from fall_of_penghu.camera import Camera
from fall_of_penghu.chat import ChatLog, ChatMessage
from fall_of_penghu.world.notices import color_for
from fall_of_penghu.world.entities.dynamic import DynamicObject
from fall_of_penghu.world.entities.game_object import GameObject
from fall_of_penghu.world.entities.intercept import TRAIL_MAX, Intercept
from fall_of_penghu.world.entities.kinds import SHOT_KINDS, is_static_kind
from fall_of_penghu.world.entities.route import Route
from fall_of_penghu.world.entities.static import StaticObject
from fall_of_penghu.world.entities.tracer import Tracer
from fall_of_penghu.world.entities.transport import CrossingJob
from fall_of_penghu.world.map_bake import fingerprint
from fall_of_penghu.world.perception.alerts import _Cluster
from fall_of_penghu.world.perception.imprint import ContactImprint
from fall_of_penghu.world.world import World

FORMAT = "fall-of-penghu-slot"
VERSION = 1

_EXTRAS = ("role", "sweep_k", "patrol_xy", "patrol_slot", "plan_sim")


def _load_kills(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for kind, n in raw.items():
        count = int(n)
        if count > 0:
            out[str(kind)] = count
    return out


def dump_match(match) -> dict[str, Any]:
    world: World = match.world
    return {
        "format": FORMAT,
        "version": VERSION,
        "fingerprint": fingerprint(world),
        "clock_label": world.clock.clock_label(),
        "seed": world.seed,
        "forgotten_ids": sorted(world.entities.forgotten_ids),
        "clock": _dump_clock(world.clock),
        "objects": [_dump_object(obj) for obj in world.entities.items],
        "transport": _dump_transport(world.transport),
        "control": {str(iid): fac for iid, fac in world.control.owner.items()},
        "combat": _dump_combat(world.combat),
        "perception": _dump_perception(world.perception),
        "china": _dump_china(match.china),
        "camera": _dump_camera(match.camera),
        "kills": dict(world.kills),
        "defeat": None
        if world.defeat is None
        else {"held_s": world.defeat.held_s, "kills": dict(world.defeat.kills)},
        "control_landings": [list(row) for row in world.control._landings],
        "chat": [
            {
                "text": msg.text,
                "object_ids": list(msg.object_ids),
                "x": msg.x,
                "y": msg.y,
                "category": msg.category,
                "calendar_time": msg.calendar_time,
                "sat_down": msg.sat_down,
                "icon_kinds": list(msg.icon_kinds),
            }
            for msg in match.chat.messages
        ],
    }


def apply_world(world: World, data: dict[str, Any]) -> None:
    if data.get("format") != FORMAT or data.get("version") != VERSION:
        raise ValueError("unsupported save format")
    if data.get("fingerprint") != fingerprint(world):
        raise ValueError("save does not match this map")
    world.seed = int(data.get("seed") or 0)
    _apply_clock(world.clock, data.get("clock") or {})
    objects = [_load_object(rec) for rec in data.get("objects") or []]
    world.entities.replace_saved(
        objects, {str(oid) for oid in data.get("forgotten_ids") or []}
    )
    _apply_transport(world.transport, data.get("transport") or {})
    world.control.owner = {
        int(iid): str(fac) for iid, fac in (data.get("control") or {}).items()
    }
    world.control._ready = True
    world.control._landings = {
        (int(row[0]), int(row[1]))
        for row in data.get("control_landings") or []
        if isinstance(row, (list, tuple)) and len(row) >= 2
    }
    _apply_combat(world.combat, data.get("combat") or {})
    _apply_perception(world.perception, data.get("perception") or {})
    world.kills = _load_kills(data.get("kills"))
    raw = data.get("defeat")
    if raw:
        from fall_of_penghu.world.victory import DefeatReport

        world.defeat = DefeatReport(
            held_s=float(raw.get("held_s") or 0.0),
            kills=_load_kills(raw.get("kills") or world.kills),
        )
    else:
        world.defeat = None


def apply_china(china, data: dict[str, Any]) -> None:
    if not data:
        return
    intel = china.intel
    air = china.air
    naval = china.naval
    ground = china.ground
    intel.assault = _load_beach(data.get("assault"))
    intel._scout_n = int(data.get("scout_n") or 0)
    intel._scout_ready_sim = float(data.get("scout_ready_sim") or 0.0)
    intel._progress = {int(k): int(v) for k, v in (data.get("progress") or {}).items()}
    intel._alive = {str(oid) for oid in data.get("alive") or []}
    intel._jobs = {str(k): dict(v) for k, v in (data.get("jobs") or {}).items()}
    intel._orphans = [dict(row) for row in data.get("orphans") or []]
    intel._kills = [tuple(row) for row in data.get("kills") or []]
    intel._pose = {str(k): (float(v[0]), float(v[1])) for k, v in (data.get("pose") or {}).items()}
    intel._now = float(data.get("now") or 0.0)
    intel._block_sim = float(data.get("block_sim") or -1e9)
    intel._scout_i = int(data.get("scout_i") or 0)
    intel._book_sim = float(data.get("book_sim") or -1e9)
    intel._rings = [tuple(row) for row in data.get("rings") or []]
    intel._posts = [(float(x), float(y)) for x, y in data.get("posts") or []]
    intel._loop = tuple((float(x), float(y)) for x, y in data.get("loop") or [])
    intel._claimed = {str(k): str(v) for k, v in (data.get("claimed") or {}).items()}
    heat = intel.heat
    heat.embers = {
        str(k): Ember(
            source_id=str(row["source_id"]),
            kind=str(row["kind"]),
            x=float(row["x"]),
            y=float(row["y"]),
            last_sim=float(row["last_sim"]),
        )
        for k, row in (data.get("embers") or {}).items()
    }
    heat._ember_sig = None
    forest = intel.forest
    forest._mark_sim = float(data.get("forest_mark_sim") or -1e9)
    _restore_forest(forest, data.get("forest") or {})
    air._drone_n = int(data.get("drone_n") or 0)
    air._carrier_n = int(data.get("carrier_n") or 0)
    air._drone_i = int(data.get("drone_i") or 0)
    air._no_tgt_log = float(data.get("no_tgt_log") or 0.0)
    if data.get("air_rng") is not None:
        _load_rng(air._rng, data["air_rng"])
    naval._ship_seq = int(data.get("ship_seq") or 0)
    naval._next_ship_sim = float(data.get("next_ship_sim") or 0.0)
    naval._ferry_n = int(data.get("naval_ferry_n") or 0)
    naval._cargo_n = int(data.get("cargo_n") or 0)
    naval._beach_i = int(data.get("beach_i") or 0)
    naval._occupy_sim = {int(k): float(v) for k, v in (data.get("occupy_sim") or {}).items()}
    naval._occupy_ids = {str(oid) for oid in data.get("occupy_ids") or []}
    naval._occupy_due = {int(k): float(v) for k, v in (data.get("occupy_due") or {}).items()}
    naval._occupy_i = int(data.get("occupy_i") or 0)
    naval._hop_i = int(data.get("naval_hop_i") or 0)
    naval._ship_i = int(data.get("ship_i") or 0)
    naval._reload_sim = float(data.get("reload_sim") or -1e9)
    naval.axis = str(data.get("axis") or "west")
    ground._hops = {
        str(k): (float(v[0]), float(v[1])) for k, v in (data.get("hops") or {}).items()
    }
    ground._hop_dest = {str(k): int(v) for k, v in (data.get("hop_dest") or {}).items()}
    ground._assign_due = {int(k): float(v) for k, v in (data.get("assign_due") or {}).items()}
    ground._assign_i = int(data.get("assign_i") or 0)
    ground._repath_i = int(data.get("repath_i") or 0)


def apply_camera(camera: Camera, data: dict[str, Any]) -> None:
    if not data:
        return
    camera.x = float(data["x"])
    camera.y = float(data["y"])
    camera.view_width_m = float(data["view_width_m"])
    camera.target_x = camera.x
    camera.target_y = camera.y
    camera.target_view_width_m = camera.view_width_m
    camera.radar_mode = bool(data.get("radar_mode"))
    camera.debug_mode = bool(data.get("debug_mode"))
    camera.flying = False


def apply_chat(chat: ChatLog, rows: list[dict[str, Any]]) -> None:
    chat.messages = [
        ChatMessage(
            text=str(row["text"]),
            object_ids=tuple(str(oid) for oid in row.get("object_ids") or ()),
            x=float(row["x"]),
            y=float(row["y"]),
            category=str(row.get("category") or "contact"),
            calendar_time=float(row.get("calendar_time") or 0.0),
            color=color_for(
                str(row.get("category") or "contact"),
                sat_down=bool(row.get("sat_down")),
            ),
            sat_down=bool(row.get("sat_down")),
            born=0.0,
            icon_kinds=tuple(str(kind) for kind in row.get("icon_kinds") or ()),
        )
        for row in rows
    ]


def _dump_clock(clock) -> dict[str, Any]:
    return {
        "k": clock.k,
        "speed": clock.speed,
        "resume_speed": clock._resume_speed,
        "wall_time": clock.wall_time,
        "simulation_time": clock.simulation_time,
        "calendar_time": clock.calendar_time,
    }


def _apply_clock(clock, data: dict[str, Any]) -> None:
    if not data:
        return
    clock.k = float(data.get("k") or clock.k)
    resume = float(data.get("resume_speed") or data.get("speed") or 1.0)
    if resume <= 0.0:
        resume = 1.0
    clock.wall_time = float(data.get("wall_time") or 0.0)
    clock.simulation_time = float(data.get("simulation_time") or 0.0)
    clock.calendar_time = float(data.get("calendar_time") or clock.calendar_time)
    clock.dt_wall = 0.0
    clock.dt_sim = 0.0
    clock.dt_calendar = 0.0
    clock.set_speed(resume)


def _dump_object(obj: GameObject) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "id": obj.id,
        "faction": obj.faction,
        "kind": obj.kind,
        "name": obj.name,
        "x": obj.x,
        "y": obj.y,
        "heading": obj.heading,
        "active": obj.active,
        "orient_icon": obj.orient_icon,
        "orient_radar": obj.orient_radar,
        "hp": obj.hp,
        "max_hp": obj.max_hp,
        "ferries": obj.ferries,
        "last_hurt_sim": obj.last_hurt_sim,
    }
    if isinstance(obj, DynamicObject):
        rec.update(
            {
                "speed_mps": obj.speed_mps,
                "mobility": obj.mobility,
                "ground": obj.ground,
                "ground_id": obj.ground_id,
                "doctrine": obj.doctrine,
                "weapon_ready_sim": obj.weapon_ready_sim,
                "clip": obj.clip,
                "reserve": obj.reserve,
                "reloading": obj.reloading,
                "last_moved_sim": obj.last_moved_sim,
                "rest_ammo_acc": obj.rest_ammo_acc,
                "cargo_id": obj.cargo_id,
                "strike_id": obj.strike_id,
                "armed": obj.armed,
                "engage_kinds": None if obj.engage_kinds is None else sorted(obj.engage_kinds),
                "engage_kinds_saved": (
                    None
                    if obj.engage_kinds_saved is None
                    else sorted(obj.engage_kinds_saved)
                ),
                "aim_xy": list(obj.aim_xy) if obj.aim_xy is not None else None,
                "focus_ids": sorted(obj.focus_ids),
                "magazine": obj.magazine,
                "stowed": obj.stowed,
                "docked": obj.docked,
                "home_port_id": obj.home_port_id,
                "xfer": obj.xfer,
                "xfer_frac": obj.xfer_frac,
                "task": obj.task,
                "ammo_note": obj.ammo_note,
                "route": _dump_route(obj.route),
            }
        )
        extras = {}
        for name in _EXTRAS:
            if hasattr(obj, name):
                extras[name] = _json(getattr(obj, name))
        if extras:
            rec["extras"] = extras
    if isinstance(obj, Intercept):
        rec["shot"] = {
            "type": "intercept",
            "shooter_id": obj.shooter_id,
            "target_id": obj.target_id,
            "kill_m": obj.kill_m,
            "born_sim": obj.born_sim,
            "life_sim_s": obj.life_sim_s,
            "damage": obj.damage,
            "trail": list(obj.trail),
        }
    elif isinstance(obj, Tracer):
        rec["shot"] = {
            "type": obj.kind,
            "shooter_id": obj.shooter_id,
            "target_id": obj.target_id,
            "aim_x": obj.aim_x,
            "aim_y": obj.aim_y,
            "will_hit": obj.will_hit,
            "damage": obj.damage,
            "born_sim": obj.born_sim,
            "life_sim_s": obj.life_sim_s,
            "blast_m": obj.blast_m,
            "from_x": obj.from_x,
            "from_y": obj.from_y,
            "mark_x": obj.mark_x,
            "mark_y": obj.mark_y,
            "scatter_m": obj.scatter_m,
        }
    return rec


def _load_object(rec: dict[str, Any]) -> GameObject:
    kind = str(rec["kind"])
    shot = rec.get("shot") or {}
    if kind == "intercept" or shot.get("type") == "intercept":
        obj: DynamicObject = Intercept(
            id=str(rec["id"]),
            faction=str(rec["faction"]),
            x=float(rec["x"]),
            y=float(rec["y"]),
            heading=float(rec.get("heading") or 0.0),
            speed_mps=float(rec.get("speed_mps") or 1.0),
            shooter_id=str(shot.get("shooter_id") or ""),
            target_id=str(shot.get("target_id") or ""),
            kill_m=float(shot.get("kill_m") or 0.0),
            born_sim=float(shot.get("born_sim") or 0.0),
            life_sim_s=float(shot.get("life_sim_s") or 0.0),
            damage=float(shot.get("damage") or 100.0),
        )
        obj.trail = deque(
            ((float(x), float(y)) for x, y in shot.get("trail") or []),
            maxlen=TRAIL_MAX,
        )
        _fill_dynamic(obj, rec)
        return obj
    if kind in SHOT_KINDS:
        obj = Tracer(
            id=str(rec["id"]),
            faction=str(rec["faction"]),
            x=float(rec["x"]),
            y=float(rec["y"]),
            heading=float(rec.get("heading") or 0.0),
            speed_mps=float(rec.get("speed_mps") or 1.0),
            shooter_id=str(shot.get("shooter_id") or ""),
            target_id=str(shot.get("target_id") or ""),
            aim_x=float(shot.get("aim_x") or rec["x"]),
            aim_y=float(shot.get("aim_y") or rec["y"]),
            will_hit=bool(shot.get("will_hit")),
            damage=float(shot.get("damage") or 0.0),
            born_sim=float(shot.get("born_sim") or 0.0),
            life_sim_s=float(shot.get("life_sim_s") or 0.0),
            kind=kind,
            blast_m=float(shot.get("blast_m") or 0.0),
            from_x=shot.get("from_x"),
            from_y=shot.get("from_y"),
            mark_x=shot.get("mark_x"),
            mark_y=shot.get("mark_y"),
            scatter_m=float(shot.get("scatter_m") or 0.0),
        )
        _fill_dynamic(obj, rec)
        return obj
    if is_static_kind(kind):
        obj_s = StaticObject(
            id=str(rec["id"]),
            faction=str(rec["faction"]),
            kind=kind,
            name=str(rec["name"]),
            x=float(rec["x"]),
            y=float(rec["y"]),
            heading=float(rec.get("heading") or 0.0),
            active=bool(rec.get("active", True)),
        )
        _fill_base(obj_s, rec)
        return obj_s
    obj = DynamicObject(
        id=str(rec["id"]),
        faction=str(rec["faction"]),
        kind=kind,
        name=str(rec["name"]),
        x=float(rec["x"]),
        y=float(rec["y"]),
        heading=float(rec.get("heading") or 0.0),
        active=bool(rec.get("active", True)),
        speed_mps=float(rec.get("speed_mps") or 10.0),
        mobility=str(rec.get("mobility") or "land"),
    )
    _fill_dynamic(obj, rec)
    return obj


def _fill_base(obj: GameObject, rec: dict[str, Any]) -> None:
    obj.orient_icon = bool(rec.get("orient_icon", obj.orient_icon))
    obj.orient_radar = bool(rec.get("orient_radar", obj.orient_radar))
    obj.hp = float(rec.get("hp", obj.hp))
    obj.max_hp = float(rec.get("max_hp", obj.max_hp))
    obj.ferries = int(rec.get("ferries") or 0)
    obj.last_hurt_sim = float(rec.get("last_hurt_sim") or 0.0)


def _fill_dynamic(obj: DynamicObject, rec: dict[str, Any]) -> None:
    _fill_base(obj, rec)
    obj.speed_mps = float(rec.get("speed_mps", obj.speed_mps))
    obj.mobility = str(rec.get("mobility") or obj.mobility)
    obj.ground = rec.get("ground")
    gid = rec.get("ground_id")
    obj.ground_id = gid if gid is None or isinstance(gid, int) else (
        int(gid) if str(gid).lstrip("-").isdigit() else str(gid)
    )
    obj.doctrine = str(rec.get("doctrine") or obj.doctrine)
    obj.weapon_ready_sim = float(rec.get("weapon_ready_sim") or 0.0)
    obj.clip = int(rec.get("clip") or 0)
    obj.reserve = int(rec.get("reserve") or 0)
    obj.reloading = bool(rec.get("reloading"))
    obj.last_moved_sim = float(rec.get("last_moved_sim") or 0.0)
    obj.rest_ammo_acc = float(rec.get("rest_ammo_acc") or 0.0)
    obj.cargo_id = rec.get("cargo_id")
    obj.strike_id = rec.get("strike_id")
    obj.armed = bool(rec.get("armed"))
    kinds = rec.get("engage_kinds")
    obj.engage_kinds = None if kinds is None else frozenset(str(k) for k in kinds)
    saved = rec.get("engage_kinds_saved")
    obj.engage_kinds_saved = None if saved is None else frozenset(str(k) for k in saved)
    aim = rec.get("aim_xy")
    obj.aim_xy = None if aim is None else (float(aim[0]), float(aim[1]))
    obj.focus_ids = frozenset(str(oid) for oid in rec.get("focus_ids") or ())
    obj.magazine = int(rec.get("magazine") or 0)
    obj.stowed = bool(rec.get("stowed"))
    obj.docked = bool(rec.get("docked"))
    obj.home_port_id = rec.get("home_port_id")
    obj.xfer = rec.get("xfer")
    obj.xfer_frac = float(rec.get("xfer_frac") or 0.0)
    obj.task = str(rec.get("task") or "")
    note = rec.get("ammo_note")
    obj.ammo_note = None if note is None else str(note)
    obj.route = _load_route(rec.get("route"))
    for name, value in (rec.get("extras") or {}).items():
        setattr(obj, name, _from_json(value))


def _dump_route(route: Route | None) -> dict[str, Any] | None:
    if route is None:
        return None
    return {
        "points": [list(pt) for pt in route.points],
        "s": route.s,
        "bridges": [[a, b, oid] for a, b, oid in route.bridges],
    }


def _load_route(data: dict[str, Any] | None) -> Route | None:
    if not data:
        return None
    points = [(float(x), float(y)) for x, y in data.get("points") or []]
    if len(points) < 2:
        return None
    return Route(
        points=points,
        s=float(data.get("s") or 0.0),
        bridges=[
            (float(a), float(b), str(oid)) for a, b, oid in data.get("bridges") or []
        ],
    )


def _dump_transport(transport) -> dict[str, Any]:
    return {
        "jobs": [_dump_job(job) for job in transport._jobs],
        "recalls": [list(pair) for pair in transport._recalls],
        "cargo_resume": {
            cid: list(xy) for cid, xy in transport._cargo_resume.items()
        },
        "ferry_n": transport._ferry_n,
    }


def _apply_transport(transport, data: dict[str, Any]) -> None:
    transport._jobs = [_load_job(row) for row in data.get("jobs") or []]
    transport._recalls = [
        (str(a), str(b)) for a, b in data.get("recalls") or []
    ]
    transport._cargo_resume = {
        str(k): (float(v[0]), float(v[1]))
        for k, v in (data.get("cargo_resume") or {}).items()
    }
    transport._ferry_n = int(data.get("ferry_n") or 0)


def _dump_job(job: CrossingJob) -> dict[str, Any]:
    return {
        "cargo_id": job.cargo_id,
        "ferry_id": job.ferry_id,
        "dest": None if job.dest is None else list(job.dest),
        "drop": list(job.drop),
        "home_port_id": job.home_port_id,
        "dest_port_id": job.dest_port_id,
        "pickup": list(job.pickup),
        "ferry_meet": list(job.ferry_meet),
        "drop_meet": list(job.drop_meet),
        "phase": job.phase,
        "wait_until": job.wait_until,
        "beach_load": job.beach_load,
        "beach_drop": job.beach_drop,
        "auto": job.auto,
        "wait_sim": job.wait_sim,
        "hold_shore": job.hold_shore,
        "stage": None if job.stage is None else list(job.stage),
    }


def _load_job(row: dict[str, Any]) -> CrossingJob:
    dest = row.get("dest")
    stage = row.get("stage")
    return CrossingJob(
        cargo_id=str(row["cargo_id"]),
        ferry_id=str(row["ferry_id"]),
        dest=None if dest is None else (float(dest[0]), float(dest[1])),
        drop=(float(row["drop"][0]), float(row["drop"][1])),
        home_port_id=str(row["home_port_id"]),
        dest_port_id=None if row.get("dest_port_id") is None else str(row["dest_port_id"]),
        pickup=(float(row["pickup"][0]), float(row["pickup"][1])),
        ferry_meet=(float(row["ferry_meet"][0]), float(row["ferry_meet"][1])),
        drop_meet=(float(row["drop_meet"][0]), float(row["drop_meet"][1])),
        phase=str(row["phase"]),
        wait_until=float(row.get("wait_until") or 0.0),
        beach_load=bool(row.get("beach_load")),
        beach_drop=bool(row.get("beach_drop")),
        auto=bool(row.get("auto", True)),
        wait_sim=row.get("wait_sim"),
        hold_shore=bool(row.get("hold_shore")),
        stage=None if stage is None else (float(stage[0]), float(stage[1])),
    )


def _dump_combat(combat) -> dict[str, Any]:
    return {"seq": combat._seq, "rng": _dump_rng(combat._rng)}


def _apply_combat(combat, data: dict[str, Any]) -> None:
    combat._seq = int(data.get("seq") or 0)
    if data.get("rng") is not None:
        _load_rng(combat._rng, data["rng"])


def _dump_perception(perception) -> dict[str, Any]:
    return {
        "imprints": {
            fac: [_dump_imprint(mark) for mark in marks]
            for fac, marks in perception._imprints.items()
        },
        "prev_ids": {
            fac: sorted(ids) for fac, ids in perception._prev_ids.items()
        },
        "imprint_n": perception._imprint_n,
        "china_held": sorted(perception.china_held),
        "china_wall": perception._china_wall,
        "alerts": [
            {
                "faction": row.faction,
                "seed_x": row.seed_x,
                "seed_y": row.seed_y,
                "opened_sim": row.opened_sim,
                "ids": sorted(row.ids),
                "kinds": list(row.kinds),
                "slow_time": row.slow_time,
            }
            for row in perception.alerts._open
        ],
        "sat_was": perception._sat_was,
        "spotted": [list(row) for row in perception._spotted],
    }


def _apply_perception(perception, data: dict[str, Any]) -> None:
    perception._imprints = {
        fac: [_load_imprint(row) for row in rows]
        for fac, rows in (data.get("imprints") or {}).items()
    }
    for fac in list(perception._visible):
        perception._imprints.setdefault(fac, [])
    perception._prev_ids = {
        fac: {str(oid) for oid in ids}
        for fac, ids in (data.get("prev_ids") or {}).items()
    }
    for fac in list(perception._visible):
        perception._prev_ids.setdefault(fac, set())
    perception._imprint_n = int(data.get("imprint_n") or 0)
    perception.china_held = {int(iid) for iid in data.get("china_held") or []}
    perception._china_wall = float(data.get("china_wall") or -1e9)
    perception._pose = {}
    perception._pose_n = 0
    perception._live_ids = set()
    perception._stowed = {}
    sat_was = data.get("sat_was")
    perception._sat_was = None if sat_was is None else bool(sat_was)
    perception._spotted = {
        (str(row[0]), str(row[1]))
        for row in data.get("spotted") or []
        if isinstance(row, (list, tuple)) and len(row) >= 2
    }
    perception.alerts._open = [
        _Cluster(
            faction=str(row["faction"]),
            seed_x=float(row["seed_x"]),
            seed_y=float(row["seed_y"]),
            opened_sim=float(row["opened_sim"]),
            ids={str(oid) for oid in row.get("ids") or []},
            kinds=[str(k) for k in row.get("kinds") or []],
            slow_time=bool(row.get("slow_time")),
        )
        for row in data.get("alerts") or []
    ]


def _dump_imprint(mark: ContactImprint) -> dict[str, Any]:
    return {
        "id": mark.id,
        "source_id": mark.source_id,
        "faction": mark.faction,
        "kind": mark.kind,
        "name": mark.name,
        "x": mark.x,
        "y": mark.y,
        "heading": mark.heading,
        "born_sim": mark.born_sim,
        "fade_sim_s": mark.fade_sim_s,
        "moving": mark.moving,
        "trail": [list(pt) for pt in mark.trail],
        "orient_radar": mark.orient_radar,
        "active": mark.active,
        "permanent": mark.permanent,
    }


def _load_imprint(row: dict[str, Any]) -> ContactImprint:
    return ContactImprint(
        id=str(row["id"]),
        source_id=str(row["source_id"]),
        faction=str(row["faction"]),
        kind=str(row["kind"]),
        name=str(row["name"]),
        x=float(row["x"]),
        y=float(row["y"]),
        heading=float(row.get("heading") or 0.0),
        born_sim=float(row.get("born_sim") or 0.0),
        fade_sim_s=float(row.get("fade_sim_s") or 0.0),
        moving=bool(row.get("moving")),
        trail=tuple((float(x), float(y)) for x, y in row.get("trail") or []),
        orient_radar=bool(row.get("orient_radar")),
        active=bool(row.get("active", True)),
        permanent=bool(row.get("permanent")),
    )


def _dump_china(china) -> dict[str, Any]:
    intel = china.intel
    air = china.air
    naval = china.naval
    ground = china.ground
    assault = intel.assault
    return {
        "assault": None
        if assault is None
        else {
            "island": assault.island,
            "x": assault.x,
            "y": assault.y,
            "landing": assault.landing,
            "cost": assault.cost,
            "n_land": assault.n_land,
            "inhabited": assault.inhabited,
        },
        "scout_n": intel._scout_n,
        "scout_ready_sim": intel._scout_ready_sim,
        "progress": {str(k): v for k, v in intel._progress.items()},
        "alive": sorted(intel._alive),
        "jobs": intel._jobs,
        "orphans": intel._orphans,
        "kills": [list(row) for row in intel._kills],
        "pose": {k: list(v) for k, v in intel._pose.items()},
        "now": intel._now,
        "block_sim": intel._block_sim,
        "scout_i": intel._scout_i,
        "book_sim": intel._book_sim,
        "rings": [list(row) for row in intel._rings],
        "posts": [list(pt) for pt in intel._posts],
        "loop": [list(pt) for pt in intel._loop],
        "claimed": intel._claimed,
        "embers": {
            sid: {
                "source_id": ember.source_id,
                "kind": ember.kind,
                "x": ember.x,
                "y": ember.y,
                "last_sim": ember.last_sim,
            }
            for sid, ember in intel.heat.embers.items()
        },
        "forest_mark_sim": intel.forest._mark_sim,
        "forest": {
            "seen": {str(k): list(v) for k, v in intel.forest.seen.items()},
            "ever": {str(k): list(v) for k, v in intel.forest.ever.items()},
            "air_blocked": {
                str(k): list(v) for k, v in intel.forest.air_blocked.items()
            },
        },
        "drone_n": air._drone_n,
        "carrier_n": air._carrier_n,
        "drone_i": air._drone_i,
        "no_tgt_log": float(getattr(air, "_no_tgt_log", 0.0) or 0.0),
        "air_rng": _dump_rng(air._rng),
        "ship_seq": naval._ship_seq,
        "next_ship_sim": naval._next_ship_sim,
        "naval_ferry_n": naval._ferry_n,
        "cargo_n": naval._cargo_n,
        "beach_i": naval._beach_i,
        "occupy_sim": {str(k): v for k, v in naval._occupy_sim.items()},
        "occupy_ids": sorted(naval._occupy_ids),
        "occupy_due": {str(k): v for k, v in naval._occupy_due.items()},
        "occupy_i": naval._occupy_i,
        "naval_hop_i": naval._hop_i,
        "ship_i": naval._ship_i,
        "reload_sim": naval._reload_sim,
        "axis": naval.axis,
        "hops": {k: list(v) for k, v in ground._hops.items()},
        "hop_dest": ground._hop_dest,
        "assign_due": {str(k): v for k, v in ground._assign_due.items()},
        "assign_i": ground._assign_i,
        "repath_i": ground._repath_i,
    }


def _load_beach(row: dict[str, Any] | None) -> BeachPick | None:
    if not row:
        return None
    return BeachPick(
        island=int(row["island"]),
        x=float(row["x"]),
        y=float(row["y"]),
        landing=float(row["landing"]),
        cost=float(row["cost"]),
        n_land=int(row["n_land"]),
        inhabited=bool(row["inhabited"]),
    )


def _restore_forest(forest, data: dict[str, Any]) -> None:
    for name in ("seen", "ever", "air_blocked"):
        src = data.get(name) or {}
        dest = getattr(forest, name)
        for key, values in src.items():
            iid = int(key)
            if iid not in dest or len(dest[iid]) != len(values):
                continue
            dest[iid] = list(values)


def _dump_camera(camera: Camera) -> dict[str, Any]:
    return {
        "x": camera.x,
        "y": camera.y,
        "view_width_m": camera.view_width_m,
        "radar_mode": camera.radar_mode,
        "debug_mode": camera.debug_mode,
    }


def _dump_rng(rng) -> list[Any]:
    ver, key, gauss = rng.getstate()
    return [ver, list(key), gauss]


def _load_rng(rng, data: list[Any]) -> None:
    ver, key, gauss = data
    rng.setstate((int(ver), tuple(int(v) for v in key), gauss))


def _json(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_json(v) for v in value]
    return value


def _from_json(value: Any) -> Any:
    if isinstance(value, list) and len(value) == 2 and all(
        isinstance(v, (int, float)) for v in value
    ):
        return (float(value[0]), float(value[1]))
    return value
