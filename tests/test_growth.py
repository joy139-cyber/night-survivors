"""Tests for growth: gems, XP, level-up cards, all weapons and passive items."""

import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rules import STEP_TIME, Enemy, Gem, World  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "..", "data", "game.json"), encoding="utf-8") as f:
    CONFIG = json.load(f)


def make_world(seed=1):
    world = World(CONFIG, seed=seed)
    world.stop()
    world.enemies = []
    world.gems = []
    return world


def run_steps(world, n):
    for _ in range(n):
        world.step(STEP_TIME)


def pin_at(enemy, x, y):
    enemy.x = x
    enemy.y = y


class GemTests(unittest.TestCase):
    def test_a_dead_enemy_drops_its_xp_as_a_gem(self):
        world = make_world()
        world.weapons = {"spark": 1}
        bat = Enemy("bat", world.hero_x + 60, world.hero_y, 8, 10)
        world.enemies.append(bat)
        run_steps(world, 12)  # killed at about step 7, the gem is still flying in
        self.assertEqual(world.kills, 1)
        self.assertEqual(len(world.gems), 1)
        self.assertEqual(world.gems[0].xp, CONFIG["enemy_types"]["bat"]["xp"])
        self.assertEqual(world.xp, 0)
        run_steps(world, 15)  # the magnet radius covers it, so it arrives
        self.assertEqual(world.gems, [])
        self.assertEqual(world.xp, CONFIG["enemy_types"]["bat"]["xp"])

    def test_the_boss_drops_nothing(self):
        world = make_world()
        world.enemies.append(Enemy("demon", 5, 0, 0, 16))
        world._collect_dead_enemies()
        self.assertEqual(world.kills, 1)
        self.assertEqual(world.gems, [])

    def test_gem_inside_the_magnet_radius_flies_to_the_hero(self):
        world = make_world()
        magnet = CONFIG["hero"]["magnet_radius"]
        world.gems.append(Gem(world.hero_x + magnet - 5, world.hero_y, 1))
        start = world.gems[0].x
        run_steps(world, 6)
        self.assertLess(world.gems[0].x, start)

    def test_gem_outside_the_magnet_radius_stays(self):
        world = make_world()
        far = CONFIG["hero"]["magnet_radius"] + 100
        world.gems.append(Gem(world.hero_x + far, world.hero_y, 1))
        run_steps(world, 30)
        self.assertAlmostEqual(world.gems[0].x, world.hero_x + far, places=6)

    def test_collected_gem_adds_xp(self):
        world = make_world()
        world.gems.append(Gem(world.hero_x + 5, world.hero_y, 2))
        run_steps(world, 1)
        self.assertEqual(world.gems, [])
        self.assertEqual(world.xp, 2)


class XpTests(unittest.TestCase):
    def test_the_xp_curve_is_5_8_11(self):
        world = make_world()
        needs = []
        for level in (1, 2, 3):
            world.level = level
            needs.append(world.xp_needed())
        self.assertEqual(needs, [5, 8, 11])

    def test_xp_over_the_need_levels_up_and_carries_the_rest(self):
        world = make_world()
        world._add_xp(world.xp_needed() + 2)
        self.assertEqual(world.level, 2)
        self.assertEqual(world.xp, 2)

    def test_one_big_gain_can_earn_two_levels(self):
        world = make_world()
        world._add_xp(5 + 8)
        self.assertEqual(world.level, 3)
        self.assertEqual(world.pending_level_ups, 2)


