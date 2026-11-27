"""Regression checks for verified Linux AppImage release update flow."""
from pathlib import Path
import hashlib
import io
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import launcher_updates as updates


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.content = b"example AppImage payload"
        self.digest = hashlib.sha256(self.content).hexdigest()
        self.release = [{"tag_name": "linux-v2.4.0", "draft": False,
                         "prerelease": False, "assets": [{
                             "name": updates.ASSET, "size": len(self.content),
                             "digest": "sha256:" + self.digest,
                         }]}]

    def test_release_checks_reject_missing_asset_digest(self):
        entries = [{"tag_name": "linux-v5.0.0", "assets": [{
            "name": updates.ASSET, "size": 20,
            "digest": None,
        }]}]
        with patch.object(updates, "_github_json", return_value=entries):
            self.assertIsNone(updates.check_updates()["latest"])

    def test_semver_order_and_update_detection(self):
        data = self.release + [{"tag_name": "linux-v1.20.0",
             "assets": [{"name": updates.ASSET, "size": 20,
                        "digest": "sha256:" + "a" * 64}]}]
        with patch.object(updates, "_github_json", return_value=data):
            found = updates.check_updates()
        self.assertEqual(found["latest"]["tag"], "linux-v2.4.0")
        self.assertTrue(found["available"])
        self.assertIsNone(updates.version_tuple("nonsense"))

    def test_download_verifies_digest_and_does_not_execute(self):
        class Response:
            def __init__(self, value):
                self.stream = io.BytesIO(value)
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                return False
            def read(self, size=-1):
                return self.stream.read(size)
        with (patch.dict(os.environ, {"XDG_DATA_HOME": str(self.root / "data")}),
              patch.object(updates, "_github_json", return_value=self.release),
              patch.object(updates.urllib.request, "urlopen", return_value=Response(self.content))):
            result = updates.download_update()
        self.assertEqual(result["status"], "downloaded")
        self.assertEqual(Path(result["file"]).read_bytes(), self.content)

    def test_changed_binary_checksum_blocks_download(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                return False
            def read(self, size=-1):
                return b"different content" if size != -1 else b""
        with (patch.dict(os.environ, {"XDG_DATA_HOME": str(self.root / "data")}),
              patch.object(updates, "_github_json", return_value=self.release),
              patch.object(updates.urllib.request, "urlopen", return_value=Response())):
            with self.assertRaises(ValueError):
                updates.download_update()
        self.assertFalse(any((self.root / "data").rglob(updates.ASSET)))

    def test_apply_requires_explicit_consent(self):
        with self.assertRaisesRegex(ValueError, "approval"):
            updates.apply_downloaded_update(self.root / "missing.AppImage")

    def test_apply_preserves_previous_appimage(self):
        current = self.root / "AMDNR-old.AppImage"
        current.write_bytes(b"old launcher")
        package = self.root / "data/amdnr/updates/linux-v2.4.0" / updates.ASSET
        package.parent.mkdir(parents=True)
        package.write_bytes(self.content)
        with (patch.dict(os.environ, {
                    "APPIMAGE": str(current), "XDG_DATA_HOME": str(self.root / "data")
              }),
              patch.object(updates, "_github_json", return_value=self.release)):
            result = updates.apply_downloaded_update(package, consent=True)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(current.read_bytes(), self.content)
        self.assertEqual(Path(result["previous_launcher"]).read_bytes(), b"old launcher")


if __name__ == "__main__":
    unittest.main()
