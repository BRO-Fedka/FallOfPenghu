from __future__ import annotations

from math import atan2, cos, hypot, pi, sin, sqrt
from typing import TYPE_CHECKING

from fall_of_penghu.ai.heatmap import BeachPick, IslandHeatmaps
from fall_of_penghu.world.entities.command import SetRoute
from fall_of_penghu.world.entities.dynamic import DynamicObject
from fall_of_penghu.world.entities.game_object import FACTION_CHINA, FACTION_PLAYER
from fall_of_penghu.world.entities.kinds import SHOT_KINDS

if TYPE_CHECKING:
    from fall_of_penghu.ai.log import DecisionLog
    from fall_of_penghu.world.world import World

SCOUT_LAUNCH_S = 10.0
LAUNCH_BURST = 5
SCOUT_SPAWN_M = 700.0
SIT_M = 50.0
COVER_FRAC = 0.85
SWEEP_DONE_M = 80.0
AA_PAD_M = 250.0
AA_HEAT = 0.35
KILL_ZONE_S = 900.0
SEG_SAMPLE_M = 180.0
MAX_SWEEP_VERTS = 80
AA_CLEAR_M = 80.0
GROUND_FOLLOW = frozenset({"infantry", "artillery", "tank", "truck"})
GROUND_AA = frozenset({"aaw", "aa_pickup"})
Ring = tuple[float, float, float]


