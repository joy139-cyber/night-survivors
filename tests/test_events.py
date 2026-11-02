"""Tests for the notes rules.py leaves in world.events (sound and feel).

The rules only say what happened; main.py decides what to play or draw.
These tests read the numbers from data/game.json, like the other test files.
"""

import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rules import STEP_TIME, Enemy, Gem, Spark, World  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "..", "data", "game.json"), encoding="utf-8") as f:
    CONFIG = json.load(f)


def make_world(seed=1, config=None):
    world = World(config or CONFIG, seed=seed)
    world.stop()
    world.enemies = []
    world.gems = []
    world.sparks = []
    world.weapons = {}
    world.hp = 10**9  # immortal unless the test wants damage
    world.clear_events()
    return world


def run_steps(world, n):
    for _ in range(n):
        world.step(STEP_TIME)


def only(world, kind):
    return [event for event in world.events if event["kind"] == kind]


class HitTests(unittest.TestCase):
    def test_a_spark_hit_is_recorded_with_its_damage(self):
        world = make_world()
        level = CONFIG["weapons"]["spark"]["levels"][0]
        shot = CONFIG["weapons"]["spark"]["projectile"]
        world.enemies.append(Enemy("bat", 30, 0, 10**9, 10))  # too tough to die
        world.sparks.append(
            Spark(0, 0, 1, 0, shot["speed"], level["damage"], shot["radius"],
                  shot["max_distance"]))
        run_steps(world, 5)
        hits = only(world, "hit")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["weapon"], "spark")
        self.assertEqual(hits[0]["damage"], level["damage"])

    def test_a_blade_hit_is_recorded_with_its_damage(self):
        world = make_world()
        world.weapons = {"blades": 1}
        level = CONFIG["weapons"]["blades"]["levels"][0]
        bx, by = world.blade_positions()[0]
        world.enemies.append(Enemy("bat", bx, by, 10**9, 10))
        world.step(STEP_TIME)
        hits = only(world, "hit")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["weapon"], "blades")
        self.assertEqual(hits[0]["damage"], level["damage"])

    def test_the_ring_records_one_hit_per_enemy_inside(self):
        world = make_world()
        world.weapons = {"ring": 1}
        level = CONFIG["weapons"]["ring"]["levels"][0]
        for x in (-(level["radius"] - 5), level["radius"] - 5,
                  -(level["radius"] + 5), level["radius"] + 5):
            world.enemies.append(Enemy("bat", x, 0, 10**9, 10))
        run_steps(world, 2)  # one pulse only: the cooldown is much longer
        hits = only(world, "hit")
        self.assertEqual(len(hits), 2)
        self.assertTrue(all(h["weapon"] == "ring" for h in hits))
        self.assertTrue(all(h["damage"] == level["damage"] for h in hits))

    def test_a_hit_notes_where_the_enemy_stood(self):
        world = make_world()
        world.weapons = {"ring": 1}
        world.enemies.append(Enemy("slime", 20, 5, 10**9, 12))
        world.step(STEP_TIME)
        hits = only(world, "hit")
        self.assertEqual(len(hits), 1)
        # The enemy has already walked a little in this same step.
        self.assertAlmostEqual(hits[0]["x"], world.enemies[0].x)
        self.assertAlmostEqual(hits[0]["y"], world.enemies[0].y)

    def test_a_dead_enemy_is_never_hit_again(self):
        world = make_world()
        world.weapons = {"ring": 1}
        world.enemies.append(Enemy("bat", 10, 0, 0, 10))  # a corpse inside the ring
        world._ring_cooldown = 0.0
        world._pulse_ring(STEP_TIME)
        self.assertEqual(only(world, "hit"), [])


class DeathTests(unittest.TestCase):
    def test_a_death_is_recorded_with_the_enemy_and_its_size(self):
        world = make_world()
        world.weapons = {"ring": 1}
        world.enemies.append(Enemy("bat", 40, -20, 1, 10))
        run_steps(world, 2)
        deaths = only(world, "death")
        self.assertEqual(len(deaths), 1)
        self.assertEqual(deaths[0]["enemy"], "bat")
        self.assertEqual(deaths[0]["radius"], 10)
        self.assertFalse(deaths[0]["boss"])

    def test_the_boss_death_is_marked_as_a_boss(self):
        world = make_world()
        world.weapons = {"ring": 1}
        world.enemies.append(Enemy("demon", 30, 30, 1, 16))
        run_steps(world, 2)
        deaths = only(world, "death")
        self.assertEqual(len(deaths), 1)
        self.assertTrue(deaths[0]["boss"])


class HurtTests(unittest.TestCase):
    def test_the_hero_getting_hurt_is_recorded(self):
        world = make_world()
        world.hp = 100.0
        damage = CONFIG["enemy_types"]["bat"]["damage"]
        world.enemies.append(Enemy("bat", 8, 0, 10**9, 10))
        world.step(STEP_TIME)
        hurts = only(world, "hurt")
        self.assertEqual(len(hurts), 1)
        self.assertEqual(hurts[0]["damage"], damage)
        self.assertEqual(hurts[0]["enemy"], "bat")
        self.assertEqual(world.hp, 100.0 - damage)

    def test_one_hurt_note_per_enemy_per_hit_interval(self):
        world = make_world()
        world.enemies.append(Enemy("bat", 10, 0, 10**9, 10))
        run_steps(world, 30)  # half a second: only the first hit is allowed
        self.assertEqual(len(only(world, "hurt")), 1)
        run_steps(world, 10)  # the next one is due
        self.assertEqual(len(only(world, "hurt")), 2)

    def test_two_enemies_hurt_twice_as_often(self):
        world = make_world()
        world.enemies.append(Enemy("bat", 10, 0, 10**9, 10))
        world.enemies.append(Enemy("slime", -10, 4, 10**9, 12))
        world.step(STEP_TIME)
        self.assertEqual(len(only(world, "hurt")), 2)


