"""Make the short sound files the game plays.

Run this on your computer:  python make_sounds.py
It writes sounds/*.wav using only Python's standard library, so nothing has to
be installed. main.py only loads the finished files; it never imports this.
"""

import array
import math
import os
import random
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "sounds")
RATE = 22050  # samples per second; plenty for short beeps
MASTER = 0.9  # every file is made to peak at this loudness

_rng = random.Random(1)  # fixed seed: running the script twice gives the same files


def note(seconds, hz, to_hz=None, decay=20.0, volume=1.0):
    """One sine note that fades away. `to_hz` slides the pitch while it plays."""
    total = int(RATE * seconds)
    out = []
    phase = 0.0
    for i in range(total):
        t = i / RATE
        now = hz if to_hz is None else hz + (to_hz - hz) * (i / total)
        phase += 2.0 * math.pi * now / RATE
        out.append(math.sin(phase) * math.exp(-decay * t) * volume)
    return out


def hiss(seconds, decay=40.0, volume=1.0, soften=0.35):
    """Filtered noise: a soft knock rather than white static."""
    total = int(RATE * seconds)
    out = []
    prev = 0.0
    for i in range(total):
        raw = _rng.uniform(-1.0, 1.0) * math.exp(-decay * (i / RATE)) * volume
        prev = prev + soften * (raw - prev)  # one-pole low-pass
        out.append(prev)
    return out


def delay(seconds, samples):
    """Move a sound later in time by adding silence in front of it."""
    return [0.0] * int(RATE * seconds) + samples


def mix(*tracks):
    """Add tracks together; the result is as long as the longest one."""
    out = [0.0] * max(len(t) for t in tracks)
    for track in tracks:
        for i, sample in enumerate(track):
            out[i] += sample
    return out


def save(name, samples):
    peak = max(abs(s) for s in samples)
    if peak > 0:
        samples = [s * (MASTER / peak) for s in samples]
    pcm = array.array("h")
    for s in samples:
        pcm.append(int(round(max(-1.0, min(1.0, s)) * 32767)))
    path = os.path.join(OUT, name + ".wav")
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes(pcm.tobytes())
    print(f"{name}.wav {len(samples) / RATE:.2f} s -> {path}")


# --- the five things the game says, one short file each ---

def hit():
    """A spark or blade landing: a quick dry tick."""
    return mix(hiss(0.05, decay=90.0, volume=0.9),
               note(0.05, 1300, 800, decay=70.0, volume=0.5))


def gem():
    """Picking up XP: two bright notes going up."""
    return mix(note(0.09, 880, decay=28.0, volume=0.8),
               delay(0.05, note(0.11, 1320, decay=22.0, volume=0.8)))


def level_up():
    """A broken chord going up, so it feels like a step forward."""
    steps = [523.25, 659.25, 783.99, 1046.5]
    return mix(*[delay(i * 0.09, note(0.2, hz, decay=12.0, volume=0.9))
                 for i, hz in enumerate(steps)])


def hurt():
    """The hero takes damage: a low thud with the pitch falling."""
    return mix(note(0.22, 220, 90, decay=14.0, volume=0.9),
               hiss(0.12, decay=45.0, volume=0.7, soften=0.18))


def end():
    """GAME OVER: two notes falling, the last one left hanging."""
    return mix(note(0.3, 392, 330, decay=9.0, volume=0.9),
               delay(0.25, note(0.6, 262, 196, decay=5.0, volume=0.9)))


def win():
    """VICTORY: four notes going up and a bright pair on top at the end."""
    steps = [523.25, 659.25, 783.99, 1046.5]
    return mix(*[delay(i * 0.12, note(0.3, hz, decay=7.0, volume=0.9))
                 for i, hz in enumerate(steps)],
               delay(0.5, note(0.5, 1568, decay=6.0, volume=0.5)))


BUILDERS = {"hit": hit, "gem": gem, "level_up": level_up,
            "hurt": hurt, "end": end, "win": win}


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, build in BUILDERS.items():
        save(name, build())


if __name__ == "__main__":
    main()
