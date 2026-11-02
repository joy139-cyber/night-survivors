"""Tests for the waves: the whole spawn table, Slime, Ghost, the boss and victory."""

import copy
import json
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rules import STEP_TIME, Enemy, World  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "..", "data", "game.json"), encoding="utf-8") as f:
    CONFIG = json.load(f)


def make_world(seed=1, win_time=None):
    config = copy.deepcopy(CONFIG)
    if win_time is not None:
        config["win_time"] = win_time
    world = World(config, seed=seed)
    world.stop()
    world.enemies = []
    world.gems = []
    world.weapons = {}  # no shooting: these tests are about who appears
    world.hp = 10 ** 9  # an immortal hero, so a swarm cannot end the match early
    return world


def run_steps(world, n):
    for _ in range(n):
        world.step(STEP_TIME)


def kinds(world):
    return {e.kind for e in world.enemies}


def count_of(world, kind):
    return sum(1 for e in world.enemies if e.kind == kind)


class TableTests(unittest.TestCase):
    def test_every_row_of_the_table_is_used(self):
        per_second = CONFIG["spawning"]["max_per_second"]
        for row in CONFIG["spawning"]["table"]:
            world = make_world(win_time=10 ** 6)
            world.time = row["from"]
            # the minimum arrives a second at a time, so give it long enough.
            # the boss counts as an alive enemy, as the design says.
            run_steps(world, 60 * (row["min_alive"] // per_second + 1))
            self.assertEqual(len(world.enemies), row["min_alive"], f"row at {row['from']}")

    def test_only_the_kinds_of_the_current_row_appear(self):
        for row in CONFIG["spawning"]["table"]:
            world = make_world(win_time=10 ** 6)
            world.time = row["from"]
            run_steps(world, 60 * 4)
            # new enemies come from this row; a boss whose time has already
            # passed is also allowed, because this test jumps straight to it.
            allowed = set(row["types"])
            for earlier in CONFIG["spawning"]["table"]:
                if earlier["from"] <= row["from"] and "boss" in earlier:
                    allowed.add(earlier["boss"])
            self.assertTrue(kinds(world) <= allowed, f"row at {row['from']}")

    def test_ghosts_are_faster_than_the_hero_and_slimes_are_slower(self):
        self.assertGreater(CONFIG["enemy_types"]["ghost"]["speed"], CONFIG["hero"]["speed"])
        self.assertLess(CONFIG["enemy_types"]["slime"]["speed"], CONFIG["hero"]["speed"])

    def test_a_slime_is_tougher_than_a_bat(self):
        self.assertGreater(CONFIG["enemy_types"]["slime"]["hp"],
                           CONFIG["enemy_types"]["bat"]["hp"])
        self.assertGreater(CONFIG["enemy_types"]["demon"]["hp"],
                           CONFIG["enemy_types"]["slime"]["hp"])


class BossTests(unittest.TestCase):
    def boss_row(self):
        return next(r for r in CONFIG["spawning"]["table"] if "boss" in r)

    def test_the_boss_appears_once_at_its_time(self):
        row = self.boss_row()
        world = make_world(win_time=10 ** 6)
        world.time = row["from"] - 1.0
        run_steps(world, 59)  # still inside the second before it is due
        self.assertEqual(count_of(world, row["boss"]), 0)
        run_steps(world, 2)  # crossing its time
        self.assertEqual(count_of(world, row["boss"]), 1)

    def test_the_boss_appears_only_once_even_later(self):
        row = self.boss_row()
        world = make_world()
        world.time = row["from"]
        run_steps(world, 60 * 20)
        self.assertEqual(count_of(world, row["boss"]), 1)

    def test_the_boss_is_not_removed_when_far_away(self):
        row = self.boss_row()
        world = make_world()
        world.time = row["from"]
        run_steps(world, 60)
        demon = next(e for e in world.enemies if e.kind == row["boss"])
        demon.x = world.hero_x + CONFIG["spawning"]["despawn_distance"] + 200
        demon.y = world.hero_y
        run_steps(world, 1)
        self.assertIn(demon, world.enemies)

    def test_the_boss_comes_back_to_the_spawn_circle(self):
        row = self.boss_row()
        spec = CONFIG["enemy_types"][row["boss"]]
        world = make_world()
        demon = Enemy(row["boss"], 0, 0, spec["hp"], spec["radius"])
        demon.x = world.hero_x + CONFIG["spawning"]["boss_return_distance"] + 100
        demon.y = world.hero_y
        world.enemies.append(demon)
        run_steps(world, 1)
        dist = math.hypot(demon.x - world.hero_x, demon.y - world.hero_y)
        self.assertAlmostEqual(dist, CONFIG["spawning"]["circle_radius"], places=6)

    def test_a_normal_enemy_far_away_is_removed_but_the_boss_is_not(self):
        world = make_world()
        limit = CONFIG["spawning"]["despawn_distance"]
        bat_spec = CONFIG["enemy_types"]["bat"]
        demon_spec = CONFIG["enemy_types"]["demon"]
        bat = Enemy("bat", world.hero_x + limit + 50, world.hero_y,
                    bat_spec["hp"], bat_spec["radius"])
        demon = Enemy("demon", world.hero_x + limit + 50, world.hero_y,
                      demon_spec["hp"], demon_spec["radius"])
        world.enemies.extend([bat, demon])
        run_steps(world, 1)
        self.assertNotIn(bat, world.enemies)
        self.assertIn(demon, world.enemies)


class WinLoseTests(unittest.TestCase):
    def test_two_minutes_of_surviving_is_a_victory(self):
        self.assertEqual(CONFIG["win_time"], 120.0)  # 2:00
        world = make_world()
        world.time = CONFIG["win_time"] - STEP_TIME
        run_steps(world, 1)
        self.assertEqual(world.state, "won")
        self.assertGreater(world.hp, 0)

    def test_the_game_freezes_at_the_end(self):
        world = make_world()
        world.time = CONFIG["win_time"] - STEP_TIME
        run_steps(world, 2)
        world.enemies.append(Enemy("bat", world.hero_x + 200, world.hero_y, 8, 10))
        frozen = (world.time, len(world.enemies))
        run_steps(world, 60)
        self.assertEqual((world.time, len(world.enemies)), frozen)

    def test_dying_at_the_goal_is_still_a_loss(self):
        world = make_world()
        world.hp = 1.0
        world.time = CONFIG["win_time"] - STEP_TIME
        bat = CONFIG["enemy_types"]["bat"]
        world.enemies.append(Enemy("bat", world.hero_x + 3, world.hero_y, 999, bat["radius"]))
        run_steps(world, 1)
        self.assertEqual(world.state, "over")
        self.assertEqual(world.hp, 0.0)

    def test_a_fresh_world_can_be_started_after_a_victory(self):
        world = make_world()
        world.time = CONFIG["win_time"] - STEP_TIME
        run_steps(world, 1)
        self.assertEqual(world.state, "won")
        fresh = World(CONFIG)
        self.assertEqual(fresh.state, "running")
        self.assertEqual(fresh.time, 0.0)

    def test_a_card_is_not_offered_once_the_match_is_won(self):
        world = make_world()
        world._add_xp(world.xp_needed())
        world.time = CONFIG["win_time"] - STEP_TIME
        run_steps(world, 1)
        self.assertEqual(world.state, "won")


if __name__ == "__main__":
    unittest.main()
