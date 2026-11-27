import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch


MODULE = Path(__file__).resolve().parents[1] / "amdnr_launcher.py"
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
        cover.write_bytes(b"\xff\xd8\xff" + b"x" * 100)
        with patch.object(launcher, "steam_games", return_value=[("Test", game)]), \
             patch.object(launcher, "steam_roots", return_value=[steam]):
            details = launcher.steam_game_details()
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]["name"], "Test")
        self.assertEqual(details[0]["artwork"], str(cover))

    def test_steam_artwork_uses_nested_cache_layout(self):
        steam = self.root / "Steam"
        cache = steam / "appcache/librarycache/123"
        cache.mkdir(parents=True)
        cover = cache / "library_600x900.jpg"
        cover.write_bytes(b"\xff\xd8\xff" + b"x" * 100)
        self.assertEqual(launcher._steam_artwork("123", [steam]), str(cover))

    def test_steam_artwork_rejects_non_numeric_app_id(self):
        with patch.object(launcher.urllib.request, "urlopen") as request:
            self.assertIsNone(launcher._steam_artwork("../test", [], True))
            request.assert_not_called()

    def test_steam_artwork_downloads_and_caches_missing_cover(self):
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _size):
                return b"\xff\xd8\xff" + b"\x00" * 200

        with patch.dict(launcher.os.environ, {
            "XDG_CACHE_HOME": str(self.root / "cache"),
            "AMDNR_NO_ARTWORK_DOWNLOAD": "0",
        }), patch.object(launcher.urllib.request, "urlopen", return_value=FakeResponse()) as get:
            found = launcher._steam_artwork("123", [], True)
            self.assertEqual(Path(found).read_bytes()[:3], b"\xff\xd8\xff")
            self.assertIn("/steam/apps/123/library_600x900.jpg", get.call_args.args[0].full_url)
            self.assertEqual(launcher._steam_artwork("123", [], True), found)
            self.assertEqual(get.call_count, 2)

    def test_user_grid_artwork_precedes_official_cache(self):
        steam = self.root / "Steam"
        grid = steam / "userdata/12345/config/grid"
        grid.mkdir(parents=True)
        custom = grid / "678p.png"
        custom.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 80)
        cache = steam / "appcache/librarycache"
        cache.mkdir(parents=True)
        (cache / "678_library_600x900.jpg").write_bytes(b"\xff\xd8\xff" + b"x" * 90)
        self.assertEqual(launcher._steam_artwork("678", [steam]), str(custom))

    def test_per_game_manual_artwork_override(self):
        artwork = self.root / "custom.png"
        artwork.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)
        with patch.dict(launcher.os.environ, {
            "XDG_DATA_HOME": str(self.root / "data"),
        }):
            saved = launcher.set_artwork(self.game, artwork)
            self.assertTrue(Path(saved).is_file())
            self.assertEqual(launcher._steam_artwork("123", [], game_folder=self.game), saved)

    def test_manual_artwork_rejects_nonimage(self):
        bad = self.root / "not-an-image.jpg"
        bad.write_text("not an image")
        with self.assertRaisesRegex(ValueError, "JPEG and PNG"):
            launcher.set_artwork(self.game, bad)

    def test_artwork_from_secondary_steam_library_cache(self):
        secondary = self.root / "SecondLibrary"
        cache = secondary / "appcache/librarycache"
        cache.mkdir(parents=True)
        cover = cache / "234_library_600x900.jpg"
        cover.write_bytes(b"\xff\xd8\xff" + b"x" * 100)
        with patch.object(launcher, "steam_libraries", return_value=[secondary]):
            self.assertEqual(launcher._cached_artwork("234", []), cover)

    def test_missing_artwork_report(self):
        with patch.object(launcher, "steam_game_details", return_value=[
            {"name": "Has Art", "folder": "/example/a", "artwork": "/example/pic.jpg"},
            {"name": "No Art", "folder": "/example/b", "artwork": None},
        ]):
            report = launcher.artwork_diagnostics()
        self.assertEqual(report["total"], 2)
        self.assertEqual(report["with_artwork"], 1)
        self.assertEqual(report["missing"][0]["name"], "No Art")

    def test_hashed_subdirectory_steam_artwork(self):
        steam = self.root / "Steam"
        hashed = steam / "appcache/librarycache/987/012345abcdef"
        hashed.mkdir(parents=True)
        art = hashed / "library_600x900.jpg"
        art.write_bytes(b"\xff\xd8\xff" + b"x" * 100)
        self.assertEqual(launcher._cached_artwork("987", [steam]), art)

    def test_game_names_not_used_as_artwork_identifiers(self):
        with patch.object(launcher, "steam_games", return_value=[
            ("Some New Game", self.game),
        ]), patch.object(launcher, "steam_roots", return_value=[]), \
             patch.object(launcher, "_steam_artwork", return_value=None) as get:
            result = launcher.steam_game_details()
        self.assertEqual(result[0]["artwork"], None)
        # Source lookups use Steam IDs / installation directories, not a
        # hand-maintained mapping of game names.
        self.assertEqual(get.call_args.args[3], self.game)

    def test_missing_game_executable_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Windows"):
            launcher.install(self.archive, self.game / "missing.exe", "dxgi.dll")


if __name__ == "__main__":
    unittest.main()