class LevelUpTests(unittest.TestCase):
    def test_the_game_pauses_and_shows_three_cards(self):
        world = make_world()
        world.enemies.append(Enemy("bat", 1000, 0, 8, 10))
        world._add_xp(world.xp_needed())
        run_steps(world, 1)
        self.assertEqual(world.state, "choosing")
        self.assertEqual(len(world.cards), 3)

    def test_nothing_moves_while_a_card_is_shown(self):
        world = make_world()
        bat = Enemy("bat", world.hero_x + 200, world.hero_y, 999, 10)
        world.enemies.append(bat)
        world._add_xp(world.xp_needed())
        run_steps(world, 2)
        before = (bat.x, world.time)
        run_steps(world, 30)
        self.assertEqual((bat.x, world.time), before)

    def test_choosing_a_card_resumes_the_game(self):
        world = make_world()
        world._add_xp(world.xp_needed())
        run_steps(world, 1)
        world.choose_card(0)
        self.assertEqual(world.state, "running")
        self.assertEqual(world.pending_level_ups, 0)

    def test_two_level_ups_show_two_card_screens(self):
        world = make_world()
        world._add_xp(5 + 8)
        run_steps(world, 1)
        self.assertEqual(world.state, "choosing")
        world.choose_card(0)
        self.assertEqual(world.state, "choosing")  # the second one is still owed
        world.choose_card(0)
        self.assertEqual(world.state, "running")

    def test_a_new_weapon_card_gives_that_weapon_level_1(self):
        world = make_world()
        world._add_xp(world.xp_needed())
        run_steps(world, 1)
        new = next(c for c in world.cards if c["kind"] == "new")
        world.choose_card(world.cards.index(new))
        self.assertEqual(world.weapon_level(new["id"]), 1)

    def test_an_upgrade_card_raises_a_weapon_by_one_level(self):
        world = make_world()
        world._add_xp(world.xp_needed())
        run_steps(world, 1)
        up = next(c for c in world.cards if c["kind"] == "upgrade" and c["id"] == "spark")
        world.choose_card(world.cards.index(up))
        self.assertEqual(world.weapon_level("spark"), 2)

    def test_at_most_three_weapons(self):
        world = make_world()
        world.weapons = {"spark": 1, "blades": 1, "ring": 1}
        self.assertFalse(any(o[1] in ("spark", "blades", "ring") and o[0] == "new"
                             for o in world.card_options()))
        world._add_xp(world.xp_needed())
        run_steps(world, 1)
        self.assertEqual(len(world.weapons), 3)
        for card in world.cards:
            self.assertNotEqual(card["kind"], "new")

    def test_nothing_at_level_5_is_ever_offered(self):
        world = make_world()
        world.weapons = {wid: len(spec["levels"]) for wid, spec in CONFIG["weapons"].items()}
        world.passives = {pid: len(spec["levels"]) for pid, spec in CONFIG["passives"].items()}
        self.assertEqual(world.card_options(), [])
        world._add_xp(world.xp_needed())
        run_steps(world, 1)
        self.assertEqual([c["kind"] for c in world.cards], ["heal", "heal", "heal"])

    def test_heal_is_the_fallback(self):
        world = make_world()
        world.hp = 40
        world.weapons = {wid: len(spec["levels"]) for wid, spec in CONFIG["weapons"].items()}
        world.passives = {pid: len(spec["levels"]) for pid, spec in CONFIG["passives"].items()}
        world._add_xp(world.xp_needed())
        run_steps(world, 1)
        world.choose_card(0)
        self.assertEqual(world.hp, 40 + CONFIG["heal_card"]["amount"])

    def test_a_short_offer_is_padded_with_heal(self):
        world = make_world()
        world.weapons = {wid: len(spec["levels"]) for wid, spec in CONFIG["weapons"].items()}
        world.passives = {"boots": 5, "heart": 5, "magnet": 4}
        world._add_xp(world.xp_needed())
        run_steps(world, 1)
        self.assertEqual(len(world.cards), 3)
        self.assertEqual(sum(1 for c in world.cards if c["kind"] == "heal"), 2)


class PassiveTests(unittest.TestCase):
    def test_swift_boots_add_speed_every_level(self):
        world = make_world()
        base = CONFIG["hero"]["speed"]
        self.assertAlmostEqual(world.walk_speed(), base)
        world.passives["boots"] = 2
        self.assertAlmostEqual(world.walk_speed(), base * 1.2)

    def test_magnet_adds_radius_every_level(self):
        world = make_world()
        self.assertEqual(world.magnet_radius(), CONFIG["hero"]["magnet_radius"])
        world.passives["magnet"] = 1
        self.assertEqual(world.magnet_radius(), CONFIG["hero"]["magnet_radius"] + 30)

    def test_big_heart_adds_max_hp_and_heals(self):
        world = make_world()
        world.hp = 50
        world._add_xp(world.xp_needed())
        run_steps(world, 1)
        world.passives = {"boots": 5, "magnet": 5}
        world.weapons = {wid: len(spec["levels"]) for wid, spec in CONFIG["weapons"].items()}
        world._add_xp(world.xp_needed())
        run_steps(world, 1)
        heart = next(c for c in world.cards if c["id"] == "heart")
        world.choose_card(world.cards.index(heart))
        gain = CONFIG["passives"]["heart"]["per_level"]
        self.assertEqual(world.max_hp, CONFIG["hero"]["hp"] + gain)
        self.assertEqual(world.hp, 50 + gain)

    def test_big_heart_never_heals_above_the_new_max(self):
        world = make_world()
        world.hp = world.max_hp
        world.passives["heart"] = 1
        world.max_hp += 20
        world.hp = min(world.hp + 20, world.max_hp)
        self.assertEqual(world.hp, world.max_hp)


