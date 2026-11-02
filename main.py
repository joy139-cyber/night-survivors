"""Night Survivors — window, drawing, sound and input.

The rules live in rules.py; this file only turns one World into pixels
and feeds it commands from the mouse or a finger.
"""

import asyncio
import json
import math
import os
import random
import sys

import pygame

from rules import STEP_TIME, World

HERE = os.path.dirname(os.path.abspath(__file__))

COLOR_SPARK = (255, 220, 90)
COLOR_BACKGROUND = (24, 26, 36)
COLOR_HP = (220, 70, 70)
COLOR_XP = (90, 150, 240)
COLOR_BAR_BG = (20, 20, 28)
COLOR_TEXT = (235, 235, 235)
COLOR_RING = (240, 230, 150)
COLOR_CARD = (44, 48, 66)
COLOR_CARD_EDGE = (150, 170, 220)
COLOR_NUMBER = (255, 255, 255)
COLOR_NUMBER_SHADOW = (30, 26, 22)
COLOR_FLASH = (255, 246, 205)


def load_config():
    with open(os.path.join(HERE, "data", "game.json"), encoding="utf-8") as f:
        return json.load(f)


def picture_files(config):
    """Every .png name the config refers to, from assets/ (made by make_assets.py)."""
    files = set(config["pictures"].values())
    files.add(config["hero"]["picture"])
    files.update(spec["picture"] for spec in config["enemy_types"].values())
    return files


def load_pictures(config):
    pictures = {}
    for name in picture_files(config):
        surface = pygame.image.load(os.path.join(HERE, "assets", name))
        pictures[name] = surface.convert_alpha()
    # The boss is drawn twice as big (scale_by keeps the pixels square).
    for spec in config["enemy_types"].values():
        scale = spec.get("picture_scale", 1)
        if scale != 1:
            pictures[spec["picture"]] = pygame.transform.scale_by(
                pictures[spec["picture"]], scale)
    return pictures


def screen_to_world(camera_x, camera_y, sx, sy):
    return camera_x + sx, camera_y + sy


def sound_file(name):
    """sounds/<name>.ogg if it is there, else sounds/<name>.wav, else None."""
    for ext in (".ogg", ".wav"):
        path = os.path.join(HERE, "sounds", name + ext)
        if os.path.exists(path):
            return path
    return None


def load_sounds(config):
    """The finished files from sounds/ (made by make_sounds.py)."""
    sounds = {}
    for kind, spec in config["sounds"].items():
        path = sound_file(spec["file"])
        if path is None:
            continue
        sound = pygame.mixer.Sound(path)
        sound.set_volume(spec["volume"])
        sounds[kind] = sound
    return sounds


class Jukebox:
    """Plays the sound a rule event asks for. The same sound never plays twice
    inside its `min_gap`, so a hundred bats dying is a beat, not a wall of noise."""

    def __init__(self, config, sounds):
        self.sounds = sounds
        self.gaps = {kind: spec["min_gap"] for kind, spec in config["sounds"].items()}
        self.last_played = {}
        self.plays = {}  # kind -> how often it really played (the headless check reads this)

    def play(self, kind):
        sound = self.sounds.get(kind)
        if sound is None:
            return
        now = pygame.time.get_ticks() / 1000.0
        if now - self.last_played.get(kind, -1e9) < self.gaps.get(kind, 0.0):
            return
        self.last_played[kind] = now
        self.plays[kind] = self.plays.get(kind, 0) + 1
        sound.play()


