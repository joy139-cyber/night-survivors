"""The game rules, run at a fixed time step (1/60 s). No pygame here.

main.py and the tests give this module a command each step:
  aim_xy: the world point the hero walks toward, or None to stand still.
The hero stops when he is close enough to that point.
Everything else (weapons, gems, XP, level-up cards) happens by itself.

Each step also leaves a note in world.events about what happened (a hit, a
death, a gem, the hero getting hurt, a level-up, the end). main.py reads those
notes to play a sound or draw an effect, then clears them. The rules never
care what happens to them, so this file stays free of pygame.
"""

import math
import random

STEP_TIME = 1.0 / 60.0


class Enemy:
    def __init__(self, kind, x, y, hp, radius):
        self.kind = kind
        self.x = x
        self.y = y
        self.hp = hp
        self.radius = radius
        self.hit_ready = 0.0  # seconds until this enemy may hurt the hero again
        self.blade_ready = {}  # blade index -> seconds until that blade may hurt it


class Spark:
    def __init__(self, x, y, dx, dy, speed, damage, radius, max_travel):
        self.x = x
        self.y = y
        self.dx = dx
        self.dy = dy
        self.speed = speed
        self.damage = damage
        self.radius = radius
        self.traveled = 0.0
        self.max_travel = max_travel


class Gem:
    def __init__(self, x, y, xp):
        self.x = x
        self.y = y
        self.xp = xp


