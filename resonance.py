#!/usr/bin/env python3
"""
RESONANCE: The Sightless Warden
================================
A full-screen, top-down acoustic radar stealth-survival terminal game.
Navigate lightless subterranean catacombs using echolocation and acoustic resonance.

Zero external dependencies. Python 3.10+ standard library only.
"""

from __future__ import annotations

import atexit
from collections import deque
from dataclasses import dataclass, field
import math
import os
import random
import shutil
import signal
import sys
import time
from typing import Dict, List, Optional, Set, Tuple

# Platform-specific non-blocking I/O imports
IS_POSIX = os.name == "posix"
if IS_POSIX:
    import select
    import termios
    import tty
else:
    import msvcrt


# ==============================================================================
# 1. TERMINAL CONTROLLER & COMPOSITOR
# ==============================================================================

class TerminalController:
    """Manages raw terminal I/O, cursor visibility, alternate buffer, and clean teardown."""

    def __init__(self) -> None:
        self.is_posix = IS_POSIX
        self.old_settings = None
        self.fd = sys.stdin.fileno() if sys.stdin.isatty() else None
        self.in_fullscreen = False

        # Register exit and signal hooks
        atexit.register(self.restore)
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, _signum, _frame) -> None:
        self.restore()
        sys.exit(0)

    def enter_fullscreen(self) -> None:
        """Enters alternate screen buffer, hides cursor, and configures non-blocking input."""
        if not self.in_fullscreen:
            # \033[?1049h: Alternate buffer
            # \033[?25l: Hide cursor
            # \033[2J: Clear screen
            # \033[H: Cursor home
            sys.stdout.write("\033[?1049h\033[?25l\033[2J\033[H")
            sys.stdout.flush()
            self.in_fullscreen = True

        if self.is_posix and self.fd is not None:
            try:
                self.old_settings = termios.tcgetattr(self.fd)
                tty.setcbreak(self.fd)
            except Exception:
                pass

    def restore(self) -> None:
        """Restores cursor, original terminal screen, styling, and terminal mode."""
        if self.is_posix and self.fd is not None and self.old_settings is not None:
            try:
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old_settings)
            except Exception:
                pass
            self.old_settings = None

        if self.in_fullscreen:
            # \033[?1049l: Exit alternate buffer
            # \033[?25h: Show cursor
            # \033[0m: Reset colors
            sys.stdout.write("\033[0m\033[?25h\033[?1049l")
            sys.stdout.flush()
            self.in_fullscreen = False

    def render(self, frame_buffer: str) -> None:
        """Flicker-free single-write rendering using cursor home."""
        sys.stdout.write("\033[H" + frame_buffer)
        sys.stdout.flush()


# ==============================================================================
# 2. NON-BLOCKING CROSS-PLATFORM INPUT
# ==============================================================================

class InputHandler:
    """Non-blocking input parser for WASD, Arrow keys, Space, E, Q, R, and ESC."""

    def __init__(self, controller: TerminalController) -> None:
        self.controller = controller
        self.last_key_time = 0.0

    def poll_keys(self) -> List[str]:
        keys: List[str] = []
        if IS_POSIX:
            if self.controller.fd is None:
                return keys
            while True:
                rlist, _, _ = select.select([sys.stdin], [], [], 0)
                if not rlist:
                    break
                try:
                    ch = sys.stdin.read(1)
                except Exception:
                    break

                if ch == "\x1b":
                    # Check for ANSI escape sequences (Arrow keys)
                    seq = ""
                    while True:
                        r2, _, _ = select.select([sys.stdin], [], [], 0.005)
                        if not r2:
                            break
                        seq += sys.stdin.read(1)

                    if seq == "[A":
                        keys.append("UP")
                    elif seq == "[B":
                        keys.append("DOWN")
                    elif seq == "[C":
                        keys.append("RIGHT")
                    elif seq == "[D":
                        keys.append("LEFT")
                    elif not seq:
                        keys.append("ESC")
                elif ch in ("w", "W"):
                    keys.append("UP")
                elif ch in ("s", "S"):
                    keys.append("DOWN")
                elif ch in ("a", "A"):
                    keys.append("LEFT")
                elif ch in ("d", "D"):
                    keys.append("RIGHT")
                elif ch == " ":
                    keys.append("SPACE")
                elif ch in ("e", "E"):
                    keys.append("THROW")
                elif ch in ("q", "Q", "\x03"):
                    keys.append("QUIT")
                elif ch in ("r", "R"):
                    keys.append("RESTART")
                elif ch in ("\r", "\n"):
                    keys.append("ENTER")
        else:
            # Windows msvcrt implementation
            while msvcrt.kbhit():
                ch = msvcrt.getch()
                if ch in (b"\x00", b"\xe0"):
                    code = msvcrt.getch()
                    if code == b"H":
                        keys.append("UP")
                    elif code == b"P":
                        keys.append("DOWN")
                    elif code == b"M":
                        keys.append("RIGHT")
                    elif code == b"K":
                        keys.append("LEFT")
                elif ch == b"\x1b":
                    keys.append("ESC")
                elif ch in (b"w", b"W"):
                    keys.append("UP")
                elif ch in (b"s", b"S"):
                    keys.append("DOWN")
                elif ch in (b"a", b"A"):
                    keys.append("LEFT")
                elif ch in (b"d", b"D"):
                    keys.append("RIGHT")
                elif ch == b" ":
                    keys.append("SPACE")
                elif ch in (b"e", b"E"):
                    keys.append("THROW")
                elif ch in (b"q", b"Q", b"\x03"):
                    keys.append("QUIT")
                elif ch in (b"r", b"R"):
                    keys.append("RESTART")
                elif ch in (b"\r", b"\n"):
                    keys.append("ENTER")

        return keys


# ==============================================================================
# 3. COLOR GRADING & PHOSPHOR LOOKUP TABLES
# ==============================================================================

def rgb(r: int, g: int, b: int) -> str:
    return f"\033[38;2;{r};{g};{b}m"

RESET = "\033[0m"
CLR_PLAYER = rgb(255, 235, 170)
CLR_PLAYER_HURT = rgb(255, 60, 60)
CLR_SPIRIT = "\033[38;2;80;240;220m"
CLR_RELIC = rgb(255, 215, 0)
CLR_EXIT_LOCKED = rgb(235, 45, 45)
CLR_EXIT_OPEN = rgb(50, 255, 130)
CLR_DECOY = rgb(240, 240, 255)
CLR_RIPPLE = rgb(180, 220, 255)