class IntelOps:
    """Scouts, heatmaps, landing site. Does not own kamikaze."""

    def __init__(self, log: DecisionLog) -> None:
        self.log = log
        self.heat = IslandHeatmaps()
        self.assault: BeachPick | None = None
        self._scout_n = 0
        self._scout_ready_sim = 0.0
        self._baked = False
        self._sweeps: list[tuple[int, tuple[tuple[float, float], ...]]] = []
        self._circuit: tuple[tuple[float, float], ...] = ()
        self._progress: dict[int, int] = {}
        self._alive: set[str] = set()
        self._jobs: dict[str, dict] = {}
        self._orphans: list[dict] = []
        self._kills: list[tuple[float, float, float, float]] = []
        self._pose: dict[str, tuple[float, float]] = {}

    def bake(self, world: World) -> None:
        self.heat.bake(world)
        self._sweeps = _forest_sweeps(world, self.heat)
        self._circuit = tuple(path[0] for _iid, path in self._sweeps if path)
        if len(self._circuit) == 1:
            self._circuit = self._circuit + self._circuit
        self._baked = True

    def step(self, world: World) -> None:
        if not self._baked or not self._sweeps:
            self.bake(world)
        self.heat.refresh(world)
        prev = None if self.assault is None else self.assault.island
        self.assault = self.heat.pick_landing(world)
        if self.assault is None:
            if prev is not None:
                self.log.emit(world.clock.simulation_time, "assault", "hold — all beaches hot")
        elif prev != self.assault.island:
            self.log.emit(
                world.clock.simulation_time,
                "assault",
                f"island {self.assault.island} "
                f"{self.assault.x:.0f},{self.assault.y:.0f} heat={self.assault.landing:.2f}",
            )
        self._step_scouts(world)

    def sample(self, x: float, y: float) -> tuple[float, float, float] | None:
        return self.heat.sample(x, y)

    def _step_scouts(self, world: World) -> None:
        catalog = world.catalog
        cap = catalog.scout_count
        n_patrol = min(catalog.scout_patrol_count, cap)
        n_search = max(0, cap - n_patrol)
        now = world.clock.simulation_time
        dusk = world.clock.time_of_day >= catalog.scout_dusk_tod
        scouts = _china_kind(world, "scout")
        self._note_deaths(world, scouts, now, catalog)
        scouts = self._cull_scouts(world, cap)
        rings = _aa_rings(world, self._kills, now)
        claimed = _follow_claimed(scouts)
        posts = _cluster_posts(world, catalog, rings, self, claimed) if dusk else []
        used_posts: set[int] = set()
        patrol, search = _split_roles(scouts, n_patrol)
        _bind_slots(patrol, n_patrol)
        _bind_slots(search, max(1, n_search))
        self._hand_off(world, search, claimed, now, rings)
        for scout in patrol:
            self._drive_circuit(world, scout, now, rings)
        for scout in search:
            slot = int(getattr(scout, "patrol_slot", 0) or 0)
            self._drive_search(
                world, scout, now, dusk, slot, n_search, posts, used_posts, claimed, rings
            )
            self._jobs[scout.id] = {
                "role": "search",
                "slot": slot,
                "sweep_k": int(getattr(scout, "sweep_k", 0) or 0),
                "follow_id": scout.strike_id if scout.task == "follow" else None,
            }
            self._progress[slot] = int(getattr(scout, "sweep_k", 0) or 0)
        if now < self._scout_ready_sim:
            return
        carrier = _best_carrier(world)
        if carrier is None:
            return
        launched = 0
        skips = 0
        blocked_p: set[int] = set()
        while launched < LAUNCH_BURST:
            alive = _china_kind(world, "scout")
            if len(alive) >= cap:
                break
            patrol_used = {
                int(getattr(obj, "patrol_slot", -1) or -1)
                for obj in alive
                if getattr(obj, "role", "") == "circuit"
            } | blocked_p
            search_used = {
                int(getattr(obj, "patrol_slot", -1) or -1)
                for obj in alive
                if getattr(obj, "role", "") != "circuit"
            }
            miss_p = [i for i in range(n_patrol) if i not in patrol_used]
            miss_s = [i for i in range(n_search) if i not in search_used]
            if miss_p:
                slot = miss_p[0]
                task = "circuit"
                path: tuple[tuple[float, float], ...] = ()
                dest = self._circuit[slot % len(self._circuit)] if self._circuit else None
                k = 0
            elif miss_s:
                slot = miss_s[0]
                task = "search"
                k = self._progress.get(slot, 0)
                path = self._search_path(slot, n_search, k)
                dest = path[0] if path else None
            else:
                break
            if dest is None:
                if self.assault is not None:
                    dest = (self.assault.x, self.assault.y)
                elif self._circuit:
                    dest = self._circuit[0]
                else:
                    skips += 1
                    if task == "search":
                        self._progress[slot] = k + 1
                    else:
                        blocked_p.add(slot)
                    if skips > 16:
                        break
                    continue
            if not self._launch_scout(
                world, carrier, dest, task, slot, path, rings, k=k
            ):
                skips += 1
                if skips > 16:
                    break
                continue
            launched += 1
        if launched:
            self._scout_ready_sim = now + SCOUT_LAUNCH_S
            alive = _china_kind(world, "scout")
            search = [obj for obj in alive if getattr(obj, "role", "") != "circuit"]
            self._hand_off(world, search, _follow_claimed(alive), now, rings)

    def _note_deaths(
        self, world: World, scouts: list[DynamicObject], now: float, catalog
    ) -> None:
        live = {obj.id for obj in scouts}
        pickup = (catalog.engagement_m("aa_pickup") or 2000.0) + AA_PAD_M
        for oid in self._alive - live:
            xy = self._pose.get(oid)
            job = self._jobs.pop(oid, None)
            if xy is not None:
                self._kills.append((xy[0], xy[1], pickup, now + KILL_ZONE_S))
                self.log.emit(now, "scout-lost", f"{oid} zone {xy[0]:.0f},{xy[1]:.0f}")
            if job is not None:
                if job.get("follow_id"):
                    self._orphans.append(job)
                if job.get("role") == "search":
                    self._progress[int(job.get("slot") or 0)] = int(job.get("sweep_k") or 0)
        self._alive = live
        self._pose = {obj.id: (obj.x, obj.y) for obj in scouts}
        self._kills = [row for row in self._kills if row[3] > now]

    def _hand_off(
        self,
        world: World,
        search: list[DynamicObject],
        claimed: dict[str, str],
        now: float,
        rings: list[Ring],
    ) -> None:
        keep: list[dict] = []
        for job in self._orphans:
            fid = job.get("follow_id")
            if not fid or fid in claimed:
                continue
            tgt = _followable(world, fid)
            if tgt is None or _aa_hot(tgt.x, tgt.y, rings, self):
                continue
            free = [
                obj
                for obj in search
                if obj.task != "follow" and obj.id not in claimed.values()
            ]
            if not free:
                keep.append(job)
                continue
            pick = min(free, key=lambda obj: hypot(obj.x - tgt.x, obj.y - tgt.y))
            hold = _watch_xy(world, pick, tgt, rings, self, world.catalog)
            if hold is None:
                keep.append(job)
                continue
            pick.task = "follow"
            pick.strike_id = fid
            pick.sweep_k = int(job.get("sweep_k") or getattr(pick, "sweep_k", 0) or 0)
            claimed[fid] = pick.id
            _sit(world, pick, hold, rings, self)
            self.log.emit(now, "scout-take", f"{pick.id} takes {tgt.kind}:{fid}")
        self._orphans = keep

    def _search_path(
        self, search_slot: int, n_search: int, sweep_k: int
    ) -> tuple[tuple[float, float], ...]:
        if not self._sweeps or n_search <= 0:
            return ()
        mine = [
            path
            for i, (_iid, path) in enumerate(self._sweeps)
            if i % n_search == search_slot % n_search
        ]
        if not mine:
            mine = [path for _iid, path in self._sweeps]
        if not mine:
            return ()
        return mine[sweep_k % len(mine)]

    def _skip_hot_islands(
        self,
        search_slot: int,
        n_search: int,
        sweep_k: int,
        path: tuple[tuple[float, float], ...],
        rings: list[Ring],
    ) -> tuple[tuple[float, float], ...]:
        k = sweep_k
        cur = path
        for _ in range(max(1, len(self._sweeps))):
            land = tuple(pt for pt in cur if not _aa_hot(pt[0], pt[1], rings, self))
            if land:
                if k != sweep_k:
                    self._progress[search_slot] = k
                return land
            k += 1
            cur = self._search_path(search_slot, n_search, k)
        self._progress[search_slot] = k
        return ()

    def _cull_scouts(self, world: World, cap: int) -> list[DynamicObject]:
        scouts = _china_kind(world, "scout")
        if len(scouts) <= cap:
            return scouts
        ranked = sorted(
            scouts,
            key=lambda obj: (
                0 if obj.task in ("follow", "circuit") else 1,
                obj.id,
            ),
        )
        keep = ranked[:cap]
        drop = ranked[cap:]
        for obj in drop:
            self._alive.discard(obj.id)
            self._jobs.pop(obj.id, None)
            self._pose.pop(obj.id, None)
            world.entities.discard(obj.id)
        self.log.emit(
            world.clock.simulation_time,
            "scout-cull",
            f"keep {len(keep)} drop {len(drop)}",
        )
        return keep

    def _drive_circuit(
        self, world: World, scout: DynamicObject, now: float, rings: list[Ring]
    ) -> None:
        loop = self._circuit
        if not loop:
            return
        scout.task = "circuit"
        scout.role = "circuit"
        scout.strike_id = None
        remaining = scout.route.remaining_length() if scout.route is not None else 0.0
        loop = _reachable_loop(self._sweeps, rings, self) or loop
        if remaining > SWEEP_DONE_M and not _route_hits_aa(scout, rings, self):
            return
        verts = _safe_verts(world, scout, _loop_from(scout, loop), rings, self)
        if not verts:
            goal = _nearest_reachable(scout, loop, rings, self)
            if goal is not None:
                hop = _clear_hop((scout.x, scout.y), goal, rings, self)
                if hop:
                    _fly_verts(world, scout, hop)
            return
        _fly_verts(world, scout, verts)
        last = float(getattr(scout, "task_sim", 0.0) or 0.0)
        if now - last >= 30.0:
            scout.task_sim = now
            self.log.emit(now, "scout-circuit", f"{scout.id} loop {len(verts)} pts")

    def _drive_search(
        self,
        world: World,
        scout: DynamicObject,
        now: float,
        dusk: bool,
        slot: int,
        n_search: int,
        posts: list[tuple[float, float]],
        used_posts: set[int],
        claimed: dict[str, str],
        rings: list[Ring],
    ) -> None:
        catalog = world.catalog
        scout.role = "search"
        locked = _locked_target(world, scout)
        if locked is not None:
            owner = claimed.get(locked.id)
            if owner in (None, scout.id):
                claimed[locked.id] = scout.id
                hold = _watch_xy(world, scout, locked, rings, self, catalog)
                if hold is not None:
                    scout.task = "follow"
                    _sit(world, scout, hold, rings, self)
                    return
            scout.strike_id = None
        lost = False
        if scout.task == "follow":
            self.log.emit(now, "scout-search", f"{scout.id} lost lock")
            scout.strike_id = None
            scout.task = "search"
            lost = True
        found = _forest_contact(world, scout, claimed, rings, self)
        if found is not None:
            hold = _watch_xy(world, scout, found, rings, self, catalog)
            if hold is not None:
                scout.task = "follow"
                scout.strike_id = found.id
                scout.task_sim = now
                claimed[found.id] = scout.id
                _sit(world, scout, hold, rings, self)
                self.log.emit(
                    now,
                    "scout-follow",
                    f"{scout.id} {found.kind}:{found.id} stand {hold[0]:.0f},{hold[1]:.0f}",
                )
                return
        if dusk and posts:
            current = getattr(scout, "patrol_xy", None)
            if scout.task == "watch" and current is not None:
                for i, cand in enumerate(posts):
                    if i in used_posts:
                        continue
                    if hypot(current[0] - cand[0], current[1] - cand[1]) < 250.0:
                        used_posts.add(i)
                        hold = _push_out(cand, rings, self)
                        scout.patrol_xy = hold
                        _sit(world, scout, hold, rings, self)
                        return
            post = _take_post(scout, posts, used_posts)
            if post is not None:
                scout.task = "watch"
                hold = _push_out(post, rings, self)
                scout.patrol_xy = hold
                _sit(world, scout, hold, rings, self)
                return
        remaining = scout.route.remaining_length() if scout.route is not None else 0.0
        if (
            remaining > SWEEP_DONE_M
            and scout.task == "search"
            and not lost
            and not _route_hits_aa(scout, rings, self)
        ):
            return
        k = int(getattr(scout, "sweep_k", 0) or 0)
        if remaining <= SWEEP_DONE_M and scout.task == "search" and not lost:
            k += 1
        verts: tuple[tuple[float, float], ...] = ()
        for _try in range(max(1, len(self._sweeps))):
            path = self._search_path(slot, n_search, k)
            path = _reachable_cells(path, rings, self)
            if lost:
                path = _from_nearest(scout, path)
            verts = _safe_verts(world, scout, path, rings, self)
            if verts:
                break
            k += 1
            lost = False
        else:
            scout.sweep_k = k
            raw = self._search_path(slot, n_search, k)
            goal = _nearest_reachable(scout, raw, rings, self)
            if goal is not None:
                hop = _clear_hop((scout.x, scout.y), goal, rings, self)
                if hop:
                    _fly_verts(world, scout, hop)
            return
        scout.sweep_k = k
        scout.patrol_slot = slot
        scout.task = "search"
        scout.task_sim = now
        scout.patrol_xy = verts[0]
        _fly_verts(world, scout, verts[: MAX_SWEEP_VERTS + 4])
        self.log.emit(
            now,
            "scout-sweep",
            f"{scout.id} forest {len(verts)} pts {verts[0][0]:.0f},{verts[0][1]:.0f}",
        )

    def _launch_scout(
        self,
        world: World,
        carrier: DynamicObject,
        hover: tuple[float, float],
        task: str,
        slot: int,
        path: tuple[tuple[float, float], ...],
        rings: list[Ring],
        *,
        k: int,
    ) -> bool:
        self._scout_n += 1
        oid = f"c_scout_{self._scout_n:03d}"
        jx = (self._scout_n % 7 - 3) * (SCOUT_SPAWN_M / 3.0)
        jy = ((self._scout_n * 5) % 7 - 3) * (SCOUT_SPAWN_M / 3.0)
        sx, sy = carrier.x + jx, carrier.y + jy
        scout = DynamicObject(
            id=oid,
            faction=FACTION_CHINA,
            kind="scout",
            name=f"PLA scout {self._scout_n}",
            x=sx,
            y=sy,
            heading=atan2(hover[1] - sy, hover[0] - sx),
            speed_mps=world.catalog.speed_mps("scout"),
            mobility="air",
        )
        scout.task = task
        scout.role = task
        scout.task_sim = world.clock.simulation_time
        scout.patrol_xy = hover
        scout.patrol_slot = slot
        scout.sweep_k = k
        world.entities.add(scout)
        seed = path if path else ((hover,) if hover is not None else ())
        if task == "circuit" and self._circuit:
            seed = _reachable_loop(self._sweeps, rings, self) or self._circuit
        verts = _safe_verts(world, scout, seed, rings, self)
        if verts:
            _fly_verts(world, scout, verts[: MAX_SWEEP_VERTS + 4])
            dest = verts[0]
        else:
            goal = _nearest_reachable(scout, seed or (hover,), rings, self)
            if goal is not None:
                hop = _clear_hop((scout.x, scout.y), goal, rings, self)
                if hop:
                    _fly_verts(world, scout, hop)
                    dest = hop[-1]
                else:
                    dest = goal
                    _fly(world, scout, dest)
            else:
                # Stay aloft near the carrier; next step will retry a clear forest.
                dest = (sx, sy)
                scout.route = None
        scout.patrol_xy = dest
        self._jobs[oid] = {
            "role": task,
            "slot": slot,
            "sweep_k": k,
            "follow_id": None,
        }
        self.log.emit(
            world.clock.simulation_time,
            "scout-launch",
            f"{oid} {task} slot {slot} {dest[0]:.0f},{dest[1]:.0f}",
        )
        return True


