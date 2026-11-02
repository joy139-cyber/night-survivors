"""Tests for the game rules in rules.py (no pygame, no drawing)."""

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


def make_world(seed=1):
    return World(CONFIG, seed=seed)


def run_steps(world, n):
    for _ in range(n):
        world.step(STEP_TIME)


class SpawningTests(unittest.TestCase):
    def test_reaches_minimum_after_two_seconds(self):
        # 12 needed but at most 8 per second, so the minimum arrives at t=2 s
        world = make_world()
        run_steps(world, 60)
        self.assertEqual(len(world.enemies), CONFIG["spawning"]["max_per_second"])
        run_steps(world, 60)
        minimum = CONFIG["spawning"]["table"][0]["min_alive"]
        self.assertEqual(len(world.enemies), minimum)

    def test_at_most_eight_per_second(self):
        world = make_world()
        run_steps(world, 60)
        self.assertLessEqual(len(world.enemies),
                             CONFIG["spawning"]["max_per_second"])

    def test_spawn_on_circle_around_hero(self):
        world = make_world()
        run_steps(world, 300)  # 5 seconds
        radius = CONFIG["spawning"]["circle_radius"]
        for e in world.enemies:
            d = math.hypot(e.x - world.hero_x, e.y - world.hero_y)
            self.assertLess(d, radius + 250)  # walked towards us since spawn

    def test_far_enemies_are_removed(self):
        world = make_world()
        limit = CONFIG["spawning"]["despawn_distance"]
        world.enemies.append(Enemy("bat", world.hero_x + limit + 50, world.hero_y, 8, 10))
        run_steps(world, 1)
        self.assertFalse(any(e.x > world.hero_x + limit for e in world.enemies))

    def test_never_more_than_max_alive(self):
        # Ask for more enemies than the cap so the cap is what we are testing,
        # and a win time far away so the match keeps running.
        config = copy.deepcopy(CONFIG)
        config["win_time"] = 1e9
        config["spawning"]["table"][-1]["min_alive"] = 200
        world = World(config, seed=1)
        world.weapons = {}
        world.hp = 10 ** 9  # an immortal hero, so we test the cap and not his death
        world.time = 200.0
        run_steps(world, 60 * 30)
        self.assertEqual(len(world.enemies), config["spawning"]["max_alive"])


class ContactDamageTests(unittest.TestCase):
    def test_touching_hero_costs_hp(self):
        world = make_world()
        world.stop()
        bat = CONFIG["enemy_types"]["bat"]
        world.enemies.append(Enemy("bat", world.hero_x + 3, world.hero_y, bat["hp"], bat["radius"]))
        run_steps(world, 1)
        self.assertAlmostEqual(world.hp, CONFIG["hero"]["hp"] - bat["damage"])

    def test_same_enemy_hits_at_most_once_per_half_second(self):
        world = make_world()
        world.stop()
        bat = CONFIG["enemy_types"]["bat"]
        e = Enemy("bat", world.hero_x + 3, world.hero_y, 999, bat["radius"])
        world.enemies.append(e)
        run_steps(world, 60)  # 1 second touching
        # at t=0 one hit, at t=0.5 one hit, at t=1.0 the third step happens
        # before the cooldown refreshes, so exactly 2 or 3 hits in 1 s
        hits = (CONFIG["hero"]["hp"] - world.hp) / bat["damage"]
        self.assertIn(hits, (2.0, 3.0))


class SparkWandTests(unittest.TestCase):
    def test_spark_kills_a_bat(self):
        world = make_world()
        world.stop()
        bat = CONFIG["enemy_types"]["bat"]
        target = Enemy("bat", world.hero_x + 60, world.hero_y, bat["hp"], bat["radius"])
        world.enemies.append(target)
        run_steps(world, 90)  # 1.5 s: fires at 0 s, spark reaches in ~0.15 s
        self.assertEqual(world.kills, 1)
        self.assertNotIn(target, world.enemies)

    def test_sparks_shoot_at_the_nearest_enemy(self):
        world = make_world()
        world.stop()
        far = Enemy("bat", world.hero_x + 300, world.hero_y, 8, 10)
        near = Enemy("bat", world.hero_x + 40, world.hero_y, 8, 10)
        world.enemies.extend([far, near])
        run_steps(world, int(0.05 / STEP_TIME))
        self.assertEqual(len(world.sparks), 1)
        s = world.sparks[0]
        self.assertGreater(s.dx, 0.99)  # straight towards the near bat on +x
        self.assertLess(abs(s.dy), 0.01)


class HeroTests(unittest.TestCase):
    def test_walks_to_a_fixed_touch_point_and_stops(self):
        world = make_world()  # touch mode: the finger is a fixed world point
        world.aim_follows_hero = False
        world.set_aim(100, 0)
        run_steps(world, 15)  # 0.25 s: 30 px
        self.assertAlmostEqual(world.hero_x, 30.0, places=6)
        run_steps(world, 60)
        self.assertLessEqual(abs(world.hero_x - 100.0),
                             CONFIG["controls"]["mouse_keep_walking_px"])

    def test_mouse_aim_keeps_its_distance_on_screen(self):
        world = make_world()  # mouse mode: the pointer keeps its screen place
        world.aim_follows_hero = True
        world.set_aim(100, 0)
        run_steps(world, 60)
        self.assertAlmostEqual(world.aim_x - world.hero_x, 100.0, places=6)
        self.assertGreater(world.hero_x, 0)  # he kept walking while it was far

    def test_stops_when_pointer_is_within_the_threshold(self):
        world = make_world()
        world.aim_follows_hero = True
        world.set_aim(10, 0)  # only 10 px away, less than the 12 px threshold
        run_steps(world, 60)
        self.assertEqual(world.hero_x, 0.0)

    def test_walks_to_the_point_and_does_not_overshoot(self):
        world = make_world()
        world.aim_follows_hero = False  # aim is a fixed world point
        world.set_aim(60, 0)
        run_steps(world, 60)  # 1 s at 120 px/s would overshoot
        self.assertLessEqual(abs(world.hero_x - 60.0),
                             CONFIG["controls"]["mouse_keep_walking_px"])
        self.assertLessEqual(world.hero_x, 60.0)


class GameOverTests(unittest.TestCase):
    def test_hp_zero_ends_the_game(self):
        world = make_world()
        world.hp = CONFIG["enemy_types"]["bat"]["damage"]
        world.stop()
        bat = CONFIG["enemy_types"]["bat"]
        world.enemies.append(Enemy("bat", world.hero_x + 3, world.hero_y, 999, bat["radius"]))
        run_steps(world, 1)
        self.assertEqual(world.state, "over")
        self.assertEqual(world.hp, 0.0)

    def test_a_new_world_can_be_started(self):
        world = make_world()
        world.hp = 0
        run_steps(world, 1)
        self.assertEqual(world.state, "over")
        fresh = World(CONFIG)
        self.assertEqual(fresh.state, "running")
        self.assertEqual(fresh.hp, CONFIG["hero"]["hp"])


if __name__ == "__main__":
    unittest.main()
