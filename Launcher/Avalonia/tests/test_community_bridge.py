"""Safety checks for the separately fetched community bridge adapter (offline)."""
import io
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