def _sit(
    world: World,
    scout: DynamicObject,
    dest: tuple[float, float],
    rings: list[Ring] | None = None,
    intel: IntelOps | None = None,
) -> None:
    if hypot(scout.x - dest[0], scout.y - dest[1]) <= SIT_M:
        scout.route = None
        scout.patrol_xy = dest
        return
    if scout.route is None or _aim_off(scout, dest) > 60.0:
        if rings is not None and intel is not None:
            hop = _clear_hop((scout.x, scout.y), dest, rings, intel)
            if hop:
                _fly_verts(world, scout, hop)
                scout.patrol_xy = dest
                return
        _fly(world, scout, dest)
        scout.patrol_xy = dest


def _aim_off(scout: DynamicObject, dest: tuple[float, float]) -> float:
    route = scout.route
    if route is None or not route.points:
        return 1e9
    end = route.points[-1]
    return hypot(end[0] - dest[0], end[1] - dest[1])


def _watch_xy(
    world: World,
    scout: DynamicObject,
    target,
    rings: list[Ring],
    intel: IntelOps,
    catalog,
) -> tuple[float, float] | None:
    cover = world.perception.cover
    vis = catalog.scaled_range_m(
        "visual_advanced",
        target.kind,
        world.clock.darkness,
        emitter_kind="scout",
    ) or 6000.0
    if cover is not None:
        vis *= catalog.cover_factor(
            "visual_advanced", cover.at(target.x, target.y, "ground")
        )
    stand = min(catalog.scout_standoff_m, vis * 0.8)
    if stand < 80.0:
        return None
    prev = getattr(scout, "patrol_xy", None)
    best = None
    best_key = None
    for i in range(16):
        ang = i * (2.0 * pi / 16.0)
        cand = (target.x + cos(ang) * stand, target.y + sin(ang) * stand)
        if _aa_hot(cand[0], cand[1], rings, intel):
            continue
        d_prev = 0.0 if prev is None else hypot(cand[0] - prev[0], cand[1] - prev[1])
        key = (d_prev, hypot(cand[0] - scout.x, cand[1] - scout.y))
        if best_key is None or key < best_key:
            best = cand
            best_key = key
    return best