# Precomputed 16-level Phosphor CRT decay ramps for maximum performance
WALL_RAMP: List[str] = [
    " ",                                 # 0: Pitch black
    f"{rgb(45, 22, 10)}░",               # 1: Deepest sepia
    f"{rgb(60, 30, 14)}░",               # 2
    f"{rgb(80, 42, 18)}░",               # 3: Dark sepia
    f"{rgb(105, 55, 22)}▒",              # 4
    f"{rgb(130, 70, 28)}▒",              # 5: Muted bronze
    f"{rgb(155, 88, 35)}▒",              # 6
    f"{rgb(180, 108, 42)}▓",             # 7: Warm amber
    f"{rgb(205, 130, 52)}▓",             # 8
    f"{rgb(225, 155, 65)}▓",             # 9: Amber-gold
    f"{rgb(238, 175, 80)}▓",             # 10
    f"{rgb(245, 195, 100)}█",            # 11: Glowing gold
    f"{rgb(250, 210, 120)}█",            # 12
    f"{rgb(255, 225, 145)}█",            # 13: Bright gold
    f"{rgb(255, 235, 165)}█",            # 14
    f"{rgb(255, 245, 190)}█",            # 15: Brilliant bone-gold
]

FLOOR_RAMP_A: List[str] = [
    " ",                                 # 0: Pitch black
    " ",                                 # 1
    f"{rgb(35, 20, 8)}.",                # 2: Faint dust
    f"{rgb(50, 30, 12)}.",               # 3
    f"{rgb(70, 42, 16)}.",               # 4: Dim cobblestone
    f"{rgb(90, 56, 22)}.",               # 5
    f"{rgb(115, 72, 28)}·",              # 6: Amber flagstone
    f"{rgb(140, 90, 36)}·",              # 7
    f"{rgb(165, 110, 45)}·",             # 8: Warm flagstone
    f"{rgb(185, 128, 55)}·",             # 9
    f"{rgb(205, 148, 68)}·",             # 10: Bright amber
    f"{rgb(220, 165, 80)}·",             # 11
    f"{rgb(235, 185, 95)}·",             # 12: Illuminated floor
    f"{rgb(245, 200, 115)}·",            # 13
    f"{rgb(252, 215, 135)}·",            # 14
    f"{rgb(255, 230, 160)}·",            # 15: Radiant stone
]

FLOOR_RAMP_B: List[str] = [
    " ", " ",
    f"{rgb(30, 18, 8)}.",
    f"{rgb(45, 26, 10)}.",
    f"{rgb(65, 38, 14)}.",
    f"{rgb(85, 50, 20)}.",
    f"{rgb(105, 65, 26)}.",
    f"{rgb(130, 82, 32)}.",
    f"{rgb(155, 100, 40)}·",
    f"{rgb(175, 118, 50)}·",
    f"{rgb(195, 138, 62)}·",
    f"{rgb(212, 155, 74)}·",
    f"{rgb(228, 175, 88)}·",
    f"{rgb(240, 192, 108)}·",
    f"{rgb(248, 208, 128)}·",
    f"{rgb(255, 225, 150)}·",
]


# ==============================================================================
# 4. ACOUSTIC RADAR WAVE SYSTEM
# ==============================================================================

@dataclass
class AcousticWave:
    """Expanding circular acoustic shockwave with terminal aspect ratio correction."""
    cx: float
    cy: float
    current_r: float
    speed: float
    max_r: float
    energy: float
    wave_type: str  # 'fork', 'step', 'decoy', 'relic_hum', 'relic_burst', 'spirit_screech'
    heard_by: Set[int] = field(default_factory=set)
    alive: bool = True

    def update(self, dt: float) -> None:
        self.current_r += self.speed * dt
        if self.current_r >= self.max_r:
            self.alive = False

    def rasterize(self, light_buffer: List[List[float]], grid: List[List[str]], w: int, h: int) -> None:
        """Rasterizes the aspect-corrected ring onto the light buffer."""
        r = self.current_r
        if r < 0.2:
            ix, iy = int(round(self.cx)), int(round(self.cy))
            if 0 <= ix < w and 0 <= iy < h:
                light_buffer[iy][ix] = min(1.0, light_buffer[iy][ix] + self.energy)
            return

        r_sq = r * r
        # Acoustic attenuation: energy decays with distance traveled
        attenuation = self.energy / (1.0 + 0.035 * r)

        # 1. Row scan: for each vertical offset dy
        dy_limit = int(math.ceil(r))
        for dy in range(-dy_limit, dy_limit + 1):
            rem = r_sq - (dy * dy)
            if rem >= 0:
                # Terminal Aspect Ratio Correction formula:
                # dx_offset = math.sqrt(current_r^2 - dy^2) / 0.55
                dx = math.sqrt(rem) / 0.55
                y = int(round(self.cy + dy))
                if 0 <= y < h:
                    for sign in (-1.0, 1.0):
                        x = int(round(self.cx + sign * dx))
                        if 0 <= x < w:
                            boost = attenuation
                            # Acoustic reflection: hard granite catacomb walls reflect sound brilliantly
                            if grid[y][x] == "#":
                                boost *= 1.45
                            light_buffer[y][x] = min(1.0, light_buffer[y][x] + boost)

        # 2. Column scan: prevents horizontal gaps near poles
        dx_limit = int(math.ceil(r / 0.55))
        for dx_cell in range(-dx_limit, dx_limit + 1):
            rem = r_sq - ((dx_cell * 0.55) ** 2)
            if rem >= 0:
                dy_val = math.sqrt(rem)
                x = int(round(self.cx + dx_cell))
                if 0 <= x < w:
                    for sign in (-1.0, 1.0):
                        y = int(round(self.cy + sign * dy_val))
                        if 0 <= y < h:
                            boost = attenuation
                            if grid[y][x] == "#":
                                boost *= 1.45
                            light_buffer[y][x] = min(1.0, light_buffer[y][x] + boost)


# ==============================================================================
# 5. DECOY BONE-STONE PROJECTILE
# ==============================================================================

@dataclass
class BoneStone:
    """A thrown bone-stone pebble that travels along a vector and shatters on impact."""
    x: float
    y: float
    dx: float
    dy: float
    speed: float = 34.0
    distance_remaining: float = 18.0
    alive: bool = True

    def update(self, dt: float, grid: List[List[str]], w: int, h: int) -> Optional[Tuple[int, int]]:
        """Advances stone. Returns impact coordinates if stone strikes stone or expires."""
        travel = self.speed * dt
        steps = int(math.ceil(travel * 3))
        step_dt = travel / max(1, steps)

        for _ in range(steps):
            nx = self.x + self.dx * step_dt
            ny = self.y + self.dy * step_dt
            ix, iy = int(round(nx)), int(round(ny))

            self.distance_remaining -= step_dt

            # Check boundary collision or wall impact
            if ix < 1 or ix >= w - 1 or iy < 1 or iy >= h - 1 or grid[iy][ix] == "#":
                self.alive = False
                return (int(round(self.x)), int(round(self.y)))

            if self.distance_remaining <= 0:
                self.alive = False
                return (ix, iy)

            self.x = nx
            self.y = ny

        return None


