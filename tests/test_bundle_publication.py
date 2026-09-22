"""F14 checksummed export publication races on synthetic evidence only."""
from pathlib import Path
import json
import unittest
from unittest.mock import patch
import zipfile
import test_core
from test_strategy_package import package
from quantlab.trading.strategy_package import compile_strategy
from quantlab.workbench.jobs import execute, prepare
from quantlab.storage.bundle import export_bundle, restore_bundle

class BundlePublicationTests(unittest.TestCase):
    def setUp(self):
        self.fx=test_core.CoreTests();self.fx.setUp();self.addCleanup(self.fx.tearDown)
        self.root=self.fx.root.resolve();self.run=execute(prepare(compile_strategy(package())['spec']),self.root,self.root/'runs')
    def test_mutation_between_manifest_and_zip_write_refuses_publication(self):
        destination=self.root/'changed.zip';original=zipfile.ZipFile.write;changed=[]
        def write(archive,filename,*args,**kwargs):
            if Path(filename)==self.run.artifact_path/'report.md' and not changed:
                changed.append(True);Path(filename).write_text('changed after hashing')
            return original(archive,filename,*args,**kwargs)
        with patch.object(zipfile.ZipFile,'write',write),self.assertRaises(ValueError):
            export_bundle(self.run.artifact_path,destination)
        self.assertTrue(changed);self.assertFalse(destination.exists())
    def test_symlink_archive_root_is_rejected_before_export(self):
        alias=self.root/'alias';alias.symlink_to(self.run.artifact_path,target_is_directory=True)
        with self.assertRaises(ValueError):export_bundle(alias,self.root/'alias.zip')
        self.assertFalse((self.root/'alias.zip').exists())
    def test_interrupted_publication_is_not_success_or_silently_overwritten(self):
        destination=self.root/'partial.zip'
        import shutil
        copy=shutil.copyfileobj
        def interrupted(source,target,*args):
            if getattr(target,'name',None)==str(destination):
                target.write(b'partial publication');raise OSError('simulated write interrupted')
            return copy(source,target,*args)
        with patch('quantlab.storage.bundle.shutil.copyfileobj',side_effect=interrupted),self.assertRaisesRegex(OSError,'interrupted'):
            export_bundle(self.run.artifact_path,destination)
        # Preserve evidence of the failed exclusive write; it cannot masquerade as a usable bundle.
        self.assertEqual(destination.read_bytes(),b'partial publication')
        with self.assertRaises(FileExistsError):export_bundle(self.run.artifact_path,destination)
        with self.assertRaises(zipfile.BadZipFile):restore_bundle(destination,self.root/'invalid-restore')
        self.assertFalse((self.root/'invalid-restore').exists())

    def test_restore_does_not_replace_destination_created_during_validation(self):
        from quantlab.storage import bundle as module
        destination=self.root/'restore-race';archive=self.root/'good.zip'
        export_bundle(self.run.artifact_path,archive);write=Path.write_text;identity=[]
        def concurrent(path,value,*args,**kwargs):
            result=write(path,value,*args,**kwargs)
            if Path(path).name=='bundle.json' and Path(path).parent.name.startswith('.restore-'):
                destination.mkdir();identity.append(destination.stat().st_ino)
            return result
        with patch.object(Path,'write_text',concurrent),self.assertRaises(FileExistsError):
            restore_bundle(archive,destination)
        self.assertEqual(destination.stat().st_ino,identity[0]);self.assertEqual(list(destination.iterdir()),[])

    def test_interrupted_restore_keeps_incomplete_destination_and_refuses_retry(self):
        destination=self.root/'partial-restore';archive=self.root/'complete.zip'
        export_bundle(self.run.artifact_path,archive);rename=Path.rename
        def interrupted(path,target):
            if path.parent.name.startswith('.restore-'):raise OSError('restore publication interrupted')
            return rename(path,target)
        with patch.object(Path,'rename',interrupted),self.assertRaisesRegex(OSError,'interrupted'):
            restore_bundle(archive,destination)
        self.assertTrue((destination/'.restore-incomplete').is_file())
        with self.assertRaises(FileExistsError):restore_bundle(archive,destination)
        self.assertTrue((self.run.artifact_path/'experiment.json').is_file())

if __name__=='__main__':unittest.main()