def _locked_target(world: World, scout: DynamicObject):
    return _followable(world, scout.strike_id or "")


def _followable(world: World, sid: str):
    if not sid:
        return None
    obj = world.entities.get(sid)
    if obj is None or not obj.active or obj.faction != FACTION_PLAYER:
        return None
    if getattr(obj, "stowed", False) or obj.kind in SHOT_KINDS:
        return None
    if obj.kind not in GROUND_FOLLOW:
        return None
    return obj


def _forest_contact(
    world: World,
    scout: DynamicObject,
    claimed: dict[str, str],
    rings: list[Ring],
    intel: IntelOps,
):
    cover = world.perception.cover
    if cover is None:
        return None
    catalog = world.catalog
    vis = catalog.scaled_range_m(
        "visual_advanced",
        "infantry",
        world.clock.darkness,
        emitter_kind="scout",
    ) or 6000.0
    vis *= catalog.cover_factor("visual_advanced", "forest")
    best = None
    best_d = vis
    for obj in world.perception.visible_objects(FACTION_CHINA):
        if obj.faction != FACTION_PLAYER or not obj.active:
            continue
        if obj.kind not in GROUND_FOLLOW:
            continue
        if getattr(obj, "stowed", False):
            continue
        if cover.at(obj.x, obj.y, "ground") != "forest":
            continue
        owner = claimed.get(obj.id)
        if owner and owner != scout.id:
            continue
        if _aa_hot(obj.x, obj.y, rings, intel):
            continue
        d = hypot(obj.x - scout.x, obj.y - scout.y)
        if d <= best_d:
            best = obj
            best_d = d
    return best


