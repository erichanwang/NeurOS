import contextlib
import importlib.util
import io
import json
import os
import tarfile
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from unittest.mock import patch


ROOT = os.path.join(os.path.dirname(__file__), "..", "config", "includes.chroot", "usr", "local", "bin")


def load(name):
    path = os.path.join(ROOT, name)
    loader = SourceFileLoader(name.replace("-", "_"), path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class TestBackupRestore(unittest.TestCase):
    def test_restore_rejects_path_traversal(self):
        backup = load("neuros-backup")
        with tempfile.TemporaryDirectory() as work:
            backup_dir = os.path.join(work, "backups")
            target = os.path.join(work, "restore")
            outside = os.path.join(work, "outside.txt")
            os.makedirs(backup_dir)
            archive_name = "malicious.tar.gz"
            archive_path = os.path.join(backup_dir, archive_name)
            with tarfile.open(archive_path, "w:gz") as tar:
                info = tarfile.TarInfo("../../outside.txt")
                data = b"must not be written"
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))

            backup.BACKUP_DIR = backup_dir
            backup.INDEX_FILE = os.path.join(backup_dir, "index.json")
            with open(backup.INDEX_FILE, "w") as f:
                json.dump([{"id": 1, "archive": archive_name, "files": 1}], f)

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                backup.restore_backup(1, target)
            self.assertIn("Refusing unsafe archive member", output.getvalue())
            self.assertFalse(os.path.exists(outside))


class TestTemplateSafety(unittest.TestCase):
    def test_template_path_rejects_adversarial_names(self):
        template = load("neuros-template")
        for name in ("../outside", "a/b", "", ".", ".."):
            with self.assertRaises(ValueError):
                template._template_path(name)

    def test_template_path_keeps_metacharacters_as_data(self):
        template = load("neuros-template")
        for name in ('name;touch', 'name"quoted', "name`sub`", "name\nother", "-leading"):
            self.assertEqual(os.path.basename(template._template_path(name)), name)

    def test_remove_requires_confirmation(self):
        template = load("neuros-template")
        with tempfile.TemporaryDirectory() as work:
            template.TEMPLATE_DIR = os.path.join(work, "templates")
            template.INDEX_FILE = os.path.join(template.TEMPLATE_DIR, "index.json")
            os.makedirs(template.TEMPLATE_DIR)
            with open(template.INDEX_FILE, "w") as f:
                json.dump([{"name": "safe"}], f)
            os.makedirs(os.path.join(template.TEMPLATE_DIR, "safe"))
            with patch("builtins.input", return_value="n"):
                with patch("sys.argv", ["neuros-template", "remove", "safe"]):
                    template.main()
            self.assertTrue(os.path.isdir(os.path.join(template.TEMPLATE_DIR, "safe")))


class TestDedupSafety(unittest.TestCase):
    def test_changed_duplicate_is_not_removed(self):
        dedup = load("neuros-dedup")
        with tempfile.TemporaryDirectory() as work:
            path = os.path.join(work, 'file with spaces; "quotes"\n`ticks`.txt')
            with open(path, "wb") as f:
                f.write(b"original")
            expected = dedup.file_hash(path)
            with open(path, "wb") as f:
                f.write(b"changed")
            self.assertFalse(dedup.remove_if_unchanged(path, expected))
            self.assertTrue(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