class Feel:
    """Damage numbers, the flash when an enemy dies, the shake when the hero is
    hurt. Everything here comes from the notes in world.events."""

    def __init__(self, config):
        self.config = config["feel"]
        self.numbers = []  # [x, y, text, age in seconds]
        self.flashes = []  # [x, y, enemy radius, age in seconds]
        self.shake = 0.0
        self.rng = random.Random()

    def reset(self):
        self.numbers = []
        self.flashes = []
        self.shake = 0.0

    def add(self, event):
        kind = event["kind"]
        if kind == "hit":
            self.numbers.append([event["x"], event["y"], str(event["damage"]), 0.0])
            most = self.config["damage_number"]["max_shown"]
            if len(self.numbers) > most:
                del self.numbers[:len(self.numbers) - most]
        elif kind == "death":
            self.flashes.append([event["x"], event["y"], event["radius"], 0.0])
        elif kind == "hurt":
            self.shake = self.config["hurt_shake"]["life"]

    def tick(self, dt):
        for item in self.numbers:
            item[3] += dt
        for item in self.flashes:
            item[3] += dt
        life = self.config["damage_number"]["life"]
        self.numbers = [n for n in self.numbers if n[3] < life]
        life = self.config["death_flash"]["life"]
        self.flashes = [f for f in self.flashes if f[3] < life]
        self.shake = max(0.0, self.shake - dt)

    def camera_offset(self):
        """The scene jumps a little while the shake is running, then settles."""
        if self.shake <= 0.0:
            return 0.0, 0.0
        spec = self.config["hurt_shake"]
        strength = spec["px"] * (self.shake / spec["life"])
        angle = self.rng.uniform(0.0, 2.0 * math.pi)
        return math.cos(angle) * strength, math.sin(angle) * strength

    def draw(self, screen, camera_x, camera_y, font):
        spec = self.config["death_flash"]
        life = spec["life"]
        for x, y, radius, age in self.flashes:
            grow = spec["start_scale"] + (spec["end_scale"] - spec["start_scale"]) * (age / life)
            r = max(1, round(radius * grow))
            alpha = round(spec["max_alpha"] * (1.0 - age / life))
            disc = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
            pygame.draw.circle(disc, (*COLOR_FLASH, alpha), (r, r), r)
            screen.blit(disc, (round(x - camera_x) - r, round(y - camera_y) - r))

        spec = self.config["damage_number"]
        life = spec["life"]
        for x, y, text, age in self.numbers:
            fade = age / life
            colour = tuple(
                round(COLOR_NUMBER[i] + (COLOR_BACKGROUND[i] - COLOR_NUMBER[i]) * fade)
                for i in range(3))
            px = round(x - camera_x) - 6
            py = round(y - camera_y - spec["rise_px"] * fade) - 12
            # A dark copy behind the white one, so it reads on the light floor.
            screen.blit(font.render(text, True, COLOR_NUMBER_SHADOW), (px + 1, py + 1))
            screen.blit(font.render(text, True, colour), (px, py))


def blit_center(surface, image, cx, cy):
    rect = image.get_rect(center=(round(cx), round(cy)))
    surface.blit(image, rect)


def clock_text(seconds):
    minutes = int(seconds) // 60
    return f"{minutes}:{int(seconds) % 60:02d}"


def card_rects(screen_size, count):
    """Three big cards, stacked, with a small gap."""
    w, h = screen_size
    card_w = w - 40
    card_h = 130
    gap = 16
    total = count * card_h + (count - 1) * gap
    top = (h - total) // 2
    return [
        pygame.Rect(20, top + i * (card_h + gap), card_w, card_h)
        for i in range(count)
    ]


def inventory_line(world, config):
    """What the hero has, e.g. 'Spark 2  Blades 1  Boots 1'."""
    parts = []
    for wid, level in world.weapons.items():
        parts.append(f"{config['weapons'][wid]['short']} {level}")
    for pid, level in world.passives.items():
        parts.append(f"{config['passives'][pid]['short']} {level}")
    return "  ".join(parts)


def card_at(world, pos, screen_size):
    """Which of the three level-up cards is under this screen point."""
    if world.state != "choosing":
        return None
    for i, rect in enumerate(card_rects(screen_size, len(world.cards))):
        if rect.collidepoint(pos):
            return i
    return None


def camera_of(world, screen_size):
    """The camera follows the hero, so the hero is always in the middle."""
    return world.hero_x - screen_size[0] / 2, world.hero_y - screen_size[1] / 2


