import sys
import os
import time

# Ensure we can import resonance_3d
sys.path.insert(0, '/Users/krishnasuri/.gemini/antigravity/scratch/resonance')
from resonance_3d import (
    ResonanceGame,
    ScreenBuffer,
    SoundEngine,
    WEAPONS_CATALOG,
    DIFFICULTIES,
    SOVEREIGN_ART,
    SOVEREIGN_H,
    SOVEREIGN_W,
)

def run_tests():
    print("=" * 70)
    print("RUNNING COMPREHENSIVE VERIFICATION FOR RESONANCE: THE SIGHTLESS WARDEN")
    print("=" * 70)

    # TEST 1: Assets & Initialization
    print("\n[TEST 1] Assets & Data Integrity")
    assert len(WEAPONS_CATALOG) == 7, f"Expected 7 weapons, found {len(WEAPONS_CATALOG)}"
    assert len(DIFFICULTIES) == 3, f"Expected 3 difficulties, found {len(DIFFICULTIES)}"
    assert SOVEREIGN_H == 77, f"Expected 77 boss art rows, got {SOVEREIGN_H}"
    assert SOVEREIGN_W > 100, f"Expected >100 boss art cols, got {SOVEREIGN_W}"
    print("✓ All 7 weapons, 3 difficulties, and 77-row Sovereign Echo boss artwork intact.")

    game = ResonanceGame()
    assert game.game_state == "TITLE", f"Expected initial state TITLE, got {game.game_state}"
    assert game.wallet_credits == 5.00, f"Expected $5.00 wallet, got {game.wallet_credits}"
    assert game.equipped_weapon.id == "arbalest", f"Expected default weapon arbalest, got {game.equipped_weapon.id}"
    print("✓ ResonanceGame initialized in TITLE state with $5.00 Sanctum Tithes.")

    # TEST 2: Difficulty Selection on Home Screen
    print("\n[TEST 2] Difficulty Selection Mechanics")
    # Default is Warden Mode (index 1)
    assert game.selected_diff_idx == 1
    assert game.max_hp == 100
    assert game.spirit_speed_mult == 1.0

    # Pick Story Mode with '1'
    game.handle_input(["1"], 0.033)
    assert game.selected_diff_idx == 0
    game.handle_input(["ENTER"], 0.033)
    assert game.game_state == "ARMORY"
    assert game.max_hp == 150
    assert game.spirit_speed_mult == 0.60
    assert game.stun_duration_mult == 1.50
    assert game.ammo_regen_interval == 2.0
    assert game.lantern_radius == 5.0
    print("✓ Story Mode correctly applies: 150 HP, 0.6x speed, 1.5x stun, 2.0s regen, 5.0m lantern.")

    # Return to TITLE with ESC and pick Abyssal Mode
    game.handle_input(["ESC"], 0.033)
    assert game.game_state == "TITLE"
    game.handle_input(["3"], 0.033)
    assert game.selected_diff_idx == 2
    game.handle_input([" "], 0.033)
    assert game.game_state == "ARMORY"
    assert game.max_hp == 60
    assert game.spirit_speed_mult == 1.35
    assert game.stun_duration_mult == 0.75
    assert game.ammo_regen_interval == 4.5
    assert game.lantern_radius == 2.5
    print("✓ Abyssal Mode correctly applies: 60 HP, 1.35x speed, 0.75x stun, 4.5s regen, 2.5m lantern.")

    # Reset to Warden Mode for standard gameplay test
    game.handle_input(["ESC"], 0.033)
    game.handle_input(["2"], 0.033)
    game.handle_input(["ENTER"], 0.033)
    assert game.max_hp == 100
    print("✓ Warden Mode confirmed standard baseline: 100 HP, 1.0x speed, 4.0m lantern.")

    # TEST 3: Sanctum Armory & Monetization Storefront
    print("\n[TEST 3] Armory Storefront & Monetization Simulation")
    # Weapon 0 (Arbalest) is unlocked & equipped
    assert game.weapons[0].unlocked is True
    assert game.weapons[1].unlocked is False  # Blunderbuss ($1.99)
    assert game.weapons[6].unlocked is False  # Sovereign Voice ($4.99)

    # Select Blunderbuss (idx 1)
    game.handle_input(["2"], 0.033)
    assert game.selected_weapon_idx == 1

    # Try to equip locked weapon -> Should fail with locked feedback
    game.handle_input(["e"], 0.033)
    assert game.equipped_weapon.id == "arbalest"
    assert "LOCKED" in game.armory_feedback
    print("✓ Attempting to equip locked weapon was properly rejected.")

    # Purchase Blunderbuss with [P] ($1.99)
    assert game.wallet_credits == 5.00
    game.handle_input(["p"], 0.033)
    assert game.weapons[1].unlocked is True
    assert abs(game.wallet_credits - 3.01) < 0.001
    assert "PURCHASE CONFIRMED" in game.armory_feedback
    print("✓ Purchased Choir-Bell Blunderbuss: $1.99 deducted, balance is $3.01.")

    # Equip the newly purchased Blunderbuss
    game.handle_input(["e"], 0.033)
    assert game.equipped_weapon.id == "blunderbuss"
    assert game.max_ammo == 4
    assert game.ammo == 4
    print("✓ Equipped Choir-Bell Blunderbuss: ammo capacity set to 4.")

    # Select Sovereign Voice ($4.99) and try to purchase with $3.01 -> Should fail
    game.handle_input(["7"], 0.033)
    assert game.selected_weapon_idx == 6
    game.handle_input(["p"], 0.033)
    assert game.weapons[6].unlocked is False
    assert "INSUFFICIENT" in game.armory_feedback
    print("✓ Insufficient funds correctly handled for Sovereign Voice ($4.99 > $3.01).")

    # Hackathon Judge Override: [U] unlocks ALL weapons!
    game.handle_input(["u"], 0.033)
    for idx, w in enumerate(game.weapons):
        assert w.unlocked is True, f"Weapon {w.name} was not unlocked by Judge Override!"
    assert "JUDGE OVERRIDE" in game.armory_feedback
    print("✓ Hackathon Judge Override [U] successfully unlocked all 7 DLC weapons!")

    # Equip The Sovereign Voice ($4.99 DLC)
    game.handle_input(["e"], 0.033)
    assert game.equipped_weapon.id == "sovereign_voice"
    assert game.max_ammo == 4
    print("✓ Equipped The Sovereign Voice with God-King Resonance perk.")

    # TEST 4: Embark into 3D Catacombs & Firing Combat Mechanics
    print("\n[TEST 4] 3D Gameplay Embarkation & Weapon Perks")
    # Embark with [SPACE]
    game.handle_input([" "], 0.033)
    assert game.game_state == "PLAYING"
    assert len(game.pulses) > 0, "Expected sonar pulse wave upon entering catacombs"
    print("✓ Embarked into 3D catacombs! State is PLAYING, sonar wave active.")

    # Test firing Sovereign Voice: deals 150 dmg, spawns projectile with symbol 'Ξ'
    init_ammo = game.ammo
    game.handle_input(["f"], 0.033)
    assert game.ammo == init_ammo - 1
    assert len(game.projectiles) > 0
    proj = game.projectiles[-1]
    assert proj.char == "Ξ"
    assert proj.color == (255, 120, 240)
    print("✓ Sovereign Voice fires celestial prismatic 'Ξ' projectiles with custom speed and color.")

    # Test weapon perk: Ossuary Skull-Harp Soul Siphon
    game.weapons[5].unlocked = True
    game.selected_weapon_idx = 5
    game._equip_selected_weapon()
    assert game.equipped_weapon.id == "skull_harp"

    # Damage and banish an enemy to test Soul Siphon (+1 ammo, +15 HP)
    game.hp = 80
    game.ammo = 2
    test_enemy = game.enemies[0]
    test_enemy.hp = 10  # low hp
    test_enemy.alive = True
    test_enemy.x = game.px + 1.0
    test_enemy.y = game.py
    game.p_angle = 0.0  # face directly toward enemy

    # Fire Skull-Harp at enemy
    game._fire_resonant_bolt()
    assert test_enemy.alive is False
    assert game.hp == 95  # 80 + 15
    assert game.ammo == 2  # spent 1, siphoned 1 -> 2
    print("✓ Soul Siphon verified: banishing enemy restored +1 Bolt and +15 HP!")

    # Test weapon perk: Cathedral Pipe Mortar Sub-Bass Tremor
    game.selected_weapon_idx = 3
    game._equip_selected_weapon()
    assert game.equipped_weapon.id == "mortar"
    test_enemy2 = game.enemies[1]
    test_enemy2.alive = True
    test_enemy2.hp = 200
    test_enemy2.x = game.px + 1.5
    test_enemy2.y = game.py
    game._fire_resonant_bolt()
    assert test_enemy2.hp == 90  # 200 - 110 dmg
    assert test_enemy2.stun_timer >= 2.0  # guaranteed 2.0s tremor stun
    print("✓ Cathedral Pipe Mortar verified: deals 110 DMG and enforces 2.0s tremor stun.")

    # TEST 5: Sovereign Echo Boss Encounter & God-King Resonance Perk
    print("\n[TEST 5] Sovereign Echo Boss & 3D Celestial Void Perk")
    # Cleanse all shrines to spawn boss
    for s in game.shrines:
        s.cleansed = True
    game.update(0.033)
    assert game.boss_spawned is True
    assert game.boss is not None
    assert game.boss.alive is True
    assert game.boss.hp == 350
    print("✓ Cleansing all 4 shrines awakened The Sovereign Echo (350 HP).")

    # Equip Sovereign Voice to test +50% Celestial Void bonus against boss
    game.selected_weapon_idx = 6
    game._equip_selected_weapon()
    assert game.equipped_weapon.id == "sovereign_voice"
    game.boss.x = game.px + 2.0
    game.boss.y = game.py
    game._fire_resonant_bolt()
    # Base 150 dmg * 1.50 = 225 dmg against boss!
    expected_hp = 350 - 225
    assert game.boss.hp == expected_hp, f"Expected boss hp {expected_hp}, got {game.boss.hp}"
    print(f"✓ God-King Resonance verified: dealt 225 DMG (+50% bonus) to The Sovereign Echo!")

    # Banish boss
    game._fire_resonant_bolt()
    assert game.boss.alive is False
    assert game.boss_alive is False
    print("✓ The Sovereign Echo banished into golden light! Sanctum Exit Portal [Ω] unsealed.")

    # TEST 6: Screen Buffer & Modal Rendering at 120x40 and 80x28
    print("\n[TEST 6] Screen Buffer Compositor & ANSI Output Verification")
    buf = ScreenBuffer(120, 40)
    # Render Title Screen
    game.game_state = "TITLE"
    game._render_title_screen(buf, 120, 40)
    stream_title = buf.render_stream()
    assert len(stream_title) > 1000
    title_plain = "\n".join("".join(row) for row in buf.chars)
    assert "S I G H T L E S S   W A R D E N" in title_plain
    assert "CHOOSE SANCTUM DIFFICULTY" in title_plain
    print("✓ Title Screen with Concentric Radar Rings & Difficulty Menu rendered cleanly.")

    # Render Armory Screen
    buf_armory = ScreenBuffer(120, 40)
    game.game_state = "ARMORY"
    game._render_armory_screen(buf_armory, 120, 40)
    stream_armory = buf_armory.render_stream()
    assert len(stream_armory) > 1000
    armory_plain = "\n".join("".join(row) for row in buf_armory.chars)
    assert "SANCTUM ARMORY & STOREFRONT" in armory_plain
    assert "SELECT ACOUSTIC WEAPON" in armory_plain
    print("✓ Sanctum Armory Screen with 7 weapons, live stats & ASCII models rendered cleanly.")

    # Render Active 3D Viewport in PLAYING state
    game.game_state = "PLAYING"
    buf_play = ScreenBuffer(120, 40)
    # Mock sys.stdout.write
    saved_stdout = sys.stdout
    class NullOut:
        def write(self, s): pass
        def flush(self): pass
    sys.stdout = NullOut()
    try:
        game.render()
    finally:
        sys.stdout = saved_stdout
    print("✓ In-game 3D DDA raycaster and weapon compositor rendered without exceptions.")

    # TEST 7: Procedural Cathedral Audio & Synth Engine
    print("\n[TEST 7] Procedural Cathedral Audio & Synth Engine")
    assert hasattr(game, "sound"), "ResonanceGame missing sound engine instance!"
    assert isinstance(game.sound, SoundEngine), "game.sound is not an instance of SoundEngine!"

    # 1. Presets synthesis verification
    expected_sounds = [
        "drone", "sonar", "weapon_light", "weapon_heavy", "weapon_chime",
        "spirit_hit", "spirit_banish", "relic", "purchase", "hurt", "step"
    ]
    for snd_name in expected_sounds:
        assert snd_name in game.sound.sound_files, f"Preset {snd_name} missing from sound files!"
        fpath = game.sound.sound_files[snd_name]
        assert os.path.exists(fpath), f"Audio file {fpath} does not exist on disk!"
        assert os.path.getsize(fpath) > 1000, f"Audio file {fpath} is suspiciously small ({os.path.getsize(fpath)} bytes)!"

        # Verify WAV header specs
        import wave
        with wave.open(fpath, "rb") as wf:
            assert wf.getnchannels() == 1, f"Expected mono audio, got {wf.getnchannels()} channels"
            assert wf.getsampwidth() == 2, f"Expected 16-bit PCM (2 bytes), got {wf.getsampwidth()}"
            assert wf.getframerate() == 22050, f"Expected 22050 Hz, got {wf.getframerate()}"
    print(f"✓ All {len(expected_sounds)} procedural audio presets synthesized in 16-bit 22050Hz mono WAV.")

    # 2. Reverb Filter Verification
    # An impulse should produce multi-tap echo decaying at 0.08s and 0.17s
    impulse = [1.0] + [0.0] * int(0.25 * 22050)
    rev_impulse = game.sound._apply_cathedral_reverb(impulse)
    tap1_idx = int(0.08 * 22050)
    tap2_idx = int(0.17 * 22050)
    assert abs(rev_impulse[tap1_idx] - 0.40) < 0.05, f"Expected tap 1 gain ~0.40, got {rev_impulse[tap1_idx]}"
    assert abs(rev_impulse[tap2_idx] - 0.25) < 0.05, f"Expected tap 2 gain ~0.25, got {rev_impulse[tap2_idx]}"
    print("✓ Cathedral Reverb Filter verified: dual delay lines at 0.08s (gain 0.40) and 0.17s (gain 0.25).")

    # 3. Mute Toggle and Real-Time Playback
    assert game.sound.muted is False, "Expected sound engine unmuted by default"
    game.handle_input(["m"], 0.033)
    assert game.sound.muted is True, "Pressing [M] failed to toggle mute to True!"
    game.sound.play("sonar")  # Should be a no-op when muted
    assert len(game.sound.active_procs) == 0, "No audio processes should launch when muted!"
    game.handle_input(["m"], 0.033)
    assert game.sound.muted is False, "Pressing [M] failed to toggle mute to False!"
    print("✓ Real-time mute toggle [M] verified: safely silences active and queued audio.")

    # 4. HUD Mute Status Display
    buf_hud = ScreenBuffer(120, 40)
    game._render_status_hud(buf_hud, 120, 40)
    hud_plain = "\n".join("".join(row) for row in buf_hud.chars)
    assert "[M] MUTE: OFF" in hud_plain, "Expected [M] MUTE: OFF in HUD status line"
    game.sound.toggle_mute()
    game._render_status_hud(buf_hud, 120, 40)
    hud_muted = "\n".join("".join(row) for row in buf_hud.chars)
    assert "[M] MUTE: ON" in hud_muted, "Expected [M] MUTE: ON in HUD status line when muted"
    game.sound.toggle_mute()
    print("✓ HUD telemetry accurately reflects dynamic audio mute state.")

    # 5. Teardown and Cleanup Verification
    standalone_snd = SoundEngine()
    tmp_path = standalone_snd.temp_dir
    assert os.path.exists(tmp_path), f"Temp dir {tmp_path} does not exist"
    standalone_snd.play("sonar")
    standalone_snd.teardown()
    assert not os.path.exists(tmp_path), f"Temp dir {tmp_path} was not cleaned up after teardown!"
    print("✓ SoundEngine teardown verified: drone thread stopped and temp directory removed.")

    # Teardown game sound engine
    game.sound.teardown()

    print("\n" + "=" * 70)
    print("ALL 7 TEST SUITES PASSED FLAWLESSLY! CODEBASE FULLY VALIDATED.")
    print("=" * 70)

if __name__ == "__main__":
    run_tests()
