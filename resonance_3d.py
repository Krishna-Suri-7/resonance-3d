#!/usr/bin/env python3
"""
RESONANCE: Strike the Void
===========================
A full-screen, first-person 3D acoustic horror-action shooter rendered entirely in ANSI text.
Navigate subterranean catacombs using an expanding acoustic sonar pulse wave with wave freeze,
procedural cathedral masonry with Bayer dithering, multi-frame ASCII wraiths, inertial movement,
wide-cone sonic shotgun blasts with auto-lock & knockback, and a circular GTA radar with edge-pinned waypoints.

Zero external dependencies. Python 3.10+ standard library only.
"""

from __future__ import annotations

import atexit
import copy
from dataclasses import dataclass, field
import math
import os
import random
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
from typing import Dict, List, Optional, Set, Tuple
import wave

# Platform-specific non-blocking I/O and audio imports
IS_POSIX = os.name == "posix"
if IS_POSIX:
    import select
    import termios
    import tty
else:
    import msvcrt
    try:
        import winsound
    except Exception:
        winsound = None


# ==============================================================================
# 1. PLATFORM & TERMINAL CONTROLLER
# ==============================================================================

class TerminalController:
    """Manages raw terminal I/O, cursor visibility, alternate buffer, and clean teardown."""

    def __init__(self) -> None:
        self.is_posix = IS_POSIX
        self.old_settings = None
        self.fd = sys.stdin.fileno() if sys.stdin.isatty() else None
        self.in_fullscreen = False

        # Register exit and signal hooks for clean restoration
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
            # \033[0m: Reset styles
            # \033[?25h: Show cursor
            # \033[?1049l: Exit alternate buffer
            sys.stdout.write("\033[0m\033[?25h\033[?1049l")
            sys.stdout.flush()
            self.in_fullscreen = False

    def bell(self) -> None:
        """Modulates terminal bell audio chirp."""
        sys.stdout.write("\a")
        sys.stdout.flush()


class InputController:
    """Non-blocking keyboard input reader supporting POSIX and Windows."""

    def __init__(self) -> None:
        self.is_posix = IS_POSIX

    def read_keys(self) -> List[str]:
        keys: List[str] = []
        if self.is_posix:
            rlist, _, _ = select.select([sys.stdin], [], [], 0)
            if rlist:
                try:
                    data = os.read(sys.stdin.fileno(), 64).decode("latin-1", errors="ignore")
                except Exception:
                    return keys
                i = 0
                while i < len(data):
                    if data[i] == "\x1b":
                        if i + 2 < len(data) and data[i + 1] == "[":
                            code = data[i:i + 3]
                            if code == "\x1b[A":
                                keys.append("UP")
                            elif code == "\x1b[B":
                                keys.append("DOWN")
                            elif code == "\x1b[C":
                                keys.append("RIGHT")
                            elif code == "\x1b[D":
                                keys.append("LEFT")
                            else:
                                keys.append("ESC")
                            i += 3
                            continue
                        else:
                            keys.append("ESC")
                            i += 1
                            continue
                    else:
                        keys.append(data[i])
                        i += 1
        else:
            while msvcrt.kbhit():
                ch = msvcrt.getch()
                if ch in (b"\x00", b"\xe0"):
                    ch2 = msvcrt.getch()
                    if ch2 == b"H":
                        keys.append("UP")
                    elif ch2 == b"P":
                        keys.append("DOWN")
                    elif ch2 == b"M":
                        keys.append("RIGHT")
                    elif ch2 == b"K":
                        keys.append("LEFT")
                elif ch == b"\x1b":
                    keys.append("ESC")
                else:
                    try:
                        keys.append(ch.decode("latin-1"))
                    except Exception:
                        pass
        return keys


# ==============================================================================
# 2. PROCEDURAL CATHEDRAL AUDIO & SYNTH ENGINE
# ==============================================================================

