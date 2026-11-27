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

    def test_installed_games_overview_reads_records_without_hashing(self):
        state_home = self.root / "state"
        with patch.dict("os.environ", {"XDG_STATE_HOME": str(state_home)}):
            launcher._write_library_index([{
                "name": "Game With Spaces", "folder": str(self.game),
                "executable": str(self.exe), "custom": False,
            }])
            record = self.game / launcher.STATE_NAME
            record.write_text(json.dumps({
                "format": 1, "alias": "dxgi.dll",
                "files": [{"path": "missing.dll", "sha256": "not-verified"}],
                "source_archive": "/tmp/amd-nr.zip",
            }))
            with patch.object(launcher, "_digest",
                              side_effect=AssertionError("unexpected hashing")), \
                 patch.object(launcher, "_game_binary_scan",
                              side_effect=AssertionError("unexpected scan")):
                overview = launcher.installed_games_overview()
            self.assertEqual(len(overview), 1)
            self.assertEqual(overview[0]["status"], "recorded")
            self.assertEqual(overview[0]["alias"], "dxgi.dll")
            self.assertEqual(overview[0]["tracked_files"], 1)
            self.assertEqual(overview[0]["source_archive"], "/tmp/amd-nr.zip")
            record.unlink()
            self.assertEqual(launcher.installed_games_overview(), [])

    def test_installed_games_overview_marks_corrupt_records(self):
        state_home = self.root / "state"
        with patch.dict("os.environ", {"XDG_STATE_HOME": str(state_home)}):
            launcher._write_library_index([{
                "name": "Game", "folder": str(self.game),
                "executable": str(self.exe), "custom": True,
            }])
            record = self.game / launcher.STATE_NAME
            record.write_text('{"format": 1, "alias": "bad.dll", "files": []}')
            overview = launcher.installed_games_overview()
            self.assertEqual(overview[0]["status"], "invalid_record")
            self.assertIsNone(overview[0]["alias"])
            self.assertTrue(overview[0]["custom"])

    def test_installed_games_overview_ignores_stale_index_paths(self):
        state_home = self.root / "state"
        with patch.dict("os.environ", {"XDG_STATE_HOME": str(state_home)}):
            launcher._write_library_index([{
                "name": "Removed game", "folder": str(self.root / "gone"),
                "executable": str(self.root / "gone" / "game.exe"),
            }])
            self.assertEqual(launcher.installed_games_overview(), [])

    def test_community_mochi_requires_explicit_opt_in(self):
        with patch.object(launcher, "_github_json") as metadata:
            with self.assertRaisesRegex(ValueError, "explicit user opt-in"):
                launcher.prepare_mochi_from_community(self.exe)
            metadata.assert_not_called()

    def test_community_mochi_verifies_zip_and_dll_before_preparation(self):
        import hashlib
        import io
        dll = b"example known test DLL content"
        memory = io.BytesIO()
        with zipfile.ZipFile(memory, "w") as archive:
            archive.writestr("payload/nvngx_dlssnr.dll", dll)
        payload = memory.getvalue()
        zip_digest = hashlib.sha256(payload).hexdigest()
        dll_digest = hashlib.sha256(dll).hexdigest()
        metadata = {"tag_name": launcher.MOCHI_COMMUNITY_TAG,
                    "assets": [{"name": launcher.MOCHI_COMMUNITY_ASSET,
                                "size": len(payload),
                                "digest": "sha256:" + zip_digest}]}
        class Response:
            def __init__(self):
                self.stream = io.BytesIO(payload)
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                pass
            def read(self, size=-1):
                return self.stream.read(size)
        def extract_verified(_exe, source):
            self.assertEqual(source.name, "nvngx_dlssnr.dll")
            self.assertEqual(source.read_bytes(), dll)
            return {"status": "prepared", "models": {"dlssnr.bin": {
                "bytes": 42, "sha256": "a" * 64}}}
        with (patch.object(launcher, "MOCHI_COMMUNITY_ZIP_SHA256", zip_digest),
              patch.object(launcher, "MOCHI_EXPECTED_DLL_SHA256", dll_digest),
              patch.object(launcher, "_github_json", return_value=metadata),
              patch.object(launcher.urllib.request, "urlopen", return_value=Response()),
              patch.object(launcher, "prepare_mochi_model", side_effect=extract_verified) as prepare):
            result = launcher.prepare_mochi_from_community(self.exe, consent=True)
        self.assertEqual(result["status"], "prepared")
        self.assertEqual(result["community_mirror"], "RankFTW/rhi-repo")
        prepare.assert_called_once()
        self.assertFalse(any(self.game.glob(".amdnr-community-*")))
        self.assertFalse((self.game / "nvngx_dlssnr.dll").exists())

    def test_community_mochi_rejects_replaced_mirror_digest_before_download(self):
        metadata = {"assets": [{"name": launcher.MOCHI_COMMUNITY_ASSET,
                                "size": 123,
                                "digest": "sha256:" + "0" * 64}]}
        with (patch.object(launcher, "_github_json", return_value=metadata),
              patch.object(launcher.urllib.request, "urlopen") as download):
            with self.assertRaisesRegex(ValueError, "digest changed"):
                launcher.prepare_mochi_from_community(self.exe, consent=True)
            download.assert_not_called()

    def test_community_mochi_rejects_unexpected_dll_and_does_not_prepare(self):
        import hashlib
        import io
        memory = io.BytesIO()
        with zipfile.ZipFile(memory, "w") as archive:
            archive.writestr("nvngx_dlssnr.dll", b"unapproved DLL")
        payload = memory.getvalue()
        digest = hashlib.sha256(payload).hexdigest()
        metadata = {"assets": [{"name": launcher.MOCHI_COMMUNITY_ASSET,
                                "size": len(payload),
                                "digest": "sha256:" + digest}]}
        class Response:
            def __init__(self):
                self.stream = io.BytesIO(payload)
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                pass
            def read(self, size=-1):
                return self.stream.read(size)
        with (patch.object(launcher, "MOCHI_COMMUNITY_ZIP_SHA256", digest),
              patch.object(launcher, "_github_json", return_value=metadata),
              patch.object(launcher.urllib.request, "urlopen", return_value=Response()),
              patch.object(launcher, "prepare_mochi_model") as prepare):
            with self.assertRaisesRegex(ValueError, "does not match supported"):
                launcher.prepare_mochi_from_community(self.exe, consent=True)
            prepare.assert_not_called()
        self.assertFalse(any(self.game.glob(".amdnr-community-*")))

    def test_mochi_model_preparation_only_installs_verified_local_outputs(self):
        import subprocess
        source = self.root / "nvngx_dlssnr.dll"
        source.write_bytes(b"fixture local NVIDIA input")
        def fake_extract(command, **kwargs):
            staging = Path(command[3])
            (staging / "dlssnr.bin").write_bytes(b"NRMODEL1" + b"x" * (1024 * 1024 + 16))
            (staging / "dlssnr-small.bin").write_bytes(b"NRMODEL1" + b"y" * (1024 * 1024 + 16))
            return subprocess.CompletedProcess(command, 0, stdout="verified fixture", stderr="")
        with patch.object(subprocess, "run", side_effect=fake_extract):
            result = launcher.prepare_mochi_model(self.exe, source)
        self.assertEqual(result["status"], "prepared")
        model_a = self.game / "dlssnr-amd/dlssnr.bin"
        self.assertTrue(model_a.is_file())
        self.assertTrue((self.game / "dlssnr-amd/dlssnr-small.bin").exists())
        self.assertTrue(launcher.runtime_diagnostics(self.exe)["mochi_model_present"])
        with patch.object(subprocess, "run") as ignored:
            with self.assertRaisesRegex(ValueError, "already exists"):
                launcher.prepare_mochi_model(self.exe, source)
            ignored.assert_not_called()
        self.assertEqual(model_a.read_bytes()[:8], b"NRMODEL1")

    def test_mochi_model_preparation_rejects_bad_source_and_failed_extraction(self):
        import subprocess
        source = self.root / "nvngx_dlssnr.dll"
        source.write_bytes(b"bad")
        other = self.root / "wrong.dll"
        other.write_bytes(b"bad")
        with self.assertRaisesRegex(ValueError, "named nvngx_dlssnr.dll"):
            launcher.prepare_mochi_model(self.exe, other)
        with patch.object(subprocess, "run",
                          return_value=subprocess.CompletedProcess(
                              ["bash"], 1, stdout="", stderr="bad source SHA256")):
            with self.assertRaisesRegex(ValueError, "bad source SHA256"):
                launcher.prepare_mochi_model(self.exe, source)
        self.assertFalse((self.game / "dlssnr-amd/dlssnr.bin").exists())

    def test_runtime_diagnostics_reads_missing_and_present_files_without_modification(self):
        with patch.dict("os.environ", {"XDG_STATE_HOME": str(self.root / "state")}):
            initial = launcher.runtime_diagnostics(self.exe)
            self.assertFalse(initial["mochi_runtime_present"])
            self.assertFalse(initial["mochi_model_present"])
            self.assertFalse(initial["mochi_shader_dir_present"])
            self.assertFalse(initial["mochi_legacy_asi_required"])
            self.assertFalse(initial["daniel_pass_present"])
            self.assertFalse(initial["daniel_weights_present"])
            self.assertEqual(initial["folder"], str(self.game))
            (self.game / "MochizukiNrRuntime.dll").write_bytes(b"mock mochi runtime")
            for number in range(1, 4):
                (self.game / f"dlssnr_amd_pass{number}.dll").write_bytes(b"mock daniel pass")
            (self.game / "dlssnr_on_amd_weights.bin").write_bytes(b"mock weights")
            after = launcher.runtime_diagnostics(self.exe)
            self.assertTrue(after["mochi_runtime_present"])
            self.assertFalse(after["mochi_model_present"])
            model = self.game / "dlssnr-amd/dlssnr.bin"
            model.parent.mkdir()
            model.write_bytes(b"locally derived model")
            (self.game / "dlssnr-amd/shaders").mkdir()
            (self.game / "dlssnr-amd/aco").mkdir()
            after = launcher.runtime_diagnostics(self.exe)
            self.assertTrue(after["mochi_model_present"])
            self.assertTrue(after["mochi_shader_dir_present"])
            self.assertTrue(after["mochi_aco_dir_present"])
            self.assertTrue(after["daniel_pass_present"])
            self.assertTrue(after["daniel_weights_present"])
            self.assertEqual((self.game / "MochizukiNrRuntime.dll").read_bytes(),
                             b"mock mochi runtime")

    def test_official_daniel_runtime_discovery_uses_historical_release(self):
        releases = [{"tag_name": "Alpha2", "assets": [{"name": "SHA256SUMS.txt"}]}]
        daniel = {"tag_name": "Alpha0.3.5.5R4", "assets": [
            {"name": "SHA256SUMS.txt"}, {"name": "v0.6.0-Runtime.zip", "size": 176366023}]}
        with patch.object(launcher, "_github_json", side_effect=[releases, daniel]) as getter:
            found = launcher.component_catalog()
        self.assertEqual(found[0]["asset"], "v0.6.0-Runtime.zip")
        self.assertEqual(found[0]["tag"], "Alpha0.3.5.5R4")
        self.assertIn("3zwr1", launcher.RELEASE_REPO)
        self.assertIn("Alpha0.3.5.5R4", getter.call_args_list[1].args[0])

    def test_daniel_runtime_installs_required_files_to_game_root_only(self):
        tag, asset = "Alpha0.3.5.5R4", "v0.6.0-Runtime.zip"
        cache = self.root / tag
        cache.mkdir()
        archive = cache / asset
        with zipfile.ZipFile(archive, "w") as stream:
            for i in range(1, 4):
                stream.writestr(f"package/bin/dlssnr_amd_pass{i}.dll", b"pass " + bytes([i]))
            stream.writestr("package/bin/dlssnr_on_amd_weights.bin", b"weights")
            stream.writestr("package/docs/danielblnc_ATTRIBUTION.txt", b"credit")
            stream.writestr("package/dxgi.dll", b"must not install")
            stream.writestr("package/setup.exe", b"must not install")
        with (patch.dict("os.environ", {"XDG_STATE_HOME": str(self.root / "state")}),
              patch.object(launcher, "download_release", return_value=archive),
              patch.object(launcher, "_release_cache_dir", return_value=self.root)):
            preview = launcher.component_preview(self.exe, tag, asset)
            self.assertTrue(preview["installable"])
            self.assertEqual(preview["file_count"], 5)
            self.assertIn("dlssnr_amd_pass1.dll", preview["files"])
            launcher.install_component(self.exe, tag, asset)
            self.assertTrue(launcher.runtime_diagnostics(self.exe)["daniel_pass_present"])
            self.assertTrue(launcher.runtime_diagnostics(self.exe)["daniel_weights_present"])
            self.assertFalse((self.game / "dxgi.dll").exists())
            self.assertFalse((self.game / "package").exists())
            launcher.remove_component(self.exe, asset)
            self.assertFalse((self.game / "dlssnr_amd_pass1.dll").exists())

    def test_daniel_runtime_rejects_missing_pass_and_duplicate_destinations(self):
        tag, asset = "Alpha0.3.5.5R4", "v0.6.0-Runtime.zip"
        archive = self.root / asset
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr("dlssnr_amd_pass1.dll", b"one")
        with patch.object(launcher, "download_release", return_value=archive):
            with self.assertRaisesRegex(ValueError, "missing required"):
                launcher.component_preview(self.exe, tag, asset)
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr("folder1/dlssnr_amd_pass1.dll", b"one")
            stream.writestr("folder2/dlssnr_amd_pass1.dll", b"two")
        with patch.object(launcher, "download_release", return_value=archive):
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                launcher.component_preview(self.exe, tag, asset)

    def test_official_component_catalog_filters_and_deduplicates(self):
        releases = [
            {"tag_name": "Alpha2", "draft": False, "assets": [
                {"name": "SHA256SUMS.txt", "size": 20},
                {"name": "AMDNR-Mochi-1-component.zip", "size": 120},
                {"name": "AMDNR-v1.zip", "size": 150},
                {"name": "AMDNR-Launcher.exe", "size": 40}]},
            {"tag_name": "Alpha1", "draft": False, "assets": [
                {"name": "SHA256SUMS.txt", "size": 20},
                {"name": "AMDNR-Mochi-1-component.zip", "size": 120},
                {"name": "AMDNR-lmxxf-2.zip", "size": 150}]}
        ]
        with patch.object(launcher, "_github_json", return_value=releases):
            result = launcher.component_catalog()
        self.assertEqual([x["asset"] for x in result],
                         ["AMDNR-Mochi-1-component.zip", "AMDNR-lmxxf-2.zip"])
        self.assertEqual(result[0]["tag"], "Alpha2")
        self.assertEqual(launcher.RELEASE_REPO, "3zwr1/AMD-NR---OptiScaler")

    def test_official_component_install_preview_and_safe_remove(self):
        tag, asset = "Alpha1", "AMDNR-Mochi-1-component.zip"
        cache = self.root / "cache" / tag
        cache.mkdir(parents=True)
        archive = cache / asset
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr("components/MochizukiNrRuntime.dll", b"official runtime")
            stream.writestr("components/LICENSE.txt", b"license")
        state = self.root / "state"
        with (patch.dict("os.environ", {"XDG_STATE_HOME": str(state)}),
              patch.object(launcher, "download_release", return_value=archive),
              patch.object(launcher, "_release_cache_dir", return_value=cache.parent)):
            preview = launcher.component_preview(self.exe, tag, asset)
            self.assertTrue(preview["installable"])
            self.assertEqual(len(preview["files"]), 2)
            result = launcher.install_component(self.exe, tag, asset)
            self.assertEqual(result["files"], 2)
            self.assertEqual(len(launcher.installed_components(self.exe)), 1)
            with self.assertRaisesRegex(ValueError, "already managed"):
                launcher.install_component(self.exe, tag, asset)
            target = self.game / "components" / "MochizukiNrRuntime.dll"
            target.write_bytes(b"modified externally")
            with self.assertRaisesRegex(ValueError, "modified"):
                launcher.remove_component(self.exe, asset)
            self.assertTrue(target.exists())
            target.write_bytes(b"official runtime")
            launcher.remove_component(self.exe, asset)
            self.assertFalse(target.exists())
            self.assertFalse((self.game / "components" / "LICENSE.txt").exists())
            self.assertEqual(launcher.installed_components(self.exe), [])

    def test_large_file_count_archive_is_installable_within_limit(self):
        tag, asset = "Alpha1", "AMDNR-Mochi-1-component.zip"
        archive = self.root / asset
        with zipfile.ZipFile(archive, "w") as stream:
            for i in range(520):
                stream.writestr(f"models/shader_{i:04d}.bin", b"tiny")
        with patch.object(launcher, "download_release", return_value=archive):
            preview = launcher.component_preview(self.exe, tag, asset)
        self.assertEqual(preview["file_count"], 520)
        self.assertEqual(len(preview["files"]), 50)
        self.assertFalse(preview["too_many_files"])
        self.assertFalse(preview["safety_limit_exceeded"])
        self.assertTrue(preview["installable"])

    def test_component_preview_preserves_identical_and_blocks_different_files(self):
        tag, asset = "Alpha1", "AMDNR-Mochi-1-component.zip"
        cache = self.root / tag
        cache.mkdir()
        archive = cache / asset
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr("plugins/existing.txt", b"match")
            stream.writestr("plugins/new.bin", b"new data")
        (self.game / "plugins").mkdir()
        existing = self.game / "plugins/existing.txt"
        existing.write_bytes(b"match")
        with (patch.dict("os.environ", {"XDG_STATE_HOME": str(self.root / "state")}),
              patch.object(launcher, "download_release", return_value=archive),
              patch.object(launcher, "_release_cache_dir", return_value=self.root)):
            preview = launcher.component_preview(self.exe, tag, asset)
            self.assertTrue(preview["installable"])
            self.assertEqual(preview["identical_count"], 1)
            self.assertEqual(preview["new_file_count"], 1)
            self.assertEqual(preview["conflict_count"], 0)
            launcher.install_component(self.exe, tag, asset)
            self.assertEqual(existing.read_bytes(), b"match")
            owned = launcher._component_records(self.exe)[asset]["files"]
            self.assertEqual(set(owned), {"plugins/new.bin"})
            launcher.remove_component(self.exe, asset)
            self.assertTrue(existing.exists())
            self.assertFalse((self.game / "plugins/new.bin").exists())

    def test_component_backup_replacement_restores_original_on_removal(self):
        tag, asset = "Alpha1", "AMDNR-Mochi-1-component.zip"
        cache = self.root / tag
        cache.mkdir()
        archive = cache / asset
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr("dlssnr-amd/shaders/accumulation.txt", b"new constant")
            stream.writestr("dlssnr-amd/shaders/new.nrp", b"new shader")
        original = self.game / "dlssnr-amd/shaders/accumulation.txt"
        original.parent.mkdir(parents=True)
        original.write_bytes(b"old constant")
        with (patch.dict("os.environ", {"XDG_STATE_HOME": str(self.root / "state")}),
              patch.object(launcher, "download_release", return_value=archive),
              patch.object(launcher, "_release_cache_dir", return_value=self.root)):
            preview = launcher.component_preview(self.exe, tag, asset)
            self.assertEqual(preview["conflict_count"], 1)
            self.assertEqual(preview["replaceable_count"], 1)
            with self.assertRaisesRegex(ValueError, "overwrite"):
                launcher.install_component(self.exe, tag, asset)
            result = launcher.install_component(self.exe, tag, asset, replace_conflicts=True)
            self.assertEqual(result["replaced_files"], 1)
            self.assertEqual(original.read_bytes(), b"new constant")
            self.assertEqual(launcher.installed_components(self.exe)[0]["modified"], [])
            launcher.remove_component(self.exe, asset)
            self.assertEqual(original.read_bytes(), b"old constant")
            self.assertFalse((original.parent / "new.nrp").exists())

    def test_component_replacement_refuses_symlink_and_later_edit(self):
        tag, asset = "Alpha1", "AMDNR-WrongGPU-1.zip"
        cache = self.root / tag
        cache.mkdir()
        archive = cache / asset
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr("settings.txt", b"new")
        original = self.game / "settings.txt"
        original.write_bytes(b"old")
        with (patch.dict("os.environ", {"XDG_STATE_HOME": str(self.root / "state")}),
              patch.object(launcher, "download_release", return_value=archive),
              patch.object(launcher, "_release_cache_dir", return_value=self.root)):
            launcher.install_component(self.exe, tag, asset, replace_conflicts=True)
            original.write_bytes(b"edited by user")
            with self.assertRaisesRegex(ValueError, "modified"):
                launcher.remove_component(self.exe, asset)
            self.assertEqual(original.read_bytes(), b"edited by user")
            original.write_bytes(b"new")
            launcher.remove_component(self.exe, asset)
            self.assertEqual(original.read_bytes(), b"old")

            original.unlink()
            original.symlink_to(self.exe)
            preview = launcher.component_preview(self.exe, tag, asset)
            self.assertEqual(preview["replaceable_count"], 0)
            with self.assertRaisesRegex(ValueError, "overwrite"):
                launcher.install_component(self.exe, tag, asset, replace_conflicts=True)
            self.assertTrue(original.is_symlink())

    def test_component_registry_handles_many_installed_files(self):
        files = {f"dlssnr/records/file_{i:04d}.nrp": "a" * 64 for i in range(2325)}
        with patch.dict("os.environ", {"XDG_STATE_HOME": str(self.root / "state")}):
            launcher._save_component_records(self.exe, {
                "AMDNR-Mochi-1-component.zip": {"tag": "Alpha1", "files": files}})
            self.assertEqual(len(launcher._component_records(self.exe)[
                "AMDNR-Mochi-1-component.zip"]["files"]), 2325)

    def test_component_differs_from_existing_and_must_not_overwrite(self):
        tag, asset = "Alpha1", "AMDNR-Mochi-1-component.zip"
        archive = self.root / asset
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr("present.dll", b"replacement")
        target = self.game / "present.dll"
        target.write_bytes(b"original")
        with patch.object(launcher, "download_release", return_value=archive):
            preview = launcher.component_preview(self.exe, tag, asset)
            self.assertFalse(preview["installable"])
            self.assertEqual(preview["conflict_count"], 1)
            self.assertEqual(preview["identical_count"], 0)
        self.assertEqual(target.read_bytes(), b"original")

    def test_realistic_mochi_file_count_does_not_trigger_safety_block(self):
        tag, asset = "Alpha1", "AMDNR-Mochi-1-component.zip"
        archive = self.root / asset
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as stream:
            for i in range(2325):
                stream.writestr(f"dlssnr-amd/aco/records/shader_{i:04d}.nrp", b"x")
        with patch.object(launcher, "download_release", return_value=archive):
            preview = launcher.component_preview(self.exe, tag, asset)
        self.assertEqual(preview["file_count"], 2325)
        self.assertFalse(preview["safety_limit_exceeded"])
        self.assertTrue(preview["installable"])

    def test_large_valid_component_archive_can_be_previewed(self):
        # ZIP metadata of a >1 GiB component: avoid allocating a giant test file.
        import unittest.mock
        entry = zipfile.ZipInfo("models/large-model.bin")
        entry.file_size = 2 * 1024 ** 3
        entry.compress_size = 200 * 1024 ** 2
        fake_zip = unittest.mock.MagicMock()
        fake_zip.__enter__.return_value = fake_zip
        fake_zip.infolist.return_value = [entry]
        archive = self.root / "large.zip"
        with patch.object(launcher.zipfile, "ZipFile", return_value=fake_zip):
            entries = launcher._component_entries(archive)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].file_size, 2 * 1024 ** 3)

    def test_oversized_component_preview_reports_files_without_installing(self):
        tag, asset = "Alpha1", "AMDNR-Mochi-1-component.zip"
        entry = zipfile.ZipInfo("models/huge-model.bin")
        entry.file_size = 13 * 1024 ** 3
        entry.compress_size = 93 * 1024 ** 2
        fake_zip = unittest.mock.MagicMock()
        fake_zip.__enter__.return_value = fake_zip
        fake_zip.infolist.return_value = [entry]
        with (patch.object(launcher, "download_release", return_value=self.root / asset),
              patch.object(launcher.zipfile, "ZipFile", return_value=fake_zip)):
            preview = launcher.component_preview(self.exe, tag, asset)
            self.assertFalse(preview["installable"])
            self.assertTrue(preview["safety_limit_exceeded"])
            self.assertEqual(preview["extracted_bytes"], 13 * 1024 ** 3)
            self.assertEqual(preview["largest_files"][0]["name"], entry.filename)
            with self.assertRaisesRegex(ValueError, "inspection only"):
                launcher.install_component(self.exe, tag, asset)

    def test_component_extracted_size_is_bounded(self):
        import unittest.mock
        entry = zipfile.ZipInfo("models/oversized.bin")
        entry.file_size = 13 * 1024 ** 3
        entry.compress_size = 900 * 1024 ** 2
        fake_zip = unittest.mock.MagicMock()
        fake_zip.__enter__.return_value = fake_zip
        fake_zip.infolist.return_value = [entry]
        with patch.object(launcher.zipfile, "ZipFile", return_value=fake_zip):
            with self.assertRaisesRegex(ValueError, "exceeds"):
                launcher._component_entries(self.root / "oversized.zip")

    def test_component_install_refuses_insufficient_space(self):
        import shutil
        tag, asset = "Alpha1", "AMDNR-Mochi-1-component.zip"
        cache = self.root / tag
        cache.mkdir()
        archive = cache / asset
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr("components/runtime.dll", b"component")
        fake_usage = shutil._ntuple_diskusage(total=100, used=90, free=10)
        with (patch.dict("os.environ", {"XDG_STATE_HOME": str(self.root / "state")}),
              patch.object(launcher, "download_release", return_value=archive),
              patch.object(launcher, "_release_cache_dir", return_value=self.root),
              patch.object(launcher.shutil, "disk_usage", return_value=fake_usage)):
            with self.assertRaisesRegex(ValueError, "Insufficient free disk"):
                launcher.install_component(self.exe, tag, asset)
        self.assertFalse((self.game / "components" / "runtime.dll").exists())

    def test_official_component_rejects_conflicts_and_zip_traversal(self):
        tag, asset = "Alpha1", "AMDNR-WrongGPU-1.zip"
        archive = self.root / asset
        (self.game / "present.dll").write_bytes(b"existing")
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr("present.dll", b"replacement")
        with patch.object(launcher, "download_release", return_value=archive):
            preview = launcher.component_preview(self.exe, tag, asset)
            self.assertEqual(preview["conflicts"], ["present.dll"])
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr("../escaped.dll", b"evil")
        with patch.object(launcher, "download_release", return_value=archive):
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                launcher.component_preview(self.exe, tag, asset)
        self.assertFalse((self.root / "escaped.dll").exists())

    def test_extension_inventory_loader_toggle_and_backup(self):
        ini = self.game / "OptiScaler.ini"
        ini.write_text("[Other]\nKey=1\n[Plugins]\nLoadAsiPlugins=false\n")
        plugins = self.game / "plugins"
        plugins.mkdir()
        (plugins / "Existing.asi").write_bytes(b"existing")
        with patch.dict("os.environ", {"XDG_STATE_HOME": str(self.root / "state")}):
            before = launcher.extension_inventory(self.exe)
            self.assertFalse(before["enabled"])
            self.assertFalse(before["plugins"][0]["managed"])
            initial = launcher.ini_snapshot(self.exe)
            changed = launcher.set_extension_loader(self.exe, initial["sha256"], True)
            self.assertEqual(changed["status"], "saved")
            self.assertTrue(Path(changed["backup"]).is_file())
            self.assertTrue(launcher.extension_inventory(self.exe)["enabled"])
            with self.assertRaisesRegex(ValueError, "changed"):
                launcher.set_extension_loader(self.exe, initial["sha256"], False)
            current = launcher.ini_snapshot(self.exe)
            launcher.set_extension_loader(self.exe, current["sha256"], False)
            self.assertFalse(launcher.extension_inventory(self.exe)["enabled"])
            self.assertIn("Key=1", ini.read_text())

    def test_extension_import_remove_hash_guard_and_external_preservation(self):
        config = self.game / "OptiScaler.ini"
        config.write_text("[Plugins]\nLoadAsiPlugins=true\n")
        incoming = self.root / "MyPlugin.asi"
        incoming.write_bytes(b"trusted input")
        with patch.dict("os.environ", {"XDG_STATE_HOME": str(self.root / "state")}):
            added = launcher.import_extension(self.exe, incoming)
            self.assertEqual(added["status"], "installed")
            record = launcher.extension_inventory(self.exe)
            self.assertEqual(record["plugins"][0]["name"], "MyPlugin.asi")
            self.assertTrue(record["plugins"][0]["managed"])
            with self.assertRaisesRegex(ValueError, "already exists"):
                launcher.import_extension(self.exe, incoming)
            target = self.game / "plugins/MyPlugin.asi"
            target.write_bytes(b"changed by another tool")
            with self.assertRaisesRegex(ValueError, "modified"):
                launcher.remove_managed_extension(self.exe, "MyPlugin.asi")
            self.assertTrue(target.is_file())
            target.write_bytes(b"trusted input")
            launcher.remove_managed_extension(self.exe, "MyPlugin.asi")
            self.assertFalse(target.exists())

    def test_extension_refuses_symlink_and_outside_source(self):
        (self.game / "plugins").symlink_to(self.root, target_is_directory=True)
        incoming = self.root / "Extension.asi"
        incoming.write_bytes(b"test")
        with patch.dict("os.environ", {"XDG_STATE_HOME": str(self.root / "state")}):
            with self.assertRaisesRegex(ValueError, "symlink"):
                launcher.import_extension(self.exe, incoming)
            (self.game / "plugins").unlink()
            (self.game / "plugins").mkdir()
            (self.game / "plugins/Outside.asi").write_bytes(b"external")
            with self.assertRaisesRegex(ValueError, "not managed"):
                launcher.remove_managed_extension(self.exe, "Outside.asi")
            self.assertTrue((self.game / "plugins/Outside.asi").is_file())

    def test_ini_editor_preserves_unknown_settings_and_backups(self):
        ini = self.game / "OptiScaler.ini"
        original = (b"\xef\xbb\xbf[Upscaling]\r\n; keep this comment\r\n"
                    b"CustomSetting = magic\r\n[Other]\r\nEnabled=true\r\n")
        ini.write_bytes(original)
        with patch.dict("os.environ", {"XDG_STATE_HOME": str(self.root / "state")}):
            snap = launcher.ini_snapshot(self.exe)
            self.assertEqual(snap["sections"][1]["name"], "Upscaling")
            self.assertIn("CustomSetting", snap["sections"][1]["keys"])
            updated = snap["text"].replace("magic", "new-value")
            saved = launcher.save_game_ini(self.exe, snap["sha256"], updated)
            self.assertEqual(saved["status"], "saved")
            self.assertEqual(Path(saved["backup"]).read_bytes(), original)
            self.assertIn("CustomSetting = new-value", ini.read_text(encoding="utf-8-sig"))
            self.assertIn("; keep this comment", ini.read_text(encoding="utf-8-sig"))
            self.assertEqual(launcher.save_game_ini(
                self.exe, saved["sha256"], updated)["status"], "unchanged")

    def test_ini_editor_conflict_and_restrictions(self):
        ini = self.game / "OptiScaler.ini"
        ini.write_text("[Settings]\nKnown=1\n")
        with patch.dict("os.environ", {"XDG_STATE_HOME": str(self.root / "state")}):
            snap = launcher.ini_snapshot(self.exe)
            ini.write_text("[Settings]\nKnown=2\n")
            with self.assertRaisesRegex(ValueError, "changed since"):
                launcher.save_game_ini(self.exe, snap["sha256"], "[Settings]\nKnown=3\n")
            with self.assertRaisesRegex(ValueError, "at least one"):
                launcher.save_game_ini(self.exe,
                                       launcher.ini_snapshot(self.exe)["sha256"], "x=y")
            ini.unlink()
            ini.symlink_to(self.root / "outside.ini")
            with self.assertRaisesRegex(ValueError, "not found"):
                launcher.ini_snapshot(self.exe)

    def test_persistent_launcher_preferences(self):
        config = self.root / "config"
        download = self.root / "custom-downloads"
        with patch.dict("os.environ", {"XDG_CONFIG_HOME": str(config)}):
            initial = launcher.launcher_settings()
            self.assertEqual(initial["default_alias"], "dxgi.dll")
            custom = launcher.save_launcher_settings({
                "default_alias": "winmm.dll", "download_directory": str(download),
                "show_prereleases": True
            })
            self.assertTrue(custom["show_prereleases"])
            self.assertEqual(launcher.launcher_settings()["default_alias"], "winmm.dll")
            self.assertEqual(launcher._release_cache_dir(), download)
            with self.assertRaisesRegex(ValueError, "absolute"):
                launcher.save_launcher_settings({
                    "default_alias": "winmm.dll", "download_directory": "../relative",
                    "show_prereleases": False,
                })
            with self.assertRaisesRegex(ValueError, "proxy"):
                launcher.save_launcher_settings({
                    "default_alias": "unsafe.dll", "download_directory": str(download),
                    "show_prereleases": False,
                })
            self.assertEqual(launcher.launcher_settings(), custom)

    def test_existing_full_audit_exe_is_imported_without_binary_scan(self):
        state = self.root / "state"
        with patch.dict("os.environ", {"XDG_STATE_HOME": str(state)}):
            launcher._save_library_audit([
                {"name": "Game", "folder": str(self.game), "custom": False,
                 "status": "windows_ready", "executable": str(self.exe)}
            ])
            with patch.object(launcher, "steam_games", return_value=[
                 ("Game", self.game)
            ]), patch.object(launcher, "custom_games", return_value=[]), \
                 patch.object(launcher, "steam_game_details", return_value=[
                     {"name": "Game", "folder": str(self.game), "artwork": None}
                 ]), patch.object(launcher, "executable_scan",
                                  side_effect=AssertionError("unexpected binary scan")):
                index = launcher.differential_library()
                self.assertEqual(index[0]["executable"], str(self.exe))
                self.assertEqual(launcher._read_library_index()[str(self.game)]
                                 ["executable"], str(self.exe))

    def test_differential_library_remembers_missing_artwork(self):
        # A game without a Steam cover must not trigger artwork discovery at
        # every refresh after the first unsuccessful lookup.
        state = self.root / "state"
        with patch.dict("os.environ", {"XDG_STATE_HOME": str(state)}), \
             patch.object(launcher, "steam_games", return_value=[
                 ("Game", self.game)
             ]), patch.object(launcher, "custom_games", return_value=[]), \
             patch.object(launcher, "_manual_artwork", return_value=None), \
             patch.object(launcher, "steam_game_details", return_value=[
                 {"name": "Game", "folder": str(self.game), "artwork": None}
             ]) as artwork:
            self.assertIsNone(launcher.differential_library()[0]["artwork"])
            self.assertIsNone(launcher.differential_library()[0]["artwork"])
            self.assertEqual(artwork.call_count, 1)
            index = launcher._read_library_index()
            self.assertTrue(index[str(self.game)]["artwork_checked"])

    def test_differential_library_add_remove_and_reuse_executables(self):
        first = self.root / "steamapps/common/First"
        second = self.root / "steamapps/common/Second"
        first.mkdir(parents=True)
        second.mkdir(parents=True)
        exe = first / "first.exe"
        exe.write_bytes(b"game")
        custom = self.root / "unmounted/MyCustom"
        state = self.root / "state"
        steam_entries = [("First", first)]
        with patch.dict("os.environ", {"XDG_STATE_HOME": str(state)}), \
             patch.object(launcher, "steam_games", side_effect=lambda: steam_entries), \
             patch.object(launcher, "custom_games", return_value=[
                 {"name": "MyCustom", "folder": str(custom), "artwork": None}
             ]), patch.object(launcher, "steam_game_details", return_value=[
                 {"name": "First", "folder": str(first), "artwork": None},
                 {"name": "Second", "folder": str(second), "artwork": None}
             ]), patch.object(launcher, "executable_scan",
                              side_effect=AssertionError("unexpected binary scan")):
            initial = launcher.differential_library()
            self.assertEqual(len(initial), 2)
            self.assertEqual(next(row for row in initial if row["custom"])["folder"],
                             str(custom))
            launcher.index_library_executable(first, exe)
            # A second refresh reuses the saved choice without scanning.
            refreshed = launcher.differential_library()
            self.assertEqual(next(row for row in refreshed if not row["custom"])
                             ["executable"], str(exe))
            # Discover a new game by its manifest and remove the uninstalled one.
            steam_entries[:] = [("Second", second)]
            changed = launcher.differential_library()
            self.assertEqual([row["name"] for row in changed], ["MyCustom", "Second"])
            self.assertNotIn(str(first), launcher._read_library_index())
            # The custom entry stays indexed even when its drive is unavailable.
            self.assertIn(str(custom), launcher._read_library_index())

    def test_differential_library_clears_stale_exe_without_rescanning(self):
        state = self.root / "state"
        with patch.dict("os.environ", {"XDG_STATE_HOME": str(state)}), \
             patch.object(launcher, "steam_games", return_value=[
                 ("Game", self.game)
             ]), patch.object(launcher, "custom_games", return_value=[]), \
             patch.object(launcher, "steam_game_details", return_value=[
                 {"name": "Game", "folder": str(self.game), "artwork": None}
             ]), patch.object(launcher, "executable_scan",
                              side_effect=AssertionError("unexpected binary scan")):
            launcher.differential_library()
            launcher.index_library_executable(self.game, self.exe)
            self.exe.unlink()
            entry = launcher.differential_library()[0]
            self.assertIsNone(entry["executable"])

    def test_differential_library_manual_preference_overrides_index(self):
        second = self.game / "Alternative.exe"
        second.write_bytes(b"second")
        state = self.root / "state"
        with patch.dict("os.environ", {"XDG_STATE_HOME": str(state)}), \
             patch.object(launcher, "steam_games", return_value=[
                 ("Game", self.game)
             ]), patch.object(launcher, "custom_games", return_value=[]), \
             patch.object(launcher, "steam_game_details", return_value=[
                 {"name": "Game", "folder": str(self.game), "artwork": None}
             ]):
            launcher.differential_library()
            launcher.index_library_executable(self.game, second)
            with patch.object(launcher, "saved_executable", return_value=str(self.exe)):
                self.assertEqual(launcher.differential_library()[0]["executable"],
                                 str(self.exe))

    def test_library_audit_cache_round_trip_survives_reload(self):
        with patch.dict("os.environ", {"XDG_STATE_HOME": str(self.root / "state")}):
            self.assertEqual(launcher.cached_library_audit(), [])
            rows = [{"name": "Game", "folder": str(self.game), "custom": False,
                     "status": "windows_ready", "executable": str(self.exe),
                     "source": "saved", "native": [], "steam_windows_missing": [],
                     "installed_record": False}]
            launcher._save_library_audit(rows)
            path = launcher._library_audit_cache_path()
            self.assertTrue(path.is_file())
            self.assertEqual(launcher.cached_library_audit(), rows)
            # Reading an old snapshot must never trigger discovery or scanning.
            with patch.object(launcher, "steam_games",
                              side_effect=AssertionError("unexpected rescan")), \
                 patch.object(launcher, "executable_scan",
                              side_effect=AssertionError("unexpected rescan")):
                self.assertEqual(launcher.cached_library_audit(), rows)

    def test_library_audit_cache_is_only_replaced_by_explicit_save(self):
        with patch.dict("os.environ", {"XDG_STATE_HOME": str(self.root / "state")}):
            old = [{"name": "Old", "folder": str(self.game),
                    "status": "native_linux"}]
            launcher._save_library_audit(old)
            path = launcher._library_audit_cache_path()
            initial = path.read_bytes()
            self.assertEqual(launcher.cached_library_audit(), old)
            self.assertEqual(path.read_bytes(), initial)
            new = [{"name": "Changed", "folder": str(self.game),
                    "status": "windows_ready"}]
            launcher._save_library_audit(new)
            self.assertEqual(launcher.cached_library_audit(), new)

    def test_library_audit_cache_rejects_bad_snapshot(self):
        with patch.dict("os.environ", {"XDG_STATE_HOME": str(self.root / "state")}):
            path = launcher._library_audit_cache_path()
            path.parent.mkdir(parents=True)
            path.write_text('{"format": 99, "entries": []}')
            with self.assertRaisesRegex(ValueError, "saved library audit"):
                launcher.cached_library_audit()

    def test_library_audit_respects_steam_metadata_and_saved_custom_games(self):
        steam_folder = self.root / "steamapps/common/WindowsGame"
        steam_folder.mkdir(parents=True)
        executable = steam_folder / "WindowsGame.exe"
        executable.write_bytes(b"exe")
        native_folder = self.root / "steamapps/common/LinuxGame"
        native_folder.mkdir()
        (native_folder / "LinuxGame.x86_64").write_bytes(b"\x7fELFnative")
        custom_folder = self.root / "custom/SoloGame"
        custom_folder.mkdir(parents=True)
        custom_exe = custom_folder / "Solo.exe"
        custom_exe.write_bytes(b"exe")
        custom = [{"name": "SoloGame", "folder": str(custom_folder)}]
        metadata = {"selected": str(executable), "windows_missing": []}
        with patch.object(launcher, "steam_games", return_value=[
            ("WindowsGame", steam_folder), ("LinuxGame", native_folder)
        ]), patch.object(launcher, "custom_games", return_value=custom), \
                patch.object(launcher, "steam_launch_for_directory", side_effect=lambda folder:
                             metadata if folder == steam_folder else {"selected": None}), \
                patch.object(launcher, "saved_executable", side_effect=lambda folder:
                             str(custom_exe) if folder == custom_folder else None):
            audit = launcher.library_audit()
        self.assertEqual(len(audit), 3)
        rows = {entry["name"]: entry for entry in audit}
        self.assertEqual(rows["WindowsGame"]["status"], "windows_ready")
        self.assertEqual(rows["WindowsGame"]["source"], "steam")
        self.assertEqual(rows["SoloGame"]["status"], "windows_ready")
        self.assertEqual(rows["SoloGame"]["source"], "saved")
        self.assertTrue(rows["SoloGame"]["custom"])
        self.assertEqual(rows["LinuxGame"]["status"], "native_linux")
        self.assertEqual(rows["LinuxGame"]["native"], ["LinuxGame.x86_64"])

    def test_library_audit_handles_disconnected_custom_folder(self):
        missing = self.root / "unmounted/Game"
        with patch.object(launcher, "steam_games", return_value=[]), \
                patch.object(launcher, "custom_games", return_value=[
                    {"name": "Offline game", "folder": str(missing)}
                ]):
            audit = launcher.library_audit()
        self.assertEqual(audit[0]["status"], "missing_folder")
        self.assertIsNone(audit[0]["executable"])

    def test_library_audit_installed_record_is_not_verification(self):
        with patch.object(launcher, "steam_games", return_value=[
            ("Game", self.game)
        ]), patch.object(launcher, "custom_games", return_value=[]), \
                patch.object(launcher, "steam_launch_for_directory",
                             return_value={"selected": str(self.exe)}), \
                patch.object(launcher, "saved_executable", return_value=None):
            state = self.game / launcher.STATE_NAME
            state.write_text("{}")
            audit = launcher.library_audit()
        self.assertTrue(audit[0]["installed_record"])
        self.assertEqual(audit[0]["status"], "windows_ready")

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

    def test_historical_daniel_runtime_uses_official_asset_digest_when_manifest_omits_it(self):
        import hashlib
        import io
        memory = io.BytesIO()
        with zipfile.ZipFile(memory, "w") as archive:
            archive.writestr("dlssnr_amd_pass1.dll", b"test")
        payload = memory.getvalue()
        digest = hashlib.sha256(payload).hexdigest()
        metadata = {"tag_name": "Alpha0.3.5.5R4", "assets": [
            {"name": "SHA256SUMS.txt"},
            {"name": "v0.6.0-Runtime.zip", "size": len(payload),
             "digest": "sha256:" + digest},
        ]}

        class Response:
            def __init__(self, value):
                self.stream = io.BytesIO(value)
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                pass
            def read(self, size=-1):
                return self.stream.read(size)

        def fetch(request, timeout=0):
            if request.full_url.endswith("SHA256SUMS.txt"):
                return Response(b"a" * 64 + b"  AMDNR-v0.3.5.5R4.zip\\n")
            return Response(payload)

        with (patch.dict(launcher.os.environ, {"XDG_CACHE_HOME": str(self.root / "cache")}),
              patch.object(launcher, "_github_json", return_value=metadata),
              patch.object(launcher.urllib.request, "urlopen", side_effect=fetch)):
            result = launcher.download_release("Alpha0.3.5.5R4", "v0.6.0-Runtime.zip")
            self.assertEqual(result.read_bytes(), payload)

    def test_daniel_runtime_asset_digest_mismatch_is_rejected(self):
        import hashlib
        import io
        memory = io.BytesIO()
        with zipfile.ZipFile(memory, "w") as archive:
            archive.writestr("dlssnr_amd_pass1.dll", b"test")
        payload = memory.getvalue()
        metadata = {"tag_name": "Alpha0.3.5.5R4", "assets": [
            {"name": "SHA256SUMS.txt"},
            {"name": "v0.6.0-Runtime.zip", "size": len(payload),
             "digest": "sha256:" + "0" * 64},
        ]}
        class Response:
            def __init__(self, value):
                self.stream = io.BytesIO(value)
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                pass
            def read(self, size=-1):
                return self.stream.read(size)
        def fetch(request, timeout=0):
            return Response(b"no matching ZIP hash\\n" if
                            request.full_url.endswith("SHA256SUMS.txt") else payload)
        with (patch.dict(launcher.os.environ, {"XDG_CACHE_HOME": str(self.root / "cache")}),
              patch.object(launcher, "_github_json", return_value=metadata),
              patch.object(launcher.urllib.request, "urlopen", side_effect=fetch)):
            with self.assertRaisesRegex(ValueError, "failed SHA-256"):
                launcher.download_release("Alpha0.3.5.5R4", "v0.6.0-Runtime.zip")

    def test_manifest_and_asset_digest_disagreement_is_rejected(self):
        import io
        metadata = {"tag_name": "Alpha0.3.5.5R4", "assets": [
            {"name": "SHA256SUMS.txt"},
            {"name": "v0.6.0-Runtime.zip", "size": 20,
             "digest": "sha256:" + "0" * 64},
        ]}
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                pass
            def read(self, size=-1):
                return ("a" * 64 + "  v0.6.0-Runtime.zip" + chr(10)).encode()
        with (patch.object(launcher, "_github_json", return_value=metadata),
              patch.object(launcher.urllib.request, "urlopen", return_value=Response())):
            with self.assertRaisesRegex(ValueError, "conflicts"):
                launcher.download_release("Alpha0.3.5.5R4", "v0.6.0-Runtime.zip")

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