def _follow_claimed(scouts: list[DynamicObject]) -> dict[str, str]:
    out: dict[str, str] = {}
    for scout in scouts:
        sid = scout.strike_id
        if sid and scout.task == "follow" and sid not in out:
            out[sid] = scout.id
    return out


def _known_contacts(world: World) -> list[tuple[float, float, str]]:
    now = world.clock.simulation_time
    pts: list[tuple[float, float, str]] = []
    seen: set[str] = set()
    for obj in world.perception.visible_objects(FACTION_CHINA):
        if obj.faction != FACTION_PLAYER or not obj.active:
            continue
        if obj.kind not in GROUND_FOLLOW:
            continue
        if getattr(obj, "stowed", False):
            continue
        pts.append((obj.x, obj.y, obj.id))
        seen.add(obj.id)
    for mark in world.perception.imprints(FACTION_CHINA):
        if mark.faction != FACTION_PLAYER or not mark.active:
            continue
        if mark.kind not in GROUND_FOLLOW:
            continue
        if mark.source_id in seen or mark.dead(now):
            continue
        pts.append((mark.x, mark.y, mark.source_id))
        seen.add(mark.source_id)
    return pts


def _cluster_posts(
    world: World,
    catalog,
    rings: list[Ring],
    intel: IntelOps,
    claimed: dict[str, str],
) -> list[tuple[float, float]]:
    contacts = [
        (x, y) for x, y, sid in _known_contacts(world) if sid not in claimed
    ]
    if not contacts:
        return []
    vis = catalog.emitter_range_m("visual_advanced", "scout") or 6000.0
    vis *= catalog.darkness_scale("visual_advanced", world.clock.darkness)
    vis *= catalog.cover_factor("visual_advanced", "forest")
    reach = max(vis * COVER_FRAC, 160.0)
    left = list(range(len(contacts)))
    posts: list[tuple[float, float]] = []
    while left:
        best_i = left[0]
        best_cover: list[int] = [left[0]]
        for i in left:
            cx, cy = contacts[i]
            if _aa_hot(cx, cy, rings, intel):
                continue
            covered = [
                j
                for j in left
                if hypot(contacts[j][0] - cx, contacts[j][1] - cy) <= reach
            ]
            if len(covered) > len(best_cover):
                best_i = i
                best_cover = covered
        if _aa_hot(contacts[best_i][0], contacts[best_i][1], rings, intel):
            left = [j for j in left if j != best_i]
            continue
        posts.append(contacts[best_i])
        drop = set(best_cover)
        left = [j for j in left if j not in drop]
    return posts


