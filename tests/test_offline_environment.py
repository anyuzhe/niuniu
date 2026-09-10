import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from quantlab.storage.offline_environment import _installed_wheel_matches, export_offline_environment


class OfflineEnvironmentTests(unittest.TestCase):
    def test_cached_scripts_allow_only_shebang_relocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'tool.py').write_bytes(b'#!/venv/bin/python\nprint(1)\n')
            payload=io.BytesIO()
            with zipfile.ZipFile(payload,'w') as wheel:wheel.writestr('pkg.data/scripts/tool.py',b'#!python\nprint(1)\n')
            with zipfile.ZipFile(payload) as wheel,patch('sysconfig.get_path',return_value=tmp):
                self.assertTrue(_installed_wheel_matches(wheel,None))
                (root/'tool.py').write_bytes(b'#!/venv/bin/python\nprint(2)\n')
                self.assertFalse(_installed_wheel_matches(wheel,None))

    def test_bad_interpreter_checksum_leaves_no_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive=root/'bad.tar.gz';archive.write_bytes(b'not the interpreter')
            with patch('quantlab.storage.offline_environment.environment_packages',return_value={}):
                with self.assertRaisesRegex(ValueError,'checksum'):
                    export_offline_environment(root/'out',python_archive=archive)
            self.assertFalse((root/'out').exists());self.assertFalse(list(root.glob('.offline-*')))

    def test_existing_destination_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileExistsError):export_offline_environment(tmp)
