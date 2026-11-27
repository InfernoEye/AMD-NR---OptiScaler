"""Regression coverage for independent Linux maintenance transactions."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import amdnr_launcher as core
import launcher_maintenance as maintenance


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / "Game With Spaces"
        self.game.mkdir()
        self.exe = self.game / "Game.exe"
        self.exe.write_bytes(b"game exe")
        self.archive = self.root / "v1.zip"
        self.write_zip(self.archive, b"proxy first", b"cfg first")
        core.install(self.archive, self.exe, "dxgi.dll")

    @staticmethod
    def write_zip(path, proxy, ini):
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("payload/OptiScaler.dll", proxy)
            archive.writestr("payload/OptiScaler.ini", ini)

    def test_exact_recorded_archive_repairs_missing_file(self):
        path = self.game / "dxgi.dll"
        path.unlink()
        report = maintenance.repair_or_update(self.exe, self.archive)
        self.assertEqual(report["status"], "repaired")
        self.assertEqual(path.read_bytes(), b"proxy first")
        self.assertFalse(maintenance.status(self.exe)["interrupted"])
        self.assertEqual(core.installation_report(self.exe)["status"], "healthy")

    def test_modified_file_requires_explicit_permission_and_is_preserved(self):
        path = self.game / "dxgi.dll"
        path.write_bytes(b"my custom DLL")
        with self.assertRaisesRegex(ValueError, "Modified managed file"):
            maintenance.repair_or_update(self.exe, self.archive)
        self.assertEqual(path.read_bytes(), b"my custom DLL")
        report = maintenance.repair_or_update(self.exe, self.archive, allow_modified=True)
        self.assertEqual(report["status"], "repaired")
        self.assertEqual(path.read_bytes(), b"proxy first")
        preserved = list((self.game / "AMDNR_backup").glob("linux-repair-preserved-*/dxgi.dll"))
        self.assertEqual(len(preserved), 1)
        self.assertEqual(preserved[0].read_bytes(), b"my custom DLL")

    def test_upgrade_keeps_original_game_file_for_uninstall(self):
        original = self.game / "OptiScaler.ini"
        # Upgrade after clean install; original user INI was not backed up.
        updated = self.root / "v2.zip"
        self.write_zip(updated, b"proxy next", b"cfg next")
        result = maintenance.repair_or_update(self.exe, updated, update=True)
        self.assertEqual(result["status"], "updated")
        self.assertEqual((self.game / "dxgi.dll").read_bytes(), b"proxy next")
        self.assertEqual(original.read_bytes(), b"cfg next")
        self.assertEqual(core.installation_report(self.exe)["status"], "healthy")
        removed, warnings = core.uninstall(self.exe)
        self.assertFalse(warnings)
        self.assertFalse((self.game / "dxgi.dll").exists())

    def test_update_blocks_unmanaged_file_collisions(self):
        update = self.root / "v3.zip"
        with zipfile.ZipFile(update, "w") as archive:
            archive.writestr("payload/OptiScaler.dll", b"new")
            archive.writestr("payload/new.dll", b"our new")
        (self.game / "new.dll").write_bytes(b"unmanaged")
        with self.assertRaisesRegex(ValueError, "unmanaged"):
            maintenance.repair_or_update(self.exe, update, update=True)
        self.assertEqual((self.game / "new.dll").read_bytes(), b"unmanaged")
        self.assertFalse(maintenance.status(self.exe)["interrupted"])

    def test_repair_rejects_wrong_archive_even_when_filenames_match(self):
        different = self.root / "wrong.zip"
        self.write_zip(different, b"evil", b"cfg first")
        with self.assertRaisesRegex(ValueError, "exact recorded"):
            maintenance.repair_or_update(self.exe, different)
        self.assertEqual((self.game / "dxgi.dll").read_bytes(), b"proxy first")

    def test_proxy_retry_skips_occupied_alias_and_preserves_modified(self):
        (self.game / "version.dll").write_bytes(b"third party")
        report = maintenance.next_proxy(self.exe, core.ALIASES)
        self.assertNotEqual(report["alias"], "version.dll")
        self.assertEqual((self.game / "version.dll").read_bytes(), b"third party")
        self.assertFalse((self.game / "dxgi.dll").exists())
        self.assertTrue((self.game / report["alias"]).exists())
        core.uninstall(self.exe)
        self.assertEqual((self.game / "version.dll").read_bytes(), b"third party")

    def test_recovery_restores_original_snapshot_without_overwriting_other_edits(self):
        # Emulate an interruption immediately after the new proxy was placed.
        root = self.game
        snapshot = root / "AMDNR_backup" / maintenance.TRANSACTION_DIR
        snapshot.mkdir(parents=True)
        old_state = root / ".amdnr-linux-install.json"
        state_snapshot = snapshot / "original-install.json"
        state_snapshot.write_bytes(old_state.read_bytes())
        original = root / "dxgi.dll"
        (snapshot / "dxgi.dll").write_bytes(original.read_bytes())
        changed = b"temporary replacement"
        original.write_bytes(changed)
        maintenance.write_json_atomic(root / maintenance.JOURNAL_NAME, {
            "format": 1,
            "state_sha256": maintenance.digest(old_state),
            "new_state_sha256": maintenance.digest(old_state),
            "touched": [{
                "path": "dxgi.dll",
                "previous_sha256": maintenance.digest(snapshot / "dxgi.dll"),
                "expected_sha256": __import__("hashlib").sha256(changed).hexdigest(),
            }]
        })
        result = maintenance.restore_transaction(self.exe)
        self.assertEqual(result["status"], "restored")
        self.assertEqual(original.read_bytes(), b"proxy first")
        self.assertFalse(maintenance.status(self.exe)["interrupted"])

    def test_recovery_protects_files_modified_after_interruption(self):
        root = self.game
        snapshot = root / "AMDNR_backup" / maintenance.TRANSACTION_DIR
        snapshot.mkdir(parents=True)
        state = root / ".amdnr-linux-install.json"
        (snapshot / "original-install.json").write_bytes(state.read_bytes())
        (snapshot / "dxgi.dll").write_bytes((root / "dxgi.dll").read_bytes())
        maintenance.write_json_atomic(root / maintenance.JOURNAL_NAME, {
            "format": 1, "state_sha256": maintenance.digest(state),
            "new_state_sha256": maintenance.digest(state),
            "touched": [{"path": "dxgi.dll",
                         "previous_sha256": maintenance.digest(snapshot / "dxgi.dll"),
                         "expected_sha256": "f" * 64}],
        })
        (root / "dxgi.dll").write_bytes(b"unrecognized third-party change")
        with self.assertRaisesRegex(ValueError, "changed independently"):
            maintenance.restore_transaction(self.exe)
        self.assertEqual((root / "dxgi.dll").read_bytes(),
                         b"unrecognized third-party change")


    def test_write_failure_rolls_back_all_files_and_record(self):
        old_record = (self.game / ".amdnr-linux-install.json").read_bytes()
        new_zip = self.root / "replacement.zip"
        self.write_zip(new_zip, b"proxy replacement", b"cfg replacement")
        original_writer = maintenance._write_binary_atomic
        attempts = 0

        def fail_second_write(source, target):
            nonlocal attempts
            attempts += 1
            if attempts == 2:
                raise OSError("injected disk write error")
            return original_writer(source, target)

        with mock.patch.object(maintenance, "_write_binary_atomic",
                               side_effect=fail_second_write):
            with self.assertRaisesRegex(OSError, "injected disk write error"):
                maintenance.repair_or_update(self.exe, new_zip, update=True)
        self.assertEqual((self.game / "dxgi.dll").read_bytes(), b"proxy first")
        self.assertEqual((self.game / "OptiScaler.ini").read_bytes(), b"cfg first")
        self.assertEqual((self.game / ".amdnr-linux-install.json").read_bytes(), old_record)
        self.assertFalse(maintenance.status(self.exe)["interrupted"])
        self.assertFalse((self.game / ".amdnr-maintenance-staging").exists())

    def test_corrupt_second_recovery_entry_never_changes_first_file(self):
        snapshot = self.game / "AMDNR_backup" / maintenance.TRANSACTION_DIR
        snapshot.mkdir(parents=True)
        state = self.game / ".amdnr-linux-install.json"
        (snapshot / "original-install.json").write_bytes(state.read_bytes())
        proxy = self.game / "dxgi.dll"
        (snapshot / "dxgi.dll").write_bytes(proxy.read_bytes())
        proxy.write_bytes(b"temporary installed version")
        maintenance.write_json_atomic(self.game / maintenance.JOURNAL_NAME, {
            "format": 1,
            "state_sha256": maintenance.digest(state),
            "new_state_sha256": maintenance.digest(state),
            "touched": [
                {"path": "dxgi.dll",
                 "previous_sha256": maintenance.digest(snapshot / "dxgi.dll"),
                 "expected_sha256": __import__("hashlib").sha256(
                     b"temporary installed version").hexdigest()},
                {"path": "../outside.dll", "previous_sha256": None,
                 "expected_sha256": None},
            ]
        })
        with self.assertRaisesRegex(ValueError, "Unsafe path"):
            maintenance.restore_transaction(self.exe)
        self.assertEqual(proxy.read_bytes(), b"temporary installed version")
        self.assertTrue(maintenance.status(self.exe)["interrupted"])

    def test_bad_record_checksum_keeps_recovery_journal(self):
        snapshot = self.game / "AMDNR_backup" / maintenance.TRANSACTION_DIR
        snapshot.mkdir(parents=True)
        state = self.game / ".amdnr-linux-install.json"
        (snapshot / "original-install.json").write_bytes(state.read_bytes())
        maintenance.write_json_atomic(self.game / maintenance.JOURNAL_NAME, {
            "format": 1, "state_sha256": "z" * 64,
            "new_state_sha256": "0" * 64, "touched": []
        })
        with self.assertRaisesRegex(ValueError, "snapshot changed"):
            maintenance.restore_transaction(self.exe)
        self.assertTrue(maintenance.status(self.exe)["interrupted"])

    def test_missing_original_backup_does_not_change_live_game(self):
        old_record = (self.game / ".amdnr-linux-install.json").read_bytes()
        state = json.loads(old_record)
        state["files"][0]["backed_up"] = True
        maintenance.write_json_atomic(self.game / ".amdnr-linux-install.json", state)
        update = self.root / "replacement.zip"
        self.write_zip(update, b"new proxy", b"new configuration")
        with self.assertRaisesRegex(ValueError, "Original backup missing"):
            maintenance.repair_or_update(self.exe, update, update=True)
        self.assertEqual((self.game / "dxgi.dll").read_bytes(), b"proxy first")
        self.assertEqual((self.game / "OptiScaler.ini").read_bytes(), b"cfg first")
        self.assertFalse(maintenance.status(self.exe)["interrupted"])


    def test_first_install_failure_restores_preexisting_game_files(self):
        fresh = self.root / "CleanInstall"
        fresh.mkdir()
        executable = fresh / "Test.exe"
        executable.write_bytes(b"untouched executable")
        existing = fresh / "OptiScaler.ini"
        existing.write_bytes(b"user-specific original settings")
        old_bytes = existing.read_bytes()
        original_writer = maintenance._write_binary_atomic
        attempts = 0

        def fail_second_file(source, target):
            nonlocal attempts
            attempts += 1
            if attempts == 2:
                raise OSError("injected first install failure")
            return original_writer(source, target)

        with mock.patch.object(maintenance, "_write_binary_atomic",
                               side_effect=fail_second_file):
            with self.assertRaisesRegex(OSError, "injected first install failure"):
                core.install(self.archive, executable, "dxgi.dll")
        self.assertEqual(existing.read_bytes(), old_bytes)
        self.assertEqual(executable.read_bytes(), b"untouched executable")
        self.assertFalse((fresh / "dxgi.dll").exists())
        self.assertFalse((fresh / ".amdnr-linux-install.json").exists())
        self.assertFalse((fresh / maintenance.JOURNAL_NAME).exists())

    def test_interrupted_first_install_recovery_restores_original(self):
        fresh = self.root / "InterruptedInstall"
        fresh.mkdir()
        exe = fresh / "Game.exe"
        exe.write_bytes(b"original exe")
        original = fresh / "OptiScaler.ini"
        original.write_bytes(b"original config")
        backup = fresh / "AMDNR_backup" / "linux-launcher"
        backup.mkdir(parents=True)
        (backup / "OptiScaler.ini").write_bytes(original.read_bytes())
        original_sha = maintenance.digest(original)
        installed_bytes = b"new config"
        original.write_bytes(installed_bytes)
        proxy = fresh / "dxgi.dll"
        proxy.write_bytes(b"new proxy")
        import hashlib
        maintenance.write_json_atomic(fresh / maintenance.JOURNAL_NAME, {
            "format": 2, "mode": "install",
            "new_state_sha256": "0" * 64,
            "touched": [
                {"path": "dxgi.dll", "previous_sha256": None,
                 "expected_sha256": hashlib.sha256(b"new proxy").hexdigest()},
                {"path": "OptiScaler.ini", "previous_sha256": original_sha,
                 "expected_sha256": hashlib.sha256(installed_bytes).hexdigest()},
            ],
        })
        report = maintenance.restore_transaction(exe)
        self.assertEqual(report["recovered_operation"], "install")
        self.assertEqual(original.read_bytes(), b"original config")
        self.assertFalse(proxy.exists())
        self.assertFalse((fresh / maintenance.JOURNAL_NAME).exists())

    def test_interrupted_install_refuses_modified_file_before_rollback(self):
        fresh = self.root / "ProtectedInstall"
        fresh.mkdir()
        exe = fresh / "Game.exe"
        exe.write_bytes(b"original exe")
        backup = fresh / "AMDNR_backup" / "linux-launcher"
        backup.mkdir(parents=True)
        proxy = fresh / "dxgi.dll"
        proxy.write_bytes(b"independent edit")
        maintenance.write_json_atomic(fresh / maintenance.JOURNAL_NAME, {
            "format": 2, "mode": "install", "new_state_sha256": "0" * 64,
            "touched": [{"path": "dxgi.dll", "previous_sha256": None,
                         "expected_sha256": "a" * 64}],
        })
        with self.assertRaisesRegex(ValueError, "changed independently"):
            maintenance.restore_transaction(exe)
        self.assertEqual(proxy.read_bytes(), b"independent edit")
        self.assertTrue((fresh / maintenance.JOURNAL_NAME).exists())


if __name__ == "__main__":
    unittest.main()
