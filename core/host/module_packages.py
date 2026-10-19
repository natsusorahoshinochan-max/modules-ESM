"""Install explicitly chosen wheels without changing the server environment."""
import importlib
from pathlib import Path, PurePosixPath
import fcntl
from contextlib import contextmanager
import shutil
import subprocess
import sys
import tempfile
from zipfile import BadZipFile, ZipFile

from .application import HostError


def activate(path):
    path = str(Path(path).resolve())
    if path not in sys.path:
        sys.path.insert(0, path)
    importlib.invalidate_caches()


def remove(path):
    path = Path(path).resolve()
    sys.path[:] = [item for item in sys.path if item != str(path)]
    for name, module in list(sys.modules.items()):
        source = getattr(module, '__file__', None)
        if source and Path(source).resolve().is_relative_to(path):
            sys.modules.pop(name, None)
    importlib.invalidate_caches()
    shutil.rmtree(path)


@contextmanager
def mutation_lock(host):
    with (host.root / 'module-packages.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def install(host, wheel, entry_point):
    with mutation_lock(host):
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
        activate(destination)
        from .registry import load
        declaration = load(entry_point)
        imported = importlib.import_module(entry_point.split(':')[0])
        source = getattr(imported, '__file__', None)
        if not source or not Path(source).resolve().is_relative_to(destination.resolve()):
            raise HostError('Entry point must belong to the selected wheel')
        if any(item['id'] == declaration.id for item in host.list_modules()):
            raise HostError(f'Module is already installed: {declaration.id}; uninstall it before installing a replacement')
        return host._install(entry_point, package_path=destination)
    except subprocess.TimeoutExpired as exc:
        remove(destination)
        raise HostError('Selected wheel installation timed out') from exc
    except BaseException:
        remove(destination)
        raise