# ==============================================================================
# 6. HOLLOW SPIRIT (HOLLOW ECHO) ENTITY & AI
# ==============================================================================

class HollowSpirit:
    """Starved ancestral spirit that stalks sound origins and shifts glyphs via sine wave."""

    GLYPHS = ["§", "ø", "✦", "~", "Ψ"]

    def __init__(self, spirit_id: int, x: float, y: float) -> None:
        self.id = spirit_id
        self.x = x
        self.y = y
        self.state = "patrol"  # 'patrol' or 'hunting'
        self.target_x = x
        self.target_y = y
        self.hunt_timer = 0.0
        self.phase = random.random() * math.pi * 2.0
        self.speed = 1.6
        self.patrol_timer = random.uniform(2.0, 5.0)

    def alert_to(self, sound_x: float, sound_y: float, wave_type: str) -> None:
        """Locks onto sound origin coordinate."""
        self.target_x = sound_x
        self.target_y = sound_y
        self.state = "hunting"
        if wave_type == "fork":
            self.hunt_timer = 9.0
            self.speed = 3.2
        elif wave_type == "decoy":
            self.hunt_timer = 7.5
            self.speed = 2.8
        elif wave_type == "step":
            self.hunt_timer = 5.0
            self.speed = 2.2
        else:
            self.hunt_timer = 4.0
            self.speed = 2.0

    def get_glyph(self, current_time: float) -> str:
        """Calculates floating sine glyph animation."""
        osc = math.sin(current_time * 4.5 + self.phase)
        idx = int((osc + 1.0) * 0.5 * len(self.GLYPHS)) % len(self.GLYPHS)
        return self.GLYPHS[idx]

    def update(self, dt: float, grid: List[List[str]], w: int, h: int, player_pos: Tuple[int, int]) -> None:
        if self.state == "hunting":
            self.hunt_timer -= dt
            if self.hunt_timer <= 0:
                self.state = "patrol"
                self.speed = 1.6
                self.patrol_timer = random.uniform(2.0, 4.0)

        elif self.state == "patrol":
            self.patrol_timer -= dt
            if self.patrol_timer <= 0:
                self.patrol_timer = random.uniform(3.0, 6.0)
                # Pick a random nearby floor point
                for _ in range(12):
                    rx = int(self.x + random.randint(-12, 12))
                    ry = int(self.y + random.randint(-8, 8))
                    if 1 <= rx < w - 1 and 1 <= ry < h - 1 and grid[ry][rx] == ".":
                        self.target_x = float(rx)
                        self.target_y = float(ry)
                        break

        # Move smoothly toward target
        vx = self.target_x - self.x
        vy = self.target_y - self.y
        dist = math.hypot(vx, vy)

        if dist > 0.4:
            move_dist = self.speed * dt
            step_x = (vx / dist) * move_dist
            step_y = (vy / dist) * move_dist

            nx = self.x + step_x
            ny = self.y + step_y
            ix, iy = int(round(nx)), int(round(ny))

            # Wall sliding and corridor gliding
            if 0 <= ix < w and 0 <= iy < h and grid[iy][ix] == ".":
                self.x = nx
                self.y = ny
            else:
                # Try horizontal slide
                if 0 <= ix < w and grid[int(round(self.y))][ix] == ".":
                    self.x = nx
                # Try vertical slide
                elif 0 <= iy < h and grid[iy][int(round(self.x))] == ".":
                    self.y = ny
                else:
                    # Slow ethereal phase through obstacle (incorporeal spirit)
                    self.x += step_x * 0.35
                    self.y += step_y * 0.35


# ==============================================================================
# 7. PROCEDURAL CATACOMB GENERATOR
# ==============================================================================

