"""Opt-in root/systemd tests. Every production path lives in a disposable chroot."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get("LYCEUMTV_BACKUP_INTEGRATION") == "1", "requires isolated root/systemd runner")
class PreinstallBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lyceumtv-backup-test-", dir="/var/lib")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for directory in ("usr", "etc", "run", "var/backups", "opt/lyceumtv/data", "states", "mocks"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        for name in ("bin", "sbin", "lib", "lib64"):
            (self.root / name).symlink_to("usr/" + name)
        (self.root / "etc/passwd").write_text("root:x:0:0:root:/root:/bin/bash\n")
        (self.root / "etc/group").write_text("root:x:0:\n")
        shutil.copyfile(ROOT / "scripts/preinstall_backup.sh", self.root / "backup.sh")
        (self.root / "opt/lyceumtv/data/config.json").write_text('{"fixture":true}')
        self.script("systemctl", '''#!/bin/bash
echo "$*" >> /calls
if [[ "$1" == show ]]; then
  if [[ "$4" == LoadState ]]; then
    if [[ -f "/states/$2" ]]; then echo loaded; else echo not-found; fi
  else cat "/states/$2"; fi
elif [[ "$1" == stop ]]; then echo inactive > "/states/$2"
elif [[ "$1" == start ]]; then echo active > "/states/$2"
else exit 99; fi
''')
        self.script("tar", '''#!/bin/bash
if [[ -f /fail-tar ]]; then echo "simulated tar failure" >&2; exit 23; fi
if [[ -f /corrupt-tar && "$1" == -czf ]]; then echo corrupt > "$2"; exit 0; fi
exec /usr/bin/tar "$@"
''')
        self.states = {"lyceumtv.service": "active", "lyceumtv-watchdog.timer": "active",
                       "lyceumtv-backup.timer": "inactive", "lyceumtv-mirror.service": "active"}
        for name, value in self.states.items():
            (self.root / "states" / name).write_text(value + "\n")

    def script(self, name, content):
        path = self.root / "mocks" / name
        path.write_text(content)
        path.chmod(0o755)

    def run_backup(self):
        return subprocess.run([
            "systemd-run", "--wait", "--pipe", "--collect", "--unit=lyceumtv-backup-test-" + uuid.uuid4().hex,
            "--property=RootDirectory=" + str(self.root), "--property=BindReadOnlyPaths=/usr",
            "--property=MountAPIVFS=yes", "--setenv=PATH=/mocks:/usr/bin:/bin",
            "/bin/bash", "/backup.sh",
        ], capture_output=True, text=True, timeout=30)

    def assert_restored(self):
        for name, value in self.states.items():
            self.assertEqual((self.root / "states" / name).read_text().strip(), value)
        calls = (self.root / "calls").read_text()
        self.assertNotIn("start lyceumtv-backup.timer", calls)
        stops = [line for line in calls.splitlines() if line.startswith("stop ")]
        self.assertEqual(stops[-1], "stop lyceumtv.service")

    def test_verified_archive_and_active_states_restored(self):
        result = self.run_backup()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_restored()
        archives = list((self.root / "var/backups/lyceumtv").glob("*.tar.gz"))
        self.assertEqual(len(archives), 1)
        self.assertEqual(archives[0].stat().st_mode & 0o777, 0o600)
        import tarfile
        with tarfile.open(archives[0]) as archive:
            self.assertEqual(archive.extractfile("lyceumtv/data/config.json").read(), b'{"fixture":true}')

    def test_tar_failure_restores_states_and_does_not_publish_archive(self):
        (self.root / "fail-tar").touch()
        result = self.run_backup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("simulated tar failure", result.stderr)
        self.assert_restored()
        self.assertFalse(list((self.root / "var/backups/lyceumtv").glob("*.tar.gz")))

    def test_corrupt_archive_is_rejected_and_states_restored(self):
        (self.root / "corrupt-tar").touch()
        result = self.run_backup()
        self.assertNotEqual(result.returncode, 0)
        self.assert_restored()
        self.assertFalse(list((self.root / "var/backups/lyceumtv").glob("*.tar.gz")))

    def test_pending_ota_refuses_before_stopping_services(self):
        (self.root / "opt/lyceumtv/data/ota_pending").write_text("{}")
        result = self.run_backup()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "calls").exists())

    def test_first_install_does_not_stop_services(self):
        shutil.rmtree(self.root / "opt/lyceumtv")
        result = self.run_backup()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.root / "calls").exists())