def _take_post(
    scout: DynamicObject,
    posts: list[tuple[float, float]],
    used: set[int],
) -> tuple[float, float] | None:
    best_i = None
    best_d = 1e30
    for i, pt in enumerate(posts):
        if i in used:
            continue
        d = hypot(scout.x - pt[0], scout.y - pt[1])
        if d < best_d:
            best_d = d
            best_i = i
    if best_i is None:
        return None
    used.add(best_i)
    return posts[best_i]


def _aa_rings(world: World, kills: list[tuple[float, float, float, float]], now: float) -> list[Ring]:
    catalog = world.catalog
    rings: list[Ring] = []

    def add(kind: str, x: float, y: float) -> None:
        if kind not in GROUND_AA:
            return
        reach = catalog.engagement_m(kind) or 0.0
        if reach > 0.0:
            rings.append((x, y, reach + AA_PAD_M))

    for obj in world.perception.visible_objects(FACTION_CHINA):
        if obj.faction != FACTION_PLAYER or not obj.active:
            continue
        add(obj.kind, obj.x, obj.y)
    for mark in world.perception.imprints(FACTION_CHINA):
        if mark.faction != FACTION_PLAYER or not mark.active or mark.dead(now):
            continue
        add(mark.kind, mark.x, mark.y)
    for x, y, r, exp in kills:
        if exp > now:
            rings.append((x, y, r))
    return rings


def _aa_hot(x: float, y: float, rings: list[Ring], intel: IntelOps) -> bool:
    for ax, ay, r in rings:
        if hypot(x - ax, y - ay) <= r:
            return True
    sample = intel.sample(x, y)
    return sample is not None and sample[2] >= AA_HEAT


def _push_out(
    pt: tuple[float, float], rings: list[Ring], intel: IntelOps
) -> tuple[float, float]:
    x, y = pt
    for _ in range(8):
        moved = False
        for cx, cy, r in rings:
            d = hypot(x - cx, y - cy)
            need = r + AA_CLEAR_M
            if d < need:
                n = d or 1.0
                x = cx + (x - cx) / n * need
                y = cy + (y - cy) / n * need
                moved = True
        if not moved and not _aa_hot(x, y, rings, intel):
            return (x, y)
        if not moved:
            break
    return (x, y)


def _seg_hits(a: tuple[float, float], b: tuple[float, float], ring: Ring) -> bool:
    cx, cy, r = ring
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    span2 = dx * dx + dy * dy
    if span2 <= 1e-6:
        return hypot(a[0] - cx, a[1] - cy) <= r
    t = ((cx - a[0]) * dx + (cy - a[1]) * dy) / span2
    t = min(1.0, max(0.0, t))
    px = a[0] + t * dx
    py = a[1] + t * dy
    return hypot(px - cx, py - cy) <= r


def _seg_clear(
    a: tuple[float, float], b: tuple[float, float], rings: list[Ring], intel: IntelOps
) -> bool:
    if _aa_hot(a[0], a[1], rings, intel) or _aa_hot(b[0], b[1], rings, intel):
        return False
    for ring in rings:
        if _seg_hits(a, b, ring):
            return False
    span = hypot(b[0] - a[0], b[1] - a[1])
    steps = max(1, int(span / SEG_SAMPLE_M))
    for i in range(1, steps):
        t = i / steps
        x = a[0] + (b[0] - a[0]) * t
        y = a[1] + (b[1] - a[1]) * t
        if _aa_hot(x, y, rings, intel):
            return False
    return True


def _tangents(
    a: tuple[float, float], ring: Ring
) -> list[tuple[float, float]]:
    cx, cy, r = ring
    pad = r + AA_CLEAR_M
    dx = a[0] - cx
    dy = a[1] - cy
    d = hypot(dx, dy)
    if d <= pad + 1.0:
        return []
    ang = atan2(dy, dx)
    try:
        off = acos_safe(pad / d)
    except ValueError:
        return []
    return [
        (cx + pad * cos(ang + off), cy + pad * sin(ang + off)),
        (cx + pad * cos(ang - off), cy + pad * sin(ang - off)),
    ]


def acos_safe(v: float) -> float:
    return atan2(sqrt(max(0.0, 1.0 - v * v)), v)


def _blocking_ring(
    a: tuple[float, float], b: tuple[float, float], rings: list[Ring]
) -> Ring | None:
    hit = None
    best = 1e30
    for ring in rings:
        if not _seg_hits(a, b, ring):
            continue
        d = hypot(a[0] - ring[0], a[1] - ring[1])
        if d < best:
            best = d
            hit = ring
    return hit


