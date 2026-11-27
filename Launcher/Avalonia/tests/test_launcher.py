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

    def test_installation_report_tracks_source_and_integrity(self):
        launcher.install(self.archive, self.exe, "dxgi.dll")
        report = launcher.installation_report(self.exe)
        self.assertEqual(report["status"], "healthy")
        self.assertEqual(report["source_archive"], "release.zip")
        self.assertEqual(len(report["source_sha256"]), 64)
        self.assertEqual(report["verified"], 2)
        (self.game / "dxgi.dll").write_bytes(b"tampered")
        report = launcher.installation_report(self.exe)
        self.assertEqual(report["status"], "needs_attention")
        self.assertEqual(report["modified"], 1)

    def test_old_install_record_has_no_invented_release_version(self):
        launcher.install(self.archive, self.exe, "dxgi.dll")
        record_path = self.game / launcher.STATE_NAME
        record = json.loads(record_path.read_text())
        record.pop("source_archive")
        record.pop("source_sha256")
        record_path.write_text(json.dumps(record))
        report = launcher.installation_report(self.exe)
        self.assertEqual(report["status"], "healthy")
        self.assertIsNone(report["source_archive"])

    def test_installation_report_detects_missing_backup(self):
        existing = self.game / "dxgi.dll"
        existing.write_bytes(b"original")
        launcher.install(self.archive, self.exe, "dxgi.dll")
        (self.game / "AMDNR_backup/linux-launcher/dxgi.dll").unlink()
        report = launcher.installation_report(self.exe)
        self.assertEqual(report["status"], "needs_attention")
        self.assertEqual(report["backups_missing"], 1)

    def test_installation_report_not_installed(self):
        report = launcher.installation_report(self.exe)
        self.assertFalse(report["installed"])
        self.assertEqual(report["status"], "not_installed")

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

    def test_release_catalog_filters_to_checksum_backed_amdnr_zip(self):
        releases = [
            {"tag_name": "Alpha1", "name": "AMDNR Alpha 1", "draft": False,
             "assets": [
                 {"name": "SHA256SUMS.txt", "size": 128},
                 {"name": "AMDNR-v1.zip", "size": 120},
                 {"name": "AMDNR-Launcher.exe", "size": 900},
             ]},
            {"tag_name": "Alpha2", "assets": [
                {"name": "AMDNR-v2.zip", "size": 120},
            ]},
        ]
        with patch.object(launcher, "_github_json", return_value=releases):
            catalog = launcher.release_catalog()
        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0]["tag"], "Alpha1")
        self.assertEqual(catalog[0]["asset"], "AMDNR-v1.zip")

    def test_download_release_verifies_sha256_and_caches(self):
        import hashlib
        import io
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("OptiScaler.dll", b"test binary")
        payload = stream.getvalue()
        digest = hashlib.sha256(payload).hexdigest()
        metadata = {"tag_name": "Alpha1", "assets": [
            {"name": "SHA256SUMS.txt"}, {"name": "AMDNR-v1.zip", "size": len(payload)},
        ]}

        class Response:
            status = 200

            def __init__(self, value):
                self.value = io.BytesIO(value)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

            def read(self, size=-1):
                return self.value.read(size)

        def fetch(request, timeout=0):
            url = request.full_url
            return Response((digest + "  AMDNR-v1.zip\n").encode() if
                            url.endswith("SHA256SUMS.txt") else payload)

        with patch.dict(launcher.os.environ, {"XDG_CACHE_HOME": str(self.root / "cache")}), \
             patch.object(launcher, "_github_json", return_value=metadata), \
             patch.object(launcher.urllib.request, "urlopen", side_effect=fetch) as mocked:
            destination = launcher.download_release("Alpha1", "AMDNR-v1.zip")
            self.assertEqual(destination.read_bytes(), payload)
            launcher.download_release("Alpha1", "AMDNR-v1.zip")
            # Checksum is consulted for each call; archive itself downloaded only once.
            self.assertEqual(mocked.call_count, 3)

    def test_download_rejects_bad_checksum(self):
        import io
        metadata = {"tag_name": "Alpha1", "assets": [
            {"name": "SHA256SUMS.txt"}, {"name": "AMDNR-v1.zip", "size": 50},
        ]}
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

            def read(self, size=-1):
                return b"0" * 64 + b"  AMDNR-v1.zip\n" if size > 1000 else b"bad zip content"

        with patch.dict(launcher.os.environ, {"XDG_CACHE_HOME": str(self.root / "cache")}), \
             patch.object(launcher, "_github_json", return_value=metadata), \
             patch.object(launcher.urllib.request, "urlopen", return_value=Response()):
            with self.assertRaisesRegex(ValueError, "exceeded the published size"):
                launcher.download_release("Alpha1", "AMDNR-v1.zip")

    def test_release_blocks_arbitrary_asset_names(self):
        with self.assertRaisesRegex(ValueError, "Only AMDNR release ZIP"):
            launcher._release_asset("Alpha1", "other-package.exe")

    def test_doctor_checks_installed_file_integrity(self):
        launcher.install(self.archive, self.exe, "dxgi.dll")
        with patch.object(launcher, "steam_libraries", return_value=[self.root]):
            report = launcher.doctor_report(self.exe, self.archive)
            results = {v["name"]: v for v in report["checks"]}
            self.assertTrue(results["Installed AMDNR files"]["ok"])
            (self.game / "dxgi.dll").write_bytes(b"tampered")
            report = launcher.doctor_report(self.exe, self.archive)
            results = {v["name"]: v for v in report["checks"]}
            self.assertFalse(results["Installed AMDNR files"]["ok"])
            self.assertIn("1 missing or modified", results["Installed AMDNR files"]["detail"])

    def test_doctor_without_game_is_read_only(self):
        with patch.object(launcher, "steam_libraries", return_value=[]):
            report = launcher.doctor_report(None, None)
        self.assertFalse(next(x for x in report["checks"] if x["name"] == "Game executable")["ok"])
        self.assertFalse((self.root / launcher.STATE_NAME).exists())

    def test_custom_game_persists_name_and_folder(self):
        with patch.dict(launcher.os.environ, {
            "XDG_CONFIG_HOME": str(self.root / "configuration"),
        }):
            added = launcher.add_custom_game(self.game, "My Custom Game")
            self.assertEqual(added["name"], "My Custom Game")
            saved = launcher.custom_games()
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["folder"], str(self.game))
            self.assertTrue(saved[0]["exists"])
            self.assertTrue((self.root / "configuration/amdnr/custom-games.json").is_file())
            with self.assertRaisesRegex(ValueError, "already"):
                launcher.add_custom_game(self.game, "Duplicate")
            launcher.rename_custom_game(self.game, "Updated Name")
            self.assertEqual(launcher.custom_games()[0]["name"], "Updated Name")

    def test_custom_game_missing_directory_still_listed(self):
        with patch.dict(launcher.os.environ, {
            "XDG_CONFIG_HOME": str(self.root / "configuration"),
        }):
            launcher.add_custom_game(self.game)
            self.exe.unlink()
            self.game.rmdir()
            items = launcher.custom_games()
            self.assertEqual(len(items), 1)
            self.assertFalse(items[0]["exists"])

    def test_custom_game_remove_does_not_touch_game_files(self):
        with patch.dict(launcher.os.environ, {
            "XDG_CONFIG_HOME": str(self.root / "configuration"),
        }):
            launcher.add_custom_game(self.game)
            launcher.remove_custom_game(self.game)
            self.assertEqual(launcher.custom_games(), [])
            self.assertTrue(self.exe.is_file())

    def test_custom_game_validation_and_registry_failure(self):
        with patch.dict(launcher.os.environ, {
            "XDG_CONFIG_HOME": str(self.root / "configuration"),
        }):
            with self.assertRaisesRegex(ValueError, "existing game folder"):
                launcher.add_custom_game(self.root / "not-found")
            with self.assertRaisesRegex(ValueError, "printable"):
                launcher.add_custom_game(self.game, "bad\nname")
            path = launcher._custom_games_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("invalid json", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "custom game registry"):
                launcher.custom_games()

    def test_executable_candidates_prioritize_shipping_binary(self):
        shipping = self.game / "Binaries/Win64/Example-Win64-Shipping.exe"
        shipping.parent.mkdir(parents=True)
        shipping.write_bytes(b"shipping")
        (self.game / "setup.exe").write_bytes(b"installer")
        candidates = launcher.executable_candidates(self.game)
        self.assertEqual(candidates[0]["path"], str(shipping))
        self.assertTrue(candidates[0]["recommended"])
        self.assertTrue(next(x for x in candidates
                             if x["path"].endswith("setup.exe"))["suspicious"])

    def test_developer_console_is_ranked_below_real_game(self):
        game_exe = self.game / "game/bin/win64/game.exe"
        console = self.game / "game/bin/win64/vconsole2.exe"
        game_exe.parent.mkdir(parents=True)
        game_exe.write_bytes(b"game")
        console.write_bytes(b"console")
        candidates = launcher.executable_candidates(self.game)
        self.assertEqual(candidates[0]["path"], str(game_exe))
        self.assertTrue(next(x for x in candidates
                             if x["path"] == str(console))["suspicious"])

    def test_steam_primary_launch_overrides_ambiguous_filename_scoring(self):
        (self.game / "Editor.exe").write_bytes(b"editor")
        primary = self.game / "ActualGame.exe"
        primary.write_bytes(b"target")
        report = {"source": "steam_cache", "reason": "steam_primary",
                  "selected": str(primary), "windows_candidates": [str(primary)],
                  "linux_launches": 1}
        with patch.object(launcher, "steam_launch_for_directory", return_value=report):
            result = launcher.executable_scan(self.game)
        self.assertEqual(result["reason"], "steam_primary")
        self.assertEqual(result["candidates"][0]["path"], str(primary))
        self.assertTrue(result["candidates"][0]["auto_select"])

    def test_steam_tool_metadata_never_automatically_picks_exe(self):
        report = {"source": "steam_cache", "reason": "not_a_game",
                  "selected": None, "windows_candidates": [], "linux_launches": 0}
        with patch.object(launcher, "steam_launch_for_directory", return_value=report):
            result = launcher.executable_scan(self.game)
        self.assertFalse(any(c["auto_select"] for c in result["candidates"]))

    def test_custom_games_do_not_require_steam_cache(self):
        report = launcher.steam_launch_for_directory(self.game)
        self.assertEqual(report["reason"], "not_steam_install")
        self.assertIsNone(report["selected"])

    def test_strong_executable_match_auto_selects(self):
        actual = self.game / "Binaries/Win64/Sample-Win64-Shipping.exe"
        console = self.game / "Binaries/Win64/vconsole.exe"
        actual.parent.mkdir(parents=True)
        actual.write_bytes(b"game")
        console.write_bytes(b"console")
        candidates = launcher.executable_candidates(self.game)
        self.assertEqual(candidates[0]["path"], str(actual))
        self.assertTrue(candidates[0]["auto_select"])
        self.assertFalse(candidates[1]["auto_select"])

    def test_ambiguous_executables_do_not_auto_select(self):
        (self.game / "first.exe").write_bytes(b"one")
        (self.game / "second.exe").write_bytes(b"two")
        candidates = launcher.executable_candidates(self.game)
        self.assertFalse(any(c["auto_select"] for c in candidates))

    def test_saved_game_exe_preference_survives_reload(self):
        chosen = self.game / "second.exe"
        chosen.write_bytes(b"exe")
        with patch.dict(launcher.os.environ, {
            "XDG_CONFIG_HOME": str(self.root / "config"),
        }):
            self.assertEqual(launcher.remember_executable(self.game, chosen), str(chosen))
            self.assertEqual(launcher.saved_executable(self.game), str(chosen))
            chosen.unlink()
            self.assertIsNone(launcher.saved_executable(self.game))

    def test_preference_cannot_point_outside_selected_game(self):
        other = self.root / "outside.exe"
        other.write_bytes(b"exe")
        with self.assertRaisesRegex(ValueError, "inside the selected game"):
            launcher.remember_executable(self.game, other)

    def test_nested_windows_executable_beyond_old_depth_limit(self):
        nested = self.game.joinpath(*([f"level{i}" for i in range(9)]))
        nested.mkdir(parents=True)
        executable = nested / "RealGame.EXE"
        executable.write_bytes(b"windows exe")
        scan = launcher.executable_scan(self.game)
        self.assertIn(str(executable), [item["path"] for item in scan["candidates"]])
        self.assertEqual(scan["reason"], "found_windows_exe")

    def test_native_linux_game_is_reported_without_fabricated_exe(self):
        self.exe.unlink()  # Fixture normally includes a Windows EXE.
        binary = self.game / "Game.x86_64"
        binary.write_bytes(b"\x7fELF" + b"\x00" * 50)
        scan = launcher.executable_scan(self.game)
        self.assertEqual(scan["candidates"], [])
        self.assertEqual(scan["reason"], "native_linux_files")
        self.assertIn("Game.x86_64", scan["native"])

    def test_linux_game_shell_launcher_detected(self):
        self.exe.unlink()  # Fixture normally includes a Windows EXE.
        script = self.game / "start.sh"
        script.write_bytes(b"#!/bin/sh\nexec ./game\n")
        scan = launcher.executable_scan(self.game)
        self.assertEqual(scan["reason"], "native_linux_files")
        self.assertIn("start.sh", scan["native"])

    def test_symlink_to_outside_windows_exe_is_ignored(self):
        self.exe.unlink()  # Fixture normally includes a Windows EXE.
        outside = self.root / "elsewhere"
        outside.mkdir()
        (outside / "outside.exe").write_bytes(b"outside")
        (self.game / "linked").symlink_to(outside, target_is_directory=True)
        scan = launcher.executable_scan(self.game)
        self.assertEqual(scan["candidates"], [])
        self.assertNotEqual(scan["reason"], "found_windows_exe")

    def test_scan_continues_when_one_directory_is_unreadable(self):
        good = self.game / "good"
        good.mkdir()
        (good / "working.exe").write_bytes(b"exe")
        broken = self.game / "broken"
        broken.mkdir()
        import os
        original_scandir = os.scandir
        def fake_scandir(path):
            if Path(path) == broken:
                raise PermissionError("restricted")
            return original_scandir(path)
        with patch.object(launcher.os, "scandir", side_effect=fake_scandir):
            scan = launcher.executable_scan(self.game)
        self.assertTrue(scan["partial"])
        self.assertIn(str(good / "working.exe"),
                      [item["path"] for item in scan["candidates"]])

    def test_executable_candidates_empty_for_unknown_game(self):
        self.assertEqual(launcher.executable_candidates(self.root / "missing"), [])

    def test_doctor_pending_is_not_a_failure(self):
        with patch.object(launcher, "steam_libraries", return_value=[]):
            results = launcher.doctor_report(None, None)["checks"]
        executable = next(x for x in results if x["name"] == "Game executable")
        archive = next(x for x in results if x["name"] == "AMDNR release ZIP")
        self.assertEqual(executable["status"], "not_selected")
        self.assertEqual(archive["status"], "not_selected")

    def test_missing_game_executable_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Windows"):
            launcher.install(self.archive, self.game / "missing.exe", "dxgi.dll")


if __name__ == "__main__":
    unittest.main()
