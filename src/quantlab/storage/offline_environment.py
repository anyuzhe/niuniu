"""Pinned offline research/desktop environment for the supported local platform."""
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

PYTHON_URL='https://github.com/astral-sh/python-build-standalone/releases/download/20250612/cpython-3.13.5%2B20250612-aarch64-apple-darwin-install_only.tar.gz'
PYTHON_SHA256='d7867270b8c7be69ec26a351afb6bf24802b1cd9818e8426bd69d439a619bf2d'

INSTALL_SCRIPT='''from pathlib import Path
import hashlib,json,platform,subprocess,sys
root=Path(__file__).resolve().parent
manifest=json.loads((root/'environment.json').read_text())
if platform.system()!=manifest['system'] or platform.machine()!=manifest['machine'] or platform.python_version()!=manifest['python']:
    raise SystemExit('Interpreter/platform differs from this offline bundle')
for name,expected in manifest['files'].items():
    path=root/name
    if path.is_symlink() or path.resolve().is_relative_to(root) is False:
        raise SystemExit('Unsafe environment file: '+name)
    with path.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
    if actual!=expected:raise SystemExit('Environment checksum mismatch: '+name)
if len(sys.argv)!=2:raise SystemExit('Usage: python/bin/python3 install.py NEW_ENVIRONMENT_DIRECTORY')
target=Path(sys.argv[1]).absolute()
if target.exists():raise SystemExit('Destination already exists; no overwrite')
subprocess.run([sys.executable,'-m','venv','--symlinks',str(target)],check=True)
python=target/'bin/python'
subprocess.run([str(python),'-m','pip','install','--no-index','--no-deps','--require-hashes','--find-links',str(root/'wheels'),'-r',str(root/'requirements.txt')],check=True)
subprocess.run([str(python),'-m','pip','check'],check=True)
print(json.dumps({'python':str(python),'status':'installed_offline'}))
'''


