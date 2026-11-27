"""Tests for read-only Linux environment and opt-in per-game preferences."""
from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import linux_environment as environment
import amdnr_launcher as core


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / "Game"
        self.game.mkdir()
        self.exe = self.game / "sample.exe"
        self.exe.write_bytes(b"test")
        self.config = self.root / "config"

    def _fake_proc(self, pid, *argv, comm):
        proc = self.root / "proc" / str(pid)
        proc.mkdir(parents=True)
        (proc / "cmdline").write_bytes(b"\x00".join(x.encode() for x in argv) + b"\x00")
        (proc / "comm").write_text(comm + "\n")
        return proc

    def test_running_game_check_ignores_launcher_arguments_and_win64_directory(self):
        game = self.game / "Binaries" / "Win64"
        game.mkdir(parents=True)
        exe = game / "Subnautica2-Win64-Test.exe"
        exe.write_bytes(b"test")
        proc_root = self.root / "proc"
        self._fake_proc(100, "/usr/bin/python3", "amdnr_launcher.py",
                        "--bridge-install", "--exe", str(exe), comm="python3")
        self._fake_proc(101, "/usr/bin/AMDNR-Launcher", "--exe", str(exe),
                        comm="AMDNR-Launcher")
        self._fake_proc(102, "bash", "-c", f"wine \\"{exe}\\"",
                        comm="bash")
        self.assertFalse(environment.game_running(exe, proc_root=proc_root)["running"])

    def test_running_game_check_detects_real_wine_game(self):
        exe = self.game / "Subnautica2-Win64-Test.exe"
        exe.write_bytes(b"test")
        proc_root = self.root / "proc"
        self._fake_proc(200, "/usr/bin/wine64", str(exe), comm="wine64")
        report = environment.game_running(exe, proc_root=proc_root)
        self.assertTrue(report["running"])
        self.assertEqual(report["pids"], [200])

    def test_running_game_check_detects_truncated_wine_process_name(self):
        exe = self.game / "Subnautica2-Win64-Test.exe"
        exe.write_bytes(b"test")
        proc_root = self.root / "proc"
        self._fake_proc(201, "Z:\\\\Games\\\\Subnautica2-Win64-Test.exe",
                        comm=exe.name[:15])
        report = environment.game_running(exe, proc_root=proc_root)
        self.assertTrue(report["running"])

    def test_profile_is_per_game_and_rejects_bad_options(self):
        other = self.root / "Another Game"
        other.mkdir()
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.config)}):
            self.assertFalse(environment.profile(self.game)["gamemode"])
            saved = environment.save_profile(self.game, {
                "gamemode": True, "mangohud": True,
                "selected_proton": "GE-Proton10",
                "tested_runtime": "mochizuki",
                "tested_result": "detected_in_game",
            })
            self.assertTrue(saved["gamemode"])
            self.assertFalse(environment.profile(other)["gamemode"])
            self.assertEqual(environment.profile(self.game)["tested_result"], "detected_in_game")
            with self.assertRaisesRegex(ValueError, "Unknown"):
                environment.save_profile(self.game, {"run_shell_command": "rm -rf"})
            with self.assertRaisesRegex(ValueError, "Unsupported runtime test"):
                environment.save_profile(self.game, {"tested_result": "magically_works"})

    def test_launch_preview_preserves_steam_env_without_writes(self):
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.config)}):
            with patch.object(environment.shutil, "which", return_value="/usr/bin/test"):
                environment.save_profile(self.game, {"gamemode": True})
                result = environment.launch_preview(
                    self.game, "dxgi.dll",
                    'WINEDLLOVERRIDES="version=n,b" mangohud %command% -novid')
                self.assertEqual(result["status"], "ok")
                self.assertIn("version=n,b;dxgi=n,b", result["launch_options"])
                self.assertIn("gamemoderun %command% -novid", result["launch_options"])
            bad = environment.launch_preview(self.game, "dxgi.dll", "WINEDLLOVERRIDES=$BAD %command%")
            self.assertEqual(bad["status"], "needs_review")
            self.assertIsNone(bad["launch_options"])

    def test_launch_preview_does_not_duplicate_existing_user_wrapper(self):
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.config)}):
            environment.save_profile(self.game, {"gamemode": True, "mangohud": True})
            with patch.object(environment.shutil, "which", return_value="/usr/bin/test"):
                result = environment.launch_preview(
                    self.game, "dxgi.dll", "gamemoderun mangohud %command%")
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["launch_options"].count("gamemoderun"), 1)
            self.assertEqual(result["launch_options"].count("mangohud"), 1)

    def test_launch_preview_warns_if_optional_wrapper_is_absent(self):
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.config)}):
            environment.save_profile(self.game, {"gamemode": True})
            with patch.object(environment.shutil, "which", return_value=None):
                outcome = environment.launch_preview(self.game, "dxgi.dll", "%command%")
            self.assertEqual(outcome["status"], "missing_wrapper")

    def test_anti_cheat_warning_is_read_only(self):
        (self.game / "EasyAntiCheat").mkdir()
        (self.game / "EasyAntiCheat" / "something.dll").write_bytes(b"test")
        report = environment.anti_cheat_scan(self.game)
        self.assertTrue(report["potential_anti_cheat"])
        self.assertIn("EasyAntiCheat", report["filenames"])

    def test_redacted_support_bundle_does_not_leak_secrets(self):
        (self.game / "OptiScaler.log").write_text("password=super-secret\nHello")
        (self.game / "OptiScaler.ini").write_text("[Auth]\ntoken=PRIVATE")
        with (patch.object(core, "steam_roots", return_value=[]),
              patch.object(environment, "gpu_probe", return_value=[]),
              patch.object(environment, "game_running", return_value={"running": False}),
              patch.object(environment, "proton_tools", return_value=[])):
            result = environment.support_bundle(self.exe, self.root / "reports")
        self.assertTrue(result["local_only"])
        with zipfile.ZipFile(result["file"]) as bundle:
            content = "\n".join(bundle.read(name).decode() for name in bundle.namelist())
            self.assertNotIn("super-secret", content)
            self.assertNotIn("PRIVATE", content)
            self.assertIn("report.json", bundle.namelist())

    def test_compatibility_does_not_claim_hardware_support(self):
        with (patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.config)}),
              patch.object(environment, "gpu_probe", return_value=[{
                  "vendor": "AMD", "generation": "unknown"}]),
              patch.object(environment, "game_running", return_value={"running": False}),
              patch.object(environment, "proton_tools", return_value=[])):
            info = environment.compatibility(self.exe, [])
        self.assertEqual(info["verdict"], "untested")
        self.assertIn("not supported", info["daniel_080"])


if __name__ == "__main__":
    unittest.main()