def _clear_hop(
    start: tuple[float, float],
    goal: tuple[float, float],
    rings: list[Ring],
    intel: IntelOps,
) -> tuple[tuple[float, float], ...]:
    """Polyline from start to goal hugging AA rings from outside."""
    a0 = _push_out(start, rings, intel)
    b0 = _push_out(goal, rings, intel)
    if _seg_clear(a0, b0, rings, intel):
        out = []
        if hypot(a0[0] - start[0], a0[1] - start[1]) > 20.0:
            out.append(a0)
        out.append(b0)
        return tuple(out)
    frontier = [(a0, ())]
    seen: set[tuple[int, int]] = {_qkey(a0)}
    for _depth in range(10):
        nxt: list[tuple[tuple[float, float], tuple[tuple[float, float], ...]]] = []
        for cur, trail in frontier:
            ring = _blocking_ring(cur, b0, rings)
            cands = _tangents(cur, ring) if ring is not None else []
            if not cands:
                for other in rings:
                    cands.extend(_tangents(cur, other))
            for via in cands:
                via = _push_out(via, rings, intel)
                if _aa_hot(via[0], via[1], rings, intel):
                    continue
                if not _seg_clear(cur, via, rings, intel):
                    continue
                key = _qkey(via)
                if key in seen:
                    continue
                seen.add(key)
                path = trail + (via,)
                if _seg_clear(via, b0, rings, intel):
                    out = list(path) + [b0]
                    if hypot(a0[0] - start[0], a0[1] - start[1]) > 20.0:
                        out = [a0, *out]
                    return tuple(out)
                nxt.append((via, path))
        frontier = nxt
        if not frontier:
            break
    return ()


def _qkey(pt: tuple[float, float]) -> tuple[int, int]:
    return (int(round(pt[0] / 200.0)), int(round(pt[1] / 200.0)))


def _reachable_cells(
    cells: tuple[tuple[float, float], ...],
    rings: list[Ring],
    intel: IntelOps,
) -> tuple[tuple[float, float], ...]:
    return tuple(pt for pt in cells if not _aa_hot(pt[0], pt[1], rings, intel))


def _reachable_loop(
    sweeps: list[tuple[int, tuple[tuple[float, float], ...]]],
    rings: list[Ring],
    intel: IntelOps,
) -> tuple[tuple[float, float], ...]:
    pts: list[tuple[float, float]] = []
    for _iid, path in sweeps:
        land = _reachable_cells(path, rings, intel)
        if land:
            pts.append(land[0])
    if len(pts) == 1:
        pts = pts + pts
    return tuple(pts)


def _nearest_reachable(
    scout: DynamicObject,
    seed: tuple[tuple[float, float], ...] | None,
    rings: list[Ring],
    intel: IntelOps,
) -> tuple[float, float] | None:
    if not seed:
        return None
    land = _reachable_cells(tuple(seed), rings, intel)
    if not land:
        return None
    start = (scout.x, scout.y)
    ranked = sorted(land, key=lambda pt: hypot(pt[0] - start[0], pt[1] - start[1]))
    for pt in ranked[:12]:
        if _clear_hop(start, pt, rings, intel):
            return pt
    return None


def _safe_verts(
    world: World,
    scout: DynamicObject,
    path: tuple[tuple[float, float], ...],
    rings: list[Ring],
    intel: IntelOps,
) -> tuple[tuple[float, float], ...]:
    land = list(_reachable_cells(path, rings, intel))
    if not land:
        return ()
    start = (scout.x, scout.y)
    # Pick the nearest cell we can actually approach around AA.
    entry = None
    entry_i = 0
    ranked = sorted(
        range(len(land)),
        key=lambda i: hypot(land[i][0] - start[0], land[i][1] - start[1]),
    )
    for i in ranked[:16]:
        hop = _clear_hop(start, land[i], rings, intel)
        if hop:
            entry = hop
            entry_i = i
            break
    if entry is None:
        return ()
    sweep = land[entry_i : entry_i + MAX_SWEEP_VERTS]
    if not sweep:
        return entry
    chain: list[tuple[float, float]] = list(entry[:-1]) if len(entry) > 1 else []
    cur = entry[-1]
    chain.append(cur)
    for nxt in sweep[1:]:
        hop = _clear_hop(cur, nxt, rings, intel)
        if not hop:
            # Skip hot/unreachable cells; keep sweeping the reachable pocket.
            continue
        for pt in hop:
            if hypot(pt[0] - chain[-1][0], pt[1] - chain[-1][1]) > 20.0:
                chain.append(pt)
        cur = chain[-1]
    if hypot(chain[0][0] - scout.x, chain[0][1] - scout.y) < 25.0:
        chain = chain[1:]
    return tuple(chain)


def _route_hits_aa(scout: DynamicObject, rings: list[Ring], intel: IntelOps) -> bool:
    route = scout.route
    if route is None or len(route.points) < 2:
        return _aa_hot(scout.x, scout.y, rings, intel)
    pts = [(scout.x, scout.y), *route.points]
    for a, b in zip(pts, pts[1:]):
        if not _seg_clear(a, b, rings, intel):
            return True
    return False


