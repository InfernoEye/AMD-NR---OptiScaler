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
