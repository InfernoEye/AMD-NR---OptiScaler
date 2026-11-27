"""Safety checks for the separately fetched community bridge adapter (offline)."""
import io
import struct
import json
import subprocess
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import community_bridge as bridge
import bridge_discovery as discovery
import bridge_deps as deps
import hashlib


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        mock = patch.object(bridge, "cache_dir", return_value=self.root / "cache")
        mock.start()
        self.addCleanup(mock.stop)

    def exe(self, inner=True):
        base = self.root / "steamapps/common/TestGame"
        folder = base / "Game/Binaries/Win64" if inner else base
        folder.mkdir(parents=True, exist_ok=True)
        executable = folder / ("TestGame-Win64-Test.exe" if inner else "TestGame.exe")
        executable.write_bytes(b"fake")
        return executable

    def tar(self, entries):
        path = self.root / "source.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            for name, payload in entries:
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
        return path

    def fake_compiler(self, folder, x64=True):
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "d3dcompiler_47.dll"
        fake = bytearray(70000)
        fake[:2] = b"MZ"
        struct.pack_into("<I", fake, 0x3c, 128)
        fake[128:132] = b"PE" + bytes([0, 0])
        struct.pack_into("<H", fake, 132, 0x8664 if x64 else 0x14c)
        struct.pack_into("<H", fake, 148, 240)  # PE32+ optional header bytes
        struct.pack_into("<H", fake, 150, 0x2000)  # IMAGE_FILE_DLL
        struct.pack_into("<H", fake, 152, 0x20b if x64 else 0x10b)
        path.write_bytes(fake)
        return path

    def test_compiler_discovery_prefers_selected_game_and_is_read_only(self):
        exe = self.exe()
        game = self.root / "steamapps/common/TestGame"
        compiler = self.fake_compiler(game / "Dependencies")
        result = discovery.discover(exe, include_library=False)
        self.assertEqual(len(result["compiler_candidates"]), 1)
        self.assertEqual(result["compiler_candidates"][0]["path"], str(compiler))
        self.assertEqual(result["compiler_candidates"][0]["source"], "selected_game")
        self.assertFalse(result["automatic_changes"])
        self.assertFalse((self.root / "cache").exists())

    def test_compiler_discovery_skips_proton_runtime_directories(self):
        exe = self.exe()
        common = self.root / "steamapps/common"
        self.fake_compiler(common / "Proton 9.0 (Beta)" / "files/lib64/wine/x86_64-windows")
        owned = self.fake_compiler(common / "OtherGame" / "bin")
        found = discovery.find_compilers(exe, include_library=True)
        self.assertIn(str(owned), [entry["path"] for entry in found])
        self.assertFalse(any("Proton 9.0" in entry["path"] for entry in found))

    def test_compiler_discovery_rejects_wine_builtin_placeholder(self):
        compiler = self.fake_compiler(self.root / "Game")
        content = bytearray(compiler.read_bytes())
        content[260:276] = b"Wine builtin DLL"
        compiler.write_bytes(content)
        self.assertFalse(discovery.compiler_is_candidate(compiler))

    def test_compiler_discovery_rejects_non_native_and_symlink(self):
        exe = self.exe()
        game = self.root / "steamapps/common/TestGame"
        invalid = self.fake_compiler(game / "Invalid", x64=False)
        good = self.fake_compiler(game / "Good")
        links = game / "Links"
        links.mkdir()
        (links / "d3dcompiler_47.dll").symlink_to(good)
        self.assertFalse(discovery.compiler_is_candidate(invalid))
        self.assertFalse(discovery.compiler_is_candidate(links / "d3dcompiler_47.dll"))
        found = discovery.find_compilers(exe, include_library=False)
        self.assertEqual([x["path"] for x in found], [str(good)])

    def test_compiler_discovery_refuses_missing_executable(self):
        with self.assertRaisesRegex(ValueError, "executable"):
            discovery.discover(self.root / "fake.exe")

    def test_discovery_cli_is_headless_and_json_only(self):
        exe = self.exe()
        entrypoint = Path(__file__).resolve().parents[1] / "amdnr_launcher.py"
        completed = subprocess.run(
            [sys.executable, str(entrypoint), "--bridge-discover-json",
             "--exe", str(exe)], capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["selected_executable"], str(exe))
        self.assertNotIn("Tkinter", completed.stderr)

    def test_ubuntu_pin_reuses_distro_package_cache_without_downloading(self):
        blob = b"example pinned distro archive for unit test"
        name = "libelf1_fake_amd64.deb"
        expected = hashlib.sha256(blob).hexdigest()
        pkg = self.root / "apt-cache" / name
        pkg.parent.mkdir(parents=True)
        pkg.write_bytes(blob)
        cached = self.root / "upstream-cache"
        with patch.object(deps, "UBUNTU_PACKAGES", ((name, expected, "e/elfutils"),)):
            result = deps.reuse_or_fetch_pinned_ubuntu_packages(
                cached, self.root / "apt-cache",
                opener=lambda *args, **kwargs: self.fail("unexpected download"))
        self.assertIn("Reused verified", result[0])
        self.assertEqual((cached / name).read_bytes(), blob)

    def test_archived_mirror_fallback_preserves_upstream_hash(self):
        blob = b"pinned prerequisite package"
        name = "libelf1_fake_amd64.deb"
        expected = hashlib.sha256(blob).hexdigest()
        requested = []

        class Response(io.BytesIO):
            def geturl(self):
                return "https://mirrors.edge.kernel.org/ubuntu/pool/main/e/elfutils/" + name

        def opener(url, timeout):
            requested.append(url)
            if "mirrors.edge.kernel.org" not in url:
                raise __import__("urllib").error.HTTPError(url, 404, "Not Found", None, None)
            return Response(blob)

        with patch.object(deps, "UBUNTU_PACKAGES", ((name, expected, "e/elfutils"),)):
            result = deps.reuse_or_fetch_pinned_ubuntu_packages(
                self.root / "mirror-verified", self.root / "missing", opener=opener)
        self.assertIn("SHA-256 verified", result[0])
        self.assertTrue(any("mirrors.edge.kernel.org" in url for url in requested))
        self.assertEqual((self.root / "mirror-verified" / name).read_bytes(), blob)

    def test_ubuntu_pin_mirror_recovery_checks_hash(self):
        blob = b"fake exact pinned Ubuntu package"
        name = "libelf1_fake_amd64.deb"
        expected = hashlib.sha256(blob).hexdigest()
        urls = []
        class Response(io.BytesIO):
            def geturl(self):
                return "https://security.ubuntu.com/ubuntu/pool/main/e/elfutils/" + name
        def opener(url, timeout):
            urls.append(url)
            return Response(blob)
        with patch.object(deps, "UBUNTU_PACKAGES", ((name, expected, "e/elfutils"),)):
            result = deps.reuse_or_fetch_pinned_ubuntu_packages(
                self.root / "verified", self.root / "missing", opener=opener)
        self.assertIn("SHA-256 verified", result[0])
        self.assertIn("security.ubuntu.com", urls[0])
        self.assertEqual((self.root / "verified" / name).read_bytes(), blob)

    def test_ubuntu_pin_refuses_bad_archive_even_when_name_matches(self):
        name = "libelf1_fake_amd64.deb"
        cache = self.root / "verified"
        cache.mkdir()
        (cache / name).write_bytes(b"modified")
        with patch.object(deps, "UBUNTU_PACKAGES",
                          ((name, hashlib.sha256(b"original").hexdigest(), "e/elfutils"),)):
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                deps.reuse_or_fetch_pinned_ubuntu_packages(cache)

    def test_distro_dependency_prompt_is_read_only(self):
        with (patch.object(deps, "distro_info",
                           return_value={"ID": "arch", "PRETTY_NAME": "Arch Linux"}),
              patch.object(deps.ctypes.util, "find_library", return_value=None)):
            report = deps.host_library_status()
        self.assertEqual(len(report["missing_system_libraries"]), 2)
        self.assertIn("sudo pacman", report["install_command_preview"])
        self.assertFalse(report["system_packages_will_be_installed"])
        self.assertTrue(report["private_rocm_required"])

    def test_release_check_marks_newer_versions_unreviewed(self):
        releases = [
            {"tag_name": "linux-v0.4.0", "draft": False, "prerelease": False,
             "published_at": "2026-12-01T00:00:00Z",
             "assets": [{"name": "AMDNR-Linux-v0.4.0.tar.gz"}]},
            {"tag_name": "linux-v0.3.7", "draft": False, "prerelease": False,
             "assets": [{"name": "AMDNR-Linux-v0.3.7.tar.gz"}]},
            {"tag_name": "linux-v9.9.9", "draft": True,
             "assets": [{"name": "AMDNR-Linux-v9.9.9.tar.gz"}]},
            {"tag_name": "linux-v0.4.1-preview",
             "assets": [{"name": "AMDNR-Linux-v0.4.1-preview.tar.gz"}]},
            {"tag_name": "linux-v0.4.2",
             "assets": [{"name": "unrelated.zip"}]},
        ]
        class Response(io.BytesIO):
            def geturl(self):
                return "https://api.github.com/repos/hassanm0301/AMDNR-Linux/releases"
        def opener(request, timeout):
            self.assertEqual(timeout, 15)
            self.assertIn("api.github.com", request.full_url)
            return Response(json.dumps(releases).encode())
        outcome = bridge.check_releases(opener=opener)
        self.assertEqual(outcome["latest_upstream_version"], "0.4.0")
        self.assertTrue(outcome["newer_upstream_available"])
        self.assertFalse(outcome["updated_automatically"])
        self.assertEqual([x["version"] for x in outcome["releases"]], ["0.4.0", "0.3.7"])
        self.assertFalse(outcome["releases"][0]["download_allowed"])
        self.assertEqual(outcome["releases"][0]["compatibility"], "requires_review")
        self.assertTrue(outcome["releases"][1]["download_allowed"])

    def test_release_check_fails_closed_on_oversized_or_insecure_response(self):
        class Response(io.BytesIO):
            def __init__(self, data, url):
                super().__init__(data)
                self.url = url
            def geturl(self):
                return self.url
        with self.assertRaisesRegex(ValueError, "insecure"):
            bridge.check_releases(opener=lambda *_a, **_kw: Response(b"[]", "http://example.test/"))
        with self.assertRaisesRegex(ValueError, "size limit"):
            bridge.check_releases(opener=lambda *_a, **_kw: Response(
                b"x" * (256 * 1024 + 1), "https://api.github.com/releases"))

    def test_release_status_never_fetches_updates_implicitly(self):
        with patch.object(bridge.urllib.request, "urlopen",
                          side_effect=AssertionError("unexpected network")):
            result = bridge.status()
        self.assertEqual(result["release_approval"], "reviewed_sha256_pin")
        self.assertFalse(result["updates_checked_online"])

    def test_reviewed_libelf_patch_is_exact_and_idempotent(self):
        src = self.root / "source"
        script = src / "linux/fetch-rocm.py"
        script.parent.mkdir(parents=True)
        script.write_text(
            "PACKAGES = [(UBUNTU + \"" + bridge.UPSTREAM_LIBELF_PIN + ")]\\n"
        )
        self.assertTrue(bridge.apply_reviewed_libelf_pin(src))
        revised = script.read_text()
        self.assertIn(bridge.REVIEWED_LIBELF_PIN, revised)
        self.assertNotIn(bridge.UPSTREAM_LIBELF_PIN, revised)
        self.assertFalse(bridge.apply_reviewed_libelf_pin(src))
        self.assertEqual(script.read_text(), revised)

    def test_reviewed_libelf_patch_rejects_unknown_script(self):
        src = self.root / "source"
        script = src / "linux/fetch-rocm.py"
        script.parent.mkdir(parents=True)
        script.write_text("PACKAGES = []\\n")
        with self.assertRaisesRegex(ValueError, "Unrecognized"):
            bridge.apply_reviewed_libelf_pin(src)
        self.assertEqual(script.read_text(), "PACKAGES = []\\n")

    def test_reviewed_dependency_pin_matches_source_patch(self):
        from bridge_deps import UBUNTU_PACKAGES
        package_name, digest, suffix = UBUNTU_PACKAGES[0]
        self.assertIn(package_name, bridge.REVIEWED_LIBELF_PIN)
        self.assertIn(digest, bridge.REVIEWED_LIBELF_PIN)
        self.assertEqual(suffix, "e/elfutils")

    def test_current_amdnr_pin_updates_exact_private_upstream_source(self):
        src = self.root / "source"
        manager = src / "linux/manage.py"
        setup = src / "linux/setup.py"
        manager.parent.mkdir(parents=True)
        manager.write_text(
            "RELEASES = {\\n" + bridge.UPSTREAM_HOST_ENTRY +
            "\\n}\\n" + bridge.UPSTREAM_LMXXF_ENTRY + "\\n}\\n"
        )
        setup.write_text(bridge.UPSTREAM_DEFAULT_HOST + "\\n")
        self.assertTrue(bridge.apply_current_amdnr_pin(src))
        modified_manager = manager.read_text()
        modified_setup = setup.read_text()
        self.assertIn(bridge.UPSTREAM_HOST_ENTRY, modified_manager)
        self.assertIn(bridge.UPDATED_HOST_ENTRY, modified_manager)
        self.assertIn(bridge.UPDATED_LMXXF_ENTRY, modified_manager)
        self.assertIn(bridge.UPDATED_DEFAULT_HOST, modified_setup)
        self.assertNotIn(bridge.UPSTREAM_DEFAULT_HOST, modified_setup)
        self.assertFalse(bridge.apply_current_amdnr_pin(src))
        self.assertEqual(manager.read_text(), modified_manager)
        self.assertEqual(setup.read_text(), modified_setup)

    def test_current_amdnr_pin_rejects_unexpected_layout(self):
        src = self.root / "source"
        manager = src / "linux/manage.py"
        setup = src / "linux/setup.py"
        manager.parent.mkdir(parents=True)
        manager.write_text("RELEASES = {}\\n")
        setup.write_text(bridge.UPSTREAM_DEFAULT_HOST + "\\n")
        with self.assertRaisesRegex(ValueError, "Unexpected upstream"):
            bridge.apply_current_amdnr_pin(src)
        self.assertEqual(manager.read_text(), "RELEASES = {}\\n")
        self.assertEqual(setup.read_text(), bridge.UPSTREAM_DEFAULT_HOST + "\\n")

    def test_current_amdnr_prepared_package_must_match_source_receipt(self):
        package = bridge.prepared_path()
        (package / "amdnr-linux").mkdir(parents=True)
        (package / "amdnr-linux/run.sh").write_text("run")
        (package / "d3d12.dll").write_bytes(b"stub")
        marker = package / "amdnr-linux/SOURCE.txt"
        marker.write_text(
            f"Host/runtime: AMDNR {bridge.HOST_VERSION}, upstream\\n"
            f"Archive SHA-256: {bridge.HOST_SHA256}\\n"
            f"lmxxf archive: upstream, SHA-256 {bridge.LMXXF_SHA256}\\n"
        )
        components = package / "amdnr-linux/components.json"
        components.write_text(json.dumps({"neural_runtime": "lmxxf"}))
        self.assertTrue(bridge.package_is_ready(package))
        components.write_text(json.dumps({"neural_runtime": "daniel"}))
        self.assertFalse(bridge.package_is_ready(package))
        components.write_text(json.dumps({"neural_runtime": "lmxxf"}))
        marker.write_text("legacy build")
        self.assertFalse(bridge.package_is_ready(package))

    def test_current_amdnr_host_pin_is_separate_from_bridge_version(self):
        self.assertEqual(bridge.VERSION, "0.3.7")
        self.assertEqual(bridge.HOST_VERSION, "0.3.5.8.28")
        self.assertEqual(bridge.LMXXF_VERSION, "0.4.6.2")
        self.assertEqual(len(bridge.HOST_SHA256), 64)
        self.assertEqual(len(bridge.LMXXF_SHA256), 64)
        self.assertNotEqual(bridge.prepared_path(), bridge.cache_dir() / "package")

    def test_daniel_runtime_choices_are_pinned_to_060_or_older(self):
        self.assertIn("lmxxf", bridge.RUNTIME_CHOICES)
        self.assertIn("0.6.0", bridge.RUNTIME_CHOICES)
        self.assertIn("0.4.0", bridge.RUNTIME_CHOICES)
        self.assertNotIn("0.8.0", bridge.RUNTIME_CHOICES)
        self.assertNotIn("0.9.0", bridge.RUNTIME_CHOICES)
        with self.assertRaisesRegex(ValueError, "Unsupported neural runtime"):
            bridge.validate_runtime("0.8.0")

    def test_daniel_packages_have_separate_verified_receipts(self):
        original = bridge.prepared_path()
        daniel = bridge.prepared_path("0.6.0")
        self.assertNotEqual(original, daniel)
        (daniel / "amdnr-linux").mkdir(parents=True)
        (daniel / "amdnr-linux/run.sh").write_text("run")
        (daniel / "d3d12.dll").write_bytes(b"stub")
        (daniel / "amdnr-linux/SOURCE.txt").write_text(
            f"Host/runtime: AMDNR {bridge.HOST_VERSION}, upstream\n"
            f"Archive SHA-256: {bridge.HOST_SHA256}\n"
            f"lmxxf archive: upstream, SHA-256 {bridge.LMXXF_SHA256}\n"
        )
        receipt = daniel / "amdnr-linux/components.json"
        receipt.write_text(json.dumps({"neural_runtime": "daniel",
                                       "daniel": {"version": "0.6.0"}}))
        self.assertTrue(bridge.package_is_ready(daniel, "0.6.0"))
        self.assertFalse(bridge.package_is_ready(daniel, "lmxxf"))
        self.assertFalse(bridge.package_is_ready(daniel, "0.5.1"))
        with self.assertRaisesRegex(ValueError, "Unsupported neural runtime"):
            bridge.status(runtime="0.8.0")

    def test_release_pin(self):
        self.assertEqual(len(bridge.SHA256), 64)
        self.assertEqual(bridge.VERSION, "0.3.7")
        self.assertIn("hassanm0301", bridge.URL)

    def test_archive_rejects_traversal(self):
        tar = self.tar([
            (bridge.SOURCE_ROOT + "/RELEASE-MANIFEST.json", b"{}"),
            (bridge.SOURCE_ROOT + "/../escape", b"untrusted"),
        ])
        with self.assertRaises(ValueError):
            bridge.safe_extract(tar, self.root / "extract")
        self.assertFalse((self.root / "escape").exists())

    def test_archive_requires_manifest(self):
        tar = self.tar([(bridge.SOURCE_ROOT + "/linux/setup.py", b"hello")])
        with self.assertRaises(ValueError):
            bridge.safe_extract(tar, self.root / "extract")

    def test_safe_archive_extracts_without_escaping(self):
        tar = self.tar([
            (bridge.SOURCE_ROOT + "/RELEASE-MANIFEST.json",
             json.dumps({"release": "linux-v0.3.7"}).encode()),
            (bridge.SOURCE_ROOT + "/linux/setup.py", b"print('offline')\n"),
        ])
        root = bridge.safe_extract(tar, self.root / "extract")
        self.assertTrue((root / "linux/setup.py").is_file())
        with self.assertRaises(ValueError):
            bridge.safe_extract(tar, self.root / "extract")

    def test_nested_executable_detects_root_managed_install(self):
        exe = self.exe()
        root = self.root / "steamapps/common/TestGame"
        (root / bridge.OWN_RECORD).write_text("{}")
        errors = bridge.game_conflicts(exe)
        self.assertTrue(any("installation record" in x.lower() for x in errors))

    def test_nested_executable_detects_reshade_conflict(self):
        exe = self.exe()
        (exe.parent / "ReShade.ini").write_text("[GENERAL]")
        (exe.parent / "dxgi.dll").write_bytes(b"existing mod")
        errors = bridge.game_conflicts(exe)
        self.assertTrue(any("ReShade.ini" in x for x in errors))
        self.assertTrue(any("dxgi.dll" in x for x in errors))

    def test_status_is_read_only(self):
        exe = self.exe()
        result = bridge.status(exe)
        self.assertEqual(result["provider"], "hassanm0301/AMDNR-Linux")
        self.assertFalse(result["prepared"])
        self.assertFalse(result["can_install"])
        self.assertFalse((self.root / "cache").exists())

    def test_no_arguments_is_cli_only_and_never_opens_window(self):
        # The removed Tkinter GUI must not reappear via default CLI dispatch.
        entrypoint = Path(__file__).resolve().parents[1] / "amdnr_launcher.py"
        with patch.dict("os.environ", {"DISPLAY": "", "WAYLAND_DISPLAY": ""}):
            completed = subprocess.run(
                [sys.executable, str(entrypoint)],
                capture_output=True, text=True, timeout=12, check=False,
            )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("Start the native Avalonia launcher", completed.stderr)
        self.assertNotIn("Tkinter", completed.stderr)
        self.assertEqual(completed.stdout, "")

    def test_bridge_status_cli_exits_without_opening_tkinter(self):
        # Regression: --bridge-status-json previously fell through into gui(),
        # opening a second white Python window and leaving Avalonia waiting.
        executable = Path(__file__).resolve().parents[1] / "amdnr_launcher.py"
        completed = subprocess.run(
            [sys.executable, str(executable), "--bridge-status-json"],
            capture_output=True, text=True, timeout=12, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["provider"],
                         "hassanm0301/AMDNR-Linux")
        self.assertNotIn("Tkinter", completed.stderr)

    def test_install_refuses_without_consent(self):
        exe = self.exe()
        with self.assertRaisesRegex(ValueError, "approval"):
            bridge.install(exe, False)

    def test_installer_refuses_conflicted_target_even_with_consent(self):
        exe = self.exe()
        (exe.parent / "ReShade.log").touch()
        with self.assertRaisesRegex(ValueError, "Prepare"):
            bridge.install(exe, True)


if __name__ == "__main__":
    unittest.main()