def _forest_sweeps(
    world: World, heat: IslandHeatmaps
) -> list[tuple[int, tuple[tuple[float, float], ...]]]:
    cover = world.perception.cover
    if cover is None:
        return []
    by_island: dict[int, list[tuple[float, float]]] = {}
    cell = max(50.0, world.catalog.heat_cell_m)
    for grid in heat.grids.values():
        for i, land in enumerate(grid.land):
            if not land:
                continue
            pt = grid.center(i)
            if cover.at(pt[0], pt[1], "ground") != "forest":
                continue
            by_island.setdefault(grid.island, []).append(pt)
    ordered = sorted(
        by_island.items(),
        key=lambda row: (sum(p[1] for p in row[1]) / len(row[1]), row[0]),
    )
    return [(iid, tuple(_snake(cells, cell))) for iid, cells in ordered if cells]


def _snake(
    cells: list[tuple[float, float]], cell_m: float
) -> list[tuple[float, float]]:
    rows: dict[int, list[tuple[float, float]]] = {}
    for x, y in cells:
        rows.setdefault(int(round(y / cell_m)), []).append((x, y))
    path: list[tuple[float, float]] = []
    for i, gy in enumerate(sorted(rows)):
        row = sorted(rows[gy], key=lambda p: p[0])
        if i % 2:
            row.reverse()
        path.extend(row)
    return path


def _from_nearest(
    scout: DynamicObject, path: tuple[tuple[float, float], ...]
) -> tuple[tuple[float, float], ...]:
    if not path:
        return path
    start = min(
        range(len(path)),
        key=lambda i: hypot(scout.x - path[i][0], scout.y - path[i][1]),
    )
    return path[start:]


def _loop_from(
    scout: DynamicObject, loop: tuple[tuple[float, float], ...]
) -> tuple[tuple[float, float], ...]:
    if not loop:
        return loop
    start = min(
        range(len(loop)),
        key=lambda i: hypot(scout.x - loop[i][0], scout.y - loop[i][1]),
    )
    ordered = list(loop[start:]) + list(loop[:start])
    if hypot(scout.x - ordered[0][0], scout.y - ordered[0][1]) < 20.0 and len(ordered) > 1:
        ordered = ordered[1:] + ordered[:1]
    return tuple(ordered)


def _fly(world: World, unit: DynamicObject, xy: tuple[float, float]) -> None:
    world.entities.dispatch(
        SetRoute(object_id=unit.id, mode="auto", target=xy),
        as_faction=FACTION_CHINA,
    )


def _fly_verts(
    world: World, unit: DynamicObject, verts: tuple[tuple[float, float], ...]
) -> None:
    if not verts:
        return
    if len(verts) == 1:
        _fly(world, unit, verts[0])
        return
    world.entities.dispatch(
        SetRoute(object_id=unit.id, mode="manual", vertices=verts),
        as_faction=FACTION_CHINA,
    )


def _split_roles(
    scouts: list[DynamicObject], n_patrol: int
) -> tuple[list[DynamicObject], list[DynamicObject]]:
    patrol: list[DynamicObject] = []
    search: list[DynamicObject] = []
    unroled: list[DynamicObject] = []
    for obj in sorted(scouts, key=lambda row: row.id):
        role = getattr(obj, "role", "") or ""
        if not role:
            unroled.append(obj)
            continue
        if role == "circuit":
            patrol.append(obj)
        else:
            search.append(obj)
    for obj in unroled:
        if len(patrol) < n_patrol:
            obj.role = "circuit"
            patrol.append(obj)
        else:
            obj.role = "search"
            search.append(obj)
    return patrol, search


def _bind_slots(units: list[DynamicObject], n: int) -> None:
    n = max(n, 1)
    taken: set[int] = set()
    pending: list[DynamicObject] = []
    for obj in sorted(units, key=lambda row: row.id):
        raw = getattr(obj, "patrol_slot", None)
        if raw is None:
            pending.append(obj)
            continue
        slot = int(raw)
        if slot < 0 or slot in taken:
            pending.append(obj)
            continue
        taken.add(slot)
    miss = [i for i in range(n) if i not in taken]
    extra = n
    for obj in pending:
        if miss:
            obj.patrol_slot = miss.pop(0)
        else:
            obj.patrol_slot = extra
            extra += 1


def _china_kind(world: World, kind: str) -> list[DynamicObject]:
    out: list[DynamicObject] = []
    for obj in world.entities.items:
        if (
            isinstance(obj, DynamicObject)
            and obj.active
            and obj.faction == FACTION_CHINA
            and obj.kind == kind
            and not getattr(obj, "stowed", False)
        ):
            out.append(obj)
    return out


def _best_carrier(world: World) -> DynamicObject | None:
    ships = _china_kind(world, "drone_carrier")
    alive = [obj for obj in ships if (obj.task or "") != "leave"]
    if not alive:
        return None
    alive.sort(
        key=lambda obj: (0 if (obj.task or "station") == "station" else 1, obj.id)
    )
    return alive[0]
