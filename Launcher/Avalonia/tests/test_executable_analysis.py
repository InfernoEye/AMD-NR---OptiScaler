"""Regression tests for the read-only, generic executable-layout diagnostics."""
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "tools" / "analyze_executables.py"
spec = importlib.util.spec_from_file_location("executable_analysis", SOURCE)
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


class FakeBackend:
    def executable_scan(self, folder):
        return {"candidates": [], "reason": "no_windows_exe", "partial": False}

    def steam_games(self):
        return []

    def saved_executable(self, folder):
        return None


def pe_binary(dll=False):
    """Minimal DOS + PE header; this test does not execute the file."""
    blob = bytearray(256)
    blob[:2] = b"MZ"
    struct.pack_into("<I", blob, 0x3c, 128)
    blob[128:132] = b"PE\x00\x00"
    struct.pack_into("<H", blob, 128 + 22, 0x2000 if dll else 0x0002)
    return bytes(blob)


class ExecutableLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / "Example"
        self.game.mkdir()

    def test_sniffer_distinguishes_pe_exe_and_dll(self):
        exe = self.game / "game.bin"
        dll = self.game / "library.dll"
        exe.write_bytes(pe_binary())
        dll.write_bytes(pe_binary(dll=True))
        self.assertEqual(analysis.sniff_binary(exe), "PE executable")
        self.assertEqual(analysis.sniff_binary(dll), "PE DLL")

    def test_reports_pe_file_without_exe_extension(self):
        nested = self.game / "Content" / "Windows" / "Build"
        nested.mkdir(parents=True)
        launcher = nested / "launch.bin"
        launcher.write_bytes(pe_binary())
        report = analysis.inspect_game(self.game, FakeBackend())
        self.assertEqual(report["potential_executable_count"], 1)
        candidate = report["potential_executables"][0]
        self.assertEqual(candidate["relative_path"], "Content/Windows/Build/launch.bin")
        self.assertEqual(candidate["signature"], "PE executable")
        self.assertTrue(candidate["possible_misnamed_pe"])
        self.assertFalse(candidate["recognized_by_launcher"])

    def test_identifies_native_game_and_shell_script(self):
        (self.game / "Game.x86_64").write_bytes(b"\x7fELF" + bytes(60))
        (self.game / "start.sh").write_bytes(b"#!/bin/sh\nexit 0\n")
        report = analysis.inspect_game(self.game, FakeBackend())
        signatures = report["signature_counts"]
        self.assertEqual(signatures["ELF"], 1)
        self.assertEqual(signatures["script"], 1)

    def test_never_follows_symlinks(self):
        outside = Path(self.temp.name) / "secret"
        outside.mkdir()
        (outside / "secret.exe").write_bytes(pe_binary())
        (self.game / "linked").symlink_to(outside, target_is_directory=True)
        report = analysis.inspect_game(self.game, FakeBackend())
        self.assertEqual(report["symlinks_skipped"], 1)
        self.assertEqual(report["potential_executable_count"], 0)

    def test_limits_and_local_report_format(self):
        for i in range(7):
            (self.game / f"example{i}.exe").write_bytes(pe_binary())
        report = analysis.inspect_game(self.game, FakeBackend(), max_files=4, examples=2)
        self.assertEqual(report["files_examined"], 4)
        self.assertEqual(len(report["potential_executables"]), 2)
        self.assertTrue(any("limit" in w for w in report["warnings"]))
        self.assertFalse(any(self.temp.name in x["relative_path"]
                             for x in report["potential_executables"]))

    def test_script_main_accepts_specific_game(self):
        (self.game / "game.exe").write_bytes(pe_binary())
        from contextlib import redirect_stdout
        import io
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(analysis.main(["--game", str(self.game)]), 0)
        data = json.loads(out.getvalue())
        self.assertTrue(data["read_only"])
        self.assertEqual(data["games_examined"], 1)
        self.assertEqual(data["reports"][0]["game"], "Example")


if __name__ == "__main__":
    unittest.main()
