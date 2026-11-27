import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch


MODULE = Path(__file__).resolve().parents[1] / "amdnr_linux_launcher.py"
spec = importlib.util.spec_from_file_location("amdnr_linux_launcher", MODULE)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.game = self.root / "Game With Spaces"
        self.game.mkdir()
        self.exe = self.game / "Game.exe"
        self.exe.write_bytes(b"fake game")
        self.archive = self.root / "release.zip"
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("release/OptiScaler.dll", b"new proxy")
            archive.writestr("release/OptiScaler.ini", b"configuration")
            archive.writestr("release/setup_windows.bat", b"not installed")

    def test_install_uninstall_restores_existing_files(self):
        proxy = self.game / "dxgi.dll"
        proxy.write_bytes(b"previous game dll")
        options = launcher.install(self.archive, self.exe, "dxgi.dll")
        self.assertIn('WINEDLLOVERRIDES="dxgi=n,b"', options)
        self.assertEqual(proxy.read_bytes(), b"new proxy")
        self.assertTrue((self.game / launcher.STATE_NAME).exists())
        self.assertFalse((self.game / "setup_windows.bat").exists())
        self.assertEqual(
            (self.game / "AMDNR_backup/linux-launcher/dxgi.dll").read_bytes(),
            b"previous game dll"
        )
        count, warnings = launcher.uninstall(self.exe)
        self.assertEqual((count, warnings), (2, []))
        self.assertEqual(proxy.read_bytes(), b"previous game dll")
        self.assertFalse((self.game / "OptiScaler.ini").exists())

    def test_modified_files_are_kept(self):
        launcher.install(self.archive, self.exe, "dxgi.dll")
        (self.game / "dxgi.dll").write_bytes(b"user changed this")
        _, warnings = launcher.uninstall(self.exe)
        self.assertEqual(len(warnings), 1)
        self.assertEqual((self.game / "dxgi.dll").read_bytes(), b"user changed this")
        state = json.loads((self.game / launcher.STATE_NAME).read_text())
        self.assertEqual(len(state["files"]), 1)

    def test_reinstall_is_refused(self):
        launcher.install(self.archive, self.exe, "dxgi.dll")
        with self.assertRaisesRegex(ValueError, "already recorded"):
            launcher.install(self.archive, self.exe, "dxgi.dll")

    def test_archive_path_traversal_is_rejected(self):
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("../outside/OptiScaler.dll", b"bad")
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            launcher.install(self.archive, self.exe, "dxgi.dll")
        self.assertFalse((self.root / "outside").exists())

    def test_steam_game_details_reads_local_artwork(self):
        library = self.root / "library"
        common = library / "steamapps/common"
        game = common / "TestGame"
        game.mkdir(parents=True)
        (library / "steamapps/appmanifest_123.acf").write_text(
            '"AppState"\n{\n"appid" "123"\n"name" "Test"\n"installdir" "TestGame"\n}',
            encoding="utf-8")
        steam = self.root / "Steam"
        cache = steam / "appcache/librarycache"
        cache.mkdir(parents=True)
        cover = cache / "123_library_600x900.jpg"
        cover.write_bytes(b"fake cover")
        with patch.object(launcher, "steam_games", return_value=[("Test", game)]), \
             patch.object(launcher, "steam_roots", return_value=[steam]):
            details = launcher.steam_game_details()
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]["name"], "Test")
        self.assertEqual(details[0]["artwork"], str(cover))

    def test_missing_game_executable_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Windows"):
            launcher.install(self.archive, self.game / "missing.exe", "dxgi.dll")


if __name__ == "__main__":
    unittest.main()