class World:
    def __init__(self, config, seed=None):
        self.config = config
        self.rng = random.Random(seed)

        hero = config["hero"]
        self.hero_x = 0.0
        self.hero_y = 0.0
        self.max_hp = float(hero["hp"])
        self.hp = float(hero["hp"])
        self.radius = hero["radius"]

        self.weapons = {"spark": 1}  # the hero starts with the Spark Wand
        self.passives = {}
        self.level = 1
        self.xp = 0
        self.pending_level_ups = 0
        self.cards = []

        self.enemies = []
        self.sparks = []
        self.gems = []
        self.time = 0.0
        self.kills = 0
        self.state = "running"  # "running", "choosing", "over" or "won"
        self.events = []  # what happened since main.py last looked

        # The hero walks toward this world point while it is far enough away.
        self.aim_x = None
        self.aim_y = None
        # Mouse mode: the aim is a screen pointer, so it is a world point that
        # moves with the hero (the pointer keeps its place on the screen).
        # Touch mode: the finger is a fixed world point; the hero walks to it.
        self.aim_follows_hero = True

        self._spawn_timer = 0.0
        self._bosses_spawned = set()  # a boss appears once per game, not once per second
        self._spark_cooldown = 0.0
        self._ring_cooldown = 0.0
        self._blade_phase = 0.0

    # --- numbers that come from the hero, his weapons and his passives ---

    def _passive_level(self, pid):
        return self.passives.get(pid, 0)

    def walk_speed(self):
        spec = self.config["passives"]["boots"]
        return self.config["hero"]["speed"] * (1 + spec["per_level"] * self._passive_level("boots"))

    def magnet_radius(self):
        spec = self.config["passives"]["magnet"]
        return self.config["hero"]["magnet_radius"] + spec["per_level"] * self._passive_level("magnet")

    def xp_needed(self):
        xp = self.config["xp"]
        return xp["first_need"] + xp["need_step"] * (self.level - 1)

    def weapon_level(self, wid):
        return self.weapons.get(wid, 0)

    def weapon_spec(self, wid):
        """The numbers for the level this weapon is at, or None if not owned."""
        level = self.weapons.get(wid)
        if not level:
            return None
        return self.config["weapons"][wid]["levels"][level - 1]

    def ring_radius(self):
        spec = self.weapon_spec("ring")
        return spec["radius"] if spec else 0

    # --- commands from main.py ---

    def set_aim(self, x, y):
        self.aim_x = x
        self.aim_y = y

    def stop(self):
        self.aim_x = None
        self.aim_y = None

    def clear_events(self):
        """main.py calls this once it has looked at the notes."""
        self.events = []

    def _record(self, kind, **details):
        self.events.append(dict(details, kind=kind))

    def choose_card(self, index):
        """Take one of the offered cards; the game only runs again when the
        last pending level-up is answered."""
        if self.state != "choosing" or not (0 <= index < len(self.cards)):
            return
        card = self.cards[index]
        kind = card["kind"]
        if kind == "heal":
            amount = self.config["heal_card"]["amount"]
            self.hp = min(self.hp + amount, self.max_hp)
        elif kind in ("new", "upgrade"):
            self.weapons[card["id"]] = card["level"]
        elif kind == "passive":
            pid = card["id"]
            self.passives[pid] = card["level"]
            if pid == "heart":
                gain = self.config["passives"]["heart"]["per_level"]
                self.max_hp += gain
                self.hp = min(self.hp + gain, self.max_hp)
        self.pending_level_ups -= 1
        if self.pending_level_ups > 0:
            self._open_cards()
        else:
            self.cards = []
            self.state = "running"

    # --- one fixed step ---

    def step(self, dt=STEP_TIME):
        if self.state != "running":
            return
        self.time += dt

        self._move_hero(dt)
        self._move_enemies(dt)
        self._fire_sparks(dt)
        self._move_sparks(dt)
        self._spin_blades(dt)
        self._pulse_ring(dt)
        self._collect_dead_enemies()
        self._move_gems(dt)
        self._spawn_tick(dt)
        self._spawn_bosses()
        self._keep_the_boss_close()
        self._despawn_far_enemies()

        if self.hp <= 0.0:
            self.hp = 0.0
            self.state = "over"
            self._record("over")
        elif self.time >= self.config["win_time"]:
            self.state = "won"
            self._record("won")
        elif self.pending_level_ups > 0:
            self._open_cards()

    def _move_hero(self, dt):
        if self.aim_x is None:
            return
        vx = self.aim_x - self.hero_x
        vy = self.aim_y - self.hero_y
        dist = math.hypot(vx, vy)
        stop_dist = self.config["controls"]["mouse_keep_walking_px"]
        if dist <= stop_dist:
            return
        step = min(self.walk_speed() * dt, dist)
        nx = self.hero_x + vx / dist * step
        ny = self.hero_y + vy / dist * step
        if self.aim_follows_hero:
            # A screen pointer keeps its place on the screen: slide the world
            # aim by the same offset, so the hero keeps walking while the
            # mouse does not move.
            self.aim_x += nx - self.hero_x
            self.aim_y += ny - self.hero_y
        self.hero_x = nx
        self.hero_y = ny

    def _move_enemies(self, dt):
        interval = self.config["enemy_hit_interval"]
        for e in self.enemies:
            e.hit_ready = max(0.0, e.hit_ready - dt)
            for blade in e.blade_ready:
                e.blade_ready[blade] = max(0.0, e.blade_ready[blade] - dt)
            vx = self.hero_x - e.x
            vy = self.hero_y - e.y
            dist = math.hypot(vx, vy)
            if dist > 0:
                step = self.config["enemy_types"][e.kind]["speed"] * dt
                e.x += vx / dist * step
                e.y += vy / dist * step
            if dist <= self.radius + e.radius and e.hit_ready <= 0.0:
                damage = self.config["enemy_types"][e.kind]["damage"]
                self.hp -= damage
                e.hit_ready = interval
                self._record("hurt", enemy=e.kind, damage=damage,
                             x=self.hero_x, y=self.hero_y)

    def _fire_sparks(self, dt):
        spec = self.config["weapons"]["spark"]
        level = self.weapon_spec("spark")
        self._spark_cooldown -= dt
        if level is None or self._spark_cooldown > 0 or not self.enemies:
            return
        self._spark_cooldown += level["interval"]
        shot = spec["projectile"]
        nearest = sorted(
            self.enemies,
            key=lambda e: (e.x - self.hero_x) ** 2 + (e.y - self.hero_y) ** 2,
        )
        for i in range(level["count"]):
            target = nearest[i % len(nearest)]
            vx = target.x - self.hero_x
            vy = target.y - self.hero_y
            dist = math.hypot(vx, vy) or 1.0
            self.sparks.append(
                Spark(
                    self.hero_x, self.hero_y,
                    vx / dist, vy / dist,
                    shot["speed"], level["damage"], shot["radius"], shot["max_distance"],
                )
            )

    def _move_sparks(self, dt):
        alive_sparks = []
        for s in self.sparks:
            step = s.speed * dt
            s.x += s.dx * step
            s.y += s.dy * step
            s.traveled += step
            hit = False
            for e in self.enemies:
                if e.hp <= 0:
                    continue
                if (e.x - s.x) ** 2 + (e.y - s.y) ** 2 <= (e.radius + s.radius) ** 2:
                    e.hp -= s.damage
                    self._record("hit", weapon="spark", damage=s.damage, x=e.x, y=e.y)
                    hit = True
                    break
            if not hit and s.traveled < s.max_travel:
                alive_sparks.append(s)
        self.sparks = alive_sparks

    def blade_positions(self):
        """Where the spinning blades are now, for both damage and drawing."""
        spec = self.config["weapons"]["blades"]
        level = self.weapon_spec("blades")
        if level is None:
            return []
        orbit = spec["orbit"]
        count = level["count"]
        return [
            (
                self.hero_x + math.cos(self._blade_phase + 2 * math.pi * i / count) * orbit["radius"],
                self.hero_y + math.sin(self._blade_phase + 2 * math.pi * i / count) * orbit["radius"],
            )
            for i in range(count)
        ]

    def _spin_blades(self, dt):
        spec = self.config["weapons"]["blades"]
        level = self.weapon_spec("blades")
        if level is None:
            return
        orbit = spec["orbit"]
        self._blade_phase += 2 * math.pi * dt / orbit["period"]
        for index, (bx, by) in enumerate(self.blade_positions()):
            for e in self.enemies:
                if e.hp <= 0 or e.blade_ready.get(index, 0.0) > 0:
                    continue
                reach = orbit["blade_radius"] + e.radius
                if (e.x - bx) ** 2 + (e.y - by) ** 2 <= reach * reach:
                    e.blade_ready[index] = orbit["hit_interval"]
                    e.hp -= level["damage"]
                    self._record("hit", weapon="blades", damage=level["damage"],
                                 x=e.x, y=e.y)

    def _pulse_ring(self, dt):
        level = self.weapon_spec("ring")
        self._ring_cooldown -= dt
        if level is None or self._ring_cooldown > 0:
            return
        self._ring_cooldown += level["interval"]
        reach = level["radius"] ** 2
        for e in self.enemies:
            if e.hp <= 0:
                continue  # already dead this step: the spark and blades do the same
            if (e.x - self.hero_x) ** 2 + (e.y - self.hero_y) ** 2 <= reach:
                e.hp -= level["damage"]
                self._record("hit", weapon="ring", damage=level["damage"], x=e.x, y=e.y)

    def _collect_dead_enemies(self):
        alive = []
        for e in self.enemies:
            if e.hp > 0:
                alive.append(e)
                continue
            self.kills += 1
            spec = self.config["enemy_types"][e.kind]
            self._record("death", enemy=e.kind, x=e.x, y=e.y,
                         radius=e.radius, boss=bool(spec.get("boss")))
            if spec["xp"] > 0:
                self.gems.append(Gem(e.x, e.y, spec["xp"]))
        self.enemies = alive

    def _move_gems(self, dt):
        magnet = self.magnet_radius()
        fly = self.config["gems"]["fly_speed"]
        kept = []
        for g in self.gems:
            vx = self.hero_x - g.x
            vy = self.hero_y - g.y
            dist = math.hypot(vx, vy)
            if dist <= self.radius:
                self._record("gem", xp=g.xp, x=self.hero_x, y=self.hero_y)
                self._add_xp(g.xp)
                continue
            if dist <= magnet:
                step = min(fly * dt, dist)
                g.x += vx / dist * step
                g.y += vy / dist * step
            kept.append(g)
        self.gems = kept

    def _add_xp(self, amount):
        self.xp += amount
        while self.xp >= self.xp_needed():
            self.xp -= self.xp_needed()
            self.level += 1
            self.pending_level_ups += 1
            self._record("level_up", level=self.level)

    # --- level-up cards ---

    def card_options(self):
        """Everything the hero may be offered: a new weapon (if he has fewer
        than three), +1 level for a weapon he has, or a passive item.
        Nothing already at level 5 is offered."""
        options = []
        for wid, spec in self.config["weapons"].items():
            level = self.weapons.get(wid, 0)
            if level == 0:
                if len(self.weapons) < self.config["max_weapons"]:
                    options.append(("new", wid, 1, spec))
            elif level < len(spec["levels"]):
                options.append(("upgrade", wid, level + 1, spec))
        for pid, spec in self.config["passives"].items():
            level = self.passives.get(pid, 0)
            if level < len(spec["levels"]):
                options.append(("passive", pid, level + 1, spec))
        return options

    def _make_card(self, option):
        kind, cid, level, spec = option
        if kind == "new":
            text = spec["levels"][0]["text"]
        else:
            text = spec["levels"][level - 1]["text"]
        return {
            "kind": kind,
            "id": cid,
            "label": spec["label"],
            "short": spec["short"],
            "level": level,
            "text": text,
        }

    def _open_cards(self):
        options = self.card_options()
        picked = self.rng.sample(options, min(3, len(options))) if options else []
        self.cards = [self._make_card(o) for o in picked]
        if self.config.get("heal_card") and len(self.cards) < 3:
            heal = self.config["heal_card"]
            while len(self.cards) < 3:
                self.cards.append({
                    "kind": "heal", "id": "heal", "label": heal["label"],
                    "short": heal["short"], "level": None, "text": heal["text"],
                })
        self.state = "choosing"

    # --- spawning ---

    def current_row(self):
        row = self.config["spawning"]["table"][0]
        for candidate in self.config["spawning"]["table"]:
            if self.time >= candidate["from"] - 1e-9:
                row = candidate
        return row

    def _spawn_tick(self, dt):
        self._spawn_timer += dt
        spawning = self.config["spawning"]
        if self._spawn_timer < spawning["every"]:
            return
        self._spawn_timer -= spawning["every"]
        row = self.current_row()
        budget = min(
            spawning["max_per_second"],
            spawning["max_alive"] - len(self.enemies),
        )
        for _ in range(max(0, budget)):
            if len(self.enemies) >= row["min_alive"]:
                break
            self._spawn_one(row["types"])

    def _spawn_point(self):
        """A random point on the circle just outside the screen."""
        angle = self.rng.uniform(0.0, 2.0 * math.pi)
        dist = self.config["spawning"]["circle_radius"]
        return self.hero_x + math.cos(angle) * dist, self.hero_y + math.sin(angle) * dist

    def _spawn_one(self, kinds):
        x, y = self._spawn_point()
        kind = self.rng.choice(kinds)
        spec = self.config["enemy_types"][kind]
        self.enemies.append(Enemy(kind, x, y, spec["hp"], spec["radius"]))

    def _spawn_bosses(self):
        """A row of the table can name a boss; it appears once, at that time."""
        for row in self.config["spawning"]["table"]:
            kind = row.get("boss")
            if not kind or kind in self._bosses_spawned:
                continue
            if self.time >= row["from"] - 1e-9:
                self._bosses_spawned.add(kind)
                spec = self.config["enemy_types"][kind]
                x, y = self._spawn_point()
                self.enemies.append(Enemy(kind, x, y, spec["hp"], spec["radius"]))

    def _keep_the_boss_close(self):
        """The boss is never removed: once it drifts too far it comes back to
        the spawn circle, so the fight cannot be avoided by running."""
        limit = self.config["spawning"]["boss_return_distance"]
        bosses = self._boss_kinds()
        for e in self.enemies:
            if e.kind in bosses and math.hypot(e.x - self.hero_x, e.y - self.hero_y) > limit:
                e.x, e.y = self._spawn_point()

    def _despawn_far_enemies(self):
        limit = self.config["spawning"]["despawn_distance"]
        bosses = self._boss_kinds()
        self.enemies = [
            e
            for e in self.enemies
            if e.kind in bosses
            or (e.x - self.hero_x) ** 2 + (e.y - self.hero_y) ** 2 <= limit * limit
        ]

    def _boss_kinds(self):
        return {k for k, v in self.config["enemy_types"].items() if v.get("boss")}