def draw_scene(screen, world, config, pictures, font, big_font, small_font,
               feel=None, number_font=None):
    size = screen.get_size()
    camera_x, camera_y = camera_of(world, size)
    if feel is not None:
        dx, dy = feel.camera_offset()  # the whole scene jumps when the hero is hurt
        camera_x += dx
        camera_y += dy

    screen.fill(COLOR_BACKGROUND)
    draw_floor(screen, pictures[config["pictures"]["floor"]], camera_x, camera_y)

    for g in world.gems:
        blit_center(screen, pictures[config["pictures"][f"gem_xp_{g.xp}"]],
                    g.x - camera_x, g.y - camera_y)
    if world.weapon_level("ring"):
        pygame.draw.circle(screen, COLOR_RING,
                           (round(world.hero_x - camera_x), round(world.hero_y - camera_y)),
                           world.ring_radius(), 2)
    for e in world.enemies:
        blit_center(screen, pictures[config["enemy_types"][e.kind]["picture"]],
                    e.x - camera_x, e.y - camera_y)
    for s in world.sparks:
        pygame.draw.circle(screen, COLOR_SPARK,
                           (round(s.x - camera_x), round(s.y - camera_y)), s.radius)
    blit_center(screen, pictures[config["hero"]["picture"]],
                world.hero_x - camera_x, world.hero_y - camera_y)
    for bx, by in world.blade_positions():
        blit_center(screen, pictures[config["pictures"]["blade"]],
                    bx - camera_x, by - camera_y)

    if feel is not None:
        feel.draw(screen, camera_x, camera_y, number_font or font)

    # HUD: HP and XP bars plus the level, top left; time survived, top right.
    bar_w, bar_h = 140, 14
    pygame.draw.rect(screen, COLOR_BAR_BG, (10, 10, bar_w, bar_h))
    hp_frac = max(0.0, world.hp / world.max_hp)
    pygame.draw.rect(screen, COLOR_HP, (10, 10, round(bar_w * hp_frac), bar_h))
    pygame.draw.rect(screen, COLOR_BAR_BG, (10, 30, bar_w, bar_h))
    xp_frac = min(1.0, world.xp / world.xp_needed())
    pygame.draw.rect(screen, COLOR_XP, (10, 30, round(bar_w * xp_frac), bar_h))
    screen.blit(font.render(f"Lv {world.level}", True, COLOR_TEXT), (160, 22))
    goal = clock_text(config["win_time"])
    timer = font.render(f"{clock_text(world.time)} / {goal}", True, COLOR_TEXT)
    screen.blit(timer, (size[0] - timer.get_width() - 8, 8))
    screen.blit(small_font.render(inventory_line(world, config), True, COLOR_TEXT),
                (10, size[1] - 24))

    if world.state == "choosing":
        shade = pygame.Surface(size, pygame.SRCALPHA)
        shade.fill((0, 0, 0, 150))
        screen.blit(shade, (0, 0))
        title = big_font.render("LEVEL UP", True, COLOR_TEXT)
        screen.blit(title, ((size[0] - title.get_width()) // 2, 90))
        rects = card_rects(size, len(world.cards))
        for rect, card in zip(rects, world.cards):
            pygame.draw.rect(screen, COLOR_CARD, rect, border_radius=12)
            pygame.draw.rect(screen, COLOR_CARD_EDGE, rect, 2, border_radius=12)
            heading = (card["label"] if card["level"] is None
                       else f"{card['label']}  {card['level']}")
            screen.blit(font.render(heading, True, COLOR_TEXT), (rect.x + 18, rect.y + 18))
            screen.blit(font.render(card["text"], True, COLOR_TEXT), (rect.x + 18, rect.y + 58))
        hint = font.render("click or tap a card", True, COLOR_TEXT)
        screen.blit(hint, ((size[0] - hint.get_width()) // 2, rects[-1].bottom + 12))

    if world.state in ("over", "won"):
        shade = pygame.Surface(size, pygame.SRCALPHA)
        shade.fill((0, 0, 0, 170))
        screen.blit(shade, (0, 0))
        title = big_font.render(
            "VICTORY" if world.state == "won" else "GAME OVER", True, COLOR_TEXT)
        screen.blit(title, ((size[0] - title.get_width()) // 2, size[1] // 2 - 60))
        stats = font.render(
            f"time {clock_text(world.time)}  kills {world.kills}  level {world.level}",
            True, COLOR_TEXT)
        screen.blit(stats, ((size[0] - stats.get_width()) // 2, size[1] // 2))
        hint = font.render("click or tap to play again", True, COLOR_TEXT)
        screen.blit(hint, ((size[0] - hint.get_width()) // 2, size[1] // 2 + 40))


def draw_floor(surface, tile, camera_x, camera_y):
    """Repeat one tile forever: the map has no edges."""
    w, h = surface.get_size()
    size = tile.get_width()
    x0 = int(math.floor(camera_x / size))
    y0 = int(math.floor(camera_y / size))
    for gx in range(x0, x0 + w // size + 2):
        for gy in range(y0, y0 + h // size + 2):
            surface.blit(tile, (round(gx * size - camera_x), round(gy * size - camera_y)))


async def main(max_frames=0, shot_path=None):
    config = load_config()
    pygame.init()
    size = (config["screen"]["width"], config["screen"]["height"])
    screen = pygame.display.set_mode(size)
    pygame.display.set_caption("Night Survivors")
    clock = pygame.time.Clock()
    font = pygame.font.Font(None, 28)
    small_font = pygame.font.Font(None, 18)
    big_font = pygame.font.Font(None, 64)
    number_font = pygame.font.Font(None, config["feel"]["damage_number"]["font_px"])

    # A machine or a browser tab with no sound device still has to play.
    try:
        pygame.mixer.init()
        sounds = load_sounds(config)
    except pygame.error:
        sounds = {}
        print("no audio device: playing in silence")
    jukebox = Jukebox(config, sounds)
    feel = Feel(config)

    world = World(config, seed=None)
    pictures = load_pictures(config)
    camera_x, camera_y = camera_of(world, size)
    mouse_mode = True  # mouse gives the aim; a finger takes over while touching
    running = True
    acc = 0.0
    frames = 0
    last_state = world.state

    while running:
        if max_frames:
            # Headless check (SDL_VIDEODRIVER=dummy): post fake input so the
            # mouse, click and touch paths all run, then stop after N frames.
            if frames == 5:
                pygame.event.post(pygame.event.Event(
                    pygame.MOUSEMOTION, {"pos": (200, 200), "rel": (10, 10)}))
                pygame.event.post(pygame.event.Event(
                    pygame.MOUSEBUTTONDOWN, {"pos": (200, 200), "button": 1}))
            elif frames == 30:
                pygame.event.post(pygame.event.Event(
                    pygame.FINGERDOWN, {"finger_id": 0, "x": 0.3, "y": 0.7,
                                        "dx": 0.0, "dy": 0.0}))
                pygame.event.post(pygame.event.Event(
                    pygame.FINGERMOTION, {"finger_id": 0, "x": 0.4, "y": 0.6,
                                          "dx": 0.1, "dy": -0.1}))
            elif frames == 55:
                pygame.event.post(pygame.event.Event(
                    pygame.FINGERUP, {"finger_id": 0, "x": 0.4, "y": 0.6,
                                      "dx": 0.0, "dy": 0.0}))
            elif frames == 80:
                # Enough XP for one level: the card screen must open and pause.
                world._add_xp(world.xp_needed())
            elif frames == 86:
                centre = card_rects(size, len(world.cards))[1].center
                pygame.event.post(pygame.event.Event(
                    pygame.MOUSEBUTTONDOWN, {"pos": centre, "button": 1}))
            elif frames == 92:
                world._add_xp(world.xp_needed())
            elif frames == 98:
                world.hp = 1.0  # so a Heal card has something to heal
                centre = card_rects(size, len(world.cards))[0].center
                pygame.event.post(pygame.event.Event(
                    pygame.FINGERDOWN, {"finger_id": 0, "x": centre[0] / size[0],
                                        "y": centre[1] / size[1], "dx": 0.0, "dy": 0.0}))
                pygame.event.post(pygame.event.Event(
                    pygame.FINGERUP, {"finger_id": 0, "x": centre[0] / size[0],
                                      "y": centre[1] / size[1], "dx": 0.0, "dy": 0.0}))
            elif frames == max_frames - 12:
                # Reach the goal alive: the next step must show VICTORY.
                if world.state != "running":
                    world = World(config)
                    feel.reset()
                world.hp = 10**9
                world.time = config["win_time"] - 2 * STEP_TIME
            elif frames == max_frames - 10:
                pygame.event.post(pygame.event.Event(
                    pygame.MOUSEBUTTONDOWN, {"pos": (10, 10), "button": 1}))
            elif frames == max_frames - 6:
                world.hp = 0.0
            elif frames == max_frames - 4:
                pygame.event.post(pygame.event.Event(
                    pygame.FINGERUP, {"finger_id": 0, "x": 0.5, "y": 0.5,
                                      "dx": 0.0, "dy": 0.0}))
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.MOUSEMOTION and mouse_mode:
                if event.rel != (0, 0):  # a still pointer must not stop the hero
                    world.aim_follows_hero = True
                    wx, wy = screen_to_world(camera_x, camera_y, event.pos[0], event.pos[1])
                    world.set_aim(wx, wy)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if world.state in ("over", "won"):
                    world = World(config)
                    feel.reset()
                else:
                    index = card_at(world, event.pos, size)
                    if index is not None:
                        world.choose_card(index)
                    elif mouse_mode:
                        world.aim_follows_hero = True
                        wx, wy = screen_to_world(camera_x, camera_y, event.pos[0], event.pos[1])
                        world.set_aim(wx, wy)
            elif event.type == pygame.FINGERDOWN:
                mouse_mode = False
                world.aim_follows_hero = False
                wx, wy = screen_to_world(camera_x, camera_y,
                                         event.x * size[0], event.y * size[1])
                world.set_aim(wx, wy)
            elif event.type == pygame.FINGERMOTION and not mouse_mode:
                world.aim_follows_hero = False
                wx, wy = screen_to_world(camera_x, camera_y,
                                         event.x * size[0], event.y * size[1])
                world.set_aim(wx, wy)
            elif event.type == pygame.FINGERUP:
                if world.state in ("over", "won"):
                    world = World(config)
                    feel.reset()
                else:
                    index = card_at(world, (event.x * size[0], event.y * size[1]), size)
                    if index is not None:
                        world.choose_card(index)
                world.stop()
                mouse_mode = True

        # Fixed time step: run whole steps until the frame budget is used up.
        acc += clock.tick(60) / 1000.0
        while acc >= STEP_TIME:
            acc -= STEP_TIME
            world.step(STEP_TIME)
            for event in world.events:
                jukebox.play(event["kind"])
                feel.add(event)
            world.clear_events()
            feel.tick(STEP_TIME)

        # The camera follows the hero.
        camera_x, camera_y = camera_of(world, size)
        draw_scene(screen, world, config, pictures, font, big_font, small_font,
                   feel, number_font)

        pygame.display.flip()
        frames += 1
        if max_frames and world.state != last_state:
            offered = [c["short"] + (f" {c['level']}" if c["level"] else "")
                       for c in world.cards]
            print(f"  frame {frames}: {last_state} -> {world.state}"
                  + (f", cards {offered}" if offered else ""))
            last_state = world.state
        if max_frames:
            if frames == max_frames and shot_path:
                pygame.image.save(screen, shot_path)
            if frames >= max_frames:
                running = False
        await asyncio.sleep(0)

    pygame.quit()
    if max_frames:
        print(f"headless check ok: {frames} frames, "
              f"pictures {len(pictures)}, sounds {len(sounds)}, "
              f"played {dict(sorted(jukebox.plays.items()))}, "
              f"hero ({world.hero_x:.0f}, {world.hero_y:.0f}), "
              f"enemies {len(world.enemies)}, sparks {len(world.sparks)}, "
              f"gems {len(world.gems)}, kills {world.kills}, "
              f"lv {world.level} xp {world.xp}/{world.xp_needed()}, "
              f"has {inventory_line(world, config)}, "
              f"hp {world.hp:.0f}/{world.max_hp:.0f}, state {world.state}"
              + (f", shot -> {shot_path}" if shot_path else ""))


if __name__ == "__main__":
    if "--frames" in sys.argv:
        n = int(sys.argv[sys.argv.index("--frames") + 1])
        shot = None
        if "--shot" in sys.argv:
            shot = sys.argv[sys.argv.index("--shot") + 1]
        asyncio.run(main(max_frames=n, shot_path=shot))
    else:
        asyncio.run(main())
