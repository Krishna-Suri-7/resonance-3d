# RESONANCE: The Sightless Warden

```
  ██████╗ ███████╗███████╗ ██████╗ ███╗   ██╗ █████╗ ███╗   ██╗ ██████╗███████╗
  ██╔══██╗██╔════╝██╔════╝██╔═══██╗████╗  ██║██╔══██╗████╗  ██║██╔════╝██╔════╝
  ██████╔╝█████╗  ███████╗██║   ██║██╔██╗ ██║███████║██╔██╗ ██║██║     █████╗  
  ██╔══██╗██╔══╝  ╚════██║██║   ██║██║╚██╗██║██╔══██║██║╚██╗██║██║     ██╔══╝  
  ██║  ██║███████╗███████║╚██████╔╝██║ ╚████║██║  ██║██║ ╚████║╚██████╗███████╗
  ╚═╝  ╚═╝╚══════╝╚══════╝ ╚═════╝ ╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝╚══════╝
              ───  T H E   S I G H T L E S S   W A R D E N  ───
          A 3D Acoustic Horror-Action Terminal FPS Rendered in ANSI Truecolor
```

<div align="center">

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/Dependencies-ZERO_(100%25_Stdlib)-brightgreen.svg?style=for-the-badge)](https://docs.python.org/3/library/)
[![Engine](https://img.shields.io/badge/Engine-Custom_3D_ANSI_Raycaster-orange.svg?style=for-the-badge)](#technical-architecture-for-hackathon-judges)
[![Audio](https://img.shields.io/badge/Audio-Procedural_16--Bit_PCM_Synth-purple.svg?style=for-the-badge)](#procedural-cathedral-audio-dsp-engine)
[![Platform](https://img.shields.io/badge/Platform-macOS_%7C_Linux_%7C_Windows-lightgrey.svg?style=for-the-badge)](#cross-platform-compatibility)
[![Performance](https://img.shields.io/badge/Performance-Locked_30--60_FPS-cyan.svg?style=for-the-badge)](#zero-flicker-truecolor-compositor)
[![License](https://img.shields.io/badge/License-MIT-green.svg?style=for-the-badge)](LICENSE)

*Navigate subterranean catacombs using an expanding acoustic sonar shockwave, butter-smooth inertial kinematics, a 7-weapon armory storefront, procedural cathedral audio synthesis, and a circular GTA radar to banish the ancient Sovereign Echo.*

**Zero external dependencies. No Pygame. No curses. No numpy. 100% pure Python standard library.**

[Quick Start (10 Seconds)](#-quick-start-play-in-10-seconds) • [The Lore](#-the-lore--gameplay-concept) • [Key Features](#-key-features) • [Technical Architecture](#-technical-architecture-for-hackathon-judges) • [Sanctum Armory](#-sanctum-armory--dlc-storefront) • [Controls](#-complete-controls-reference)

</div>

---

## ⚡ Quick Start (Play in 10 Seconds)

No virtual environment needed. No `pip install` commands. Run straight out of the box in any standard modern terminal:

```bash
# 1. Clone the repository
git clone https://github.com/Krishna-Suri-7/resonance-3d.git
cd resonance-3d

# 2. Maximize your terminal window (Recommended: 120x40 or Full Screen)
# 3. Launch the game directly
python3 resonance_3d.py
```

### Run Automated System Verification
Validate all 7 core engine systems (data integrity, difficulty modes, monetization flow, 3D raycasting, boss encounter, screen buffer compositor, and DSP audio synthesis):

```bash
python3 verify_full_system.py
```

---

## 📜 The Lore & Gameplay Concept

> *"In the catacombs beneath Saint Eleanor's Basilica, darkness is not merely the absence of light. It is an ocean of silence waiting to consume your soul."*

You play as **Orren**, the last Sightless Warden of the Order of Saint Eleanor. Plunged into subterranean pitch-black catacombs, you are completely blind to ordinary sight. 

### Sound Is Your Only Light
* **The Tuning Fork (`[SPACE]`):** Striking your holy tuning fork releases a 360° expanding acoustic sonar pulse (reminiscent of a *Valorant* recon shockwave). The spherical wave illuminates Gothic arches, flagstones, and holy relics in radiant amber and cyan.
* **Wave Freeze Stun:** Wraiths caught in the expanding wave freeze in acoustic resonance for 2.5s, making them vulnerable to +25% bonus shattering damage.
* **Permanent Echo Memory:** Walls touched by your acoustic pulses permanently retain a dim sepia-amber luminance floor (`0.22`), ensuring you build a lasting mental map of the catacombs and never get lost in the dark.
* **Passive Proximity Lantern:** Your monastic robes project a steady ambient glow up to 4.0 meters, giving you instant situational awareness in tight corridors.

---

## 🎮 Key Features

| Feature | Description |
|---|---|
| **Custom 3D DDA Raycaster** | Real-time perspective projection with procedural brick & mortar UV texture coordinates, Gothic arches, and ceiling/floor architectural edge trim. |
| **Bayer Ordered Dithering** | 4×4 Bayer matrix dither filter that smoothly blends light gradients across ANSI 24-bit Truecolor palettes without harsh banding. |
| **Zero-Stutter Inertial Physics** | Custom input-persistence decay timers, linear acceleration, and exponential friction damping (`vx *= 0.80`, `v_rot *= 0.72`) eliminate OS terminal key-repeat delays. |
| **Figure-8 Lissajous Sway** | Realistic walk-cycle head bobbing and dynamic figure-8 Lissajous weapon sway proportional to player velocity. |
| **Wide-Cone Auto-Lock Combat** | 35% screen-width auto-lock target reticle `[ ✦ LOCKED ✦ ]` with physics-based knockback and particle explosions. |
| **Circular GTA-Style Radar** | Top-right 2D rotating compass radar with a 360° sweeping scan line, 8-way directional warden arrow, and edge-pinned objective waypoints (`★` Relics, `Ω` Exit Portal, `♚` Boss). |
| **7-Weapon Sanctum Armory** | Complete in-game DLC storefront simulating tithe purchases, live ASCII weapon art previews, graphical stat bars, and a **Hackathon Judge Override (`[U]`)**. |
| **3 Selectable Difficulties** | Choose between Story Mode (Initiate), Warden Mode (Standard), and Abyssal Mode (Nightmare). |
| **The Sovereign Echo Boss** | High-resolution 77×113 UV-sampled 3D ASCII boss encounter with triple shockwave attacks and reactive color shifting. |
| **Cathedral Audio & Synth DSP** | Zero-dependency 16-bit 22050Hz mono PCM audio synthesizer with dual feedback delay line reverb and continuous organ drone BGM. |

---

## 🔬 Technical Architecture (For Hackathon Judges)

Built entirely from scratch using only Python's standard library (`math`, `time`, `shutil`, `sys`, `os`, `wave`, `struct`, `tempfile`, `subprocess`, `threading`, `select`, `termios`, `tty` / `msvcrt`).

```mermaid
flowchart TD
    subgraph Inputs [Non-Blocking Input & Kinematics]
        RawIO[select / termios non-blocking read] --> KeyTimers[Key Persistence Timers: 0.18s bridge]
        KeyTimers --> VelPhys[Inertial Linear & Angular Kinematics]
        VelPhys --> Lissajous[Figure-8 Lissajous Weapon Sway & Head-Bob]
    end

    subgraph AudioEngine [Procedural Cathedral Audio DSP Engine]
        MathWave[Pure Math Waveform Generators: Sin, SMR, LFO, FM] --> DelayLine[Cathedral Reverb: 0.08s + 0.17s Delay Taps]
        DelayLine --> PCMEncode[16-Bit Mono PCM 22050Hz WAV Encoding]
        PCMEncode --> AsyncPlay[Async Popen Backend: afplay / paplay / aplay / winsound]
        AsyncPlay --> DroneLoop[Background Daemon Organ Drone Loop]
    end

    subgraph Raycaster [3D World & Shader Pipeline]
        VelPhys --> DDA[Grid DDA Raycaster: 66° FOV]
        DDA --> UVCoord[Procedural Brick & Mortar UV Mapper]
        UVCoord --> SonarShader[Radial Sonar Wave Equation + Echo Memory]
        SonarShader --> BayerDither[4x4 Bayer Ordered Dithering Matrix]
        BayerDither --> Billboards[3D Depth-Sorted Billboard Sprites & Boss UV Art]
    end

    subgraph Compositor [Zero-Flicker Double Buffer]
        Billboards --> ScreenBuf[In-Memory Character & RGB Truecolor Grid]
        Lissajous --> ScreenBuf
        Radar[Circular GTA Minimap] --> ScreenBuf
        ScreenBuf --> DeltaFlush[Batched Cursor Home \033[H Stdout Stream: Locked 30-60 FPS]
    end
```

### 1. Zero-Flicker Double-Buffered Compositor
* Never invokes slow `os.system('clear')` during gameplay.
* Maintains two 2D memory arrays: `chars[height][width]` and `fg[height][width]`.
* Formats terminal output in a single batch string using cursor homing (`\033[H`) and Truecolor ANSI escape sequences (`\033[38;2;R;G;Bm\033[48;2;R;G;Bm`).
* Render loop locks precisely to 30–60 FPS with microsecond `time.perf_counter()` compensation.

### 2. 3D DDA Raycaster & Procedural UV Masonry
* Digital Differential Analysis (DDA) raycasting over a 66° field of view.
* Computes exact horizontal wall hit coordinates $u \in [0.0, 1.0]$ and vertical height coordinates $v \in [0.0, 1.0]$.
* Accurately distinguishes between stone blocks and mortar lines, rendering Gothic cathedral masonry without texture image assets.
* Highlights ceiling and floor horizon edges with high-contrast architectural trim (`═` and `─`).

### 3. Procedural Cathedral Audio DSP Engine
* **Mathematical Synthesis:** Generates sound waves through trigonometric functions:
  * *Organ Drone:* Multi-oscillator organ with binaural detune ($55.0\text{Hz} + 55.5\text{Hz}$), fifths ($82.4\text{Hz}$), and octaves ($110.0\text{Hz}$) modulated by a $0.25\text{Hz}$ sub-bass LFO.
  * *Metallic Sonar Pulse:* $528\text{Hz}$ bell fundamental with $1056\text{Hz}, 1584\text{Hz}, 2340\text{Hz}$ bronze overtones and an exponential $120\text{Hz} \to 40\text{Hz}$ sub drop.
  * *Spectral Wail:* Frequency modulation ($f_c = 400\text{Hz} \to 180\text{Hz}$, $f_m = 273\text{Hz}$).
* **Cathedral Reverb Delay Line:** Passes all float arrays through a dual-tap feedback delay line:
  $$\text{Reverb}[i] = \text{Sample}[i] + 0.40 \cdot \text{Reverb}[i - d_1] + 0.25 \cdot \text{Reverb}[i - d_2]$$
  where $d_1 = 0.08\text{s}$ ($\sim 1764$ samples) and $d_2 = 0.17\text{s}$ ($\sim 3748$ samples).
* **Non-Blocking Asynchronous Streaming:** Dispatches playback asynchronously using platform-native utilities (`afplay` on macOS, `paplay`/`aplay` on Linux, `winsound` on Windows) with strict active process limits ($\le 8$) and an instantaneous mute toggle (`[M]`).

---

## 🏛 Sanctum Armory & DLC Storefront

Visit the 2-column Sanctum Armory before your descent. Browse weapons with live ASCII models, visual stat gauges, and simulated monetization:

| # | Weapon | Price | DMG | Cone | Range | Cap | Perk & Audio Profile |
|---|---|---|---|---|---|---|---|
| **1** | **Sanctum Tuning Arbalest** | `FREE` | 50 | 35% | 10.0m | 6 | *Harmonic Resonance:* Balanced spread; taut bowstring snap audio. |
| **2** | **Choir-Bell Blunderbuss** | `$1.99 DLC` | 75 | 55% | 7.0m | 4 | *Catacomb Repulsor:* Concussive 5.0m knockback; massive organ chord blast. |
| **3** | **Whispering Viol-Bow** | `$1.99 DLC` | 65 | 22% | 18.0m | 8 | *Silent Frequency:* High-velocity long-range silver needles. |
| **4** | **Cathedral Pipe Mortar** | `$2.99 DLC` | 110 | 40% | 12.0m | 3 | *Sub-Bass Tremor:* Enforces guaranteed 2.0s tremor stun on all enemies. |
| **5** | **Cacophony Chime Flail** | `$2.99 DLC` | 40 | 70% | 6.5m | 10 | *Resonant Storm:* Fires 7 wide-spread celestial chime shards. |
| **6** | **Ossuary Skull-Harp** | `$3.99 DLC` | 85 | 30% | 14.0m | 5 | *Soul Siphon:* Banishing an enemy restores **+1 Bolt & +15 HP**! |
| **7** | **The Sovereign Voice** | `$4.99 DLC` | 150 | 50% | 16.0m | 4 | *God-King Resonance:* Deals **+50% bonus DMG (225 DMG)** to The Sovereign Echo! |

### 👑 Hackathon Judge Override: Press `[U]`
Judges can press **`[U]`** in the Armory menu to immediately trigger the **Judge Override**, unlocking all 7 weapons instantly without spending tithes!

---

## 👁 The Sovereign Echo Boss Encounter

Purifying all 4 Sacred Relics (`★`) causes an acoustic cataclysm that unseals the **Exit Plaza** and awakens **The Sovereign Echo** (`♚`, 350 HP):
* **77×113 ASCII Artwork:** An enormous gothic titan apparition rendered directly in 3D perspective via bilinear UV coordinate sampling from raw ASCII artwork.
* **Boss Attacks:** Discharges multi-directional Abyssal Tremor shockwaves that crack monastic shields and scramble your visual HUD.
* **Celestial Counter:** Wielding **The Sovereign Voice** channels god-king frequencies, tearing through boss armor with 225 DMG strikes to unlock the Exit Portal (`Ω`).

---

## 🕹 Complete Controls Reference

### Title Screen & Difficulty Menu
* **`W` / `S`** or **`↑` / `↓`**: Navigate difficulty modes
* **`1` / `2` / `3`**: Quick-select Story, Warden, or Abyssal difficulty
* **`ENTER` / `SPACE`**: Confirm difficulty and proceed to Sanctum Armory
* **`M`**: Mute / Unmute Cathedral Audio
* **`ESC`**: Clean terminal exit

### Sanctum Armory Storefront
* **`W` / `S`** or **`↑` / `↓`**: Browse weapon catalog
* **`1` – `7`**: Quick-select weapons 1 through 7
* **`P`**: Purchase selected DLC weapon with Sanctum Tithes
* **`U`**: **Hackathon Judge Override (Unlocks ALL weapons for free)**
* **`E` / `ENTER`**: Equip selected unlocked weapon
* **`SPACE` / `B`**: Embark into the 3D catacombs
* **`M`**: Mute / Unmute Cathedral Audio
* **`ESC`**: Return to Difficulty Selection

### In-Game 3D Catacombs Combat
* **`W` / `S`** or **`↑` / `↓`**: Inertial move forward / backward with smooth wall-sliding
* **`Q` / `E`**: Lateral strafe left / right
* **`A` / `D`** or **`←` / `→`**: Kinematic camera rotation
* **`SPACE`**: Strike Holy Tuning Fork (360° expanding sonar wave & Wave Freeze)
* **`F` / `ENTER` / `K`**: Fire equipped acoustic weapon (Wide-Cone Auto-Lock)
* **`M`**: Dynamic audio mute toggle
* **`H`**: Open Warden's Field Codex guide overlay
* **`R`**: Re-awaken / Play again after Victory or Defeat
* **`ESC`**: Return to Sanctum Armory or exit

---

## 🌐 Cross-Platform Compatibility

Tested and optimized for:
* **macOS:** Terminal.app, iTerm2, Alacritty, Kitty, VS Code Terminal
* **Linux:** GNOME Terminal, Konsole, Alacritty, xterm (24-bit color supported)
* **Windows:** Windows Terminal, PowerShell, CMD (supports Windows 10+ ANSI sequences)

---

## ⚖ License

Distributed under the **MIT License**. See `LICENSE` for details.

Developed with passion by **Krishna Suri** ([@Krishna-Suri-7](https://github.com/Krishna-Suri-7)). Built for the Hackathon.