class GemAndLevelTests(unittest.TestCase):
    def test_a_collected_gem_is_recorded_with_its_xp(self):
        world = make_world()
        xp = CONFIG["enemy_types"]["slime"]["xp"]
        world.gems.append(Gem(0, 0, xp))
        world.step(STEP_TIME)
        gems = only(world, "gem")
        self.assertEqual(len(gems), 1)
        self.assertEqual(gems[0]["xp"], xp)
        self.assertEqual(world.xp, xp)

    def test_a_level_up_is_recorded_with_the_new_level(self):
        world = make_world()
        world._add_xp(CONFIG["xp"]["first_need"])
        ups = only(world, "level_up")
        self.assertEqual(len(ups), 1)
        self.assertEqual(ups[0]["level"], 2)

    def test_two_levels_at_once_record_two_notes(self):
        world = make_world()
        xp = CONFIG["xp"]
        two_levels = xp["first_need"] + (xp["first_need"] + xp["need_step"])
        world._add_xp(two_levels + 1)
        self.assertEqual([u["level"] for u in only(world, "level_up")], [2, 3])


class EndTests(unittest.TestCase):
    def test_dying_records_the_end(self):
        world = make_world()
        world.hp = 0.0
        world.step(STEP_TIME)
        self.assertEqual(world.state, "over")
        self.assertEqual([e["kind"] for e in world.events], ["over"])

    def test_surviving_to_the_goal_records_the_win(self):
        world = make_world()
        world.time = CONFIG["win_time"] - STEP_TIME
        world.step(STEP_TIME)
        self.assertEqual(world.state, "won")
        self.assertEqual([e["kind"] for e in world.events], ["won"])

    def test_dying_at_the_goal_is_still_a_loss(self):
        world = make_world()
        world.hp = 0.0
        world.time = CONFIG["win_time"]
        world.step(STEP_TIME)
        self.assertEqual(world.state, "over")
        self.assertEqual([e["kind"] for e in world.events], ["over"])


class EventListTests(unittest.TestCase):
    def test_events_stay_until_main_looks(self):
        world = make_world()
        world.enemies.append(Enemy("bat", 10, 0, 10**9, 10))
        self.assertEqual(world.events, [])
        world.step(STEP_TIME)
        self.assertEqual(len(world.events), 1)  # the first hurt
        run_steps(world, 2)  # step() adds to the list, it never clears it
        self.assertEqual(len(world.events), 1)
        world.clear_events()
        self.assertEqual(world.events, [])

    def test_a_paused_game_records_nothing(self):
        world = make_world()
        world.enemies.append(Enemy("bat", 10, 0, 10**9, 10))
        world.state = "choosing"
        run_steps(world, 5)
        self.assertEqual(world.events, [])

    def test_every_sound_in_the_config_has_an_event_behind_it(self):
        """data/game.json names a sound per event kind, so the rules must make it."""
        made = set()

        world = make_world()
        world.hp = 100.0
        world.weapons = {"ring": 1}
        world.enemies.append(Enemy("bat", 8, 0, 1, 10))  # hurts, then dies
        run_steps(world, 2)
        made.update(e["kind"] for e in world.events)

        world = make_world()
        world.gems.append(Gem(0, 0, CONFIG["xp"]["first_need"]))  # gem and level-up
        world.step(STEP_TIME)
        made.update(e["kind"] for e in world.events)

        world = make_world()
        world.hp = 0.0
        world.step(STEP_TIME)
        made.update(e["kind"] for e in world.events)

        world = make_world()
        world.time = CONFIG["win_time"] - STEP_TIME
        world.step(STEP_TIME)
        made.update(e["kind"] for e in world.events)

        missing = set(CONFIG["sounds"]) - made
        self.assertEqual(missing, set())


class ConfigNumberTests(unittest.TestCase):
    def test_a_damage_changed_in_the_data_shows_up_in_the_note(self):
        config = copy.deepcopy(CONFIG)
        config["weapons"]["spark"]["levels"][0]["damage"] = 99
        world = make_world(config=config)
        shot = config["weapons"]["spark"]["projectile"]
        world.enemies.append(Enemy("bat", 30, 0, 10**9, 10))
        world.sparks.append(Spark(0, 0, 1, 0, shot["speed"], 99, shot["radius"],
                                  shot["max_distance"]))
        run_steps(world, 5)
        self.assertEqual(only(world, "hit")[0]["damage"], 99)

    def test_the_sound_settings_are_usable(self):
        for kind in CONFIG["sounds"]:
            spec = CONFIG["sounds"][kind]
            self.assertTrue(spec["file"])
            self.assertGreater(spec["volume"], 0.0)
            self.assertLessEqual(spec["volume"], 1.0)
            self.assertGreaterEqual(spec["min_gap"], 0.0)


if __name__ == "__main__":
    unittest.main()