def _hash(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def _installed_wheel_matches(wheel, distribution):
    """Account for wheel script relocation and pip's interpreter shebang rewrite."""
    import sysconfig
    members=[n for n in wheel.namelist() if not n.endswith('/') and '.dist-info/' not in n]
    if not members:return False
    for name in members:
        expected=wheel.read(name)
        if '.data/scripts/' in name:
            relative=name.split('.data/scripts/',1)[1]
            if Path(relative).name!=relative:return False
            path=Path(sysconfig.get_path('scripts'))/relative
            if not path.is_file():return False
            actual=path.read_bytes()
            if expected.startswith((b'#!python\n',b'#!pythonw\n')):
                first,separator,body=actual.partition(b'\n')
                if not separator or not first.startswith(b'#!') or b'python' not in first:return False
                actual=expected.split(b'\n',1)[0]+b'\n'+body
        else:
            path=Path(distribution.locate_file(name))
            if not path.is_file():return False
            actual=path.read_bytes()
        if actual!=expected:return False
    return True


def environment_packages():
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.utils import canonicalize_name
    pending=[('polars',set()),('pyarrow',set()),('duckdb',set()),('pip',set())]
    for optional in ('PyQt6','vnpy','alphalens-reloaded','setuptools','wheel'):
        try:metadata.version(optional)
        except metadata.PackageNotFoundError:continue
        pending.append((optional,set()))
    packages={};seen=set()
    while pending:
        name,extras=pending.pop();name=canonicalize_name(name);key=(name,tuple(sorted(extras)))
        if key in seen:continue
        seen.add(key);distribution=metadata.distribution(name);packages[name]=distribution.version
        for text in distribution.requires or []:
            req=Requirement(text)
            if req.marker and not any(req.marker.evaluate({'extra':extra}) for extra in extras|{''}):continue
            if req.url:raise ValueError('Offline environment requires published pinned wheels: '+text)
            version=metadata.version(req.name)
            if req.specifier and not req.specifier.contains(version,prereleases=True):raise ValueError('Installed dependency conflict: '+text)
            pending.append((req.name,set(req.extras)))
    return dict(sorted(packages.items()))


def export_offline_environment(destination, *, python_archive=None):
    """Download once, then install with included Python and wheels without a network."""
    if (platform.system(),platform.machine(),platform.python_version())!=('Darwin','arm64','3.13.5'):
        raise ValueError('Offline interpreter bundle currently supports macOS arm64 / Python 3.13.5 only')
    destination=Path(destination).absolute()
    if destination.exists():raise FileExistsError(destination)
    packages=environment_packages();destination.parent.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix='.offline-',dir=destination.parent))
    try:
        archive=staging/'python.tar.gz'
        if python_archive:shutil.copyfile(python_archive,archive)
        else:
            with urllib.request.urlopen(PYTHON_URL,timeout=60) as source,archive.open('xb') as target:shutil.copyfileobj(source,target)
        if _hash(archive)!=PYTHON_SHA256:raise ValueError('Standalone Python checksum differs from pinned release')
        with tarfile.open(archive) as tar:tar.extractall(staging,filter='data')
        archive.unlink()
        wheels=staging/'wheels';wheels.mkdir()
        from pip._vendor.packaging.utils import parse_wheel_filename,canonicalize_name
        from pip._vendor.packaging.tags import sys_tags
        import zipfile
        cache_root=Path(subprocess.check_output([sys.executable,'-m','pip','cache','dir'],text=True).strip())
        cached=set();supported=set(sys_tags())
        for candidate in (cache_root/'wheels').rglob('*.whl'):
            name,version,_,tags=parse_wheel_filename(candidate.name);name=canonicalize_name(name)
            if packages.get(name)!=str(version) or not tags.intersection(supported):continue
            distribution=metadata.distribution(name)
            with zipfile.ZipFile(candidate) as wheel:
                matches=_installed_wheel_matches(wheel,distribution)
            if matches:shutil.copyfile(candidate,wheels/candidate.name);cached.add(name)
        command=[sys.executable,'-m','pip','download','--only-binary=:all:','--no-deps','--dest',str(wheels),*[name+'=='+version for name,version in packages.items() if name not in cached]]
        process=subprocess.run(command,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        (staging/'download.log').write_text(process.stdout)
        if process.returncode:raise ValueError('Pinned wheel download failed: '+process.stdout[-6000:])
        from pip._vendor.packaging.utils import parse_wheel_filename,canonicalize_name
        found={}
        for path in wheels.glob('*.whl'):
            name,version,_,_=parse_wheel_filename(path.name);found[canonicalize_name(name)]=(str(version),_hash(path))
        if {name:version for name,(version,_) in found.items()}!=packages:raise ValueError('Downloaded wheels do not match installed versions')
        (staging/'requirements.txt').write_text(''.join(f'{name}=={version} --hash=sha256:{found[name][1]}\n' for name,version in packages.items()))
        (staging/'install.py').write_text(INSTALL_SCRIPT)
        # Dereference internal interpreter links so the integrity inventory covers their bytes.
        for path in sorted((staging/'python').rglob('*')):
            if path.is_symlink() and path.is_file():
                payload=path.read_bytes();mode=path.stat().st_mode;path.unlink();path.write_bytes(payload);path.chmod(mode)
        # Interpreter imports regenerate bytecode after relocation. Inventory source,
        # libraries and executables, rather than mutable import caches.
        for path in (staging/'python').rglob('*.pyc'):path.unlink()
        files={p.relative_to(staging).as_posix():_hash(p) for p in staging.rglob('*') if p.is_file()}
        manifest={'version':1,'system':platform.system(),'machine':platform.machine(),'python':platform.python_version(),'packages':packages,'installed_verified_cached_wheels':sorted(cached),'interpreter_url':PYTHON_URL,'interpreter_archive_sha256':PYTHON_SHA256,'files':files,
            'scope':'Offline interpreter and pinned research/desktop/vn.py dependency closure for this platform. Experiment artifacts and their matching source are exported separately. Not a cross-OS environment.'}
        (staging/'environment.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
        (staging/'README.txt').write_text('macOS arm64 / Python 3.13.5\nOffline install: python/bin/python3 install.py /absolute/path/to/new-env\nThen use the experiment bundle source: PYTHONPATH=/path/to/bundle/source /path/to/new-env/bin/python /path/to/bundle/tools/reproduce.py ARCHIVE OUTPUT\nKeep this directory: the installed virtual environment uses its standalone interpreter.\n')
        staging.rename(destination)
    except Exception:
        shutil.rmtree(staging,ignore_errors=True);raise
    return {'path':str(destination),'packages':len(packages),'files':len(files),'python':str(destination/'python/bin/python3'),'status':'exported','scope':manifest['scope']}
