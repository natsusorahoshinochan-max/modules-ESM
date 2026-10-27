"""Install explicitly chosen wheels without changing the server environment."""
from pathlib import Path, PurePosixPath
import fcntl
from contextlib import contextmanager
import shutil
import subprocess
import sys
import tempfile
from zipfile import BadZipFile, ZipFile

from .application import HostError


@contextmanager
def module_lock(host):
    with (host.root / 'module-packages.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            from .registry import import_lock, reconcile
            with import_lock:
                records = host._records('module')
                reconcile(host.root / 'module-packages', [item['package_path'] for item in records if item.get('package_path')])
                yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def install(host, wheel, entry_point):
    with module_lock(host):
        return _install(host, wheel, entry_point)


def _install(host, wheel, entry_point):
    try:
        with ZipFile(wheel) as archive:
            for name in archive.namelist():
                if '\\' in name or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts:
                    raise HostError('Wheel contains an unsafe file path')
    except BadZipFile as exc:
        raise HostError('Selected package is not a readable wheel') from exc
    root = host.root / 'module-packages'
    root.mkdir(exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix='package-', dir=root))
    try:
        result = subprocess.run([sys.executable, '-m', 'pip', '--isolated', '--disable-pip-version-check', 'install', '--no-input', '--no-index', '--no-deps', '--no-compile', '--target', str(destination), str(wheel)], capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise HostError(f'Could not install selected wheel: {result.stderr.strip()}')
        return host._install(entry_point, package_path=destination)
    except subprocess.TimeoutExpired as exc:
        discard(destination)
        raise HostError('Selected wheel installation timed out') from exc
    except BaseException:
        discard(destination)
        raise


def discard(path):
    from .registry import discard_paths
    discard_paths([path])
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        pass
