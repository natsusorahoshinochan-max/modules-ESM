"""Authenticated, content-addressed storage for complete Node outputs."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import pickle
import secrets
import stat
from dataclasses import is_dataclass
from enum import Enum
import importlib
from pathlib import Path
from typing import Any

from core.storage import StoragePathError, validate_identifier


_MAGIC = b"PWB-CACHE-1\n"
_MAX_ENTRY_BYTES = 256 * 1024 * 1024


class _SafeCacheUnpickler(pickle.Unpickler):
    """Deserialize only inert dataclasses defined by the trusted type package."""

    def find_class(self, module: str, name: str) -> Any:
        if module.startswith("datatypes."):
            datatype_module = importlib.import_module(module)
            candidate = getattr(datatype_module, name, None)
            if (
                isinstance(candidate, type)
                and candidate.__module__ == module
                and is_dataclass(candidate)
            ):
                return candidate
        raise pickle.UnpicklingError(
            f"Cache global is not permitted: {module}.{name}"
        )


class CachePublishStatus(str, Enum):
    """Outcome of one immutable first-writer Cache publication."""

    CREATED = "created"
    EXISTING_VALID = "existing_valid"
    FAILED = "failed"


class CacheStore:
    """Operate inside one held, non-symlinked Cache Node namespace."""

    def __init__(self, cache_root: str | Path, node_id: str) -> None:
        self.cache_root = Path(cache_root)
        self.node_id = validate_identifier(node_id, "node_id")
        self.cache_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_flags |= getattr(os, "O_NOFOLLOW", 0)
        self._root_fd = os.open(self.cache_root, directory_flags)
        try:
            self._require_private_directory(
                self._root_fd,
                "cache_root",
            )
            try:
                os.mkdir(
                    self.node_id,
                    mode=0o700,
                    dir_fd=self._root_fd,
                )
            except FileExistsError:
                pass
        except Exception:
            os.close(self._root_fd)
            self._root_fd = -1
            raise
        try:
            self._node_fd = os.open(
                self.node_id,
                directory_flags,
                dir_fd=self._root_fd,
            )
            self._require_private_directory(
                self._node_fd,
                "node_id",
            )
        except (OSError, StoragePathError) as error:
            if getattr(self, "_node_fd", -1) >= 0:
                os.close(self._node_fd)
                self._node_fd = -1
            os.close(self._root_fd)
            self._root_fd = -1
            raise StoragePathError(
                "node_id",
                "Invalid Cache Node namespace",
            ) from error

    @staticmethod
    def _require_private_directory(
        descriptor: int,
        field: str,
    ) -> None:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
        ):
            raise StoragePathError(
                field,
                "Cache namespace permissions are unsafe",
            )
        if stat.S_IMODE(metadata.st_mode) != 0o700:
            os.fchmod(descriptor, 0o700)
            if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o700:
                raise StoragePathError(
                    field,
                    "Cache namespace permissions are unsafe",
                )

    @staticmethod
    def _is_private_file(metadata: os.stat_result) -> bool:
        return (
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_uid == os.getuid()
            and metadata.st_nlink == 1
            and stat.S_IMODE(metadata.st_mode) == 0o600
        )

    def path(self, cache_key: str) -> Path:
        safe_key = validate_identifier(cache_key, "cache_key")
        return self.cache_root / self.node_id / f"{safe_key}.pkl"

    def _key(self, *, create: bool) -> bytes | None:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(
                ".integrity-key",
                flags,
                dir_fd=self._root_fd,
            )
        except FileNotFoundError:
            if not create:
                return None
            try:
                descriptor = os.open(
                    ".integrity-key",
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=self._root_fd,
                )
            except FileExistsError:
                return self._key(create=False)
            key = secrets.token_bytes(32)
            with os.fdopen(descriptor, "wb", closefd=True) as key_file:
                key_file.write(key)
                key_file.flush()
                os.fsync(key_file.fileno())
            os.fsync(self._root_fd)
            return key
        with os.fdopen(descriptor, "rb", closefd=True) as key_file:
            metadata = os.fstat(key_file.fileno())
            if not self._is_private_file(metadata):
                raise StoragePathError(
                    "cache_root",
                    "Cache integrity key permissions are unsafe",
                )
            key = key_file.read(64)
        return key if len(key) == 32 else None

    @staticmethod
    def _header(
        *,
        module_id: str,
        module_version: str,
        cache_key: str,
        output_ports: list[dict[str, str]],
        payload: bytes,
    ) -> bytes:
        return json.dumps(
            {
                "schema_version": 1,
                "module_id": module_id,
                "module_version": module_version,
                "cache_key": cache_key,
                "output_ports": output_ports,
                "payload_sha256": hashlib.sha256(payload).hexdigest(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

    def load(
        self,
        cache_key: str,
        *,
        module_id: str = "",
        module_version: str = "",
        output_ports: list[dict[str, str]] | None = None,
    ) -> dict[str, Any] | None:
        safe_key = validate_identifier(cache_key, "cache_key")
        key = self._key(create=False)
        if key is None:
            return None
        descriptor: int | None = None
        try:
            descriptor = os.open(
                f"{safe_key}.pkl",
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=self._node_fd,
            )
            metadata = os.fstat(descriptor)
            if (
                not self._is_private_file(metadata)
                or metadata.st_size > _MAX_ENTRY_BYTES
            ):
                return None
            with os.fdopen(descriptor, "rb", closefd=True) as entry:
                descriptor = None
                encoded = entry.read()
            if not encoded.startswith(_MAGIC):
                return None
            offset = len(_MAGIC)
            header_size = int.from_bytes(encoded[offset:offset + 8], "big")
            offset += 8
            if header_size <= 0 or header_size > 1024 * 1024:
                return None
            header_bytes = encoded[offset:offset + header_size]
            offset += header_size
            signature = encoded[offset:offset + 32]
            payload = encoded[offset + 32:]
            if not hmac.compare_digest(
                signature,
                hmac.digest(key, header_bytes + payload, "sha256"),
            ):
                return None
            header = json.loads(header_bytes)
            expected_ports = output_ports if output_ports is not None else header[
                "output_ports"
            ]
            if header != json.loads(self._header(
                module_id=module_id,
                module_version=module_version,
                cache_key=safe_key,
                output_ports=expected_ports,
                payload=payload,
            )):
                return None
            cached = _SafeCacheUnpickler(io.BytesIO(payload)).load()
            return cached if isinstance(cached, dict) else None
        except (
            OSError,
            ValueError,
            KeyError,
            json.JSONDecodeError,
            pickle.PickleError,
            EOFError,
            AttributeError,
        ):
            return None
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def save(
        self,
        cache_key: str,
        outputs: dict[str, Any],
        *,
        module_id: str = "",
        module_version: str = "",
        output_ports: list[dict[str, str]] | None = None,
    ) -> CachePublishStatus:
        safe_key = validate_identifier(cache_key, "cache_key")
        key = self._key(create=True)
        if key is None:
            return CachePublishStatus.FAILED
        ports = output_ports or [
            {"name": name, "type_id": ""}
            for name in sorted(outputs)
        ]
        try:
            payload = pickle.dumps(outputs, protocol=pickle.HIGHEST_PROTOCOL)
            header = self._header(
                module_id=module_id,
                module_version=module_version,
                cache_key=safe_key,
                output_ports=ports,
                payload=payload,
            )
            signature = hmac.digest(key, header + payload, "sha256")
            encoded = (
                _MAGIC
                + len(header).to_bytes(8, "big")
                + header
                + signature
                + payload
            )
            temporary_name = f".{safe_key}.{secrets.token_hex(12)}.tmp"
            descriptor = os.open(
                temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=self._node_fd,
            )
            try:
                with os.fdopen(descriptor, "wb", closefd=True) as temporary:
                    temporary.write(encoded)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                created = True
                try:
                    os.link(
                        temporary_name,
                        f"{safe_key}.pkl",
                        src_dir_fd=self._node_fd,
                        dst_dir_fd=self._node_fd,
                    )
                except FileExistsError:
                    created = False
                os.fsync(self._node_fd)
            finally:
                try:
                    os.unlink(temporary_name, dir_fd=self._node_fd)
                except FileNotFoundError:
                    pass
        except (OSError, pickle.PickleError):
            return CachePublishStatus.FAILED
        if not created:
            existing = self.load(
                safe_key,
                module_id=module_id,
                module_version=module_version,
                output_ports=ports,
            )
            return (
                CachePublishStatus.EXISTING_VALID
                if existing is not None
                else CachePublishStatus.FAILED
            )
        try:
            metadata = os.stat(
                f"{safe_key}.pkl",
                dir_fd=self._node_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return CachePublishStatus.FAILED
        return (
            CachePublishStatus.CREATED
            if self._is_private_file(metadata)
            else CachePublishStatus.FAILED
        )

    def remove(self, cache_key: str) -> None:
        safe_key = validate_identifier(cache_key, "cache_key")
        try:
            os.unlink(f"{safe_key}.pkl", dir_fd=self._node_fd)
        except FileNotFoundError:
            pass

    def close(self) -> None:
        if getattr(self, "_node_fd", -1) >= 0:
            os.close(self._node_fd)
            self._node_fd = -1
        if getattr(self, "_root_fd", -1) >= 0:
            os.close(self._root_fd)
            self._root_fd = -1

    def __enter__(self) -> "CacheStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
