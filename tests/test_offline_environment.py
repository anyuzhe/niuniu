import io
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from quantlab.storage.offline_environment import _installed_wheel_matches, export_offline_environment

# The bundle itself is macOS arm64 / Python 3.13.5 only; tests of its checksum and destination guards
# pin the platform identity so they exercise the same code path on every developer machine.
SUPPORTED=SimpleNamespace(system=lambda:'Darwin',machine=lambda:'arm64',python_version=lambda:'3.13.5')
UNSUPPORTED=SimpleNamespace(system=lambda:'Linux',machine=lambda:'aarch64',python_version=lambda:'3.13.5')


class OfflineEnvironmentTests(unittest.TestCase):
    def test_modules_that_import_numpy_and_pandas_declare_them(self):
        import re
        import tomllib
        root = Path(__file__).resolve().parents[1]
        declared = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']['dependencies']
        names = {re.split(r'[<>=!~;\[ ]', item, maxsplit=1)[0].lower() for item in declared}
        # statistics/correlation.py and trading/sentiment_cycle.py import numpy at module level; the DATA
        # services, intraday providers and snapshots read Parquet through pandas
        self.assertTrue({'numpy', 'pandas'} <= names, names)

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
            with patch('quantlab.storage.offline_environment.platform',SUPPORTED),\
                    patch('quantlab.storage.offline_environment.environment_packages',return_value={}):
                with self.assertRaisesRegex(ValueError,'checksum'):
                    export_offline_environment(root/'out',python_archive=archive)
            self.assertFalse((root/'out').exists());self.assertFalse(list(root.glob('.offline-*')))

    def test_existing_destination_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp,patch('quantlab.storage.offline_environment.platform',SUPPORTED):
            with self.assertRaises(FileExistsError):export_offline_environment(tmp)

    def test_unsupported_platform_is_rejected_before_any_write(self):
        with tempfile.TemporaryDirectory() as tmp,patch('quantlab.storage.offline_environment.platform',UNSUPPORTED):
            with self.assertRaisesRegex(ValueError,'macOS arm64 / Python 3.13.5 only'):
                export_offline_environment(Path(tmp)/'out')
            self.assertFalse((Path(tmp)/'out').exists());self.assertFalse(list(Path(tmp).glob('.offline-*')))