class SoundEngine:
    """Zero-dependency, real-time procedural audio and cathedral synth engine.

    Synthesizes 16-bit mono PCM .wav files on startup with a multi-tap simulated
    cathedral reverb filter and plays sounds asynchronously without frame drops.
    """

    def __init__(self, sample_rate: int = 22050) -> None:
        self.sample_rate = sample_rate
        self.muted = False
        self.temp_dir: Optional[str] = tempfile.mkdtemp(prefix="resonance_sfx_")
        self.sound_files: Dict[str, str] = {}
        self.active_procs: List[subprocess.Popen] = []
        self.drone_proc: Optional[subprocess.Popen] = None
        self.drone_stop_event = threading.Event()
        self.drone_thread: Optional[threading.Thread] = None

        # Synthesize all procedural audio presets
        self._synthesize_all()

        # Start continuous background drone loop
        self.drone_thread = threading.Thread(target=self._drone_worker, daemon=True)
        self.drone_thread.start()

        # Register exit hook for clean filesystem and process teardown
        atexit.register(self.teardown)

    def _apply_cathedral_reverb(self, samples: List[float]) -> List[float]:
        """Simulated Cathedral Reverb Filter: multi-tap feedback delay line with soft clipping."""
        d1 = int(0.08 * self.sample_rate)
        d2 = int(0.17 * self.sample_rate)
        out = list(samples)
        n = len(out)
        for i in range(n):
            if i >= d1:
                out[i] += out[i - d1] * 0.40
            if i >= d2:
                out[i] += out[i - d2] * 0.25
        max_val = max((abs(x) for x in out), default=1.0)
        if max_val > 0.98:
            norm = 0.98 / max_val
            out = [x * norm for x in out]
        return out

    def _write_wav(self, name: str, samples: List[float]) -> str:
        """Applies cathedral reverb and writes 16-bit signed PCM mono WAV file to temp directory."""
        if not self.temp_dir:
            return ""
        fpath = os.path.join(self.temp_dir, f"{name}.wav")
        reverbed = self._apply_cathedral_reverb(samples)
        with wave.open(fpath, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            raw = bytearray()
            for s in reverbed:
                s_clamped = max(-1.0, min(1.0, s))
                raw.extend(struct.pack("<h", int(s_clamped * 32767.0)))
            wf.writeframes(raw)
        self.sound_files[name] = fpath
        return fpath

    def _synthesize_all(self) -> None:
        """Generates all 8 procedural sound presets (11 WAV files) on engine launch."""
        sr = self.sample_rate
        two_pi = 2.0 * math.pi

        # 1. drone (6.0s continuous drone): Binaural sub-bass organ (55.0Hz + 55.5Hz beat, 82.4Hz, 110.0Hz)
        n_drone = int(6.0 * sr)
        drone_smps = [0.0] * n_drone
        fade_len = int(0.3 * sr)
        for i in range(n_drone):
            t = i / sr
            lfo = 0.75 + 0.25 * math.sin(two_pi * 0.25 * t)
            val = (math.sin(two_pi * 55.0 * t) * 0.35 +
                   math.sin(two_pi * 55.5 * t) * 0.35 +
                   math.sin(two_pi * 82.4 * t) * 0.20 +
                   math.sin(two_pi * 110.0 * t) * 0.15) * lfo * 0.45
            if i < fade_len:
                val *= (i / fade_len)
            elif i > n_drone - fade_len:
                val *= ((n_drone - i) / fade_len)
            drone_smps[i] = val
        self._write_wav("drone", drone_smps)

        # 2. sonar (1.4s acoustic pulse): Metallic bell strike (528, 1056, 1584, 2340Hz) + pitch drop (120->40Hz)
        n_sonar = int(1.4 * sr)
        sonar_smps = [0.0] * n_sonar
        phase_sub = 0.0
        for i in range(n_sonar):
            t = i / sr
            decay_bell = math.exp(-3.5 * t)
            decay_trans = math.exp(-14.0 * t)
            decay_sub = math.exp(-2.2 * t)
            cur_f = 40.0 + 80.0 * math.exp(-4.0 * t)
            phase_sub += two_pi * cur_f / sr
            bell = (math.sin(two_pi * 528.0 * t) * 0.45 +
                    math.sin(two_pi * 1056.0 * t) * 0.30 +
                    math.sin(two_pi * 1584.0 * t) * 0.15) * decay_bell
            trans = math.sin(two_pi * 2340.0 * t) * 0.35 * decay_trans
            sub = math.sin(phase_sub) * 0.40 * decay_sub
            sonar_smps[i] = bell + trans + sub
        self._write_wav("sonar", sonar_smps)

        # 3. weapon_light (0.6s bowstring snap): Filtered noise burst + string pluck pitch bend (330->220Hz)
        n_wl = int(0.6 * sr)
        wl_smps = [0.0] * n_wl
        phase_str = 0.0
        for i in range(n_wl):
            t = i / sr
            decay_pluck = math.exp(-6.0 * t)
            freq = 220.0 + 110.0 * math.exp(-12.0 * t)
            phase_str += two_pi * freq / sr
            string_tone = (math.sin(phase_str) + 0.4 * math.sin(2.0 * phase_str)) * decay_pluck
            noise = (random.random() * 2.0 - 1.0) * (1.0 - t / 0.035) * 0.6 if t < 0.035 else 0.0
            wl_smps[i] = (string_tone * 0.7 + noise) * 0.8
        self._write_wav("weapon_light", wl_smps)

        # 4. weapon_heavy (0.9s organ chord blast): C2(65.4) + G2(98.0) + C3(130.8) + Eb3(155.6) + sub boom
        n_wh = int(0.9 * sr)
        wh_smps = [0.0] * n_wh
        phase_boom = 0.0
        for i in range(n_wh):
            t = i / sr
            decay_organ = math.exp(-3.0 * t)
            decay_boom = math.exp(-5.0 * t)
            organ = (math.sin(two_pi * 65.4 * t) * 0.35 +
                     math.sin(two_pi * 98.0 * t) * 0.25 +
                     math.sin(two_pi * 130.8 * t) * 0.25 +
                     math.sin(two_pi * 155.6 * t) * 0.25) * decay_organ
            boom_freq = 45.0 + 35.0 * math.exp(-8.0 * t)
            phase_boom += two_pi * boom_freq / sr
            boom = math.sin(phase_boom) * 0.5 * decay_boom
            wh_smps[i] = (organ * 0.6 + boom * 0.5) * 0.9
        self._write_wav("weapon_heavy", wh_smps)

        # 5. weapon_chime (0.8s crystal arpeggio): 880 -> 1108 -> 1318 -> 1760Hz with shimmering FM vibrato
        n_wc = int(0.8 * sr)
        wc_smps = [0.0] * n_wc
        notes = [880.0, 1108.0, 1318.0, 1760.0]
        step_t = 0.8 / len(notes)
        for i in range(n_wc):
            t = i / sr
            idx = min(len(notes) - 1, int(t / step_t))
            note_t = t - idx * step_t
            f = notes[idx]
            decay = math.exp(-4.5 * note_t)
            fm = 18.0 * math.sin(two_pi * 14.0 * t)
            val = math.sin(two_pi * (f + fm) * t) * decay * 0.6
            val += 0.3 * math.sin(two_pi * (f * 2.0) * t) * decay
            wc_smps[i] = val * 0.75
        self._write_wav("weapon_chime", wc_smps)

        # 6. spirit_hit (0.5s dissonant wail): FM downward glide (400 -> 180Hz, mod 273Hz)
        n_sh = int(0.5 * sr)
        sh_smps = [0.0] * n_sh
        phase_car = 0.0
        for i in range(n_sh):
            t = i / sr
            decay = math.exp(-4.0 * t)
            f_carrier = 180.0 + 220.0 * math.exp(-5.0 * t)
            mod = 60.0 * math.sin(two_pi * 273.0 * t)
            phase_car += two_pi * (f_carrier + mod) / sr
            sh_smps[i] = math.sin(phase_car) * decay * 0.75
        self._write_wav("spirit_hit", sh_smps)

        # 7. spirit_banish (1.1s spectral choir dissolve): Swelling choir into high chimes
        n_sb = int(1.1 * sr)
        sb_smps = [0.0] * n_sb
        for i in range(n_sb):
            t = i / sr
            if t < 0.4:
                env = (t / 0.4) ** 1.5
                choir = (math.sin(two_pi * 220.0 * t) +
                         math.sin(two_pi * 261.6 * t) +
                         math.sin(two_pi * 329.6 * t)) * 0.25 * env
                sb_smps[i] = choir
            else:
                decay = math.exp(-3.5 * (t - 0.4))
                chimes = (math.sin(two_pi * 1480.0 * t) * 0.3 +
                          math.sin(two_pi * 1760.0 * t) * 0.3 +
                          math.sin(two_pi * 2217.0 * t) * 0.2) * decay
                sb_smps[i] = chimes * 0.8
        self._write_wav("spirit_banish", sb_smps)

        # 8. relic (1.2s Sanctum Bell): Major-7th chord (440, 554.3, 659.2, 830.6Hz)
        n_rel = int(1.2 * sr)
        rel_smps = [0.0] * n_rel
        chord = [440.0, 554.3, 659.2, 830.6]
        for i in range(n_rel):
            t = i / sr
            decay = math.exp(-2.5 * t)
            val = sum(math.sin(two_pi * f * t) * (0.35 if f == 440.0 else 0.22) for f in chord) * decay
            rel_smps[i] = val * 0.8
        self._write_wav("relic", rel_smps)

        # 9. purchase (0.6s verification chime): 2-tone chime (1046Hz -> 1568Hz)
        n_pur = int(0.6 * sr)
        pur_smps = [0.0] * n_pur
        for i in range(n_pur):
            t = i / sr
            if t < 0.3:
                f = 1046.5
                decay = math.exp(-5.0 * t)
            else:
                f = 1568.0
                decay = math.exp(-4.0 * (t - 0.3))
            pur_smps[i] = (math.sin(two_pi * f * t) + 0.25 * math.sin(two_pi * (f * 2) * t)) * decay * 0.65
        self._write_wav("purchase", pur_smps)

        # 10. hurt (0.4s distorted impact): Sub-bass saturated boom + tritone sting (370+523Hz)
        n_hrt = int(0.4 * sr)
        hrt_smps = [0.0] * n_hrt
        for i in range(n_hrt):
            t = i / sr
            decay_impact = math.exp(-7.0 * t)
            decay_sting = math.exp(-5.0 * t)
            sub = math.sin(two_pi * 75.0 * t)
            sub_dist = math.tanh(sub * 2.5) * 0.5 * decay_impact
            sting = (math.sin(two_pi * 370.0 * t) + math.sin(two_pi * 523.0 * t)) * 0.25 * decay_sting
            hrt_smps[i] = sub_dist + sting
        self._write_wav("hurt", hrt_smps)

        # 11. step (0.15s stone tap): Heavily damped 140Hz impulse + subtle gravel noise tap
        n_stp = int(0.15 * sr)
        stp_smps = [0.0] * n_stp
        for i in range(n_stp):
            t = i / sr
            decay = math.exp(-22.0 * t)
            noise = (random.random() * 2.0 - 1.0) * 0.15 * math.exp(-35.0 * t)
            tap = math.sin(two_pi * 140.0 * t) * decay * 0.35 + noise
            stp_smps[i] = tap * 0.40
        self._write_wav("step", stp_smps)

    def _drone_worker(self) -> None:
        """Asynchronous background worker that continuously loops drone.wav."""
        drone_file = self.sound_files.get("drone")
        if not drone_file:
            return
        while not self.drone_stop_event.is_set():
            if self.muted:
                time.sleep(0.1)
                continue
            proc = None
            try:
                if sys.platform == "darwin":
                    proc = subprocess.Popen(["afplay", drone_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                elif sys.platform.startswith("linux"):
                    cmd = ["paplay", drone_file] if shutil.which("paplay") else ["aplay", "-q", drone_file]
                    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                elif os.name == "nt":
                    pass
            except Exception:
                pass

            self.drone_proc = proc
            t_start = time.time()
            while not self.drone_stop_event.is_set() and (time.time() - t_start) < 5.8:
                if self.muted:
                    if self.drone_proc:
                        try:
                            self.drone_proc.terminate()
                        except Exception:
                            pass
                        self.drone_proc = None
                    break
                time.sleep(0.1)

            if self.drone_proc:
                try:
                    self.drone_proc.terminate()
                except Exception:
                    pass
                self.drone_proc = None

    def play(self, name: str, priority: bool = False) -> None:
        """Plays a synthesized audio preset asynchronously with zero frame rate impact."""
        if self.muted:
            return
        filepath = self.sound_files.get(name)
        if not filepath or not os.path.exists(filepath):
            return

        # Prune terminated subprocesses
        self.active_procs = [p for p in self.active_procs if p.poll() is None]
        if len(self.active_procs) >= 8:
            old = self.active_procs.pop(0)
            try:
                old.terminate()
            except Exception:
                pass

        try:
            if sys.platform == "darwin":
                p = subprocess.Popen(["afplay", filepath], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.active_procs.append(p)
            elif sys.platform.startswith("linux"):
                cmd = ["paplay", filepath] if shutil.which("paplay") else ["aplay", "-q", filepath]
                p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.active_procs.append(p)
            elif os.name == "nt":
                import winsound
                flags = winsound.SND_FILENAME | winsound.SND_ASYNC
                winsound.PlaySound(filepath, flags)
        except Exception:
            pass

    def toggle_mute(self) -> bool:
        """Toggles audio mute on/off. Stops all playing audio if muted."""
        self.muted = not self.muted
        if self.muted:
            self.stop_all()
        return self.muted

    def stop_all(self) -> None:
        """Terminates all active audio subprocesses and drone playback."""
        if self.drone_proc:
            try:
                self.drone_proc.terminate()
            except Exception:
                pass
            self.drone_proc = None
        for p in self.active_procs:
            try:
                p.terminate()
            except Exception:
                pass
        self.active_procs.clear()

    def teardown(self) -> None:
        """Stops background drone thread, terminates audio processes, and cleans temp directory."""
        self.drone_stop_event.set()
        self.stop_all()
        if self.drone_thread and self.drone_thread.is_alive():
            self.drone_thread.join(timeout=0.2)
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir, ignore_errors=True)
            except Exception:
                pass


# ==============================================================================
# 3. DOUBLE-BUFFERED COMPOSITOR, BAYER DITHERING & DUAL-CHANNEL COLOR
# ==============================================================================

RGB = Tuple[int, int, int]

# 4x4 Bayer Ordered Dithering Matrix to eliminate gradient color banding
BAYER_4X4 = [
    [0, 8, 2, 10],
    [12, 4, 14, 6],
    [3, 11, 1, 9],
    [15, 7, 13, 5],
]

# Luminance density ramp for procedural masonry shading (from brightest to darkest)
LUMINANCE_RAMP = ["█", "▓", "▒", "░", "#", "≡", "=", "-", "·", " "]


def phosphor_color(light: float) -> RGB:
    """Calculates Truecolor phosphor transition based on illumination level:
    1.00: Blinding bone-white/cyan flash (255, 255, 230)
    0.80 - 1.00: Glowing white-gold (255, 220, 140)
    0.40 - 0.80: Deep warm amber (180, 110, 40)
    0.10 - 0.40: Shadowy sepia/charcoal (75, 55, 40)
    < 0.10: Black void (0, 0, 0)
    """
    if light >= 0.85:
        t = (light - 0.85) / 0.15
        return (255, int(220 + 35 * t), int(140 + 90 * t))
    elif light >= 0.40:
        t = (light - 0.40) / 0.45
        return (int(180 + 75 * t), int(110 + 110 * t), int(40 + 100 * t))
    elif light >= 0.08:
        t = (light - 0.08) / 0.32
        return (int(40 + 140 * t), int(25 + 85 * t), int(10 + 30 * t))
    elif light > 0.02:
        t = (light - 0.02) / 0.06
        return (int(40 * t), int(25 * t), int(10 * t))
    return (0, 0, 0)


def get_dual_channel_wall(
    eff_light: float, is_wave_crest: bool, is_explored: bool, is_mortar: bool
) -> Tuple[RGB, Optional[RGB]]:
    """Generates rich Dual-Channel (FG, BG) Truecolor for procedural gothic cathedral walls."""
    if is_wave_crest:
        # Blinding electric cyan-white wave crest
        fg = (220, 255, 255)
        bg = (40, 120, 140)
    elif eff_light > 0.03:
        if eff_light >= 0.80:
            t = (eff_light - 0.80) / 0.20
            fg = (255, int(210 + 45 * t), int(120 + 135 * t))
            bg = (int(50 + 20 * t), int(30 + 30 * t), int(15 + 40 * t))
        elif eff_light >= 0.40:
            t = (eff_light - 0.40) / 0.40
            fg = (int(160 + 95 * t), int(95 + 115 * t), int(35 + 85 * t))
            bg = (int(30 + 20 * t), int(18 + 12 * t), int(10 + 5 * t))
        else:  # 0.03 to 0.40
            t = max(0.0, (eff_light - 0.03) / 0.37)
            fg = (int(75 + 85 * t), int(55 + 40 * t), int(40 - 5 * t))
            bg = (int(15 + 15 * t), int(10 + 8 * t), int(8 + 2 * t))
    elif is_explored:
        # Permanent Echo Memory floor: deep indigo-sepia
        fg = (75, 55, 40)
        bg = (15, 10, 8)
    else:
        fg = (0, 0, 0)
        bg = None

    if is_mortar and bg is not None:
        bg = (int(bg[0] * 0.70), int(bg[1] * 0.70), int(bg[2] * 0.70))

    return fg, bg


class ScreenBuffer:
    """In-memory 2D character and ANSI Truecolor double-buffer with zero-flicker flush."""

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.chars: List[List[str]] = [[" " for _ in range(width)] for _ in range(height)]
        self.fg: List[List[RGB]] = [[(0, 0, 0) for _ in range(width)] for _ in range(height)]
        self.bg: List[List[Optional[RGB]]] = [[None for _ in range(width)] for _ in range(height)]

    def clear(self) -> None:
        for r in range(self.height):
            for c in range(self.width):
                self.chars[r][c] = " "
                self.fg[r][c] = (0, 0, 0)
                self.bg[r][c] = None

    def set_cell(self, r: int, c: int, char: str, fg: RGB, bg: Optional[RGB] = None) -> None:
        if 0 <= r < self.height and 0 <= c < self.width:
            self.chars[r][c] = char
            self.fg[r][c] = fg
            self.bg[r][c] = bg

    def draw_text(self, r: int, c: int, text: str, fg: RGB, bg: Optional[RGB] = None) -> None:
        if 0 <= r < self.height:
            for i, ch in enumerate(text):
                col = c + i
                if 0 <= col < self.width:
                    self.chars[r][col] = ch
                    self.fg[r][col] = fg
                    self.bg[r][col] = bg

    def apply_glitch(self) -> None:
        """Applies psychic spectral distortion and scanline glitch effect on melee damage."""
        glitch_chars = ["░", "▒", "▓", "§", "Ψ", "¤", "✦", "#", "!", "·", "?"]
        for r in range(self.height):
            if random.random() < 0.28:
                for c in range(self.width):
                    if random.random() < 0.20:
                        self.chars[r][c] = random.choice(glitch_chars)
                        self.fg[r][c] = (255, random.randint(20, 80), random.randint(30, 90))
                        self.bg[r][c] = (random.randint(40, 100), 0, 0)

    def render_stream(self) -> str:
        """Batch-generates ANSI string with color run-length caching for maximum FPS."""
        stream: List[str] = []
        last_fg: RGB = (-1, -1, -1)
        last_bg: Optional[RGB] = (-1, -1, -1)

        for r in range(self.height):
            row_chars = self.chars[r]
            row_fg = self.fg[r]
            row_bg = self.bg[r]

            for c in range(self.width):
                cfg = row_fg[c]
                cbg = row_bg[c]

                # Update FG color only when changed
                if cfg != last_fg:
                    stream.append(f"\033[38;2;{cfg[0]};{cfg[1]};{cfg[2]}m")
                    last_fg = cfg

                # Update BG color only when changed
                if cbg != last_bg:
                    if cbg is None:
                        stream.append("\033[49m")
                    else:
                        stream.append(f"\033[48;2;{cbg[0]};{cbg[1]};{cbg[2]}m")
                    last_bg = cbg

                stream.append(row_chars[c])

            if r < self.height - 1:
                stream.append("\r\n")

        stream.append("\033[0m")
        return "".join(stream)


# ==============================================================================
# 3. HIGH-DEFINITION MULTI-FRAME ASCII SPIRIT ART & GAME WORLD
# ==============================================================================

# Sovereign Echo: Massive High-Resolution Demoscene ASCII Art Matrix
SOVEREIGN_RAW = """                                                                            .i:.
                                                                          .i::::i.
                                                                         ii::::::ii.
                                                                         ii::::::::ii.
                                                                        iii::::::::::ii-.
                                                                        iiiiii:::::::::ii.
                                                                        iiiiiiiii::::::II::.
                                                                        IIiiIII::::::::I$:II.
                                                                        $IIII::::::::::i$::iI.
                                                                       .$II:::::::::::::'$:iii.
                                                                       $I:::::::::::::i:i$::iii.
                                                                     .$:::::::::::::::i::i::iiii.
                       ...                                         .$ii:::::::::::::::ii:i!:iiiii.
                    .iiiiiiiii...._                                $iiii::::::::::::::iiii!::iiii;
                   !::::::iiiiiiiii$$$b........_                 .$$iiiii:::::::::::::iiii!::iiiii;
                  .%%::::::::::iiii!iiiiiiiiiiiiii._             $$!!!iiiiii::::::::i::iii$::iiiiii!
                 iIIIii:::::::::::ii!iiiiiiiiiiiiiiii$.        .$$$iiiii:::::::::::iii:ii!$::ii:iii;
                 ii:IIii::::::::::::ii!:::::::::::::ii$iii..$$$iiiiii:::::::::::::iiii::iI$::ii::iii;
                 iiiIIIi:::::::::::::::!!ii:::::::::::!iii$$:::::iiii::::::::::::iiii!::ii$:::ii::iii!
                 'iiiII::::::::::::::::::!iii::::::ii!!!!!i$::::::::::::::::::::iiiii$$ii$::::iii::ii;
                   'iii:::::::::::::iiiiii!!!!:::::::iii!!!!$$::::::::::::::ii::iiiii$$I$$ii:::ii::'ii!
                     'ii::::::::::::::::iiiii!!!!II::::ii!;!!!$$i1111iiii::::iiiiiiii$$$$iii:::iii::ii;
                       ii:::::::::::::::::::iiiiiiIIIIIIiiiiii::IIII:::::iii:::iiiiii$$!Iiiiii::iii::ii;
                        ''i:::::ii:::::::::::::iiiiiiiiIIIiii::::::!IIIIII$$!i:iiiiii$$!IIiiiii::iii:iii!
                          'ii:::iii::::::::::::::iiiIiiiiIiii:::::::'!!!!!!!$$iiiiiii$  'IIIiii:::ii:::i!
                           'iiiii$i:::::::::::::::::iIIIiiiiii:::::::!!!!!!!!$$$iiiii$    \\III::::iii::ii.
                             'iii$$::::::::::::::::::::iIIIIiii::::::::!!!!!!!!!$III$$     \\IIII:::ii::iii.
                    ...!!!!!!!!$$$$$b::::::::::::::::::::iiiI:::::::::!!!!!!!!!!!$II$$      \\IIII::iii::iii.
                 .!!!!!!!!!!!!!!!!!!$$:::::::I::ii:::::::::iiii::::::::!!!!!!!!!!!$II$.      \\IIi::iii::iii!
               .!!::::::::::!!!!!!!!!$:::::IIiiiiii::::::::::iii:::::::::::::!!!!!!$$$$       \\ii:::ii::iiii.
              :!::::::::::::!!!!!!!!!$$$$$IIiiii&&ii::::::::::::::::::::::::::::!!!!$$$.       \\ii::::::iiii!
             :::::::::::::::!!!!:::!$$iiiiiiii&&iii:::::::::::::::::::::::::::::!!!!!!!ii.      \\ii:::::iiiii.
             ::::::::::::::!!!:::::!i$iiiiiii&iiii:::::::::::::::::::!!iiii:::::::::!!!!ii!      \\ii::::ii:ii;
             ::::::::::::::::::::::!i$$iiiii&iiiiiiiiiii:::::::::::::jjjiiii:::::::::::!ii$$.    'ii!:::ii:iiii.
             ':::::::::::::::::::::iii:$iiii&iiiiiiiiiiiii:::::::::::JJjjiiii::::::::::!!!!$$.    ii!;:::::iiiii
              '::::::::::::::::::::ii:d$ii&&iii$$$$iiiii:::::::::::::::JJjjii::::::::::!!!ii$$    iii:!::::iiiii.
              .:::::::::::::::::::::::$::&$$' 'iiii$ii$$$::::::iiiii:::::J!iiii::::::::!!!ii!$     ii:!!:::iiiiii
              :::::::::::d$$$$$$$$!::|::::$     'iii$$iii$$$::::iiiiiiiii!i!!iii:::::::!!!!!!$     ii::::::iiiiii
              '::::::::::$$$P  .$$:::|:!:d$           'iiiii$$$$$iiiiiiiii!i!!!ii:::::::!!!!!$     ii::::::iiiiII
                '\"$$$b::::$$! .$$::$$|:::$P             ''iiiiiiiiiiiiiiiii!i!!!!!:::::::!!!!$     ii::::::iiiIii
                   \"$$b::::$$$$::::$$$$::$'                  ''\"$$$$$$$$$$$$$$!::::::::::!!!!$     ii::::::iiiIii
                    \"$$:::::::::::::$$:::$                                   '$$::::::::::!ii$     iii::::iiiIii
       .--.          .':::::::::::::$$:::$                                    $$$b::::::::iii$      ii::::iiiIii
     /iiiii\\_      .ii!!!!!\"-:OOOOOO.::::$                                    $ii$!!::::::ii!$      ii::::iiIii
    !ii/\"\"\\ii\\     .iii!!ii'   'OOOOO\":::d$                                    $iii$i!!::::ii!$      ii::::iiIii
 ___!ii__..!i:'--'iii!ii'      '::::::::'                                     '.iii!!!::::ii!i\\     ii::::iIii
.iii!!!!!!:::::::::::!i'         '--' '-'                                       !iiii!!!:::iii!i\\    ii::::iiii
iii\"\"$$\"\"\"!!!iiiii:!!!i                                                          'iiii!!!::::i!!ii   ii::::iiii
$$'  $' .!!!!i\"\"i\"\"!!!!i                                                          \\iiiiii::::i!!ii   ii::::iiii
$$     .i!!'        ;!!!.                                                          \\ii!Mi::::iiii'   ii::::iiii
'.   iii'           '!!!!.                                                         $$$Mii::::iii   .ii:::iiiii
     iii             !!!!;                                                         '$$Mii::::Mii   ii::::iiii'
     iii             '!!!                                                           $MMii::::Mii   ii::::iiii
     '$$              !!!                                                          .$M$i:::::Mii   ii::::iii'
      \":             d$$'                                                          !iiii:::::Mii.  i:::::iii
       '             $P'                          _.II;                         .iiiii::::::::Iii  i:::::iii
                     :'                        .:::iII%%                     .iiiiiii::::::::iIii .i:::::ii'
                                           _.-'::::iii!'               __..iiiiii:::::::::::iiiI' ii:::::ii
                                       .$$':::::%%iiii'          ...:::$$$$IIIIii:::::IIIiiiiii\" .ii:::::I'
                                      d$!:::::%\"%::!'        .:::::::::::::::::::IIIIIiiii!''''  ii::::iII
                                  ...d$$$%%%%\" %::!'    _.$$$IIIIII:::::::::IIIIIiiiii!'        .ii:::iiI'
                               .ii:::$Piii.. .%:.!!.iIIIIII:::::::IIIIIIIIIiiiiii$$$'           iii:::iII
                            .!::::ii:$iiiii$$!::!$'iiiiiiMMMMMMMiiiiiiii''''\"\"\"\"\"''             ii:::iiII
                          d$ii::::i''!'iii$$$:::$iiiiiiiiiiiii''                               .ii::iiiI'
                          $$$$:::'   '    \"$$:::$iiiiiiii'                                     iii:iiiI'
                         d$$$'             $$.:::::$i'                                        .ii::iiii
                         $$P'               \"!!:::::'.                                        iii:iiii'
                         $$                  !!::.::!!!!.                                    .ii::iiii
                         '$                  '$:::%%%!!!!!..                                 iii:iiii'
                           '                  '$$::\\ \"%$!!!!                                .iiiiiii'
                                                $:$%%%%!!!!!                               .iiiiiiii
                                     .         .$%%:::!!$$$'                               iiiiiiii'
                                      '..__.$!!!::::%%\"                                   .iiiiiii'
                                        \"$$$$!!$$$%%\"                                    .iiiiiiii
                                   '.         /::::!                                    .iiiiiiii'
                                     $$b._.ii::::::\"                                   .iiiiiiii'
                                      '$$$$biiiP'                                     .iiiiiiii'""".strip("\n").split("\n")

_max_sovereign_w = max(len(l) for l in SOVEREIGN_RAW)
SOVEREIGN_ART: List[str] = [l.ljust(_max_sovereign_w) for l in SOVEREIGN_RAW]
SOVEREIGN_H = len(SOVEREIGN_ART)
SOVEREIGN_W = _max_sovereign_w

# Hollow Spirit Wraiths: 13x9 Multi-Layer 2D ASCII Matrix with Alternating Frames
SPIRIT_FRAMES = [
    [
        "    .~~~.    ",
        "  ./ ╲ ╱ \\.  ",
        "  | (✦_✦) |  ",
        " .~\\ ═══ /~. ",
        "╱ ░ ▌║╬║▐ ░ ╲",
        "  ▒ ╱│║│╲ ▒  ",
        "  ░  │▒│  ░  ",
        "   · ╱ ╲ ·   ",
        "    ~   ~    ",
    ],
    [
        "   .~ · ~.   ",
        "  /  ╲ ╱  \\  ",
        "  | (✦_✦) |  ",
        " ~.\\ ═══ /. ~",
        "╲ ▒ ▌║╬║▐ ▒ ╱",
        "  ░ ╱│║│╲ ░  ",
        "   · │░│ ·   ",
        "    ~ ╲ ╱ ~  ",
        "     ·   ·   ",
    ],
]

# Open 30x30 Catacomb Layout with ~40% reduced wall density, wide avenues & plazas
MAP_LAYOUT = [
    "##############################",
    "#............##............5.#",
    "#...4........##..............#",
    "#............##..............#",
    "#....................4.......#",
    "#............##..............#",
    "###..####..######..####..#####",
    "#.......#..#....#..#.........#",
    "#.......#..........#.........#",
    "#.......#...2..2...#.........#",
    "#............................#",
    "#............................#",
    "#.......#...2..2...#.........#",
    "#.......#..........#.........#",
    "#.......#..#....#..#.........#",
    "###..####..######..####..#####",
    "#............................#",
    "#............................#",
    "#...4................4.......#",
    "#............................#",
    "#............33..............#",
    "###..####..######..####..#####",
    "#............................#",
    "#............................#",
    "#............................#",
    "#............##..............#",
    "#.....P......##..............#",
    "#............##..............#",
    "#............................#",
    "##############################",
]


@dataclass
class SonarPulse:
    """Expanding acoustic shockwave emitted from tuning fork strike."""
    origin_x: float
    origin_y: float
    current_radius: float = 0.0
    wave_speed: float = 14.0
    max_radius: float = 28.0
    wave_thickness: float = 1.2
    active: bool = True


@dataclass
class Projectile:
    """Visual sonic blast spark flying along weapon cone."""
    x: float
    y: float
    vx: float
    vy: float
    lifetime: float = 0.35
    alive: bool = True
    char: str = "✦"
    color: RGB = (255, 230, 120)


@dataclass
class Particle:
    """3D sparks and acoustic embers flying on impacts with 3D gravity."""
    x: float
    y: float
    vx: float
    vy: float
    lifetime: float
    max_lifetime: float
    char: str
    color: RGB
    z: float = 0.0
    vz: float = 0.0


@dataclass
class DustMote:
    """Ambient floating dust mote in subterranean air."""
    x: float
    y: float
    z: float
    seed: float


@dataclass
class BoneCore:
    """Dropped resonant relic from a banished specter."""
    x: float
    y: float
    active: bool = True
    hover_phase: float = 0.0


@dataclass
class Shrine:
    """Ancient catacomb altar / Relic to be cleansed by sonic resonance."""
    x: float
    y: float
    name: str
    cleansed: bool = False
    resonance: float = 0.0


@dataclass
class Enemy:
    """Ethereal specter or colossal boss wandering the dark catacombs."""
    x: float
    y: float
    hp: int = 100
    max_hp: int = 100
    glyph: str = "Ψ"
    name: str = "Void Wraith"
    speed: float = 1.25  # Eerie, manageable drift
    alerted: bool = False
    revealed_timer: float = 0.0
    stun_timer: float = 0.0  # Wave freeze stun
    hit_flash: float = 0.0
    hover_phase: float = 0.0
    attack_cooldown: float = 0.0
    alive: bool = True
    is_boss: bool = False
    attack_timer: float = 0.0


@dataclass
class Weapon:
    """Acoustic weapon specification, stats, ASCII model, and exotic perks."""
    id: str
    name: str
    price_str: str
    price: float
    damage: int
    cone_half_pct: float
    cone_desc: str
    range_m: float
    max_ammo: int
    knockback: float
    theme_color: RGB
    perk_name: str
    perk_desc: str
    projectile_symbol: str
    projectile_speed: float
    spark_color: RGB
    muzzle_flash_str: str
    ascii_art: List[Tuple[str, RGB]]
    unlocked: bool = False


DIFFICULTIES: List[Dict[str, Any]] = [
    {
        "id": "story",
        "name": "STORY MODE (Initiate)",
        "tag": "INITIATE",
        "desc": "150 HP | Slower Spirits (0.6x) | +50% Stun | Fast 2.0s Ammo",
        "hp": 150,
        "spirit_speed_mult": 0.60,
        "stun_duration_mult": 1.50,
        "ammo_regen_interval": 2.0,
        "lantern_radius": 5.0,
        "color": (100, 255, 180),
    },
    {
        "id": "warden",
        "name": "WARDEN MODE (Standard)",
        "tag": "STANDARD",
        "desc": "100 HP | Standard Speed (1.0x) | Standard Stun | 3.5s Ammo",
        "hp": 100,
        "spirit_speed_mult": 1.00,
        "stun_duration_mult": 1.00,
        "ammo_regen_interval": 3.5,
        "lantern_radius": 4.0,
        "color": (255, 215, 90),
    },
    {
        "id": "abyssal",
        "name": "ABYSSAL MODE (Nightmare)",
        "tag": "NIGHTMARE",
        "desc": "60 HP  | Relentless Spirits (1.35x) | Dim 2.5m Lantern | 4.5s Ammo",
        "hp": 60,
        "spirit_speed_mult": 1.35,
        "stun_duration_mult": 0.75,
        "ammo_regen_interval": 4.5,
        "lantern_radius": 2.5,
        "color": (255, 90, 110),
    },
]

WEAPONS_CATALOG: List[Weapon] = [
    Weapon(
        id="arbalest",
        name="Sanctum Tuning Arbalest",
        price_str="FREE",
        price=0.00,
        damage=50,
        cone_half_pct=0.18,
        cone_desc="35% (Corridor Focus)",
        range_m=10.0,
        max_ammo=6,
        knockback=2.5,
        theme_color=(255, 215, 90),
        perk_name="Harmonic Resonance",
        perk_desc="Standard monastic issue. Balanced spread and kinetic impact.",
        projectile_symbol="✦",
        projectile_speed=34.0,
        spark_color=(255, 230, 120),
        muzzle_flash_str="( ( ✦  ❖  ¤  ❖  ✦ ) )",
        ascii_art=[
            ("      ║       ║      ", (180, 150, 90)),
            ("      ║   *   ║      ", (220, 180, 110)),
            ("      ║  / \\  ║      ", (180, 150, 90)),
            ("      ╚═╡ ✦ ╞═╝      ", (255, 230, 120)),
            ("        │ ¤ │        ", (100, 220, 255)),
            ("     ╔══╧═══╧══╗     ", (160, 120, 60)),
            ("     ║  ( ☼ )  ║     ", (255, 200, 70)),
            ("     ╚══╤═══╤══╝     ", (160, 120, 60)),
            ("        │ █ │        ", (130, 95, 45)),
            ("        │ ▓ │        ", (110, 80, 35)),
        ],
        unlocked=True,
    ),
    Weapon(
        id="blunderbuss",
        name="Choir-Bell Blunderbuss",
        price_str="$1.99 DLC",
        price=1.99,
        damage=75,
        cone_half_pct=0.28,
        cone_desc="55% (Ultra-Wide Scatter)",
        range_m=7.0,
        max_ammo=4,
        knockback=5.0,
        theme_color=(255, 160, 60),
        perk_name="Catacomb Repulsor",
        perk_desc="Violent 5.0m knockback slams specters across entire halls.",
        projectile_symbol="❖",
        projectile_speed=28.0,
        spark_color=(255, 170, 70),
        muzzle_flash_str="< < ❖  █  ■  █  ❖ > >",
        ascii_art=[
            ("    /═══════════\\    ", (255, 180, 90)),
            ("   /   ( (O) )   \\   ", (255, 210, 120)),
            ("  /     ░ █ ░     \\  ", (230, 150, 70)),
            (" ╚══════╡ ❖ ╞══════╝ ", (255, 190, 80)),
            ("        │ █ │        ", (160, 110, 50)),
            ("      ╔═╧═══╧═╗      ", (190, 130, 60)),
            ("      ║ [BELL]║      ", (255, 170, 70)),
            ("      ╚═╤═══╤═╝      ", (160, 110, 50)),
            ("        │ ▓ │        ", (130, 90, 40)),
            ("        │ ▒ │        ", (100, 70, 30)),
        ],
        unlocked=False,
    ),
    Weapon(
        id="viol_bow",
        name="Whispering Viol-Bow",
        price_str="$1.99 DLC",
        price=1.99,
        damage=65,
        cone_half_pct=0.11,
        cone_desc="22% (Precision Sniper)",
        range_m=18.0,
        max_ammo=8,
        knockback=1.8,
        theme_color=(70, 255, 200),
        perk_name="Silent Frequency",
        perk_desc="High-velocity acoustic needles strike specters at long range.",
        projectile_symbol="─",
        projectile_speed=48.0,
        spark_color=(80, 255, 200),
        muzzle_flash_str="--==>> ✦ <<==--",
        ascii_art=[
            ("         /|          ", (100, 240, 210)),
            ("        / |          ", (120, 255, 225)),
            ("       /  | [弓]     ", (90, 230, 200)),
            ("      (   |   )      ", (70, 210, 190)),
            ("       \\  |  /       ", (70, 210, 190)),
            ("      ╔═╡-+-╞═╗      ", (140, 255, 230)),
            ("      ║ § | § ║      ", (110, 230, 210)),
            ("      ╚═╡ ✦ ╞═╝      ", (140, 255, 230)),
            ("        │ █ │        ", (60, 160, 145)),
            ("        │ ▒ │        ", (45, 120, 110)),
        ],
        unlocked=False,
    ),
    Weapon(
        id="mortar",
        name="Cathedral Pipe Mortar",
        price_str="$2.99 DLC",
        price=2.99,
        damage=110,
        cone_half_pct=0.20,
        cone_desc="40% (Concussive Blast)",
        range_m=12.0,
        max_ammo=3,
        knockback=3.5,
        theme_color=(255, 110, 60),
        perk_name="Sub-Bass Tremor",
        perk_desc="Heavy 110 dmg with guaranteed 2.0s concussion tremor stun.",
        projectile_symbol="●",
        projectile_speed=26.0,
        spark_color=(255, 120, 60),
        muzzle_flash_str="[[[ ☼  █  ☼ ]]]",
        ascii_art=[
            ("   ║█║   ║█║   ║█║   ", (255, 130, 60)),
            ("   ║█║   ║█║   ║█║   ", (240, 110, 50)),
            ("   ║█║   ║█║   ║█║   ", (220, 90, 40)),
            ("  ╔╩═╩═══╩═╩═══╩═╩╗  ", (255, 160, 80)),
            ("  ║  ( ( ☼ ☼ ☼ ) )║  ", (255, 200, 90)),
            ("  ╚══════╤═╤══════╝  ", (200, 100, 45)),
            ("        │ █ │        ", (160, 80, 35)),
            ("      ╔═╧═══╧═╗      ", (180, 95, 40)),
            ("      ║ VALVES║      ", (255, 140, 60)),
            ("      ╚═══════╝      ", (140, 70, 30)),
        ],
        unlocked=False,
    ),
    Weapon(
        id="flail",
        name="Cacophony Chime Flail",
        price_str="$2.99 DLC",
        price=2.99,
        damage=40,
        cone_half_pct=0.35,
        cone_desc="70% (Omni-Scatter Storm)",
        range_m=6.5,
        max_ammo=10,
        knockback=2.0,
        theme_color=(220, 130, 255),
        perk_name="Resonant Storm",
        perk_desc="Discharges 7 cluster chime shards sweeping entire corridors.",
        projectile_symbol="·",
        projectile_speed=30.0,
        spark_color=(220, 140, 255),
        muzzle_flash_str="* · ¤ ✦ ¤ · *",
        ascii_art=[
            ("   *     ✦     *     ", (230, 160, 255)),
            ("  (O)   (O)   (O)    ", (255, 190, 255)),
            ("   \\     |     /     ", (200, 130, 240)),
            ("    \\    |    /      ", (170, 100, 210)),
            ("     \\   |   /       ", (150, 90, 190)),
            ("      ╔══╧══╗        ", (190, 120, 230)),
            ("      ║[FLAIL]       ", (220, 140, 255)),
            ("      ╚══╤══╝        ", (170, 100, 210)),
            ("        │ █ │        ", (130, 80, 160)),
            ("        │ ▓ │        ", (100, 60, 130)),
        ],
        unlocked=False,
    ),
    Weapon(
        id="skull_harp",
        name="Ossuary Skull-Harp",
        price_str="$3.99 DLC",
        price=3.99,
        damage=85,
        cone_half_pct=0.15,
        cone_desc="30% (Spirit Resonator)",
        range_m=14.0,
        max_ammo=5,
        knockback=2.2,
        theme_color=(130, 245, 220),
        perk_name="Soul Siphon",
        perk_desc="Banishing an enemy siphons their soul, restoring +1 Bolt and +15 HP!",
        projectile_symbol="Ψ",
        projectile_speed=36.0,
        spark_color=(130, 245, 220),
        muzzle_flash_str="~ ~ ( Ψ  ☼  Ψ ) ~ ~",
        ascii_art=[
            ("     .-.     .-.     ", (220, 245, 235)),
            ("    ( o )   ( o )    ", (140, 255, 225)),
            ("     \\  | | |  /     ", (110, 240, 210)),
            ("      ) | | | (      ", (160, 255, 230)),
            ("     (  | | |  )     ", (180, 255, 240)),
            ("     ╔══╡Ψ Ψ╞══╗     ", (140, 245, 220)),
            ("     ║  [SKULL]║     ", (230, 250, 240)),
            ("     ╚══╤═══╤══╝     ", (180, 220, 210)),
            ("        │ █ │        ", (140, 170, 160)),
            ("        │ ▓ │        ", (100, 130, 120)),
        ],
        unlocked=False,
    ),
    Weapon(
        id="sovereign_voice",
        name="The Sovereign Voice",
        price_str="$4.99 DLC",
        price=4.99,
        damage=150,
        cone_half_pct=0.25,
        cone_desc="50% (Grand Celestial Beam)",
        range_m=16.0,
        max_ammo=4,
        knockback=4.0,
        theme_color=(255, 120, 240),
        perk_name="God-King Resonance",
        perk_desc="Celestial void beam. Deals +50% bonus dmg (225 dmg) to Sovereign Echo!",
        projectile_symbol="Ξ",
        projectile_speed=42.0,
        spark_color=(255, 120, 240),
        muzzle_flash_str="{ { ✦ ══ █ ══ ✦ } }",
        ascii_art=[
            ("     .:* ✦ ☼ ✦ *:.   ", (255, 225, 120)),
            ("    *  /   |   \\  *  ", (255, 140, 240)),
            ("   ✦ ─( ( [Ω] ) )─ ✦ ", (255, 240, 180)),
            ("    *  \\   |   /  *  ", (255, 140, 240)),
            ("     '·* ✦ ☼ ✦ *'·   ", (255, 225, 120)),
            ("      ╔══╡Ξ ≡╞══╗    ", (255, 170, 250)),
            ("      ║ [VOICE] ║    ", (255, 215, 100)),
            ("      ╚══╤═══╤══╝    ", (220, 120, 220)),
            ("        │ █ │        ", (180, 90, 190)),
            ("        │ ▓ │        ", (140, 70, 150)),
        ],
        unlocked=False,
    ),
]


# ==============================================================================
# 4. GAME ENGINE & KINEMATICS SIMULATION
# ==============================================================================

class ResonanceGame:
    """Core game engine coordinating kinematics, raycasting, HUD, and audio."""

    def __init__(self) -> None:
        self.term = TerminalController()
        self.input_ctrl = InputController()
        self.sound = SoundEngine()
        self.step_timer = 0.0

        # World geometry
        self.map_w = len(MAP_LAYOUT[0])
        self.map_h = len(MAP_LAYOUT)
        self.grid: List[List[int]] = [[0 for _ in range(self.map_w)] for _ in range(self.map_h)]
        self.wall_light: List[List[float]] = [[0.0 for _ in range(self.map_w)] for _ in range(self.map_h)]

        # Permanent Echo Memory: once hit by sonar, brightness floor is permanently locked at 0.22
        self.explored_map: List[List[bool]] = [[False for _ in range(self.map_w)] for _ in range(self.map_h)]

        # Zero-Stutter Inertial Movement & Camera Kinematics
        self.px = 6.5
        self.py = 26.5
        self.p_angle = -math.pi / 2.0  # Face North toward catacomb halls
        self.vx = 0.0
        self.vy = 0.0
        self.v_rot = 0.0
        self.key_timers: Dict[str, float] = {"w": 0.0, "s": 0.0, "a": 0.0, "d": 0.0, "q": 0.0, "e": 0.0}
        self.walk_cycle = 0.0
        self.horizon_offset = 0

        # Difficulty Configuration
        self.selected_diff_idx = 1  # Standard / Warden Mode
        self.difficulty_name = "WARDEN MODE (Standard)"
        self.spirit_speed_mult = 1.0
        self.stun_duration_mult = 1.0
        self.ammo_regen_interval = 3.5
        self.lantern_radius = 4.0

        # Weapons & Monetization Storefront
        self.weapons: List[Weapon] = copy.deepcopy(WEAPONS_CATALOG)
        self.selected_weapon_idx = 0
        self.equipped_weapon_idx = 0
        self.equipped_weapon: Weapon = self.weapons[0]
        self.wallet_credits: float = 5.00
        self.armory_feedback: str = "Welcome to the Sanctum Armory. Select, purchase, and equip weapons."

        # Player stats & Combat
        self.hp = 100
        self.max_hp = 100
        self.ammo = self.equipped_weapon.max_ammo
        self.max_ammo = self.equipped_weapon.max_ammo
        self.ammo_regen_timer = self.ammo_regen_interval
        self.invuln_timer = 0.0      # 1.5s invulnerability cooldown after hits
        self.glitch_timer = 0.0
        self.sonar_cooldown = 0.0
        self.weapon_recoil_timer = 0
        self.muzzle_flash_timer = 0
        self.fork_vibrate_timer = 0

        # Objectives & Exit
        self.exit_x = 27.5
        self.exit_y = 1.5
        self.shrines: List[Shrine] = []

        # Entities & Particles
        self.pulses: List[SonarPulse] = []
        self.projectiles: List[Projectile] = []
        self.particles: List[Particle] = []
        self.dust_motes: List[DustMote] = []
        self.bone_cores: List[BoneCore] = []
        self.enemies: List[Enemy] = []

        # Sovereign Echo Boss encounter
        self.boss_spawned: bool = False
        self.boss_alive: bool = True
        self.boss: Optional[Enemy] = None

        # Telemetry & UI
        self.telemetry_msg = "Awaken, Sightless Warden. Strike the tuning fork [SPACE] to pierce the void."
        self.telemetry_timer = 6.0
        self.show_codex = False
        self.game_state = "TITLE"  # TITLE, ARMORY, PLAYING, VICTORY, GAMEOVER
        self.start_time = time.time()
        self.specters_banished = 0

        self._apply_difficulty()
        self._init_world()
        self._init_dust_motes()

    def _init_world(self) -> None:
        """Parses map layout and instantiates shrines and specters."""
        relic_names = [
            "Relic of the Obsidian Chime",
            "Relic of the Silent Bell",
            "Relic of the Crypt Harmonic",
            "Relic of the Sightless Flame",
        ]
        s_idx = 0

        for y in range(self.map_h):
            for x in range(self.map_w):
                ch = MAP_LAYOUT[y][x]
                if ch == "#":
                    self.grid[y][x] = 1
                elif ch == "2":
                    self.grid[y][x] = 2  # Stone pillar
                elif ch == "3":
                    self.grid[y][x] = 3  # Resonant gate
                elif ch == "4":
                    self.grid[y][x] = 4  # Relic Altar
                    name = relic_names[s_idx % len(relic_names)]
                    s_idx += 1
                    self.shrines.append(Shrine(x=x + 0.5, y=y + 0.5, name=name))
                elif ch == "5":
                    self.grid[y][x] = 5  # Sanctum Exit Portal
                    self.exit_x = x + 0.5
                    self.exit_y = y + 0.5
                elif ch == "P":
                    self.px = x + 0.5
                    self.py = y + 0.5
                else:
                    self.grid[y][x] = 0

        # Spawn drifting specters
        enemy_configs = [
            (14.5, 9.5, 100, "Ψ", "Void Wraith", 1.25),
            (16.5, 10.5, 100, "§", "Crypt Banshee", 1.15),
            (25.5, 4.5, 100, "ø", "Resonant Phantasm", 1.05),
            (4.5, 14.5, 100, "✦", "Astral Specter", 1.30),
            (21.5, 23.5, 100, "Ψ", "Void Wraith", 1.20),
            (11.5, 23.5, 100, "§", "Crypt Banshee", 1.10),
        ]
        for ex, ey, ehp, eglyph, ename, espd in enemy_configs:
            self.enemies.append(
                Enemy(
                    x=ex,
                    y=ey,
                    hp=ehp,
                    max_hp=ehp,
                    glyph=eglyph,
                    name=ename,
                    speed=espd,
                    hover_phase=random.uniform(0, math.pi * 2),
                )
            )

    def _init_dust_motes(self) -> None:
        """Instantiates ambient floating subterranean dust motes."""
        self.dust_motes.clear()
        for _ in range(30):
            mx = self.px + random.uniform(-8, 8)
            my = self.py + random.uniform(-8, 8)
            mz = random.uniform(-0.4, 0.4)
            self.dust_motes.append(DustMote(x=mx, y=my, z=mz, seed=random.uniform(0, 100)))

    def trigger_telemetry(self, msg: str, duration: float = 4.0) -> None:
        self.telemetry_msg = msg
        self.telemetry_timer = duration

    def spawn_sparks(self, x: float, y: float, count: int = 6, color: RGB = (255, 220, 100), z: float = 0.0) -> None:
        """Spawns 3D acoustic ember particles radiating from an impact with vertical parabolic physics."""
        chars = ["*", "✦", "·", "¤", "❖"]
        for _ in range(count):
            angle = random.uniform(0, math.pi * 2)
            spd = random.uniform(2.5, 7.5)
            vx = math.cos(angle) * spd
            vy = math.sin(angle) * spd
            vz = random.uniform(1.2, 3.8)
            lt = random.uniform(0.25, 0.55)
            self.particles.append(
                Particle(
                    x=x,
                    y=y,
                    vx=vx,
                    vy=vy,
                    lifetime=lt,
                    max_lifetime=lt,
                    char=random.choice(chars),
                    color=color,
                    z=z,
                    vz=vz,
                )
            )

    # --------------------------------------------------------------------------
    # INPUT & INERTIAL KINEMATICS
    # --------------------------------------------------------------------------

    def handle_input(self, keys: List[str], dt: float) -> bool:
        """Processes real-time keyboard commands with persistence to bridge OS key-repeat gaps."""
        for key in keys:
            if key == "ESC":
                if self.game_state == "ARMORY":
                    self.game_state = "TITLE"
                    continue
                elif self.game_state == "TITLE":
                    return False
                elif self.show_codex:
                    self.show_codex = False
                    continue
                elif self.game_state in ("GAMEOVER", "VICTORY"):
                    self.game_state = "TITLE"
                    continue
                else:
                    return False
            elif key in ("h", "H"):
                if self.game_state == "PLAYING":
                    self.show_codex = not self.show_codex
                continue

            if self.game_state == "TITLE":
                if key in ("w", "W", "UP"):
                    self.selected_diff_idx = (self.selected_diff_idx - 1) % len(DIFFICULTIES)
                    self.sound.play("step")
                    self.term.bell()
                elif key in ("s", "S", "DOWN"):
                    self.selected_diff_idx = (self.selected_diff_idx + 1) % len(DIFFICULTIES)
                    self.sound.play("step")
                    self.term.bell()
                elif key == "1":
                    self.selected_diff_idx = 0
                    self.sound.play("step")
                    self.term.bell()
                elif key == "2":
                    self.selected_diff_idx = 1
                    self.sound.play("step")
                    self.term.bell()
                elif key == "3":
                    self.selected_diff_idx = 2
                    self.sound.play("step")
                    self.term.bell()
                elif key in (" ", "\r", "\n", "ENTER"):
                    self._apply_difficulty()
                    self.game_state = "ARMORY"
                    self.armory_feedback = f"Sanctum difficulty set to {self.difficulty_name}. Choose your weapon."
                    self.sound.play("sonar")
                    self.term.bell()
                elif key in ("m", "M"):
                    is_muted = self.sound.toggle_mute()
                    state_str = "MUTED" if is_muted else "ACTIVE"
                    self.armory_feedback = f"✦ Cathedral Audio: {state_str} (Press [M] to toggle)"
                continue

            if self.game_state == "ARMORY":
                if key in ("w", "W", "UP"):
                    self.selected_weapon_idx = (self.selected_weapon_idx - 1) % len(self.weapons)
                    self.sound.play("step")
                elif key in ("s", "S", "DOWN"):
                    self.selected_weapon_idx = (self.selected_weapon_idx + 1) % len(self.weapons)
                    self.sound.play("step")
                elif key in ("1", "2", "3", "4", "5", "6", "7"):
                    self.selected_weapon_idx = int(key) - 1
                    self.sound.play("step")
                elif key in ("p", "P"):
                    self._purchase_selected_weapon()
                elif key in ("u", "U"):
                    self._unlock_all_weapons()
                elif key in ("e", "E"):
                    self._equip_selected_weapon()
                elif key in ("m", "M"):
                    is_muted = self.sound.toggle_mute()
                    state_str = "MUTED" if is_muted else "ACTIVE"
                    self.armory_feedback = f"✦ Cathedral Audio: {state_str} (Press [M] to toggle)"
                elif key in ("\r", "\n", "ENTER"):
                    w = self.weapons[self.selected_weapon_idx]
                    if not w.unlocked:
                        self._purchase_selected_weapon()
                    elif self.equipped_weapon_idx != self.selected_weapon_idx:
                        self._equip_selected_weapon()
                    else:
                        self._start_run()
                elif key in (" ", "b", "B"):
                    self._start_run()
                continue

            if self.game_state in ("GAMEOVER", "VICTORY"):
                if key in ("r", "R"):
                    self._restart()
                elif key in ("m", "M", " ", "\r", "\n", "ENTER"):
                    self.game_state = "TITLE"
                continue

            if key in ("m", "M"):
                is_muted = self.sound.toggle_mute()
                state_str = "MUTED" if is_muted else "ACTIVE"
                self.trigger_telemetry(f"✦ CATHEDRAL AUDIO: {state_str} ([M] to toggle)")
                continue

            if self.show_codex:
                self.show_codex = False
                continue

            # Bridge OS key-repeat delay by latching timer for 0.18s
            if key in ("w", "W", "UP"):
                self.key_timers["w"] = 0.18
            elif key in ("s", "S", "DOWN"):
                self.key_timers["s"] = 0.18
            elif key in ("q", "Q"):
                self.key_timers["q"] = 0.18
            elif key in ("e", "E"):
                self.key_timers["e"] = 0.18
            elif key in ("a", "A", "LEFT"):
                self.key_timers["a"] = 0.18
            elif key in ("d", "D", "RIGHT"):
                self.key_timers["d"] = 0.18

            # Action triggers
            if key == " ":
                self._strike_tuning_fork()
            elif key in ("f", "F", "k", "K", "\r", "\n"):
                self._fire_resonant_bolt()

        return True

    def _update_kinematics(self, dt: float) -> None:
        """Inertial movement & velocity kinematics with smooth exponential damping."""
        # 1. Update key timers
        for k in self.key_timers:
            if self.key_timers[k] > 0.0:
                self.key_timers[k] = max(0.0, self.key_timers[k] - dt)

        # 2. Movement Acceleration (Forward/Backward and Strafing)
        move_fwd = (1.0 if self.key_timers["w"] > 0 else 0.0) - (1.0 if self.key_timers["s"] > 0 else 0.0)
        move_strafe = (1.0 if self.key_timers["e"] > 0 else 0.0) - (1.0 if self.key_timers["q"] > 0 else 0.0)

        target_speed = 5.2
        target_vx = (math.cos(self.p_angle) * move_fwd - math.sin(self.p_angle) * move_strafe) * target_speed
        target_vy = (math.sin(self.p_angle) * move_fwd + math.cos(self.p_angle) * move_strafe) * target_speed

        # Smooth velocity interpolation toward intent
        lerp_rate = 14.0 * dt
        self.vx += (target_vx - self.vx) * min(1.0, lerp_rate)
        self.vy += (target_vy - self.vy) * min(1.0, lerp_rate)

        # Exponential friction damping every tick
        if move_fwd == 0.0 and move_strafe == 0.0:
            self.vx *= 0.80
            self.vy *= 0.80

        # 3. Camera Rotation Kinematics
        turn_intent = (1.0 if self.key_timers["d"] > 0 else 0.0) - (1.0 if self.key_timers["a"] > 0 else 0.0)
        target_v_rot = turn_intent * 3.4
        self.v_rot += (target_v_rot - self.v_rot) * min(1.0, 16.0 * dt)
        self.v_rot *= 0.72
        self.p_angle += self.v_rot * dt

        # 4. Apply Independent X and Y Wall-Sliding Collision
        self._move_player(self.vx * dt, self.vy * dt)

        # 5. Head-Bob & Lissajous Weapon Sway Kinematics
        speed = math.hypot(self.vx, self.vy)
        self.walk_cycle += speed * dt * 2.6
        self.horizon_offset = int(math.sin(self.walk_cycle * 2.0) * 1.2)

        # Footstep audio on walk cycle cadence
        if speed > 1.2:
            self.step_timer -= dt
            if self.step_timer <= 0.0:
                self.sound.play("step")
                self.step_timer = 0.38
        else:
            self.step_timer = 0.0

    def _move_player(self, dx: float, dy: float) -> None:
        """Smooth Wall-Sliding: Separate X and Y checks so sliding diagonally never stops dead."""
        radius = 0.28

        # Independent X movement
        if dx != 0.0:
            new_x = self.px + dx
            check_x = new_x + math.copysign(radius, dx)
            if 0 <= int(check_x) < self.map_w and 0 <= int(self.py) < self.map_h:
                if self.grid[int(self.py)][int(check_x)] == 0:
                    self.px = new_x

        # Independent Y movement
        if dy != 0.0:
            new_y = self.py + dy
            check_y = new_y + math.copysign(radius, dy)
            if 0 <= int(self.px) < self.map_w and 0 <= int(check_y) < self.map_h:
                if self.grid[int(check_y)][int(self.px)] == 0:
                    self.py = new_y

    def _strike_tuning_fork(self) -> None:
        """Emits an acoustic shockwave that reveals catacombs and Wave-Freezes specters."""
        if self.sonar_cooldown <= 0.0:
            self.pulses.append(SonarPulse(origin_x=self.px, origin_y=self.py))
            self.sonar_cooldown = 1.8
            self.fork_vibrate_timer = 5
            self.sound.play("sonar", priority=True)
            self.term.bell()

            # Check if struck near un-cleansed relic
            cleansed_any = False
            for shrine in self.shrines:
                if not shrine.cleansed and math.hypot(shrine.x - self.px, shrine.y - self.py) < 4.5:
                    shrine.cleansed = True
                    shrine.resonance = 1.0
                    cleansed_any = True
                    # Deposit permanent holy light in relic vicinity
                    sx, sy = int(shrine.x), int(shrine.y)
                    for ny in range(max(0, sy - 2), min(self.map_h, sy + 3)):
                        for nx in range(max(0, sx - 2), min(self.map_w, sx + 3)):
                            self.wall_light[ny][nx] = 1.0
                            self.explored_map[ny][nx] = True
                    self.trigger_telemetry(f"✦ {shrine.name.upper()} SANCTIFIED! Relic beacon ignited.")
                    self.sound.play("relic", priority=True)
                    self.term.bell()

            if not cleansed_any:
                self.trigger_telemetry("Tuning fork struck. Sonic shockwave expanding (Freezes specters)...")
        else:
            self.trigger_telemetry(f"Tuning fork dampening... ({self.sonar_cooldown:.1f}s)", 1.2)

    def _knockback_enemy(self, enemy: Enemy, push_dist: float = 2.5) -> None:
        """Pushes an enemy directly away from the player with wall collision checks."""
        dx = enemy.x - self.px
        dy = enemy.y - self.py
        d = math.hypot(dx, dy)
        if d <= 0.001:
            return

        nx = dx / d
        ny = dy / d
        sub_steps = 5
        step = push_dist / sub_steps

        for _ in range(sub_steps):
            cand_x = enemy.x + nx * step
            if 0 <= int(cand_x) < self.map_w and self.grid[int(enemy.y)][int(cand_x)] == 0:
                enemy.x = cand_x
            cand_y = enemy.y + ny * step
            if 0 <= int(cand_y) < self.map_h and self.grid[int(cand_y)][int(enemy.x)] == 0:
                enemy.y = cand_y

    def _has_line_of_sight(self, x1: float, y1: float, x2: float, y2: float) -> bool:
        """Raycasts between two coordinates to check if unobstructed by walls."""
        dist = math.hypot(x2 - x1, y2 - y1)
        steps = max(2, int(dist * 3.5))
        for s in range(1, steps):
            t = s / steps
            cx = x1 + (x2 - x1) * t
            cy = y1 + (y2 - y1) * t
            if 0 <= int(cx) < self.map_w and 0 <= int(cy) < self.map_h:
                if self.grid[int(cy)][int(cx)] > 0:
                    return False
        return True

    def _fire_resonant_bolt(self) -> None:
        """Fires equipped acoustic weapon: applies weapon damage, cone width, range, knockback, and perks."""
        w = self.equipped_weapon
        if self.ammo <= 0:
            self.trigger_telemetry(f"NO RESONANT BOLTS! Wait for auto-recharge ({self.ammo_regen_interval:.1f}s) or grab Bone Cores.", 2.0)
            self.term.bell()
            return

        self.ammo -= 1
        self.weapon_recoil_timer = 6  # Multi-stage recoil
        self.muzzle_flash_timer = 4
        if w.id in ("arbalest", "viol_bow", "skull_harp"):
            self.sound.play("weapon_light")
        elif w.id in ("blunderbuss", "mortar"):
            self.sound.play("weapon_heavy")
        elif w.id in ("flail", "sovereign_voice"):
            self.sound.play("weapon_chime")
        else:
            self.sound.play("weapon_light")
        self.term.bell()

        # Spawn visual sonic blast spark spread along the weapon's specific cone
        if w.id == "flail":
            spread_angles = [-0.30, -0.20, -0.10, 0.0, 0.10, 0.20, 0.30]
        elif w.id == "viol_bow":
            spread_angles = [-0.04, 0.0, 0.04]
        else:
            spread_angles = [-0.18, -0.09, 0.0, 0.09, 0.18]

        for ang_offset in spread_angles:
            speed = w.projectile_speed * random.uniform(0.95, 1.05)
            ang = self.p_angle + ang_offset
            self.projectiles.append(
                Projectile(
                    x=self.px,
                    y=self.py,
                    vx=math.cos(ang) * speed,
                    vy=math.sin(ang) * speed,
                    lifetime=0.35,
                    char=w.projectile_symbol,
                    color=w.spark_color,
                )
            )

        # Wide cone camera calculations based on equipped weapon cone_half_pct
        term_w, term_h = shutil.get_terminal_size((120, 40))
        term_w = max(64, term_w)
        screen_center_x = term_w // 2
        cone_half_w = term_w * w.cone_half_pct

        fov = math.radians(66)
        dir_x = math.cos(self.p_angle)
        dir_y = math.sin(self.p_angle)
        plane_len = math.tan(fov / 2.0)
        plane_x = -dir_y * plane_len
        plane_y = dir_x * plane_len
        inv_det = 1.0 / (plane_x * dir_y - dir_x * plane_y)

        hits = 0
        for enemy in self.enemies:
            if not enemy.alive:
                continue
            d = math.hypot(enemy.x - self.px, enemy.y - self.py)
            if d > w.range_m:
                continue

            rel_x = enemy.x - self.px
            rel_y = enemy.y - self.py
            trans_x = inv_det * (dir_y * rel_x - dir_x * rel_y)
            trans_y = inv_det * (-plane_y * rel_x + plane_x * rel_y)
            if trans_y <= 0.2:
                continue

            spirit_screen_x = int((term_w / 2.0) * (1.0 + trans_x / trans_y))
            if abs(spirit_screen_x - screen_center_x) < cone_half_w:
                if self._has_line_of_sight(self.px, self.py, enemy.x, enemy.y):
                    hits += 1
                    dmg = w.damage
                    if enemy.stun_timer > 0.0:
                        dmg = int(dmg * 1.25)
                    if w.id == "sovereign_voice" and enemy.is_boss:
                        dmg = int(dmg * 1.50)  # +50% Celestial Void damage to Sovereign

                    enemy.hp -= dmg
                    enemy.hit_flash = 0.3
                    base_stun = 2.0 if w.id == "mortar" else 1.0
                    enemy.stun_timer = max(enemy.stun_timer, base_stun * self.stun_duration_mult)
                    enemy.revealed_timer = 3.5

                    # Knockback: regular enemies pushed by weapon knockback; boss flinches with heavy resistance (0.7 units)
                    push_dist = 0.7 if enemy.is_boss else w.knockback
                    self._knockback_enemy(enemy, push_dist)
                    spark_color = (255, 160, 240) if enemy.is_boss else w.spark_color
                    spark_count = 18 if enemy.is_boss else 10
                    self.spawn_sparks(enemy.x, enemy.y, count=spark_count, color=spark_color)
                    self.sound.play("spirit_hit")
                    self.term.bell()

                    if enemy.hp <= 0:
                        enemy.alive = False
                        self.specters_banished += 1
                        self.bone_cores.append(BoneCore(x=enemy.x, y=enemy.y))
                        self.sound.play("spirit_banish", priority=True)
                        if w.id == "skull_harp":
                            self.ammo = min(self.max_ammo, self.ammo + 1)
                            self.hp = min(self.max_hp, self.hp + 15)
                            self.trigger_telemetry(f"✦ SOUL SIPHON: Banished {enemy.name}! +1 Bolt & +15 HP restored!", 3.0)
                        elif enemy.is_boss:
                            self.boss_alive = False
                            self.spawn_sparks(enemy.x, enemy.y, count=45, color=(255, 230, 80))
                            self.trigger_telemetry("✦ THE SOVEREIGN ECHO BANISHED! The Sanctum Exit Portal [Ω] is unsealed!", 4.0)
                        else:
                            self.trigger_telemetry(f"✦ BANISHED: {enemy.name} destroyed! Bone Core dropped.")
                    else:
                        if enemy.is_boss:
                            self.trigger_telemetry(f"✦ SOVEREIGN STRUCK: Took {dmg} dmg! ({enemy.hp}/{enemy.max_hp} HP)", 2.0)
                        else:
                            self.trigger_telemetry(f"✦ BLAST CONNECTS: {enemy.name} took {dmg} dmg! (Knocked back & Stunned)")

        if hits == 0:
            self.trigger_telemetry(f"Sonic discharge emitted from {w.name} across corridor.")

    # --------------------------------------------------------------------------
    # PHYSICS & SIMULATION UPDATE
    # --------------------------------------------------------------------------

    def update(self, dt: float) -> None:
        if self.game_state != "PLAYING":
            return

        # 1. Update Inertial Movement & Camera Kinematics
        self._update_kinematics(dt)

        # Decay action timers
        if self.sonar_cooldown > 0.0:
            self.sonar_cooldown = max(0.0, self.sonar_cooldown - dt)
        if self.invuln_timer > 0.0:
            self.invuln_timer = max(0.0, self.invuln_timer - dt)
        if self.glitch_timer > 0.0:
            self.glitch_timer = max(0.0, self.glitch_timer - dt)
        if self.telemetry_timer > 0.0:
            self.telemetry_timer = max(0.0, self.telemetry_timer - dt)
        if self.weapon_recoil_timer > 0:
            self.weapon_recoil_timer -= 1
        if self.muzzle_flash_timer > 0:
            self.muzzle_flash_timer -= 1
        if self.fork_vibrate_timer > 0:
            self.fork_vibrate_timer -= 1

        # Regenerating Resonance Ammo: auto-regenerate 1 bolt every ammo_regen_interval
        if self.ammo < self.max_ammo:
            self.ammo_regen_timer -= dt
            if self.ammo_regen_timer <= 0.0:
                self.ammo += 1
                self.ammo_regen_timer = self.ammo_regen_interval
                self.trigger_telemetry(f"Resonance recharge: +1 Bolt restored ({self.ammo}/{self.max_ammo})", 1.5)
        else:
            self.ammo_regen_timer = self.ammo_regen_interval

        # Permanent Echo Memory: Explored walls maintain minimum brightness floor of 0.22
        for y in range(self.map_h):
            row = self.wall_light[y]
            exp_row = self.explored_map[y]
            for x in range(self.map_w):
                decayed = row[x] * 0.92
                if exp_row[x]:
                    row[x] = max(0.22, decayed)
                else:
                    row[x] = decayed if decayed > 0.01 else 0.0

        # Permanent holy beacon light near cleansed shrines
        for shrine in self.shrines:
            if shrine.cleansed:
                sx, sy = int(shrine.x), int(shrine.y)
                for ny in range(max(0, sy - 1), min(self.map_h, sy + 2)):
                    for nx in range(max(0, sx - 1), min(self.map_w, sx + 2)):
                        self.wall_light[ny][nx] = max(self.wall_light[ny][nx], 0.85)
                        self.explored_map[ny][nx] = True

        # Update expanding Sonar Pulses & WAVE FREEZE STUN
        for pulse in self.pulses:
            if pulse.active:
                pulse.current_radius += pulse.wave_speed * dt
                if pulse.current_radius > pulse.max_radius:
                    pulse.active = False
                else:
                    # Illuminate walls hit by the expanding wave front across 360 degrees
                    r_max = pulse.current_radius + pulse.wave_thickness
                    box_x0 = max(0, int(pulse.origin_x - r_max - 1))
                    box_x1 = min(self.map_w - 1, int(pulse.origin_x + r_max + 1))
                    box_y0 = max(0, int(pulse.origin_y - r_max - 1))
                    box_y1 = min(self.map_h - 1, int(pulse.origin_y + r_max + 1))
                    for wy in range(box_y0, box_y1 + 1):
                        for wx in range(box_x0, box_x1 + 1):
                            if self.grid[wy][wx] > 0:
                                d_w = math.hypot(wx + 0.5 - pulse.origin_x, wy + 0.5 - pulse.origin_y)
                                if abs(d_w - pulse.current_radius) <= pulse.wave_thickness + 0.5:
                                    self.wall_light[wy][wx] = 1.0
                                    self.explored_map[wy][wx] = True

                    # Wave Freeze Stun: freezes specters for 2.5s without charge aggro
                    for enemy in self.enemies:
                        if enemy.alive:
                            d = math.hypot(enemy.x - pulse.origin_x, enemy.y - pulse.origin_y)
                            if abs(d - pulse.current_radius) < pulse.wave_thickness + 0.3:
                                enemy.revealed_timer = 3.5
                                if enemy.stun_timer <= 0.0:
                                    enemy.stun_timer = 2.5 * self.stun_duration_mult
                                    self.trigger_telemetry(f"✦ WAVE FREEZE: {enemy.name} frozen in acoustic shock! (+25% bonus dmg)")
                                    self.term.bell()
        self.pulses = [p for p in self.pulses if p.active]

        # Update Projectiles
        for proj in self.projectiles:
            if not proj.alive:
                continue
            proj.lifetime -= dt
            if proj.lifetime <= 0:
                proj.alive = False
                continue
            proj.x += proj.vx * dt
            proj.y += proj.vy * dt
            if 0 <= int(proj.x) < self.map_w and 0 <= int(proj.y) < self.map_h:
                if self.grid[int(proj.y)][int(proj.x)] > 0:
                    proj.alive = False
                    self.wall_light[int(proj.y)][int(proj.x)] = 1.0
                    self.explored_map[int(proj.y)][int(proj.x)] = True
                    self.spawn_sparks(proj.x, proj.y, count=4, color=proj.color)

        self.projectiles = [p for p in self.projectiles if p.alive]

        # Update 3D Particles with elevation and gravity
        for part in self.particles:
            part.lifetime -= dt
            part.x += part.vx * dt
            part.y += part.vy * dt
            part.z += part.vz * dt
            part.vz -= 9.8 * dt  # 3D gravity
            if part.z < -0.4:
                part.z = -0.4
                part.vz = -part.vz * 0.35  # Bouncy floor collision
                part.vx *= 0.8
                part.vy *= 0.8
        self.particles = [p for p in self.particles if p.lifetime > 0.0]

        # Update Ambient Dust Motes
        for mote in self.dust_motes:
            mote.x += math.sin(time.time() * 0.8 + mote.seed) * 0.15 * dt
            mote.y += math.cos(time.time() * 0.8 + mote.seed) * 0.15 * dt
            if math.hypot(mote.x - self.px, mote.y - self.py) > 12.0:
                mote.x = self.px + random.uniform(-6, 6)
                mote.y = self.py + random.uniform(-6, 6)

        # Check if all shrines cleansed -> AWAKEN THE SOVEREIGN ECHO
        all_cleansed = all(s.cleansed for s in self.shrines)
        if all_cleansed and not self.boss_spawned:
            self.boss_spawned = True
            self.boss_alive = True
            self.glitch_timer = 0.45
            self.term.bell()
            self.boss = Enemy(
                x=23.5,
                y=3.5,
                hp=350,
                max_hp=350,
                glyph="♚",
                name="The Sovereign Echo",
                speed=0.90,
                is_boss=True,
                hover_phase=0.0,
            )
            self.enemies.append(self.boss)
            self.spawn_sparks(23.5, 3.5, count=32, color=(255, 120, 240))
            self.trigger_telemetry("✦ ALL RELICS SANCTIFIED! THE SOVEREIGN ECHO AWAKENS IN THE EXIT HALL!", 4.5)

        # Boss special acoustic shockwave attack AI
        if self.boss and self.boss.alive:
            self.boss.attack_timer += dt
            d_boss = math.hypot(self.px - self.boss.x, self.py - self.boss.y)
            if self.boss.attack_timer >= 4.5 and d_boss < 16.0:
                self.boss.attack_timer = 0.0
                ang = math.atan2(self.py - self.boss.y, self.px - self.boss.x)
                for offset in (-0.18, 0.0, 0.18):
                    b_spd = 15.0
                    self.projectiles.append(
                        Projectile(
                            x=self.boss.x,
                            y=self.boss.y,
                            vx=math.cos(ang + offset) * b_spd,
                            vy=math.sin(ang + offset) * b_spd,
                            lifetime=0.45,
                        )
                    )
                self.spawn_sparks(self.boss.x, self.boss.y, count=14, color=(255, 90, 220))
                self.trigger_telemetry("✦ THE SOVEREIGN ECHO discharges an Abyssal Shockwave!", 2.5)
                self.term.bell()

        # Update Specters & Boss (Eerie drift & Non-punishing Stalker AI)
        for enemy in self.enemies:
            if not enemy.alive:
                continue
            enemy.hover_phase += dt * (2.2 if enemy.is_boss else 3.5)
            if enemy.revealed_timer > 0.0:
                enemy.revealed_timer = max(0.0, enemy.revealed_timer - dt)
            if enemy.stun_timer > 0.0:
                enemy.stun_timer = max(0.0, enemy.stun_timer - dt)
            if enemy.hit_flash > 0.0:
                enemy.hit_flash = max(0.0, enemy.hit_flash - dt)
            if enemy.attack_cooldown > 0.0:
                enemy.attack_cooldown = max(0.0, enemy.attack_cooldown - dt)

            # Skip movement while wave-frozen or stunned!
            if enemy.stun_timer > 0.0:
                continue

            d_to_player = math.hypot(self.px - enemy.x, self.py - enemy.y)
            # Normal specters alert at 3.0 units; Boss has wider sightline (18.0 units)
            alert_dist = 18.0 if enemy.is_boss else 3.0
            if d_to_player < alert_dist:
                enemy.alerted = True

            if enemy.alerted:
                # Eerie, manageable drift toward player
                min_stop = 1.2 if enemy.is_boss else 0.85
                if d_to_player > min_stop:
                    move_dist = enemy.speed * self.spirit_speed_mult * dt
                    edx = (self.px - enemy.x) / d_to_player * move_dist
                    edy = (self.py - enemy.y) / d_to_player * move_dist

                    # Separate sliding checks
                    new_ex = enemy.x + edx
                    if self.grid[int(enemy.y)][int(new_ex)] == 0:
                        enemy.x = new_ex
                    new_ey = enemy.y + edy
                    if self.grid[int(new_ey)][int(enemy.x)] == 0:
                        enemy.y = new_ey
                else:
                    # Melee attack with invulnerability buffer
                    if enemy.attack_cooldown <= 0.0 and self.invuln_timer <= 0.0:
                        dmg = random.randint(12, 16) if enemy.is_boss else random.randint(6, 9)
                        self.hp = max(0, self.hp - dmg)
                        self.invuln_timer = 1.8 if enemy.is_boss else 1.5
                        enemy.attack_cooldown = 1.8 if enemy.is_boss else 1.5
                        self.glitch_timer = 0.30 if enemy.is_boss else 0.20
                        self.sound.play("hurt", priority=True)
                        self.term.bell()
                        if enemy.is_boss:
                            self.trigger_telemetry(f"CRITICAL: The Sovereign Echo tears monastic shroud! (-{dmg} HP)", 2.5)
                        else:
                            self.trigger_telemetry(f"WARNING: Spectral claws scratch monastic shroud! (-{dmg} HP)", 2.0)

        # Update Bone Core pickups
        for core in self.bone_cores:
            if core.active:
                core.hover_phase += dt * 4.0
                if math.hypot(core.x - self.px, core.y - self.py) < 1.0:
                    core.active = False
                    self.ammo = min(self.max_ammo, self.ammo + 3)
                    self.hp = min(self.max_hp, self.hp + 25)
                    self.spawn_sparks(core.x, core.y, count=8, color=(255, 230, 80))
                    self.sound.play("purchase")
                    self.term.bell()
                    self.trigger_telemetry("✦ BONE CORE ABSORBED: +25 HP restored, +3 Resonant Bolts!")
        self.bone_cores = [c for c in self.bone_cores if c.active]

        # Automatic Relic collection on touch
        for shrine in self.shrines:
            if not shrine.cleansed and math.hypot(shrine.x - self.px, shrine.y - self.py) < 1.4:
                shrine.cleansed = True
                shrine.resonance = 1.0
                sx, sy = int(shrine.x), int(shrine.y)
                for ny in range(max(0, sy - 2), min(self.map_h, sy + 3)):
                    for nx in range(max(0, sx - 2), min(self.map_w, sx + 3)):
                        self.wall_light[ny][nx] = 1.0
                        self.explored_map[ny][nx] = True
                self.trigger_telemetry(f"✦ {shrine.name.upper()} SANCTIFIED! Relic beacon activated.")
                self.sound.play("relic", priority=True)
                self.term.bell()

        # Check Exit Portal touch: requires all shrines cleansed AND Sovereign Echo defeated!
        if all_cleansed and math.hypot(self.exit_x - self.px, self.exit_y - self.py) < 1.6:
            if self.boss and self.boss.alive:
                self.trigger_telemetry("THE EXIT PORTAL IS SEALED! Banish The Sovereign Echo to escape!", 2.0)
            else:
                self.game_state = "VICTORY"
                self.sound.play("relic", priority=True)
                self.term.bell()

        # Check Game Over
        if self.hp <= 0:
            self.game_state = "GAMEOVER"
            self.sound.play("hurt", priority=True)
            self.term.bell()

    def _apply_difficulty(self) -> None:
        """Applies gameplay, stat caps, and mob kinematics modifiers based on selected difficulty."""
        diff = DIFFICULTIES[self.selected_diff_idx]
        self.difficulty_name = diff["name"]
        self.max_hp = diff["hp"]
        self.hp = diff["hp"]
        self.spirit_speed_mult = diff["spirit_speed_mult"]
        self.stun_duration_mult = diff["stun_duration_mult"]
        self.ammo_regen_interval = diff["ammo_regen_interval"]
        self.lantern_radius = diff["lantern_radius"]

    def _purchase_selected_weapon(self) -> None:
        """Simulates store purchase of the selected acoustic weapon with sanctum tithes."""
        w = self.weapons[self.selected_weapon_idx]
        if w.unlocked:
            self.armory_feedback = f"✦ {w.name} is already unlocked in your Armory! Press [E] to equip."
            self.sound.play("step")
            self.term.bell()
            return
        if self.wallet_credits >= w.price:
            self.wallet_credits -= w.price
            w.unlocked = True
            self.sound.play("purchase")
            self.term.bell()
            self.armory_feedback = f"✦ PURCHASE CONFIRMED: ${w.price:.2f} deducted! {w.name} unlocked. Press [E] to equip."
        else:
            self.sound.play("step")
            self.term.bell()
            self.armory_feedback = f"✖ INSUFFICIENT SANCTUM TITHES! Balance: ${self.wallet_credits:.2f}. Press [U] for Judge Unlock!"

    def _unlock_all_weapons(self) -> None:
        """Hackathon Judge Override: instantly unlocks all 7 DLC acoustic weapons."""
        for w in self.weapons:
            w.unlocked = True
        self.sound.play("relic")
        self.term.bell()
        self.armory_feedback = "✦ HACKATHON JUDGE OVERRIDE: All 7 DLC Sanctum Weapons Unlocked Instantly!"

    def _equip_selected_weapon(self) -> None:
        """Equips the selected unlocked weapon into active combat slot."""
        w = self.weapons[self.selected_weapon_idx]
        if not w.unlocked:
            self.armory_feedback = f"✖ {w.name} is LOCKED! Press [P] to Purchase (${w.price_str}) or [U] to Unlock."
            self.sound.play("step")
            self.term.bell()
            return
        self.equipped_weapon_idx = self.selected_weapon_idx
        self.equipped_weapon = w
        self.max_ammo = w.max_ammo
        self.ammo = w.max_ammo
        self.sound.play("weapon_chime")
        self.term.bell()
        self.armory_feedback = f"✦ EQUIPPED: {w.name} primed! Press [SPACE] to embark into catacombs."

    def _start_run(self) -> None:
        """Embarks into 3D catacombs with chosen difficulty and equipped acoustic weapon."""
        self._apply_difficulty()
        self.max_ammo = self.equipped_weapon.max_ammo
        self.ammo = self.max_ammo
        self.game_state = "PLAYING"
        self.start_time = time.time()
        self._strike_tuning_fork()
        self.trigger_telemetry(f"Entering catacombs with {self.equipped_weapon.name} on {self.difficulty_name}!", 4.0)

    def _restart(self) -> None:
        """Resets the game state for immediate replay."""
        self._apply_difficulty()
        self.ammo = self.equipped_weapon.max_ammo
        self.max_ammo = self.equipped_weapon.max_ammo
        self.px = 6.5
        self.py = 26.5
        self.vx = 0.0
        self.vy = 0.0
        self.v_rot = 0.0
        self.p_angle = -math.pi / 2.0
        self.invuln_timer = 0.0
        self.boss_spawned = False
        self.boss_alive = True
        self.boss = None
        self.pulses.clear()
        self.projectiles.clear()
        self.particles.clear()
        self.bone_cores.clear()
        self.shrines.clear()
        self.enemies.clear()
        self.wall_light = [[0.0 for _ in range(self.map_w)] for _ in range(self.map_h)]
        self.explored_map = [[False for _ in range(self.map_w)] for _ in range(self.map_h)]
        self.specters_banished = 0
        self.start_time = time.time()
        self.game_state = "PLAYING"
        self._init_world()
        self._init_dust_motes()
        self._strike_tuning_fork()
        self.trigger_telemetry("The void resets. Seek the 4 Relic Beacons and reach the Exit Portal [Ω].")

    # --------------------------------------------------------------------------
    # 3D RAYCASTING & DUAL-CHANNEL PROCEDURAL SHADING
    # --------------------------------------------------------------------------

    def render(self) -> None:
        """Renders the entire game screen to the double-buffer and outputs to terminal."""
        term_w, term_h = shutil.get_terminal_size((120, 40))
        term_w = max(64, term_w)
        term_h = max(24, term_h)

        buf = ScreenBuffer(term_w, term_h)

        if self.game_state == "TITLE":
            self._render_title_screen(buf, term_w, term_h)
            frame_str = buf.render_stream()
            sys.stdout.write("\033[H" + frame_str)
            sys.stdout.flush()
            return
        elif self.game_state == "ARMORY":
            self._render_armory_screen(buf, term_w, term_h)
            frame_str = buf.render_stream()
            sys.stdout.write("\033[H" + frame_str)
            sys.stdout.flush()
            return

        h_3d = term_h - 3  # Reserve bottom 3 lines for status HUD
        horizon = (h_3d // 2) + self.horizon_offset

        # 1. 3D DDA Raycaster across all terminal columns (66° FOV)
        fov = math.radians(66)
        dir_x = math.cos(self.p_angle)
        dir_y = math.sin(self.p_angle)
        plane_len = math.tan(fov / 2.0)
        plane_x = -dir_y * plane_len
        plane_y = dir_x * plane_len

        depth_buffer = [1e30] * term_w

        for col in range(term_w):
            camera_x = 2.0 * col / float(term_w) - 1.0
            ray_dir_x = dir_x + plane_x * camera_x
            ray_dir_y = dir_y + plane_y * camera_x

            map_x = int(self.px)
            map_y = int(self.py)

            delta_dist_x = abs(1.0 / ray_dir_x) if ray_dir_x != 0.0 else 1e30
            delta_dist_y = abs(1.0 / ray_dir_y) if ray_dir_y != 0.0 else 1e30

            if ray_dir_x < 0.0:
                step_x = -1
                side_dist_x = (self.px - map_x) * delta_dist_x
            else:
                step_x = 1
                side_dist_x = (map_x + 1.0 - self.px) * delta_dist_x

            if ray_dir_y < 0.0:
                step_y = -1
                side_dist_y = (self.py - map_y) * delta_dist_y
            else:
                step_y = 1
                side_dist_y = (map_y + 1.0 - self.py) * delta_dist_y

            hit = False
            side = 0
            steps = 0
            while not hit and steps < 64:
                steps += 1
                if side_dist_x < side_dist_y:
                    side_dist_x += delta_dist_x
                    map_x += step_x
                    side = 0
                else:
                    side_dist_y += delta_dist_y
                    map_y += step_y
                    side = 1

                if 0 <= map_x < self.map_w and 0 <= map_y < self.map_h:
                    if self.grid[map_y][map_x] > 0:
                        hit = True
                else:
                    break

            # Exact perpendicular distance and fractional horizontal texture coordinate (wall_u)
            if side == 0:
                perp_dist = (map_x - self.px + (1 - step_x) / 2.0) / ray_dir_x
                hit_wx = float(map_x + (1 if step_x < 0 else 0))
                hit_wy = self.py + perp_dist * ray_dir_y
                wall_hit_coord = hit_wy
                wall_u = wall_hit_coord - math.floor(wall_hit_coord)
                if ray_dir_x > 0:
                    wall_u = 1.0 - wall_u
            else:
                perp_dist = (map_y - self.py + (1 - step_y) / 2.0) / ray_dir_y
                hit_wx = self.px + perp_dist * ray_dir_x
                hit_wy = float(map_y + (1 if step_y < 0 else 0))
                wall_hit_coord = hit_wx
                wall_u = wall_hit_coord - math.floor(wall_hit_coord)
                if ray_dir_y < 0:
                    wall_u = 1.0 - wall_u

            perp_dist = max(0.08, perp_dist)
            depth_buffer[col] = perp_dist

            # Wall slice heights
            wall_h = int((h_3d * 0.82) / perp_dist)
            wall_top = max(0, horizon - wall_h // 2)
            wall_bottom = min(h_3d - 1, horizon + wall_h // 2)
            line_span = max(1, wall_bottom - wall_top)

            # Sonar pulse crest detection
            is_wave_crest = False
            for pulse in self.pulses:
                d_origin = math.hypot(hit_wx - pulse.origin_x, hit_wy - pulse.origin_y)
                if abs(d_origin - pulse.current_radius) < pulse.wave_thickness:
                    is_wave_crest = True
                    if 0 <= map_x < self.map_w and 0 <= map_y < self.map_h:
                        self.wall_light[map_y][map_x] = 1.0
                        self.explored_map[map_y][map_x] = True
                    break

            tile_type = self.grid[map_y][map_x] if (0 <= map_x < self.map_w and 0 <= map_y < self.map_h) else 1
            is_exp = self.explored_map[map_y][map_x] if (0 <= map_x < self.map_w and 0 <= map_y < self.map_h) else False
            base_light = self.wall_light[map_y][map_x] if (0 <= map_x < self.map_w and 0 <= map_y < self.map_h) else 0.0

            if is_exp:
                base_light = max(0.22, base_light)

            ambient = max(0.0, (self.lantern_radius - perp_dist) / self.lantern_radius * 0.35) if perp_dist < self.lantern_radius else 0.0
            raw_light = max(ambient, base_light)

            # Render wall slice with UV-mapped procedural cathedral stone and 4x4 Bayer dithering
            for row in range(wall_top, wall_bottom + 1):
                # 4x4 Bayer ordered dither
                dither_offset = (BAYER_4X4[row % 4][col % 4] / 16.0 - 0.5) * 0.08
                eff_light = max(0.0, min(1.0, raw_light + dither_offset))

                # Normalized vertical coordinate
                wall_v = (row - wall_top) / float(line_span)
                tu = int(wall_u * 16) % 16
                tv = int(wall_v * 16) % 16

                # Mortar grout lines
                is_horiz_mortar = tv in (0, 5, 10, 15)
                course = tv // 5
                is_vert_mortar = (tu == 0) if (course % 2 == 0) else (tu == 8)
                is_mortar = is_horiz_mortar or is_vert_mortar

                wall_fg, wall_bg = get_dual_channel_wall(eff_light, is_wave_crest, is_exp, is_mortar)

                # Architectural molding trim on top & bottom rows
                if row == wall_top:
                    char = "▀"
                    if wall_fg != (0, 0, 0):
                        wall_fg = (min(255, int(wall_fg[0] * 1.35 + 25)), min(255, int(wall_fg[1] * 1.35 + 25)), min(255, int(wall_fg[2] * 1.35 + 25)))
                elif row == wall_bottom:
                    char = "▄"
                    if wall_fg != (0, 0, 0):
                        wall_fg = (min(255, int(wall_fg[0] * 1.35 + 25)), min(255, int(wall_fg[1] * 1.35 + 25)), min(255, int(wall_fg[2] * 1.35 + 25)))
                elif is_wave_crest:
                    # Sparkling runic crest characters
                    sparkle_chars = ["✦", "❖", "░", "▒", "~", "█"]
                    char = sparkle_chars[(tu + tv + int(time.time() * 12)) % len(sparkle_chars)]
                elif is_horiz_mortar:
                    char = "_" if eff_light > 0.3 else "-"
                elif is_vert_mortar:
                    char = "|"
                elif tile_type == 2 and 0.28 < wall_v < 0.72:
                    # Ossuary bone/skull lattice pattern
                    bone_glyphs = ["¤", "o", "x", "≡", "П", "║"]
                    char = bone_glyphs[(tu + tv) % len(bone_glyphs)]
                elif tile_type == 3:
                    # Resonant gate rune carving
                    rune_glyphs = ["§", "╬", "✦", "❖", "░"]
                    char = rune_glyphs[(tu + tv) % len(rune_glyphs)]
                elif tile_type == 4:
                    char = "★" if eff_light > 0.4 else "✦"
                elif tile_type == 5:
                    char = "Ω" if eff_light > 0.4 else "O"
                else:
                    ramp_idx = min(9, max(0, int((1.0 - eff_light) * 9.99)))
                    char = LUMINANCE_RAMP[ramp_idx]

                buf.set_cell(row, col, char, wall_fg, wall_bg)

            # Render perspective Floor and Ceiling with pulse ripples
            # Floor (rows > wall_bottom)
            for row in range(wall_bottom + 1, h_3d):
                row_dist = (0.5 * h_3d) / max(1.0, float(row - horizon))
                floor_x = self.px + ray_dir_x * (row_dist * 0.5)
                floor_y = self.py + ray_dir_y * (row_dist * 0.5)

                floor_lit = False
                for pulse in self.pulses:
                    fd = math.hypot(floor_x - pulse.origin_x, floor_y - pulse.origin_y)
                    if abs(fd - pulse.current_radius) < 0.65:
                        floor_lit = True
                        break

                if floor_lit:
                    buf.set_cell(row, col, "~", (120, 240, 255), (20, 50, 70))
                else:
                    f_map_x, f_map_y = int(floor_x), int(floor_y)
                    if 0 <= f_map_x < self.map_w and 0 <= f_map_y < self.map_h:
                        if self.wall_light[f_map_y][f_map_x] > 0.20 and (int(floor_x * 2) + int(floor_y * 2)) % 2 == 0:
                            buf.set_cell(row, col, "·", (55, 38, 20))

            # Ceiling (rows < wall_top)
            for row in range(0, wall_top):
                row_dist = (0.5 * h_3d) / max(1.0, float(horizon - row))
                ceil_x = self.px + ray_dir_x * (row_dist * 0.5)
                ceil_y = self.py + ray_dir_y * (row_dist * 0.5)

                ceil_lit = False
                for pulse in self.pulses:
                    cd = math.hypot(ceil_x - pulse.origin_x, ceil_y - pulse.origin_y)
                    if abs(cd - pulse.current_radius) < 0.65:
                        ceil_lit = True
                        break

                if ceil_lit:
                    buf.set_cell(row, col, "^", (100, 210, 255), (15, 40, 60))

        # 2. 3D Relic Light Pillars: Full-height vertical column of shimmering gold particles
        inv_det = 1.0 / (plane_x * dir_y - dir_x * plane_y)

        for shrine in self.shrines:
            if not shrine.cleansed:
                rel_x = shrine.x - self.px
                rel_y = shrine.y - self.py
                trans_x = inv_det * (dir_y * rel_x - dir_x * rel_y)
                trans_y = inv_det * (-plane_y * rel_x + plane_x * rel_y)

                if trans_y > 0.3:
                    screen_col = int((term_w / 2.0) * (1.0 + trans_x / trans_y))
                    for c in range(max(0, screen_col - 1), min(term_w, screen_col + 2)):
                        if trans_y < depth_buffer[c] + 0.3:
                            for r in range(0, h_3d):
                                if r == horizon and c == screen_col:
                                    buf.set_cell(r, c, "★", (255, 240, 90))
                                elif c == screen_col:
                                    t_phase = int(time.time() * 9.0 + r) % 4
                                    glyphs = ["│", "┆", "✦", "★"]
                                    fg = (255, 220, 60) if t_phase in (2, 3) else (255, 180, 40)
                                    buf.set_cell(r, c, glyphs[t_phase], fg)
                                else:
                                    if (r + int(time.time() * 6.0)) % 2 == 0:
                                        buf.set_cell(r, c, "·", (180, 140, 40))

        # If all shrines cleansed, show green light pillar for Exit Portal
        if all(s.cleansed for s in self.shrines):
            rel_x = self.exit_x - self.px
            rel_y = self.exit_y - self.py
            trans_x = inv_det * (dir_y * rel_x - dir_x * rel_y)
            trans_y = inv_det * (-plane_y * rel_x + plane_x * rel_y)
            if trans_y > 0.3:
                screen_col = int((term_w / 2.0) * (1.0 + trans_x / trans_y))
                for c in range(max(0, screen_col - 1), min(term_w, screen_col + 2)):
                    if trans_y < depth_buffer[c] + 0.3:
                        for r in range(0, h_3d):
                            if r == horizon and c == screen_col:
                                buf.set_cell(r, c, "Ω", (100, 255, 160))
                            elif c == screen_col:
                                t_phase = int(time.time() * 9.0 + r) % 4
                                glyphs = ["│", "┆", "✦", "Ω"]
                                buf.set_cell(r, c, glyphs[t_phase], (80, 255, 120))

        # 3. 3D Billboard Sprites (Specters, Bone Cores, Projectiles, Dust Motes, Particles)
        sprites = []
        for enemy in self.enemies:
            if enemy.alive:
                dist = math.hypot(enemy.x - self.px, enemy.y - self.py)
                sprites.append(("ENEMY", enemy.x, enemy.y, dist, enemy))
        for core in self.bone_cores:
            if core.active:
                dist = math.hypot(core.x - self.px, core.y - self.py)
                sprites.append(("CORE", core.x, core.y, dist, core))
        for proj in self.projectiles:
            if proj.alive:
                dist = math.hypot(proj.x - self.px, proj.y - self.py)
                sprites.append(("PROJ", proj.x, proj.y, dist, proj))
        for mote in self.dust_motes:
            dist = math.hypot(mote.x - self.px, mote.y - self.py)
            if dist < 8.0:
                sprites.append(("MOTE", mote.x, mote.y, dist, mote))
        for part in self.particles:
            dist = math.hypot(part.x - self.px, part.y - self.py)
            sprites.append(("PART", part.x, part.y, dist, part))

        sprites.sort(key=lambda s: -s[3])

        frame_idx = int(time.time() * 3.5) % 2

        for stype, sx, sy, dist, entity in sprites:
            rel_x = sx - self.px
            rel_y = sy - self.py
            trans_x = inv_det * (dir_y * rel_x - dir_x * rel_y)
            trans_y = inv_det * (-plane_y * rel_x + plane_x * rel_y)

            if trans_y <= 0.2:
                continue

            sprite_screen_col = int((term_w / 2.0) * (1.0 + trans_x / trans_y))
            sprite_h = int((h_3d * 0.85) / trans_y)
            sprite_w = int(sprite_h * 1.4)

            if stype == "ENEMY":
                enemy: Enemy = entity
                if not enemy.is_boss and enemy.revealed_timer <= 0.0 and enemy.stun_timer <= 0.0 and trans_y > 4.0:
                    continue

                if enemy.is_boss:
                    # The Sovereign Echo: Colossal Boss Apparition in 3D
                    boss_h = int((h_3d * 1.95) / trans_y)
                    boss_w = int(boss_h * 1.45)
                    v_hover = int(math.sin(enemy.hover_phase) * (h_3d * 0.04))
                    start_row = max(0, horizon - int(boss_h * 0.65) + v_hover)
                    end_row = min(h_3d - 1, horizon + int(boss_h * 0.35) + v_hover)
                    start_col = max(0, sprite_screen_col - boss_w // 2)
                    end_col = min(term_w - 1, sprite_screen_col + boss_w // 2)

                    spr_h_span = max(1, end_row - start_row)
                    spr_w_span = max(1, end_col - start_col)

                    # 2D UV Texture Sampling from SOVEREIGN_ART
                    for r in range(start_row, end_row + 1):
                        v = (r - start_row) / float(spr_h_span)
                        ay = min(SOVEREIGN_H - 1, max(0, int(v * SOVEREIGN_H)))
                        for c in range(start_col, end_col + 1):
                            if trans_y < depth_buffer[c]:
                                u = (c - start_col) / float(spr_w_span)
                                ax = min(SOVEREIGN_W - 1, max(0, int(u * SOVEREIGN_W)))
                                ch = SOVEREIGN_ART[ay][ax]
                                if ch != " ":
                                    if enemy.hit_flash > 0.0:
                                        buf.set_cell(r, c, ch, (255, 255, 255), (190, 150, 40))
                                    elif enemy.stun_timer > 0.0:
                                        # Glacial electric wave freeze
                                        buf.set_cell(r, c, ch, (140, 255, 255), (20, 60, 90))
                                    else:
                                        if ch in ("$", "%", "M", "b"):
                                            buf.set_cell(r, c, ch, (255, 215, 120), (45, 25, 10))
                                        elif ch in ("I", "i", "!"):
                                            buf.set_cell(r, c, ch, (100, 230, 255), (15, 35, 50))
                                        elif ch in ("O",):
                                            buf.set_cell(r, c, ch, (255, 60, 60), (70, 10, 10))
                                        else:
                                            buf.set_cell(r, c, ch, (130, 90, 210), (20, 10, 35))

                    # Floating 3D Boss Title and Health Bar
                    bar_row = start_row - 1
                    if 0 <= bar_row < h_3d:
                        hp_pct = max(0.0, enemy.hp / float(enemy.max_hp))
                        bar_len = 20
                        fill_len = int(hp_pct * bar_len)
                        bar_str = f"[{'█' * fill_len}{'░' * (bar_len - fill_len)}] {enemy.hp}/{enemy.max_hp} HP"
                        buf.draw_text(bar_row, sprite_screen_col - len(bar_str) // 2, bar_str, (255, 90, 200))
                        name_row = bar_row - 1
                        if 0 <= name_row < h_3d:
                            title_str = "✦ THE SOVEREIGN ECHO ✦"
                            buf.draw_text(name_row, sprite_screen_col - len(title_str) // 2, title_str, (255, 230, 120))
                else:
                    v_hover = int(math.sin(enemy.hover_phase) * (h_3d * 0.04))
                    start_row = max(0, horizon - sprite_h // 2 + v_hover)
                    end_row = min(h_3d - 1, horizon + sprite_h // 2 + v_hover)
                    start_col = max(0, sprite_screen_col - sprite_w // 2)
                    end_col = min(term_w - 1, sprite_screen_col + sprite_w // 2)

                    # High-Definition 13x9 Multi-Layer Spirit UV sampling
                    matrix = SPIRIT_FRAMES[frame_idx]
                    spr_h_span = max(1, end_row - start_row)
                    spr_w_span = max(1, end_col - start_col)

                    for r in range(start_row, end_row + 1):
                        v = (r - start_row) / float(spr_h_span)
                        sy = min(8, max(0, int(v * 9)))
                        for c in range(start_col, end_col + 1):
                            if trans_y < depth_buffer[c]:
                                u = (c - start_col) / float(spr_w_span)
                                sx_idx = min(12, max(0, int(u * 13)))
                                ch = matrix[sy][sx_idx]

                                if ch != " ":
                                    # Colors based on state
                                    if enemy.hit_flash > 0.0:
                                        buf.set_cell(r, c, ch, (255, 255, 255), (180, 150, 40))
                                    elif enemy.stun_timer > 0.0:
                                        if ch in ("✦", "@"):
                                            ch = "❄"
                                        buf.set_cell(r, c, ch, (140, 255, 255), (20, 60, 90))
                                    elif ch in ("✦", "@"):
                                        eye_color = (255, 60, 60) if enemy.alerted else (255, 240, 140)
                                        buf.set_cell(r, c, ch, eye_color)
                                    elif ch in ("▌", "║", "╬", "▐"):
                                        buf.set_cell(r, c, ch, (255, 220, 100))
                                    elif ch in ("░", "▒", "~", "·"):
                                        buf.set_cell(r, c, ch, (70, 200, 220), (10, 20, 30))
                                    else:
                                        buf.set_cell(r, c, ch, (90, 240, 230))

            elif stype == "CORE":
                start_row = max(0, horizon - sprite_h // 4)
                end_row = min(h_3d - 1, horizon + sprite_h // 4)
                start_col = max(0, sprite_screen_col - 1)
                end_col = min(term_w - 1, sprite_screen_col + 1)
                core_fg = (255, 215, 60)
                for c in range(start_col, end_col + 1):
                    if trans_y < depth_buffer[c]:
                        for r in range(start_row, end_row + 1):
                            buf.set_cell(r, c, "☼", core_fg)

            elif stype == "PROJ":
                proj: Projectile = entity
                if 0 <= sprite_screen_col < term_w and trans_y < depth_buffer[sprite_screen_col]:
                    buf.set_cell(horizon, sprite_screen_col, proj.char, proj.color)
                    if 0 <= horizon + 1 < h_3d:
                        buf.set_cell(horizon + 1, sprite_screen_col, "·", proj.color)

            elif stype == "MOTE":
                mote: DustMote = entity
                mote_row = horizon + int(mote.z * (h_3d * 0.4) / trans_y)
                if 0 <= mote_row < h_3d and 0 <= sprite_screen_col < term_w and trans_y < depth_buffer[sprite_screen_col]:
                    buf.set_cell(mote_row, sprite_screen_col, "·", (160, 130, 70))

            elif stype == "PART":
                part: Particle = entity
                part_row = horizon - int(part.z * (h_3d * 0.45) / trans_y)
                if 0 <= part_row < h_3d and 0 <= sprite_screen_col < term_w and trans_y < depth_buffer[sprite_screen_col]:
                    buf.set_cell(part_row, sprite_screen_col, part.char, part.color)

        # 4. Auto-Lock Reticle UI (Shows [ ✦ LOCKED ✦ ] or [ ✦ SOVEREIGN LOCKED ✦ ])
        ch_r = horizon
        ch_c = term_w // 2
        cone_half_w = term_w * self.equipped_weapon.cone_half_pct
        max_lock_range = max(10.0, self.equipped_weapon.range_m)

        enemy_locked = False
        boss_locked = False
        locked_hp = 0
        for enemy in self.enemies:
            if not enemy.alive:
                continue
            d = math.hypot(enemy.x - self.px, enemy.y - self.py)
            if d <= max_lock_range:
                rel_x = enemy.x - self.px
                rel_y = enemy.y - self.py
                trans_x = inv_det * (dir_y * rel_x - dir_x * rel_y)
                trans_y = inv_det * (-plane_y * rel_x + plane_x * rel_y)
                if trans_y > 0.2:
                    sc = int((term_w / 2.0) * (1.0 + trans_x / trans_y))
                    if abs(sc - ch_c) < cone_half_w and self._has_line_of_sight(self.px, self.py, enemy.x, enemy.y):
                        if enemy.is_boss:
                            boss_locked = True
                            locked_hp = enemy.hp
                            break
                        else:
                            enemy_locked = True
                            break

        if boss_locked:
            lock_text = f"[ ✦ SOVEREIGN LOCKED: {locked_hp} HP ✦ ]"
            start_col = ch_c - len(lock_text) // 2
            buf.draw_text(ch_r, start_col, lock_text, (255, 80, 220))
        elif enemy_locked:
            lock_text = "[ ✦ LOCKED ✦ ]"
            start_col = ch_c - len(lock_text) // 2
            buf.draw_text(ch_r, start_col, lock_text, (100, 255, 120))
        else:
            buf.set_cell(ch_r, ch_c - 1, "·", (80, 150, 160))
            buf.set_cell(ch_r, ch_c, "+", (120, 220, 240))
            buf.set_cell(ch_r, ch_c + 1, "·", (80, 150, 160))

        # 5. Stylized First-Person Resonant Weapon with Lissajous Sway & Multi-Stage Recoil
        self._render_weapon(buf, term_w, h_3d)

        # 6. GTA-Style Circular 2D Minimap with Edge-Pinned Waypoints
        self._render_circular_minimap(buf, term_w, term_h)

        # 7. Bottom Status HUD & Telemetry Bar
        self._render_status_hud(buf, term_w, term_h)

        # 8. Modals (Codex, Victory, Game Over)
        if self.show_codex:
            self._render_codex_modal(buf, term_w, term_h)
        elif self.game_state == "GAMEOVER":
            self._render_gameover_modal(buf, term_w, term_h)
        elif self.game_state == "VICTORY":
            self._render_victory_modal(buf, term_w, term_h)

        # Apply screen glitch if taking damage
        if self.glitch_timer > 0.0:
            buf.apply_glitch()

        # Overwrite terminal screen with zero flicker
        frame_str = buf.render_stream()
        sys.stdout.write("\033[H" + frame_str)
        sys.stdout.flush()

    # --------------------------------------------------------------------------
    # FIRST-PERSON WEAPON MODEL, SWAY & MULTI-STAGE RECOIL
    # --------------------------------------------------------------------------

    def _render_weapon(self, buf: ScreenBuffer, term_w: int, h_3d: int) -> None:
        """Renders equipped acoustic weapon model with figure-8 Lissajous sway and multi-stage recoil."""
        # Figure-8 Lissajous sway
        weap_ox = int(math.cos(self.walk_cycle) * 2.5)
        weap_oy = int(abs(math.sin(self.walk_cycle)) * 1.5)

        # Multi-stage recoil offsets
        recoil_table = {6: (3, 1), 5: (3, -1), 4: (2, 0), 3: (2, 0), 2: (1, 0), 1: (1, 0)}
        rec_y, rec_x = recoil_table.get(self.weapon_recoil_timer, (0, 0))

        w_col = term_w // 2 + (term_w // 10) + weap_ox + rec_x
        base_r = h_3d - 1 + weap_oy + rec_y

        weapon_art = list(self.equipped_weapon.ascii_art)

        if self.fork_vibrate_timer > 0 and len(weapon_art) >= 2:
            l0, c0 = weapon_art[0]
            l1, c1 = weapon_art[1]
            weapon_art[0] = (f"  ~ {l0.strip()} ~  ".center(len(l0)), (100, 255, 230))
            weapon_art[1] = (f" (({l1.strip()})) ".center(len(l1)), (140, 255, 240))

        for i, (line, color) in enumerate(weapon_art):
            row = base_r - len(weapon_art) + i
            start_col = w_col - len(line) // 2
            if 0 <= row < h_3d:
                for c_idx, ch in enumerate(line):
                    if ch != " ":
                        buf.set_cell(row, start_col + c_idx, ch, color)

        # Multi-stage acoustic muzzle blast sparks
        if self.muzzle_flash_timer > 0:
            flash_row = base_r - len(weapon_art) - 1
            if self.muzzle_flash_timer >= 3:
                flash_str = self.equipped_weapon.muzzle_flash_str
                flash_fg = self.equipped_weapon.spark_color
            elif self.muzzle_flash_timer == 2:
                flash_str = "  ( ·   ¤   · )  "
                flash_fg = self.equipped_weapon.spark_color
            else:
                flash_str = "      ·   ·      "
                flash_fg = (180, 130, 50)

            if 0 <= flash_row < h_3d:
                start_c = w_col - len(flash_str) // 2
                for ci, ch in enumerate(flash_str):
                    if ch != " ":
                        buf.set_cell(flash_row, start_c + ci, ch, flash_fg)

    # --------------------------------------------------------------------------
    # GTA-STYLE CIRCULAR 2D MINIMAP & EDGE-PINNED WAYPOINTS
    # --------------------------------------------------------------------------

    def _render_circular_minimap(self, buf: ScreenBuffer, term_w: int, term_h: int) -> None:
        """Renders circular GTA-style radar HUD with edge-pinned waypoints for Relics & Exit."""
        r = 7  # Circular radius in rows
        center_r = 1 + r
        center_c = term_w - (2 * r + 4)
        radar_scale = 0.55  # Map tiles per radar row

        radar_bg: RGB = (6, 12, 18)
        border_fg: RGB = (70, 190, 220)

        # Precalculate perimeter border cells using neighboring grid test
        grid_in = {}
        for dy in range(-r - 1, r + 2):
            for dx in range(-2 * r - 2, 2 * r + 3):
                grid_in[(dx, dy)] = (dx / 2.0) ** 2 + dy ** 2 <= r ** 2

        for dy in range(-r, r + 1):
            row = center_r + dy
            if not (0 <= row < term_h - 3):
                continue

            for dx in range(-2 * r, 2 * r + 1):
                col = center_c + dx
                if not (0 <= col < term_w):
                    continue

                if not grid_in.get((dx, dy), False):
                    continue

                # Check if perimeter border cell
                is_border = False
                for ndx, ndy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    if not grid_in.get((dx + ndx, dy + ndy), False):
                        is_border = True
                        break

                if is_border:
                    theta = math.atan2(dy, dx / 2.0)
                    deg = math.degrees(theta) % 360
                    if (337.5 <= deg or deg < 22.5) or (157.5 <= deg < 202.5):
                        b_char = "│"
                    elif (67.5 <= deg < 112.5) or (247.5 <= deg < 292.5):
                        b_char = "─"
                    elif 22.5 <= deg < 67.5:
                        b_char = "╯"
                    elif 112.5 <= deg < 157.5:
                        b_char = "╰"
                    elif 202.5 <= deg < 247.5:
                        b_char = "╭"
                    else:
                        b_char = "╮"
                    buf.set_cell(row, col, b_char, border_fg, radar_bg)
                    continue

                # Inside radar circle
                cell_char = " "
                cell_fg = (30, 45, 60)

                world_x = self.px + (dx / 2.0) / radar_scale
                world_y = self.py + dy / radar_scale
                dist_from_player = math.hypot(dx / 2.0, dy)

                # 1. Fog of war wall rendering: visible if wall_light > 0.05 or explored
                if 0 <= int(world_x) < self.map_w and 0 <= int(world_y) < self.map_h:
                    map_t = self.grid[int(world_y)][int(world_x)]
                    w_light = self.wall_light[int(world_y)][int(world_x)]
                    is_exp = self.explored_map[int(world_y)][int(world_x)]

                    if map_t > 0 and (w_light > 0.05 or is_exp):
                        cell_char = "★" if map_t == 4 else ("Ω" if map_t == 5 else ("П" if map_t == 2 else "#"))
                        cell_fg = phosphor_color(max(0.22, w_light) if is_exp else w_light)

                # 2. Expanding Sonar Pulse ripple ring on minimap
                for pulse in self.pulses:
                    pulse_radar_r = pulse.current_radius * radar_scale
                    if abs(dist_from_player - pulse_radar_r) < 0.68:
                        cell_char = "○" if abs(dist_from_player - pulse_radar_r) < 0.3 else "~"
                        cell_fg = (120, 255, 240)

                # 3. Enemy Blips (red for normal, cyan for wave-frozen)
                for enemy in self.enemies:
                    if enemy.alive and (enemy.alerted or enemy.revealed_timer > 0.0 or enemy.stun_timer > 0.0):
                        edx = (enemy.x - self.px) * radar_scale * 2.0
                        edy = (enemy.y - self.py) * radar_scale
                        if math.hypot(dx - edx, (dy - edy) * 2.0) < 1.4:
                            cell_char = "❄" if enemy.stun_timer > 0.0 else ("!" if enemy.alerted else "*")
                            cell_fg = (120, 255, 255) if enemy.stun_timer > 0.0 else (255, 60, 60)

                # 4. Player Direction Indicator at Center
                if dx == 0 and dy == 0:
                    deg = (math.degrees(self.p_angle) + 360) % 360
                    if 337.5 <= deg or deg < 22.5:
                        cell_char = "►"
                    elif 22.5 <= deg < 67.5:
                        cell_char = "↘"
                    elif 67.5 <= deg < 112.5:
                        cell_char = "▼"
                    elif 112.5 <= deg < 157.5:
                        cell_char = "↙"
                    elif 157.5 <= deg < 202.5:
                        cell_char = "◄"
                    elif 202.5 <= deg < 247.5:
                        cell_char = "↖"
                    elif 247.5 <= deg < 292.5:
                        cell_char = "▲"
                    else:
                        cell_char = "↗"
                    cell_fg = (255, 240, 70)

                buf.set_cell(row, col, cell_char, cell_fg, radar_bg)

        # ----------------------------------------------------------------------
        # GTA WAYPOINT EDGE-PINNING: Nearest Uncollected Relic (★) & Exit (Ω)
        # ----------------------------------------------------------------------
        # 1. Nearest Uncollected Relic (★ in gold)
        uncollected = [s for s in self.shrines if not s.cleansed]
        if uncollected:
            nearest = min(uncollected, key=lambda s: math.hypot(s.x - self.px, s.y - self.py))
            rdx = (nearest.x - self.px) * radar_scale * 2.0
            rdy = (nearest.y - self.py) * radar_scale
            dist_rel = math.hypot(rdx / 2.0, rdy)

            if dist_rel <= r - 1.2:
                pr = int(center_r + rdy)
                pc = int(center_c + rdx)
            else:
                angle = math.atan2(rdy, rdx / 2.0)
                pin_r = r - 0.75
                pr = int(center_r + math.sin(angle) * pin_r)
                pc = int(center_c + math.cos(angle) * pin_r * 2.0)

            if 0 <= pr < term_h - 3 and 0 <= pc < term_w:
                buf.set_cell(pr, pc, "★", (255, 220, 50), radar_bg)

        # 2. Exit Portal (Ω in green)
        edx = (self.exit_x - self.px) * radar_scale * 2.0
        edy = (self.exit_y - self.py) * radar_scale
        dist_exit = math.hypot(edx / 2.0, edy)

        if dist_exit <= r - 1.2:
            er = int(center_r + edy)
            ec = int(center_c + edx)
        else:
            angle = math.atan2(edy, edx / 2.0)
            pin_r = r - 0.75
            er = int(center_r + math.sin(angle) * pin_r)
            ec = int(center_c + math.cos(angle) * pin_r * 2.0)

        if 0 <= er < term_h - 3 and 0 <= ec < term_w:
            exit_fg = (80, 255, 120) if (all(s.cleansed for s in self.shrines) and not (self.boss and self.boss.alive)) else (50, 160, 80)
            buf.set_cell(er, ec, "Ω", exit_fg, radar_bg)

        # 3. Sovereign Echo Boss Waypoint (♚ in bright magenta/crimson)
        if self.boss and self.boss.alive:
            bdx = (self.boss.x - self.px) * radar_scale * 2.0
            bdy = (self.boss.y - self.py) * radar_scale
            dist_boss = math.hypot(bdx / 2.0, bdy)

            if dist_boss <= r - 1.2:
                br = int(center_r + bdy)
                bc = int(center_c + bdx)
            else:
                angle = math.atan2(bdy, bdx / 2.0)
                pin_r = r - 0.75
                br = int(center_r + math.sin(angle) * pin_r)
                bc = int(center_c + math.cos(angle) * pin_r * 2.0)

            if 0 <= br < term_h - 3 and 0 <= bc < term_w:
                buf.set_cell(br, bc, "♚", (255, 60, 200), radar_bg)

    # --------------------------------------------------------------------------
    # STATUS HUD & DYNAMIC TELEMETRY (ROWS H-3 to H-1)
    # --------------------------------------------------------------------------

    def _render_status_hud(self, buf: ScreenBuffer, term_w: int, term_h: int) -> None:
        """Draws the bottom 3-line status bar with health, ammo, pulse cooldown, and telemetry."""
        r_div = term_h - 3
        r_msg = term_h - 2
        r_hud = term_h - 1

        bg_bar: RGB = (12, 16, 22)

        # Clear HUD rows
        for r in (r_div, r_msg, r_hud):
            for c in range(term_w):
                buf.set_cell(r, c, " ", (160, 160, 160), bg_bar)

        # Top border line with title tag
        for c in range(term_w):
            buf.set_cell(r_div, c, "═", (50, 75, 100), bg_bar)
        title_str = " [ RESONANCE : STRIKE THE VOID ] "
        buf.draw_text(r_div, 2, title_str, (120, 210, 240), bg_bar)

        audio_hint = "[M] MUTE: ON" if self.sound.muted else "[M] MUTE: OFF"
        codex_hint = f"{audio_hint} | [H] CODEX | [ESC] QUIT"
        buf.draw_text(r_div, max(len(title_str) + 4, term_w - len(codex_hint) - 2), codex_hint, (100, 140, 170), bg_bar)

        # Row H-2: Dynamic Telemetry Message Log
        prefix = "» LOG: "
        buf.draw_text(r_msg, 2, prefix, (255, 215, 80), bg_bar)
        buf.draw_text(r_msg, 2 + len(prefix), self.telemetry_msg[: term_w - len(prefix) - 4], (220, 230, 240), bg_bar)

        # Row H-1: Tactical Telemetry Gauges
        # Health bar with invulnerability shield indicator
        hp_pct = max(0.0, min(1.0, self.hp / float(self.max_hp)))
        hp_bars = int(hp_pct * 10)
        if self.invuln_timer > 0.0:
            hp_str = f"HP: [{'█' * hp_bars}{'░' * (10 - hp_bars)}] {self.hp}% [WARDED]"
            hp_fg = (120, 255, 255)
        else:
            hp_str = f"HP: [{'█' * hp_bars}{'░' * (10 - hp_bars)}] {self.hp}%"
            hp_fg = (80, 255, 120) if self.hp > 50 else ((255, 190, 40) if self.hp > 25 else (255, 50, 50))
        buf.draw_text(r_hud, 2, hp_str, hp_fg, bg_bar)

        # Ammo gauge with auto-recharge timer and equipped weapon tag
        ammo_bars = "|" * self.ammo + " " * (self.max_ammo - self.ammo)
        w_tag = self.equipped_weapon.id[:4].upper()
        if self.ammo < self.max_ammo:
            ammo_str = f"[{w_tag}] AMMO: [{ammo_bars}] {self.ammo}/{self.max_ammo} ({self.ammo_regen_timer:.1f}s)"
        else:
            ammo_str = f"[{w_tag}] AMMO: [{ammo_bars}] {self.ammo}/{self.max_ammo} [FULL]"
        ammo_fg = self.equipped_weapon.theme_color if self.ammo > 0 else (255, 80, 80)
        buf.draw_text(r_hud, 26, ammo_str, ammo_fg, bg_bar)

        # Sonar Pulse Cooldown
        if self.sonar_cooldown <= 0.0:
            pulse_str = "SONAR: READY [SPACE]"
            pulse_fg = (255, 230, 90)
        else:
            pulse_str = f"SONAR: ECHOING [{self.sonar_cooldown:.1f}s]"
            pulse_fg = (180, 130, 60)
        buf.draw_text(r_hud, 58, pulse_str, pulse_fg, bg_bar)

        # Relics Sanctified & Boss / Exit Status
        cleansed_count = sum(1 for s in self.shrines if s.cleansed)
        shrines_icon = "".join("★" if s.cleansed else "☆" for s in self.shrines)
        if self.boss and self.boss.alive:
            shrine_str = f"RELICS: [{shrines_icon}] ALL PURIFIED | ⚠ BANISH THE SOVEREIGN ECHO!"
            shrine_fg = (255, 90, 210)
        elif cleansed_count == len(self.shrines):
            shrine_str = f"RELICS: [{shrines_icon}] SOVEREIGN BANISHED | EXIT [Ω] UNSEALED!"
            shrine_fg = (100, 255, 160)
        else:
            shrine_str = f"RELICS: [{shrines_icon}] {cleansed_count}/{len(self.shrines)}"
            shrine_fg = (255, 215, 70)
        buf.draw_text(r_hud, max(80, term_w - len(shrine_str) - 2), shrine_str, shrine_fg, bg_bar)

    # --------------------------------------------------------------------------
    # MODAL OVERLAYS (TITLE, CODEX, VICTORY, GAME OVER)
    # --------------------------------------------------------------------------

    def _render_title_screen(self, buf: ScreenBuffer, term_w: int, term_h: int) -> None:
        """Renders classic animated concentric sonar radar rings with gothic ASCII banner and difficulty selection."""
        t = time.time()
        center_r = term_h // 2
        center_c = term_w // 2

        # 1. Background Animation: concentric acoustic sonar radar rings across dark phosphor grid
        for r in range(term_h):
            dr = (r - center_r) * 2.0
            for c in range(term_w):
                dc = c - center_c
                dist = math.hypot(dc, dr)
                wave_val = math.sin(dist * 0.35 - t * 3.2)
                if wave_val > 0.88:
                    crest = (wave_val - 0.88) / 0.12
                    if (int(dist * 0.5) % 2) == 0:
                        fg = (120, 220, 255)
                        bg = (10, 24, 38)
                        char = "•" if crest > 0.5 else "·"
                    else:
                        fg = (255, 180, 70)
                        bg = (28, 18, 8)
                        char = "¤" if crest > 0.5 else "·"
                    buf.set_cell(r, c, char, fg, bg)
                elif wave_val > 0.70:
                    buf.set_cell(r, c, "·", (40, 70, 95), (4, 10, 16))
                else:
                    if r % 4 == 0 and c % 8 == 0:
                        buf.set_cell(r, c, "+", (25, 40, 55), (3, 5, 8))
                    else:
                        buf.set_cell(r, c, " ", (0, 0, 0), (2, 4, 7))

        # 2. Centered Gothic Banner
        banner = [
            "╔═════════════════════════════════════════════════════════════════════╗",
            "║      ╦═╗╔═╗╔═╗╔═╗╔╗╔╔═╗╔╗╔╔═╗╔═╗  :  ╔╦╗╦ ╦╔═╗  ╦  ╦╔═╗╦╔╦╗         ║",
            "║      ╠╦╝║╣ ╚═╗║ ║║║║╠═╣║║║║  ║╣   :   ║ ╠═╣║╣   ╚╗╔╝║ ║║ ║║         ║",
            "║      ╩╚═╚═╝╚═╝╚═╝╝╚╝╩ ╩╝╚╝╚═╝╚═╝  :   ╩ ╩ ╩╚═╝   ╚╝ ╚═╝╩═╩╝         ║",
            "║                                                                     ║",
            "║                 T H E   S I G H T L E S S   W A R D E N             ║",
            "╚═════════════════════════════════════════════════════════════════════╝",
        ]
        banner_w = len(banner[0])
        banner_start_c = max(1, (term_w - banner_w) // 2)
        start_r = max(1, (term_h - 22) // 2)

        modal_bg: RGB = (6, 12, 18)
        for r_i, line in enumerate(banner):
            row = start_r + r_i
            if 0 <= row < term_h:
                for c_i, ch in enumerate(line):
                    col = banner_start_c + c_i
                    if 0 <= col < term_w:
                        fg = (255, 220, 110) if r_i in (1, 2, 3) else ((100, 240, 230) if r_i == 5 else (120, 210, 240))
                        buf.set_cell(row, col, ch, fg, modal_bg)

        # 3. Centered Difficulty Selector Box
        box_start_r = start_r + len(banner) + 1
        diff_box = [
            "╔═════════════════════════════════════════════════════════════════════╗",
            "║                    CHOOSE SANCTUM DIFFICULTY                        ║",
            "║           [ UP/DOWN, W/S or 1/2/3 to Select | ENTER ]               ║",
            "╠═════════════════════════════════════════════════════════════════════╣",
            "║                                                                     ║",
        ]
        for d_idx, diff in enumerate(DIFFICULTIES):
            is_sel = d_idx == self.selected_diff_idx
            pointer = "►" if is_sel else " "
            title_str = f" {pointer} [{d_idx + 1}] {diff['name']}"
            desc_str = f"       {diff['desc']}"
            diff_box.append(f"║{title_str.ljust(69)[:69]}║")
            diff_box.append(f"║{desc_str.ljust(69)[:69]}║")
            diff_box.append("║                                                                     ║")

        diff_box.extend([
            "╠═════════════════════════════════════════════════════════════════════╣",
            "║    [ ENTER / SPACE ] Advance to Armory   [M] Audio   [ESC] Quit     ║",
            "╚═════════════════════════════════════════════════════════════════════╝",
        ])

        for r_i, line in enumerate(diff_box):
            row = box_start_r + r_i
            if 0 <= row < term_h:
                is_border = r_i in (0, 3, len(diff_box) - 3, len(diff_box) - 1)
                for c_i, ch in enumerate(line):
                    col = banner_start_c + c_i
                    if 0 <= col < term_w:
                        fg = (120, 230, 255) if is_border else (210, 230, 240)
                        if 5 <= r_i < 5 + len(DIFFICULTIES) * 3:
                            cur_diff = (r_i - 5) // 3
                            if cur_diff == self.selected_diff_idx:
                                fg = DIFFICULTIES[self.selected_diff_idx]["color"]
                        buf.set_cell(row, col, ch, fg, modal_bg)

    def _render_armory_screen(self, buf: ScreenBuffer, term_w: int, term_h: int) -> None:
        """Renders interactive 2-column Sanctum Armory & Paid DLC Storefront with live ASCII preview."""
        # 1. Dark ambient background
        for r in range(term_h):
            for c in range(term_w):
                if r % 4 == 0 and c % 8 == 0:
                    buf.set_cell(r, c, "·", (25, 38, 50), (4, 7, 10))
                else:
                    buf.set_cell(r, c, " ", (0, 0, 0), (3, 6, 9))

        box_w = min(106, term_w - 4)
        start_c = max(1, (term_w - box_w) // 2)
        start_r = max(1, (term_h - 26) // 2)

        col1_w = 40
        col2_w = box_w - col1_w - 3  # -3 for borders ║ ║ ║

        modal_bg: RGB = (8, 14, 20)
        border_fg: RGB = (100, 220, 255)
        header_fg: RGB = (255, 225, 110)

        # Header Box
        h_top = "╔" + "═" * (box_w - 2) + "╗"
        buf.draw_text(start_r, start_c, h_top, border_fg, modal_bg)

        title_text = f"  SANCTUM ARMORY & STOREFRONT  |  Tithes (Wallet): ${self.wallet_credits:.2f}  |  Diff: {self.difficulty_name}"
        buf.draw_text(start_r + 1, start_c, "║" + title_text.ljust(box_w - 2)[:box_w - 2] + "║", header_fg, modal_bg)

        div_h = "╠" + "═" * col1_w + "╦" + "═" * col2_w + "╣"
        buf.draw_text(start_r + 2, start_c, div_h, border_fg, modal_bg)

        # Column Subheaders
        c1_head = "  SELECT ACOUSTIC WEAPON (1-7):"
        c2_head = "  WEAPON SPECIFICATION & LIVE PREVIEW:"
        subhead_line = "║" + c1_head.ljust(col1_w)[:col1_w] + "║" + c2_head.ljust(col2_w)[:col2_w] + "║"
        buf.draw_text(start_r + 3, start_c, subhead_line, (140, 210, 240), modal_bg)

        sub_div = "╠" + "═" * col1_w + "╬" + "═" * col2_w + "╣"
        buf.draw_text(start_r + 4, start_c, sub_div, border_fg, modal_bg)

        # Main Body: 17 rows
        body_h = 17
        sel_w = self.weapons[self.selected_weapon_idx]

        # Pre-render right column contents
        right_lines: List[Tuple[str, RGB]] = []
        status_str = "[EQUIPPED]" if self.selected_weapon_idx == self.equipped_weapon_idx else ("[OWNED]" if sel_w.unlocked else f"[STORE: {sel_w.price_str}]")
        right_lines.append((f"  ✦ {sel_w.name.upper()}  {status_str}", sel_w.theme_color))
        right_lines.append((f"  Perk: {sel_w.perk_name} — {sel_w.perk_desc}", (200, 230, 240)))
        right_lines.append(("", (0, 0, 0)))

        # Graphical Stat Bars
        def stat_bar(val: float, max_v: float, width: int = 10) -> str:
            filled = int((val / float(max_v)) * width)
            filled = max(0, min(width, filled))
            return "█" * filled + "░" * (width - filled)

        bar_dmg = stat_bar(sel_w.damage, 150)
        bar_cone = stat_bar(sel_w.cone_half_pct, 0.35)
        bar_rng = stat_bar(sel_w.range_m, 18.0)
        bar_ammo = stat_bar(sel_w.max_ammo, 10)
        bar_kb = stat_bar(sel_w.knockback, 5.0)

        stats = [
            f"  DAMAGE    : [{bar_dmg}] {sel_w.damage:3d} DMG",
            f"  CONE WIDTH: [{bar_cone}] {sel_w.cone_desc}",
            f"  RANGE     : [{bar_rng}] {sel_w.range_m:4.1f}m",
            f"  CAPACITY  : [{bar_ammo}] {sel_w.max_ammo:2d} Bolts",
            f"  KNOCKBACK : [{bar_kb}] {sel_w.knockback:4.1f}m",
        ]
        for s in stats:
            right_lines.append((s, (180, 220, 240)))
        right_lines.append(("", (0, 0, 0)))

        # Weapon ASCII Model preview (take 6 lines)
        for line, col in sel_w.ascii_art[:6]:
            right_lines.append((f"      {line.strip()}", col))

        # Render row by row
        for r_i in range(body_h):
            curr_r = start_r + 5 + r_i
            if curr_r >= term_h:
                break
            w_i = r_i // 2
            sub_row = r_i % 2
            left_str = ""
            left_fg = (180, 200, 215)
            if w_i < len(self.weapons):
                w = self.weapons[w_i]
                is_sel = w_i == self.selected_weapon_idx
                is_eq = w_i == self.equipped_weapon_idx
                pointer = "►" if is_sel else " "
                if sub_row == 0:
                    tag = "[EQUIPPED]" if is_eq else ("[OWNED]" if w.unlocked else f"[{w.price_str}]")
                    tag_col = (255, 230, 80) if is_eq else ((100, 255, 180) if w.unlocked else (255, 170, 70))
                    num_str = f" {pointer} {w_i + 1}. {w.name[:20]}"
                    left_str = f"{num_str.ljust(col1_w - len(tag) - 1)}{tag} "
                    left_fg = w.theme_color if is_sel else (220, 230, 240)
                else:
                    left_str = f"     Dmg:{w.damage}  Cone:{w.cone_desc[:9]}  Rng:{w.range_m:.0f}m"
                    left_fg = (130, 160, 180) if not is_sel else (180, 220, 240)

            r_str = ""
            r_fg = (200, 220, 230)
            if r_i < len(right_lines):
                r_str, r_fg = right_lines[r_i]

            row_content = "║" + left_str.ljust(col1_w)[:col1_w] + "║" + r_str.ljust(col2_w)[:col2_w] + "║"
            buf.draw_text(curr_r, start_c, row_content, (120, 230, 255), modal_bg)
            buf.draw_text(curr_r, start_c + 1, left_str.ljust(col1_w)[:col1_w], left_fg, modal_bg)
            buf.draw_text(curr_r, start_c + col1_w + 2, r_str.ljust(col2_w)[:col2_w], r_fg, modal_bg)

        # Footer Divider
        foot_div = "╠" + "═" * col1_w + "╩" + "═" * col2_w + "╣"
        buf.draw_text(start_r + 5 + body_h, start_c, foot_div, border_fg, modal_bg)

        # Feedback Bar
        fb_row = start_r + 6 + body_h
        fb_text = f"  FEEDBACK: {self.armory_feedback}"
        buf.draw_text(fb_row, start_c, "║" + fb_text.ljust(box_w - 2)[:box_w - 2] + "║", (255, 230, 100), modal_bg)

        # Keybinds Footer
        key_div = "╠" + "═" * (box_w - 2) + "╣"
        buf.draw_text(fb_row + 1, start_c, key_div, border_fg, modal_bg)

        controls = "  [↑/↓, 1-7] Select  |  [P] Buy DLC  |  [U] Unlock All  |  [E] Equip  |  [SPACE] Embark  |  [M] Audio  |  [ESC] Back"
        buf.draw_text(fb_row + 2, start_c, "║" + controls.ljust(box_w - 2)[:box_w - 2] + "║", (140, 240, 255), modal_bg)

        foot_close = "╚" + "═" * (box_w - 2) + "╝"
        buf.draw_text(fb_row + 3, start_c, foot_close, border_fg, modal_bg)

    def _render_codex_modal(self, buf: ScreenBuffer, term_w: int, term_h: int) -> None:
        """Renders the Warden's Field Codex guide."""
        lines = [
            "╔═══════════════════════════════════════════════════════════════════════╗",
            "║                     RESONANCE: STRIKE THE VOID                        ║",
            "║                        WARDEN'S FIELD CODEX                           ║",
            "╠═══════════════════════════════════════════════════════════════════════╣",
            "║  [W / S]          Inertial movement with smooth wall-sliding          ║",
            "║  [Q / E]          Lateral strafe left / right                         ║",
            "║  [A / D]          Kinematic camera rotation with head-bob             ║",
            "║  [SPACE]          Strike Tuning Fork (Acoustic Wave Freeze Stun)      ║",
            "║  [F / ENTER / K]  Discharge Wide-Cone Sonic Blast (Auto-Lock reticle) ║",
            "║  [H]              Toggle this Codex overlay                           ║",
            "║  [M]              Toggle Cathedral Procedural Audio Synth Engine      ║",
            "║  [ESC]            Clean exit                                          ║",
            "║                                                                       ║",
            "║  ECHO MEMORY & PROXIMITY LANTERN:                                     ║",
            "║  Nearby walls within 4.0 units are lit by your lantern. Scanned walls ║",
            "║  permanently retain sepia-amber memory so you never get lost.         ║",
            "║                                                                       ║",
            "║  WAVE FREEZE & FORGIVING COMBAT:                                      ║",
            "║  Striking [SPACE] wave-freezes specters for 2.5s (+25% bonus dmg).    ║",
            "║  Your sonic blast knocks back 2.5 units and stuns for 1s.             ║",
            "║  Resonance ammo auto-regenerates 1 bolt every 3.5s.                   ║",
            "║                                                                       ║",
            "║  GTA RADAR & OBJECTIVE BEACONS:                                       ║",
            "║  Follow golden pins (★) on the radar edge to find the 4 Relics.       ║",
            "║  Once sanctified, reach the Exit Portal [Ω] at North-East to win!     ║",
            "╠═══════════════════════════════════════════════════════════════════════╣",
            "║                  [ PRESS ANY KEY TO RETURN TO COMBAT ]                ║",
            "╚═══════════════════════════════════════════════════════════════════════╝",
        ]
        start_r = max(1, (term_h - len(lines)) // 2)
        start_c = max(1, (term_w - len(lines[0])) // 2)
        modal_bg: RGB = (10, 16, 24)
        for r_idx, line in enumerate(lines):
            r = start_r + r_idx
            for c_idx, ch in enumerate(line):
                buf.set_cell(r, start_c + c_idx, ch, (140, 220, 240), modal_bg)

    def _render_gameover_modal(self, buf: ScreenBuffer, term_w: int, term_h: int) -> None:
        """Renders Game Over screen when Warden HP falls to 0."""
        lines = [
            "╔═══════════════════════════════════════════════════════════════════════╗",
            "║                      YOUR LIGHT IS EXTINGUISHED                       ║",
            "║                  The Abyssal Void claims your essence                 ║",
            "╠═══════════════════════════════════════════════════════════════════════╣",
            "║                                                                       ║",
            "║      Your monastic shroud was torn by wandering catacomb specters.    ║",
            "║      The sacred resonant tuning fork falls silent on the stone.       ║",
            "║                                                                       ║",
            "║                 [R] Rise & Try Again     [ESC / M] Sanctum Armory     ║",
            "╚═══════════════════════════════════════════════════════════════════════╝",
        ]
        start_r = max(2, (term_h - len(lines)) // 2)
        start_c = max(1, (term_w - len(lines[0])) // 2)
        modal_bg: RGB = (28, 6, 6)
        for r_idx, line in enumerate(lines):
            r = start_r + r_idx
            for c_idx, ch in enumerate(line):
                buf.set_cell(r, start_c + c_idx, ch, (255, 90, 90), modal_bg)

    def _render_victory_modal(self, buf: ScreenBuffer, term_w: int, term_h: int) -> None:
        """Renders Victory screen when all 4 relics are cleansed and Sovereign Echo is banished."""
        elapsed = int(time.time() - self.start_time)
        lines = [
            ("╔═══════════════════════════════════════════════════════════════════════╗", (100, 255, 180)),
            ("║                     THE CATACOMBS ARE SANCTIFIED                      ║", (255, 230, 120)),
            ("║            The Sovereign Echo Has Been Cast Into Oblivion!            ║", (255, 120, 220)),
            ("╠═══════════════════════════════════════════════════════════════════════╣", (100, 255, 180)),
            ("║                                                                       ║", (100, 255, 180)),
            ("║   The colossal apparition dissolves into echoes of pure gold light.   ║", (220, 240, 245)),
            ("║   All four resonant relics chime in triumphant acoustic harmony.      ║", (220, 240, 245)),
            ("║   You step through the sanctified Exit Portal [Ω] into the dawn.      ║", (220, 240, 245)),
            (f"║   Time Elapsed: {elapsed:3d}s   |   Specters Banished: {self.specters_banished:2d}                 ║", (255, 215, 80)),
            ("║                                                                       ║", (100, 255, 180)),
            ("║                 [R] Play Again           [ESC / M] Sanctum Armory     ║", (100, 255, 180)),
            ("╚═══════════════════════════════════════════════════════════════════════╝", (100, 255, 180)),
        ]
        start_r = max(2, (term_h - len(lines)) // 2)
        start_c = max(1, (term_w - len(lines[0][0])) // 2)
        modal_bg: RGB = (8, 24, 18)
        for r_idx, (line, color) in enumerate(lines):
            r = start_r + r_idx
            if 0 <= r < term_h:
                for c_idx, ch in enumerate(line):
                    col = start_c + c_idx
                    if 0 <= col < term_w:
                        buf.set_cell(r, col, ch, color, modal_bg)

    # --------------------------------------------------------------------------
    # MAIN LOOP (LOCKED 30 FPS ZERO-FLICKER)
    # --------------------------------------------------------------------------

    def run(self) -> None:
        """Main game loop locked at 30 FPS."""
        self.term.enter_fullscreen()
        target_fps = 30.0
        frame_dt = 1.0 / target_fps

        try:
            running = True
            while running:
                t0 = time.perf_counter()

                # 1. Non-blocking input
                keys = self.input_ctrl.read_keys()
                running = self.handle_input(keys, frame_dt)
                if not running:
                    break

                # 2. Physics & world simulation
                self.update(frame_dt)

                # 3. Double-buffered rendering
                self.render()

                # 4. Lock frame rate
                elapsed = time.perf_counter() - t0
                sleep_time = frame_dt - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

        finally:
            self.sound.teardown()
            self.term.restore()


# ==============================================================================
# 5. ENTRY POINT
# ==============================================================================

def main() -> None:
    game = ResonanceGame()
    game.run()


if __name__ == "__main__":
    main()
