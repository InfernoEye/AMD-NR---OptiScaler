"""Synthetic Steam appinfo v40, v41 and v42 cache tests. Never call Steam."""
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / "steam_launch_info.py"
spec = importlib.util.spec_from_file_location("amdnr_steam_appinfo", MODULE)
steam = importlib.util.module_from_spec(spec)
spec.loader.exec_module(steam)


def encode_kv(data, keys=None):
    out = bytearray()
    for name, value in data.items():
        out.append(0 if isinstance(value, dict) else 1)
        if keys is None:
            out.extend(name.encode() + b"\0")
        else:
            out.extend(struct.pack("<I", keys.index(name)))
        if isinstance(value, dict):
            out.extend(encode_kv(value, keys))
        else:
            out.extend(str(value).encode() + b"\0")
    out.append(8)
    return bytes(out)


def table_keys(data):
    found = []
    def visit(node):
        for name, value in node.items():
            if name not in found:
                found.append(name)
            if isinstance(value, dict):
                visit(value)
    visit(data)
    return found


def sample_app():
    return {"appinfo": {
        "common": {"type": "Game"},
        "config": {"launch": {
            "0": {"executable": r"game\bin\win64\cs2.exe",
                  "config": {"oslist": "windows", "osarch": "64"}},
            "1": {"executable": "game/cs2.sh",
                  "config": {"oslist": "linux"}},
            "2": {"executable": "editor.exe", "type": "option1",
                  "config": {"oslist": "windows", "ownsdlc": "123"}},
            "3": {"executable": "legacy.exe",
                  "config": {"oslist": "windows", "betakey": "old_branch"}},
        }}
    }}


class AppInfoTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.game = self.root / "Game"
        (self.game / "game/bin/win64").mkdir(parents=True)
        (self.game / "game/bin/win64/cs2.exe").write_bytes(b"exe")
        (self.game / "game/cs2.sh").write_bytes(b"#!/bin/sh\n")
        (self.game / "editor.exe").write_bytes(b"editor")
        (self.game / "legacy.exe").write_bytes(b"legacy")

    def test_missing_launch_section_is_not_confused_with_missing_exe(self):
        report = steam.resolve_windows_launch({"appinfo": {
            "common": {"type": "Game"}, "config": {}
        }}, self.game)
        self.assertEqual(report["reason"], "no_launch_config")
        self.assertTrue(report["metadata_present"])
        self.assertEqual(report["launch_entries"], 0)

    def test_report_declared_but_uninstalled_windows_exe(self):
        app = sample_app()
        (self.game / "game/bin/win64/cs2.exe").unlink()
        report = steam.resolve_windows_launch(app, self.game)
        self.assertEqual(report["reason"], "steam_optional_only")
        self.assertIsNone(report["selected"])
        self.assertEqual(report["windows_declared"], 3)
        self.assertEqual(report["windows_missing"], ["game/bin/win64/cs2.exe"])
        self.assertEqual(report["linux_declared"], ["game/cs2.sh"])

    def test_platform_neutral_exe_is_a_windows_candidate(self):
        # Steamworks 'All OSes' launch options omit config.oslist.
        data = {"appinfo": {"common": {"type": "Game"}, "config": {
            "launch": {"0": {"executable": r"game\bin\win64\cs2.exe"}}
        }}}
        report = steam.resolve_windows_launch(data, self.game)
        self.assertEqual(report["reason"], "steam_primary")
        self.assertEqual(report["selected"],
                         str(self.game / "game/bin/win64/cs2.exe"))
        self.assertEqual(report["windows_declared"], 1)
        self.assertEqual(report["platform_neutral_declared"], 1)

    def test_platform_neutral_linux_script_is_not_windows_candidate(self):
        data = {"appinfo": {"common": {"type": "Game"}, "config": {
            "launch": {"0": {"executable": "game/cs2.sh"}}
        }}}
        report = steam.resolve_windows_launch(data, self.game)
        self.assertEqual(report["windows_declared"], 0)
        self.assertIsNone(report["selected"])

    def test_explicit_linux_exe_must_not_be_selected_as_windows(self):
        data = {"appinfo": {"common": {"type": "Game"}, "config": {
            "launch": {"0": {"executable": "editor.exe",
                              "config": {"oslist": "linux"}}}
        }}}
        report = steam.resolve_windows_launch(data, self.game)
        self.assertEqual(report["windows_declared"], 0)
        self.assertIsNone(report["selected"])

    def test_platform_neutral_missing_exe_is_reported_not_selected(self):
        data = {"appinfo": {"common": {"type": "Game"}, "config": {
            "launch": {"0": {"executable": "missing.exe"}}
        }}}
        report = steam.resolve_windows_launch(data, self.game)
        self.assertEqual(report["windows_missing"], ["missing.exe"])
        self.assertIsNone(report["selected"])

    def test_single_labeled_steam_option_is_selected_when_unrestricted(self):
        # Actual Steam installations may give their sole launch entry a type
        # and a display description, without making it an alternate game.
        data = {"appinfo": {"common": {"type": "Game"}, "config": {
            "launch": {"0": {"executable": r"game\bin\win64\cs2.exe",
                              "type": "option1", "description": "Play game"}}
        }}}
        report = steam.resolve_windows_launch(data, self.game)
        self.assertEqual(report["reason"], "steam_unique_option")
        self.assertEqual(report["selected"],
                         str(self.game / "game/bin/win64/cs2.exe"))
        self.assertEqual(report["windows_optional"], 1)

    def test_single_beta_only_steam_option_is_not_auto_selected(self):
        data = {"appinfo": {"common": {"type": "Game"}, "config": {
            "launch": {"0": {"executable": "legacy.exe",
                              "type": "option1",
                              "config": {"betakey": "older"}}}
        }}}
        report = steam.resolve_windows_launch(data, self.game)
        self.assertIsNone(report["selected"])
        self.assertEqual(report["reason"], "steam_optional_only")

    def test_single_dlc_or_other_realm_option_not_auto_selected(self):
        for config in ({"ownsdlc": "123"}, {"realm": "steamchina"}):
            with self.subTest(config=config):
                data = {"appinfo": {"common": {"type": "Game"}, "config": {
                    "launch": {"0": {"executable": "editor.exe",
                                      "type": "option1",
                                      "config": config}}
                }}}
                report = steam.resolve_windows_launch(data, self.game)
                self.assertIsNone(report["selected"])

    def test_multiple_labeled_windows_options_stay_unselected(self):
        data = {"appinfo": {"common": {"type": "Game"}, "config": {
            "launch": {"0": {"executable": "editor.exe", "type": "option1"},
                       "1": {"executable": "legacy.exe", "type": "option2"}}
        }}}
        report = steam.resolve_windows_launch(data, self.game)
        self.assertIsNone(report["selected"])
        self.assertEqual(report["reason"], "steam_optional_only")

    def test_primary_windows_entry_ignores_linux_and_optional_launches(self):
        match = steam.resolve_windows_launch(sample_app(), self.game)
        self.assertEqual(match["reason"], "steam_primary")
        self.assertEqual(match["selected"],
                         str(self.game / "game/bin/win64/cs2.exe"))
        self.assertEqual(match["linux_launches"], 1)
        self.assertEqual(len(match["windows_candidates"]), 3)

    def test_declared_path_must_exist_and_remain_within_game(self):
        unsafe = {"appinfo": {"config": {"launch": {
            "0": {"executable": r"..\outside.exe",
                  "config": {"oslist": "windows"}},
            "1": {"executable": "/tmp/injected.exe",
                  "config": {"oslist": "windows"}},
            "2": {"executable": "absent.exe",
                  "config": {"oslist": "windows"}},
        }}}}
        match = steam.resolve_windows_launch(unsafe, self.game)
        self.assertIsNone(match["selected"])
        self.assertEqual(match["windows_candidates"], [])

    def test_ambiguous_primary_windows_entries_never_auto_select(self):
        data = sample_app()
        data["appinfo"]["config"]["launch"]["4"] = {
            "executable": "editor.exe", "config": {"oslist": "windows"}
        }
        match = steam.resolve_windows_launch(data, self.game)
        self.assertEqual(match["reason"], "steam_ambiguous")
        self.assertIsNone(match["selected"])

    def test_not_a_game_does_not_select_tools(self):
        data = sample_app()
        data["appinfo"]["common"]["type"] = "Tool"
        self.assertEqual(steam.resolve_windows_launch(data, self.game)["reason"],
                         "not_a_game")

    def test_legacy_v40_appinfo_cache(self):
        payload = encode_kv(sample_app())
        header = struct.pack("<II", steam.MAGIC40, 1)
        entry = (struct.pack("<IIIIQ", 730, 60 + len(payload), 2, 0, 0) +
                 bytes(20) + struct.pack("<I", 0) + bytes(20) + payload)
        folder = self.root / "steam"
        (folder / "appcache").mkdir(parents=True)
        (folder / "appcache/appinfo.vdf").write_bytes(
            header + entry + struct.pack("<I", 0))
        data = steam.read_cached_app(730, [folder])
        self.assertEqual(data["appinfo"]["common"]["type"], "Game")
        self.assertEqual(steam.resolve_windows_launch(data, self.game)["reason"],
                         "steam_primary")
        self.assertIsNone(steam.read_cached_app(731, [folder]))

    def test_legacy_v41_string_index_cache(self):
        app = sample_app()
        keys = table_keys(app)
        payload = encode_kv(app, keys)
        entry = (struct.pack("<IIIIQ", 730, 60 + len(payload), 2, 0, 0) +
                 bytes(20) + struct.pack("<I", 0) + bytes(20) + payload)
        offset = 16 + len(entry) + 4
        table = struct.pack("<I", len(keys)) + b"".join(
            k.encode() + b"\0" for k in keys)
        folder = self.root / "steam"
        (folder / "appcache").mkdir(parents=True)
        (folder / "appcache/appinfo.vdf").write_bytes(
            struct.pack("<IIq", steam.MAGIC41, 1, offset) +
            entry + struct.pack("<I", 0) + table)
        data = steam.read_cached_app(730, [folder])
        self.assertEqual(steam.resolve_windows_launch(data, self.game)["reason"],
                         "steam_primary")

    def test_v42_sharded_cache(self):
        app = sample_app()
        keys = table_keys(app)
        payload = encode_kv(app, keys)
        data_entry = bytes(20) + payload
        index = struct.pack("<IIII", 730, 0, len(data_entry), 0)
        strings = b"".join(k.encode() + b"\0" for k in keys)
        header = struct.pack("<11I", steam.MAGIC42, 1, steam._shard(730),
                             256, 1, len(index), len(keys), len(strings),
                             len(data_entry), 0, 0)
        folder = self.root / "steam"
        shard_dir = folder / "appcache/appinfo"
        shard_dir.mkdir(parents=True)
        (shard_dir / f"appinfo_{steam._shard(730):02x}.vdf").write_bytes(
            header + index + strings + data_entry)
        data = steam.read_cached_app(730, [folder])
        self.assertEqual(steam.resolve_windows_launch(data, self.game)["reason"],
                         "steam_primary")
        self.assertIsNone(steam.read_cached_app(731, [folder]))

    def test_missing_corrupt_cache_falls_back(self):
        folder = self.root / "steam"
        (folder / "appcache").mkdir(parents=True)
        (folder / "appcache/appinfo.vdf").write_bytes(b"bad")
        self.assertIsNone(steam.read_cached_app(730, [folder]))


if __name__ == "__main__":
    unittest.main()