class CatacombGenerator:
    """Generates gothic subterranean vaults, pillars, arches, and guarantees connectivity."""

    @staticmethod
    def generate(w: int, h: int) -> Tuple[List[List[str]], Tuple[int, int], List[Tuple[int, int]], Tuple[int, int]]:
        grid = [["#"] * w for _ in range(h)]

        # 1. Carve major gothic burial chambers and crypt chapels
        chambers: List[Tuple[int, int, int, int]] = []
        num_chambers = max(5, (w * h) // 320)

        for _ in range(num_chambers * 2):
            cw = random.randint(8, 16)
            ch = random.randint(6, 11)
            cx = random.randint(2, w - cw - 3)
            cy = random.randint(2, h - ch - 3)

            # Avoid tight overlaps
            overlaps = False
            for ocx, ocy, ocw, och in chambers:
                if not (cx + cw + 1 < ocx or cx > ocx + ocw + 1 or cy + ch + 1 < ocy or cy > ocy + och + 1):
                    overlaps = True
                    break

            if not overlaps or len(chambers) < 4:
                chambers.append((cx, cy, cw, ch))
                for y in range(cy, cy + ch):
                    for x in range(cx, cx + cw):
                        grid[y][x] = "."
                if len(chambers) >= num_chambers:
                    break

        # Fallback if few chambers were carved
        if len(chambers) < 3:
            chambers.append((4, 4, 12, 8))
            chambers.append((w - 18, h - 12, 12, 8))
            for cx, cy, cw, ch in chambers:
                for y in range(cy, cy + ch):
                    for x in range(cx, cx + cw):
                        grid[y][x] = "."

        # 2. Carve gothic vaulted colonnades & corridors between chambers
        for i in range(len(chambers)):
            c1 = chambers[i]
            c2 = chambers[(i + 1) % len(chambers)]
            x1, y1 = c1[0] + c1[2] // 2, c1[1] + c1[3] // 2
            x2, y2 = c2[0] + c2[2] // 2, c2[1] + c2[3] // 2

            cur_x, cur_y = x1, y1
            while cur_x != x2:
                grid[cur_y][cur_x] = "."
                if cur_y + 1 < h - 1:
                    grid[cur_y + 1][cur_x] = "."
                cur_x += 1 if x2 > cur_x else -1

            while cur_y != y2:
                grid[cur_y][cur_x] = "."
                if cur_x + 1 < w - 1:
                    grid[cur_y][cur_x + 1] = "."
                cur_y += 1 if y2 > cur_y else -1

        # 3. Insert grid-aligned gothic pillars with vaulted arch openings
        for y in range(3, h - 3, 3):
            for x in range(5, w - 5, 5):
                if grid[y][x] == "." and random.random() < 0.65:
                    # Place pillar if surrounding area has walking clearance
                    open_neighbors = sum(
                        1 for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                        if grid[y + dy][x + dx] == "."
                    )
                    if open_neighbors >= 6:
                        grid[y][x] = "#"

        # 4. Designate Player Spawn in first chamber with guaranteed 5x5 clearing
        px = chambers[0][0] + chambers[0][2] // 2
        py = chambers[0][1] + chambers[0][3] // 2
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                sx = px + dx
                sy = py + dy
                if 1 <= sx < w - 1 and 1 <= sy < h - 1:
                    grid[sy][sx] = "."

        # 5. Flood-fill from Player Spawn to eliminate isolated islands
        reachable = set()
        queue = deque([(px, py)])
        reachable.add((px, py))

        while queue:
            cx, cy = queue.popleft()
            for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if 1 <= nx < w - 1 and 1 <= ny < h - 1 and grid[ny][nx] == "." and (nx, ny) not in reachable:
                    reachable.add((nx, ny))
                    queue.append((nx, ny))

        # Turn all unreachable floor cells into solid boundary walls
        for y in range(h):
            for x in range(w):
                if grid[y][x] == "." and (x, y) not in reachable:
                    grid[y][x] = "#"

        # 6. Distribute 3 Harmonic Relics and 1 Sanctum Bell-Gate
        # Calculate distances from player spawn to all reachable tiles
        dist_map: Dict[Tuple[int, int], int] = {(px, py): 0}
        q2 = deque([(px, py)])
        while q2:
            cx, cy = q2.popleft()
            cd = dist_map[(cx, cy)]
            for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if (nx, ny) in reachable and (nx, ny) not in dist_map:
                    dist_map[(nx, ny)] = cd + 1
                    q2.append((nx, ny))

        # Sort reachable tiles by distance from player
        sorted_tiles = sorted(dist_map.keys(), key=lambda t: dist_map[t], reverse=True)

        # Place Bell-Gate at the furthest reachable sanctuary
        gate_pos = sorted_tiles[0]

        # Place 3 Relics well-separated across different map quadrants
        relics: List[Tuple[int, int]] = []
        candidates = [t for t in sorted_tiles if dist_map[t] >= 14 and t != gate_pos]
        random.shuffle(candidates)

        for cand in candidates:
            if len(relics) >= 3:
                break
            # Ensure candidate is well-separated from already selected relics and gate
            far_enough = True
            for rx, ry in relics + [gate_pos]:
                if math.hypot(cand[0] - rx, cand[1] - ry) < (w // 5):
                    far_enough = False
                    break
            if far_enough:
                relics.append(cand)

        # Fallback if strict separation was impossible
        if len(relics) < 3:
            for cand in candidates:
                if cand not in relics and cand != gate_pos:
                    relics.append(cand)
                    if len(relics) == 3:
                        break

        return grid, (px, py), relics, gate_pos


# ==============================================================================
# 8. TELEMETRY NARRATIVE SYSTEM
# ==============================================================================

class TelemetryLog:
    """Atmospheric dynamic narrative log with event prioritization and idle ambiance."""

    IDLE_MESSAGES = [
        "The darkness is absolute. Only sound reveals the ancient stone.",
        "Cold subterranean air drafts through vaulted ribs above.",
        "Distant water droplets pit-pat against age-worn flagstones.",
        "Faint bone dust drifts from fractured gothic arches.",
        "The tuning fork hums faintly with stored harmonic tension.",
        "Deep vibrations hum through the bedrock beneath your soles.",
    ]

    def __init__(self) -> None:
        self.current_text = "Darkness is absolute. Tread softly [WASD] or strike the bell [SPACE] to see."
        self.priority = 10
        self.timer = 8.0
        self.idle_cooldown = 4.0

    def log(self, text: str, priority: int = 1, duration: float = 3.5) -> None:
        """Pushes a narrative message if its priority exceeds or matches current message."""
        if priority >= self.priority or self.timer <= 0.2:
            self.current_text = text
            self.priority = priority
            self.timer = duration
            self.idle_cooldown = 4.0

    def update(self, dt: float) -> None:
        self.timer -= dt
        if self.timer <= 0:
            self.priority = 0
            self.idle_cooldown -= dt
            if self.idle_cooldown <= 0:
                self.current_text = random.choice(self.IDLE_MESSAGES)
                self.timer = 5.5
                self.idle_cooldown = 5.0

    def get_text(self) -> str:
        return self.current_text


# ==============================================================================
# 9. MAIN GAME ORCHESTRATOR
# ==============================================================================

class ResonanceGame:
    """The complete acoustic radar stealth-survival game loop."""

    def __init__(self) -> None:
        self.term = TerminalController()
        self.input = InputHandler(self.term)

        # Query full-screen terminal size
        tw, th = shutil.get_terminal_size((120, 40))
        self.term_w = max(60, tw)
        self.term_h = max(24, th)

        # Grid fills entire terminal, reserving 3 rows for HUD footer
        self.map_w = self.term_w
        self.map_h = self.term_h - 3

        # Phosphor CRT decay buffer
        self.light_buffer = [[0.0] * self.map_w for _ in range(self.map_h)]

        # State machine
        self.game_state = "TITLE"  # 'TITLE', 'PLAYING', 'GAME_OVER', 'VICTORY'
        self.telemetry = TelemetryLog()

        # Gameplay entities & variables
        self.grid: List[List[str]] = []
        self.player_x = 0
        self.player_y = 0
        self.player_facing = (1, 0)
        self.player_hp = 100
        self.player_decoys = 3
        self.fork_cooldown = 0.0
        self.fork_max_cooldown = 4.5
        self.invulnerable_timer = 0.0
        self.damage_flash = 0
        self.relics_collected = 0
        self.relic_positions: List[Tuple[int, int]] = []
        self.relic_hum_timers: List[float] = [0.0, 1.3, 2.6]
        self.gate_pos = (0, 0)

        self.waves: List[AcousticWave] = []
        self.projectiles: List[BoneStone] = []
        self.spirits: List[HollowSpirit] = []

        # Statistics
        self.steps_taken = 0
        self.fork_strikes = 0
        self.decoys_thrown = 0
        self.start_time = 0.0
        self.elapsed_time = 0.0

        # Step limiter to give footsteps a rhythmic, tactile cadence
        self.move_cooldown = 0.0

    def init_catacombs(self) -> None:
        """Procedurally initializes a new catacomb map and entities."""
        self.grid, spawn, self.relic_positions, self.gate_pos = CatacombGenerator.generate(self.map_w, self.map_h)
        self.player_x, self.player_y = spawn
        self.player_facing = (1, 0)
        self.player_hp = 100
        self.player_decoys = 3
        self.fork_cooldown = 0.0
        self.invulnerable_timer = 0.0
        self.damage_flash = 0
        self.relic_collected_flags = [False] * len(self.relic_positions)
        self.relics_collected = 0
        self.waves.clear()
        self.projectiles.clear()
        self.spirits.clear()

        # Reset light buffer
        self.light_buffer = [[0.0] * self.map_w for _ in range(self.map_h)]

        # Spawn 5 Hollow Spirits in distant wings of the catacombs
        num_spirits = 5
        spawn_candidates = []
        for y in range(2, self.map_h - 2):
            for x in range(2, self.map_w - 2):
                if self.grid[y][x] == "." and math.hypot(x - self.player_x, y - self.player_y) > 18:
                    spawn_candidates.append((x, y))

        random.shuffle(spawn_candidates)
        for i in range(min(num_spirits, len(spawn_candidates))):
            sx, sy = spawn_candidates[i]
            self.spirits.append(HollowSpirit(spirit_id=i, x=float(sx), y=float(sy)))

        self.steps_taken = 0
        self.fork_strikes = 0
        self.decoys_thrown = 0
        self.start_time = time.perf_counter()
        self.elapsed_time = 0.0

        # Initial subtle welcome ripple
        self.waves.append(AcousticWave(
            cx=float(self.player_x),
            cy=float(self.player_y),
            current_r=0.0,
            speed=16.0,
            max_r=7.0,
            energy=0.5,
            wave_type="step"
        ))

    def trigger_tuning_fork(self) -> None:
        """Strikes the sacred tuning fork, casting a massive radar shockwave."""
        if self.fork_cooldown > 0:
            self.telemetry.log(f"Tuning fork still resonates... [{self.fork_cooldown:.1f}s]", priority=2, duration=1.5)
            return

        self.fork_cooldown = self.fork_max_cooldown
        self.fork_strikes += 1

        max_reach = math.hypot(self.map_w * 0.55, self.map_h) * 1.15
        self.waves.append(AcousticWave(
            cx=float(self.player_x),
            cy=float(self.player_y),
            current_r=0.0,
            speed=32.0,
            max_r=max_reach,
            energy=1.0,
            wave_type="fork"
        ))
        self.telemetry.log("★ RESONANCE! Tuning fork struck — a piercing chime cascades through the crypt!", priority=5, duration=4.0)

    def throw_decoy(self) -> None:
        """Hurls a bone-stone pebble in facing direction to lure spirits away."""
        if self.player_decoys <= 0:
            self.telemetry.log("No bone-stones remaining in your pouch!", priority=3, duration=2.0)
            return

        self.player_decoys -= 1
        self.decoys_thrown += 1
        fx, fy = self.player_facing
        if fx == 0 and fy == 0:
            fx, fy = 1, 0

        self.projectiles.append(BoneStone(
            x=float(self.player_x),
            y=float(self.player_y),
            dx=float(fx),
            dy=float(fy),
            speed=32.0,
            distance_remaining=18.0
        ))
        self.telemetry.log("Bone-stone hurled forward into the dark...", priority=3, duration=2.0)

    def step_player(self, dx: int, dy: int) -> None:
        """Moves the monk softly, producing a faint footstep ripple."""
        self.player_facing = (dx, dy)
        nx = self.player_x + dx
        ny = self.player_y + dy

        if 0 <= nx < self.map_w and 0 <= ny < self.map_h and self.grid[ny][nx] == ".":
            self.player_x = nx
            self.player_y = ny
            self.steps_taken += 1

            # Emit tiny footstep ripple
            self.waves.append(AcousticWave(
                cx=float(self.player_x),
                cy=float(self.player_y),
                current_r=0.0,
                speed=15.0,
                max_r=5.5,
                energy=0.35,
                wave_type="step"
            ))

            # Check Relic collection
            for idx, rpos in enumerate(self.relic_positions):
                if not self.relic_collected_flags[idx] and (self.player_x, self.player_y) == rpos:
                    self.relic_collected_flags[idx] = True
                    self.relics_collected += 1
                    self.player_hp = min(100, self.player_hp + 25)
                    self.player_decoys += 1

                    # Radiant golden burst wave
                    self.waves.append(AcousticWave(
                        cx=float(self.player_x),
                        cy=float(self.player_y),
                        current_r=0.0,
                        speed=26.0,
                        max_r=28.0,
                        energy=1.0,
                        wave_type="relic_burst"
                    ))

                    if self.relics_collected < 3:
                        self.telemetry.log(
                            f"★ Harmonic Relic retrieved [{self.relics_collected}/3]! Resonant warmth heals +25 HP.",
                            priority=6, duration=4.5
                        )
                    else:
                        self.telemetry.log(
                            "★ ALL 3 RELICS RESTORED! The Sanctum Bell-Gate [Ω] unseals in brilliant green!",
                            priority=8, duration=6.0
                        )

            # Check Sanctum Bell-Gate
            if (self.player_x, self.player_y) == self.gate_pos:
                if self.relics_collected >= 3:
                    self.game_state = "VICTORY"
                    self.telemetry.log("THE SANCTUM BELL TOLLS! Darkness is sealed away forever.", priority=10, duration=10.0)
                else:
                    self.telemetry.log(
                        f"The Sanctum Bell-Gate [Ω] is locked. Recover all 3 Harmonic Relics! ({self.relics_collected}/3)",
                        priority=4, duration=3.0
                    )
        else:
            # Subtle cane tap against wall
            self.waves.append(AcousticWave(
                cx=float(self.player_x),
                cy=float(self.player_y),
                current_r=0.0,
                speed=12.0,
                max_r=3.0,
                energy=0.25,
                wave_type="step"
            ))

    def update_physics(self, dt: float) -> None:
        """Updates wave expansion, phosphor decay, projectiles, and entity AI."""
        current_time = time.perf_counter()
        self.elapsed_time = current_time - self.start_time

        # Update player cooldowns
        if self.fork_cooldown > 0:
            self.fork_cooldown = max(0.0, self.fork_cooldown - dt)
        if self.invulnerable_timer > 0:
            self.invulnerable_timer = max(0.0, self.invulnerable_timer - dt)
        if self.damage_flash > 0:
            self.damage_flash -= 1
        if self.move_cooldown > 0:
            self.move_cooldown = max(0.0, self.move_cooldown - dt)

        # 1. Phosphor CRT Exponential Decay (0.90 per frame)
        for y in range(self.map_h):
            row = self.light_buffer[y]
            for x in range(self.map_w):
                row[x] *= 0.90

        # 2. Ambient Proximity Glow (0.35) around player's immediate 3x3 tile area
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                px = self.player_x + dx
                py = self.player_y + dy
                if 0 <= px < self.map_w and 0 <= py < self.map_h:
                    self.light_buffer[py][px] = max(self.light_buffer[py][px], 0.35)

        # 3. Uncollected Relic Harmonic Chimes (Periodic localized beacons)
        for idx, (rx, ry) in enumerate(self.relic_positions):
            if not self.relic_collected_flags[idx]:
                self.relic_hum_timers[idx] -= dt
                if self.relic_hum_timers[idx] <= 0:
                    self.relic_hum_timers[idx] = 4.2
                    self.waves.append(AcousticWave(
                        cx=float(rx),
                        cy=float(ry),
                        current_r=0.0,
                        speed=14.0,
                        max_r=5.5,
                        energy=0.45,
                        wave_type="relic_hum"
                    ))

        # 4. Update Bone-Stone Projectiles
        active_projectiles: List[BoneStone] = []
        for proj in self.projectiles:
            impact = proj.update(dt, self.grid, self.map_w, self.map_h)
            if impact is not None:
                ix, iy = impact
                # Impact acoustic pulse
                self.waves.append(AcousticWave(
                    cx=float(ix),
                    cy=float(iy),
                    current_r=0.0,
                    speed=24.0,
                    max_r=22.0,
                    energy=0.85,
                    wave_type="decoy"
                ))
                self.telemetry.log("CLACK! Bone-stone shatters against the far stone masonry!", priority=4, duration=3.0)
            elif proj.alive:
                active_projectiles.append(proj)
        self.projectiles = active_projectiles

        # 5. Update Acoustic Shockwaves & Rasterize onto Light Buffer
        active_waves: List[AcousticWave] = []
        for wave in self.waves:
            wave.update(dt)
            wave.rasterize(self.light_buffer, self.grid, self.map_w, self.map_h)

            # Check if wave touches spirits (Hearing AI)
            for spirit in self.spirits:
                if spirit.id not in wave.heard_by:
                    # Aspect-corrected physical distance to sound origin
                    dist = math.hypot((spirit.x - wave.cx) * 0.55, spirit.y - wave.cy)
                    if abs(dist - wave.current_r) <= 1.8:
                        wave.heard_by.add(spirit.id)
                        spirit.alert_to(wave.cx, wave.cy, wave.wave_type)
                        if wave.wave_type == "fork":
                            self.telemetry.log("A Hollow Echo shrieks in the dark! Drawn toward your bell!", priority=5, duration=3.0)
                        elif wave.wave_type == "decoy":
                            self.telemetry.log("An Echo stalks toward the distant impact clatter...", priority=4, duration=3.0)
                        elif wave.wave_type == "step":
                            self.telemetry.log("A faint footstep alerts a nearby shadow...", priority=4, duration=2.5)

            if wave.alive:
                active_waves.append(wave)
        self.waves = active_waves

        # 6. Update Hollow Spirits
        p_pos = (self.player_x, self.player_y)
        for spirit in self.spirits:
            spirit.update(dt, self.grid, self.map_w, self.map_h, p_pos)

            # Check collision with player
            s_dist = math.hypot(spirit.x - self.player_x, spirit.y - self.player_y)
            if s_dist < 1.1:
                if self.invulnerable_timer <= 0:
                    self.player_hp = max(0, self.player_hp - 20)
                    self.invulnerable_timer = 1.2
                    self.damage_flash = 4

                    # Knock spirit back slightly
                    spirit.x += (spirit.x - self.player_x) * 2.0
                    spirit.y += (spirit.y - self.player_y) * 2.0

                    self.telemetry.log(
                        f"A Hollow Echo chills your soul! -20 HP! [Remaining: {self.player_hp}%]",
                        priority=7, duration=3.5
                    )

                    if self.player_hp <= 0:
                        self.game_state = "GAME_OVER"
                        self.telemetry.log("THE HOLLOW CONSUMED YOUR ESSENCE... Darkness claims the warden.", priority=10, duration=10.0)

            # Proximity warning if spirit is near but unseen
            elif s_dist < 4.5 and self.light_buffer[int(round(spirit.y))][int(round(spirit.x))] <= 0.12:
                if random.random() < 0.04:
                    self.telemetry.log("An icy chill prickles your neck... Something lurks very close.", priority=3, duration=2.0)

        # 7. Update Telemetry
        self.telemetry.update(dt)

    # ==========================================================================
    # 10. COMPOSITOR & FRAME RENDERING
    # ==========================================================================

    def render_game_frame(self) -> None:
        """Builds and flushes the entire composite terminal screen."""
        lines: List[str] = []
        cur_time = time.perf_counter()

        # Entity quick lookups
        spirit_pos: Dict[Tuple[int, int], HollowSpirit] = {}
        for sp in self.spirits:
            ix, iy = int(round(sp.x)), int(round(sp.y))
            if 0 <= ix < self.map_w and 0 <= iy < self.map_h:
                spirit_pos[(ix, iy)] = sp

        relic_pos_set = {
            self.relic_positions[i]: i for i in range(len(self.relic_positions))
            if not self.relic_collected_flags[i]
        }
        proj_pos_set = {
            (int(round(p.x)), int(round(p.y))) for p in self.projectiles if p.alive
        }

        # 1. Map Rows
        for y in range(self.map_h):
            row_chunks: List[str] = []
            for x in range(self.map_w):
                # Player
                if x == self.player_x and y == self.player_y:
                    p_clr = CLR_PLAYER_HURT if self.damage_flash > 0 else CLR_PLAYER
                    row_chunks.append(f"{p_clr}@{RESET}")
                    continue

                # Decoy Projectile
                if (x, y) in proj_pos_set:
                    row_chunks.append(f"{CLR_DECOY}*{RESET}")
                    continue

                lum = self.light_buffer[y][x]

                # Hollow Spirits (Only visible when illuminated lum > 0.12)
                if (x, y) in spirit_pos and lum > 0.12:
                    sp = spirit_pos[(x, y)]
                    glyph = sp.get_glyph(cur_time)
                    row_chunks.append(f"{CLR_SPIRIT}{glyph}{RESET}")
                    continue

                # Harmonic Relics
                if (x, y) in relic_pos_set:
                    if lum > 0.08:
                        row_chunks.append(f"{CLR_RELIC}★{RESET}")
                    else:
                        row_chunks.append(" ")
                    continue

                # Sanctum Bell-Gate
                if (x, y) == self.gate_pos:
                    if lum > 0.08:
                        g_clr = CLR_EXIT_OPEN if self.relics_collected >= 3 else CLR_EXIT_LOCKED
                        row_chunks.append(f"{g_clr}Ω{RESET}")
                    else:
                        row_chunks.append(" ")
                    continue

                # Catacomb Terrain (Walls & Cobblestone Floors)
                tile = self.grid[y][x]
                level = min(15, max(0, int(lum * 15.99)))

                if tile == "#":
                    row_chunks.append(WALL_RAMP[level])
                else:
                    # Slight cobblestone variation based on spatial coordinates
                    if (x ^ y) & 1:
                        row_chunks.append(FLOOR_RAMP_A[level])
                    else:
                        row_chunks.append(FLOOR_RAMP_B[level])

            row_str = "".join(row_chunks) + RESET + "\033[K"
            lines.append(row_str)

        # 2. 3-Row HUD Footer
        # Line 1: Stats & Vitals
        hp_blocks = self.player_hp // 10
        hp_bar_filled = "█" * hp_blocks
        hp_bar_empty = "░" * (10 - hp_blocks)
        if self.player_hp > 50:
            hp_clr = rgb(80, 240, 120)
        elif self.player_hp > 25:
            hp_clr = rgb(240, 200, 60)
        else:
            hp_clr = rgb(240, 60, 60)

        fork_str = f"{rgb(80, 240, 120)}READY [SPACE]{RESET}" if self.fork_cooldown <= 0 else f"{rgb(240, 140, 60)}CHARGING ({self.fork_cooldown:.1f}s){RESET}"
        relics_str = f"{CLR_RELIC}{self.relics_collected}/3 ★{RESET}"
        decoys_str = f"{CLR_DECOY}{self.player_decoys} [E]{RESET}"

        hud_line_1 = (
            f"HP: [{hp_clr}{hp_bar_filled}{rgb(70, 70, 70)}{hp_bar_empty}{RESET}] {self.player_hp:3d}%  "
            f"│  RELICS: {relics_str}  │  DECOYS: {decoys_str}  │  TUNING FORK: {fork_str}"
        )
        lines.append(hud_line_1 + "\033[K")

        # Line 2: Telemetry Log
        telemetry_msg = self.telemetry.get_text()
        max_log_len = max(20, self.term_w - 14)
        if len(telemetry_msg) > max_log_len:
            telemetry_msg = telemetry_msg[:max_log_len - 3] + "..."
        hud_line_2 = f"{rgb(255, 215, 120)}TELEMETRY:{RESET} {telemetry_msg}\033[K"
        lines.append(hud_line_2)

        # Line 3: Control Legend
        hud_line_3 = (
            f"{rgb(140, 140, 140)}[WASD/ARROWS]: Tread Softly   "
            f"[SPACE]: Strike Bell   [E]: Toss Decoy   [Q/ESC]: Abandon Crypt{RESET}\033[K"
        )
        lines.append(hud_line_3)

        self.term.render("\n".join(lines))

    # ==========================================================================
    # 11. TITLE, VICTORY & GAME OVER SCREENS
    # ==========================================================================

    def render_title_screen(self) -> None:
        """Renders the atmospheric title screen."""
        lines: List[str] = []
        tw, th = self.term_w, self.term_h

        banner = [
            "██████╗ ███████╗███████╗ ██████╗ ███╗   ██╗ █████╗ ███╗   ██╗ ██████╗███████╗",
            "██╔══██╗██╔════╝██╔════╝██╔═══██╗████╗  ██║██╔══██╗████╗  ██║██╔════╝██╔════╝",
            "██████╔╝█████╗  ███████╗██║   ██║██╔██╗ ██║███████║██╔██╗ ██║██║     █████╗  ",
            "██╔══██╗██╔══╝  ╚════██║██║   ██║██║╚██╗██║██╔══██║██║╚██╗██║██║     ██╔══╝  ",
            "██║  ██║███████╗███████║╚██████╔╝██║ ╚████║██║  ██║██║ ╚████║╚██████╗███████╗",
            "╚═╝  ╚═╝╚══════╝╚══════╝ ╚═════╝ ╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝╚══════╝",
        ]
        subtitle = "T H E   S I G H T L E S S   W A R D E N"

        lore = [
            "Centuries after the surface collapsed into ashes, the sightless order of",
            "Saint Eleanor survives in deep subterranean catacombs. Ancient resonant",
            "wards holding back the starved ancestral spirits have fractured into dust.",
            "",
            "You are a blind warden navigating purely through acoustic echolocation.",
            "Tread softly to sense immediate stone. Strike your tuning fork to illuminate",
            "the halls, but beware: the Hollow Echoes hunger for the warmth of your sound.",
            "",
            "MISSION: Recover the 3 Harmonic Relics [★] and reach the Sanctum Bell-Gate [Ω].",
        ]

        controls = [
            "[WASD / Arrows]  : Tread softly (emits faint footstep ripples)",
            "[Space]          : Strike Tuning Fork (casts massive acoustic radar shockwave)",
            "[E]              : Throw Decoy Bone-Stone (clatters against walls to lure spirits)",
            "[Q / ESC]        : Abandon run",
        ]

        start_prompt = "[ PRESS SPACE OR ENTER TO ENTER THE CATACOMBS ]"

        top_padding = max(1, (th - 26) // 2)
        lines.extend(["\033[K"] * top_padding)

        for bl in banner:
            padded = bl.center(tw)
            lines.append(f"{rgb(255, 215, 90)}{padded}{RESET}\033[K")

        lines.append(f"{rgb(220, 160, 50)}{subtitle.center(tw)}{RESET}\033[K")
        lines.append("\033[K")

        for l in lore:
            lines.append(f"{rgb(190, 180, 160)}{l.center(tw)}{RESET}\033[K")

        lines.append("\033[K")
        for c in controls:
            lines.append(f"{rgb(140, 220, 200)}{c.center(tw)}{RESET}\033[K")

        lines.append("\033[K")
        lines.append(f"{rgb(255, 240, 180)}{start_prompt.center(tw)}{RESET}\033[K")

        while len(lines) < th:
            lines.append("\033[K")

        self.term.render("\n".join(lines[:th]))

    def render_victory_screen(self) -> None:
        """Renders the Cathedral Bell victory screen."""
        lines: List[str] = []
        tw, th = self.term_w, self.term_h

        header = "★  THE SANCTUM BELL TOLLS  ★"
        sub = "THE HOLLOW ECHOES ARE SEALED AWAY"

        narrative = [
            "The final Harmonic Relic locks into the ancient bronze mechanism.",
            "A deafening, pure acoustic chime cascades through every vaulted arch,",
            "reverberating into the abyss and driving the hollow spirits into eternal rest.",
            "",
            "The crypt is sealed. The sightless order of Saint Eleanor endures.",
        ]

        minutes = int(self.elapsed_time // 60)
        seconds = int(self.elapsed_time % 60)
        stats = [
            f"Relics Restored : 3 / 3 ★",
            f"Final Vitality  : {self.player_hp}% HP",
            f"Footsteps Tread : {self.steps_taken}",
            f"Bells Struck    : {self.fork_strikes}",
            f"Decoys Thrown   : {self.decoys_thrown}",
            f"Catacomb Time   : {minutes:02d}:{seconds:02d}",
        ]

        prompt = "[R] Tread the Crypt Anew    [Q] Return to Eternal Silence"

        top_padding = max(1, (th - 22) // 2)
        lines.extend(["\033[K"] * top_padding)

        lines.append(f"{rgb(50, 255, 130)}{header.center(tw)}{RESET}\033[K")
        lines.append(f"{rgb(255, 215, 0)}{sub.center(tw)}{RESET}\033[K")
        lines.append("\033[K")

        for n in narrative:
            lines.append(f"{rgb(220, 220, 200)}{n.center(tw)}{RESET}\033[K")

        lines.append("\033[K")
        lines.append(f"{rgb(180, 180, 150)}{'─' * 46}".center(tw) + f"{RESET}\033[K")

        for s in stats:
            lines.append(f"{rgb(255, 230, 160)}{s.center(tw)}{RESET}\033[K")

        lines.append(f"{rgb(180, 180, 150)}{'─' * 46}".center(tw) + f"{RESET}\033[K")
        lines.append("\033[K")
        lines.append(f"{rgb(255, 255, 255)}{prompt.center(tw)}{RESET}\033[K")

        while len(lines) < th:
            lines.append("\033[K")

        self.term.render("\n".join(lines[:th]))

    def render_game_over_screen(self) -> None:
        """Renders the haunting death screen."""
        lines: List[str] = []
        tw, th = self.term_w, self.term_h

        header = "☠  THE HOLLOW CONSUMED YOUR ESSENCE  ☠"
        sub = "DARKNESS CLAIMS THE SIGHTLESS WARDEN"

        narrative = [
            "Your footsteps falter and fade into the cold silence of the stone.",
            "The starving ancestral echoes feast upon the lingering warmth of your soul.",
            "The relics remain lost in subterranean gloom.",
        ]

        minutes = int(self.elapsed_time // 60)
        seconds = int(self.elapsed_time % 60)
        stats = [
            f"Relics Recovered : {self.relics_collected} / 3 ★",
            f"Footsteps Tread  : {self.steps_taken}",
            f"Bells Struck     : {self.fork_strikes}",
            f"Decoys Thrown    : {self.decoys_thrown}",
            f"Time Survived    : {minutes:02d}:{seconds:02d}",
        ]

        prompt = "[R] Re-awaken in the Crypt    [Q] Rest in Peace"

        top_padding = max(1, (th - 22) // 2)
        lines.extend(["\033[K"] * top_padding)

        lines.append(f"{rgb(240, 50, 50)}{header.center(tw)}{RESET}\033[K")
        lines.append(f"{rgb(180, 80, 80)}{sub.center(tw)}{RESET}\033[K")
        lines.append("\033[K")

        for n in narrative:
            lines.append(f"{rgb(190, 170, 170)}{n.center(tw)}{RESET}\033[K")

        lines.append("\033[K")
        lines.append(f"{rgb(120, 60, 60)}{'─' * 46}".center(tw) + f"{RESET}\033[K")

        for s in stats:
            lines.append(f"{rgb(210, 180, 150)}{s.center(tw)}{RESET}\033[K")

        lines.append(f"{rgb(120, 60, 60)}{'─' * 46}".center(tw) + f"{RESET}\033[K")
        lines.append("\033[K")
        lines.append(f"{rgb(255, 230, 200)}{prompt.center(tw)}{RESET}\033[K")

        while len(lines) < th:
            lines.append("\033[K")

        self.term.render("\n".join(lines[:th]))

    # ==========================================================================
    # 12. RUN LOOP WITH LOCKED 30 FPS CADENCE
    # ==========================================================================

    def run(self) -> None:
        """Main game loop locked at 30 FPS (dt = 1/30.0s)."""
        self.term.enter_fullscreen()
        target_dt = 1.0 / 30.0

        try:
            while True:
                frame_start = time.perf_counter()
                keys = self.input.poll_keys()

                if "QUIT" in keys or "ESC" in keys:
                    break

                if self.game_state == "TITLE":
                    if "SPACE" in keys or "ENTER" in keys:
                        self.init_catacombs()
                        self.game_state = "PLAYING"
                    self.render_title_screen()

                elif self.game_state == "PLAYING":
                    # Input handling
                    for k in keys:
                        if k in ("UP", "DOWN", "LEFT", "RIGHT"):
                            if self.move_cooldown <= 0:
                                dx, dy = 0, 0
                                if k == "UP": dy = -1
                                elif k == "DOWN": dy = 1
                                elif k == "LEFT": dx = -1
                                elif k == "RIGHT": dx = 1
                                self.step_player(dx, dy)
                                self.move_cooldown = 0.075  # ~13 steps/sec max
                        elif k == "SPACE":
                            self.trigger_tuning_fork()
                        elif k == "THROW":
                            self.throw_decoy()

                    self.update_physics(target_dt)
                    self.render_game_frame()

                elif self.game_state in ("GAME_OVER", "VICTORY"):
                    if "RESTART" in keys or "SPACE" in keys or "ENTER" in keys:
                        self.init_catacombs()
                        self.game_state = "PLAYING"

                    if self.game_state == "VICTORY":
                        # Continuous subtle bell ripples radiating from gate
                        if random.random() < 0.1:
                            self.waves.append(AcousticWave(
                                cx=float(self.gate_pos[0]),
                                cy=float(self.gate_pos[1]),
                                current_r=0.0,
                                speed=22.0,
                                max_r=float(self.map_w),
                                energy=0.7,
                                wave_type="relic_hum"
                            ))
                        # Update phosphor decay on victory screen background
                        for y in range(self.map_h):
                            row = self.light_buffer[y]
                            for x in range(self.map_w):
                                row[x] *= 0.90
                        active_w = []
                        for w in self.waves:
                            w.update(target_dt)
                            w.rasterize(self.light_buffer, self.grid, self.map_w, self.map_h)
                            if w.alive:
                                active_w.append(w)
                        self.waves = active_w

                        self.render_victory_screen()
                    else:
                        self.render_game_over_screen()

                # Lock to 30 FPS
                frame_elapsed = time.perf_counter() - frame_start
                sleep_time = target_dt - frame_elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

        finally:
            self.term.restore()


# ==============================================================================
# ENTRY POINT
# ==============================================================================

def main() -> None:
    game = ResonanceGame()
    game.run()


if __name__ == "__main__":
    main()