class SpinBladeTests(unittest.TestCase):
    def blade_world(self):
        world = make_world()
        world.weapons = {"blades": 1}
        enemy = Enemy("bat", 0, 0, 999, 10)
        world.enemies.append(enemy)
        return world, enemy

    def test_a_blade_hurts_an_enemy_it_touches(self):
        world, enemy = self.blade_world()
        damage = CONFIG["weapons"]["blades"]["levels"][0]["damage"]
        bx, by = world.blade_positions()[0]
        pin_at(enemy, bx, by)
        run_steps(world, 1)
        self.assertEqual(enemy.hp, 999 - damage)

    def test_blade_positions_sit_on_the_orbit_circle(self):
        world, _ = self.blade_world()
        positions = world.blade_positions()
        self.assertEqual(len(positions), CONFIG["weapons"]["blades"]["levels"][0]["count"])
        radius = CONFIG["weapons"]["blades"]["orbit"]["radius"]
        for x, y in positions:
            self.assertAlmostEqual((x - world.hero_x) ** 2 + (y - world.hero_y) ** 2,
                                   radius ** 2, delta=1)

    def test_the_same_blade_hurts_one_enemy_at_most_every_half_second(self):
        world, enemy = self.blade_world()
        damage = CONFIG["weapons"]["blades"]["levels"][0]["damage"]
        half_second = int(0.5 / STEP_TIME)
        for _ in range(half_second):  # pinned to blade 0 for 0.5 s
            bx, by = world.blade_positions()[0]
            pin_at(enemy, bx, by)
            world.step(STEP_TIME)
        self.assertEqual(enemy.hp, 999 - damage)  # still only the first hit
        for _ in range(half_second):  # and it lands again just after
            bx, by = world.blade_positions()[0]
            pin_at(enemy, bx, by)
            world.step(STEP_TIME)
        self.assertEqual(enemy.hp, 999 - 2 * damage)


class HolyRingTests(unittest.TestCase):
    def test_the_ring_hurts_every_enemy_inside_it_once_per_half_second(self):
        world = make_world()
        world.weapons = {"ring": 1}
        spec = CONFIG["weapons"]["ring"]["levels"][0]
        inside = Enemy("bat", 0, 0, 999, 10)
        outside = Enemy("bat", 0, 0, 999, 10)
        world.enemies.extend([inside, outside])
        for _ in range(60):  # 1 s, both held in place
            pin_at(inside, world.hero_x + spec["radius"] - 5, world.hero_y)
            pin_at(outside, world.hero_x + spec["radius"] + 30, world.hero_y)
            world.step(STEP_TIME)
        self.assertEqual(inside.hp, 999 - 2 * spec["damage"])
        self.assertEqual(outside.hp, 999)

    def test_a_bigger_ring_reaches_further(self):
        # an enemy 55 px away: outside the level 1 circle (50), inside level 2 (60)
        distance = CONFIG["weapons"]["ring"]["levels"][0]["radius"] + 5
        for level, expected_hp in ((1, 999), (2, 999 - CONFIG["weapons"]["ring"]["levels"][1]["damage"])):
            world = make_world()
            world.weapons = {"ring": level}
            enemy = Enemy("bat", world.hero_x + distance, world.hero_y, 999, 10)
            world.enemies.append(enemy)
            run_steps(world, 1)
            self.assertEqual(enemy.hp, expected_hp, f"ring level {level}")


class SparkWandGrowthTests(unittest.TestCase):
    def test_extra_sparks_arrive_at_levels_3_and_5(self):
        for level in (1, 2, 3, 4, 5):
            world = make_world()
            world.weapons = {"spark": level}
            for i in range(5):
                world.enemies.append(Enemy("bat", world.hero_x + 100 + 20 * i,
                                           world.hero_y, 999, 10))
            run_steps(world, 1)
            expected = CONFIG["weapons"]["spark"]["levels"][level - 1]["count"]
            self.assertEqual(len(world.sparks), expected, f"level {level}")

    def test_firing_gets_faster_with_levels(self):
        def volleys(level, seconds):
            world = make_world()
            world.weapons = {"spark": level}
            tough = 10 ** 9
            enemy = Enemy("bat", world.hero_x + 300, world.hero_y, tough, 10)
            world.enemies.append(enemy)
            run_steps(world, int(seconds / STEP_TIME))
            damage = CONFIG["weapons"]["spark"]["levels"][level - 1]["damage"]
            return round((tough - enemy.hp) / damage)

        self.assertGreater(volleys(5, 3.0), volleys(1, 3.0))

    def test_a_new_weapon_starts_firing_on_its_own(self):
        world = make_world()
        world.weapons = {}
        enemy = Enemy("bat", world.hero_x + 60, world.hero_y, 999, 10)
        world.enemies.append(enemy)
        run_steps(world, 30)
        self.assertEqual(world.sparks, [])
        self.assertEqual(enemy.hp, 999)

        world.weapons = {"blades": 1}
        pin_at(enemy, world.hero_x + 60, world.hero_y)
        run_steps(world, 2)
        self.assertLess(enemy.hp, 999)


if __name__ == "__main__":
    unittest.main()
