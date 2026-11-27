"""Small, bounded integration tests for local Heroic/Lutris metadata."""
from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import third_party_stores as stores


class StoresTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "config"
        self.data = self.root / "data"
        self.folder = self.root / "installed"
        self.folder.mkdir()

    def test_heroic_installed_metadata_is_discovered(self):
        path = self.config / "heroic/legendaryConfig/legendary/installed.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            "sample": {"title": "Sample Epic Game", "install_path": str(self.folder)},
            "deleted": {"title": "Gone", "install_path": str(self.root / "missing")},
        }))
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.config),
                                    "XDG_DATA_HOME": str(self.data)}):
            games = stores.external_games()
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]["store"], "Heroic (Epic)")
        self.assertEqual(games[0]["name"], "Sample Epic Game")

    def test_lutris_metadata_is_discovered_without_executing_yaml(self):
        path = self.data / "lutris/games/sample.yml"
        path.parent.mkdir(parents=True)
        executable = self.folder / "game.exe"
        executable.write_bytes(b"dummy")
        path.write_text("name: Sample Lutris Game\n"
                        "game:\n"
                        "  exe: " + str(executable) + "\n"
                        "  working_dir: " + str(self.folder) + "\n")
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.config),
                                    "XDG_DATA_HOME": str(self.data)}):
            games = stores.external_games()
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]["name"], "Sample Lutris Game")
        self.assertEqual(games[0]["executable"], str(executable))

    def test_corrupt_and_unsafe_metadata_is_not_followed(self):
        path = self.config / "heroic/gog_store/installed.json"
        path.parent.mkdir(parents=True)
        path.write_text("not valid json")
        symlink = self.config / "heroic/nile/installed.json"
        symlink.parent.mkdir(parents=True)
        symlink.symlink_to(path)
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.config),
                                    "XDG_DATA_HOME": str(self.data)}):
            self.assertEqual(stores.external_games(), [])

    def test_duplicate_game_metadata_deduplicates(self):
        epic = self.config / "heroic/legendaryConfig/legendary/installed.json"
        gog = self.config / "heroic/gog_store/installed.json"
        epic.parent.mkdir(parents=True)
        gog.parent.mkdir(parents=True)
        payload = [{"title": "Same", "install_path": str(self.folder)}]
        epic.write_text(json.dumps(payload))
        gog.write_text(json.dumps(payload))
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.config),
                                    "XDG_DATA_HOME": str(self.data)}):
            self.assertEqual(len(stores.external_games()), 1)


if __name__ == "__main__":
    unittest.main()
