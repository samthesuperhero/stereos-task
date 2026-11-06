from __future__ import annotations

import configparser
import filecmp
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CANONICAL_ROOT = Path("/opt/stereos-task")
CONFIG_DIR = Path("/etc/stereos-task")
CONFIG_PATH = CONFIG_DIR / "stereos-task.ini"
STATIC_ROOT = Path("/var/www/stereos-task")
STATE_DIR = Path("/var/lib/stereos-task")
UNIT_PATH = Path("/etc/systemd/system/stereos-task.service")
NGINX_PATH = Path("/etc/nginx/conf.d/stereos.filestreamcloud.org.conf")
USER = "stereos-task"
PYTHON_VERSION_SCRIPT = "import sys; print('.'.join(map(str, sys.version_info[:3])))"


def _parse_ini(content: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(content)
    if parser.defaults() or parser.sections() != ["service"]:
        raise RuntimeError("Configuration must contain only a [service] section")
    return parser


def reconcile_ini(existing: str, example: str) -> str:
    try:
        desired = _parse_ini(example)
        current = _parse_ini(existing) if existing else None
    except (configparser.Error, KeyError, RuntimeError) as exc:
        raise RuntimeError(f"Cannot reconcile INI configuration: {exc}") from exc
    if current is None:
        return example if example.endswith("\n") else example + "\n"
    additions = [
        f"{key} = {value}"
        for key, value in desired["service"].items()
        if key not in current["service"]
    ]
    if not additions:
        return existing
    separator = "" if existing.endswith("\n") else "\n"
    return existing + separator + "\n".join(additions) + "\n"


def required_python_version(root: Path) -> tuple[int, ...]:
    pyproject = root / "pyproject.toml"
    try:
        content = pyproject.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"Cannot read interpreter requirement from {pyproject}: {exc}") from exc
    match = re.search(
        r"^\s*requires-python\s*=\s*['\"]>=\s*(\d+(?:\.\d+){0,2})['\"]\s*(?:#.*)?$",
        content,
        re.MULTILINE,
    )
    if not match:
        raise RuntimeError(f"Cannot determine the interpreter lower bound from {pyproject}")
    return tuple(int(part) for part in match.group(1).split("."))


def _version_meets_floor(version: tuple[int, ...], floor: tuple[int, ...]) -> bool:
    return version[: len(floor)] >= floor


def require_supported_interpreter(root: Path) -> tuple[int, ...]:
    floor = required_python_version(root)
    current = tuple(sys.version_info[:3])
    if not _version_meets_floor(current, floor):
        required = ".".join(str(part) for part in floor)
        actual = ".".join(str(part) for part in current)
        raise RuntimeError(
            f"Python >= {required} is required; current Python is {actual}"
        )
    return floor


def format_command_error(error: subprocess.CalledProcessError) -> str:
    message = str(error)
    for output in (error.stderr, error.stdout):
        if output and output.strip():
            return f"{message}\n{output.strip()}"
    return message


class Provisioner:
    def __init__(self, root: Path, dry_run: bool = False, verbose: bool = False) -> None:
        self.root = root
        self.dry_run = dry_run
        self.verbose = verbose
        self.changed = False
        self._configuration: tuple[bytes | None, str, str] | None = None

    def log(self, message: str) -> None:
        if self.verbose or self.dry_run:
            print(message)

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        self.log("+ " + " ".join(args))
        if self.dry_run:
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.run(args, check=check, text=True, capture_output=True)

    def query(self, *args: str) -> subprocess.CompletedProcess:
        self.log("+ " + " ".join(args))
        return subprocess.run(args, check=False, text=True, capture_output=True)

    def _get_mode(self, path: Path) -> int:
        return path.stat().st_mode & 0o777

    def _set_mode(self, path: Path, mode: int) -> None:
        path.chmod(mode)

    def _atomic_write_bytes(self, path: Path, content: bytes, mode: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
            self._set_mode(temporary, mode)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _atomic_write_text(self, path: Path, content: str, mode: int) -> None:
        self._atomic_write_bytes(path, content.encode("utf-8"), mode)

    def _atomic_copy(self, origin: Path, destination: Path, mode: int) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", dir=destination.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as target, origin.open("rb") as source:
                shutil.copyfileobj(source, target)
            self._set_mode(temporary, mode)
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()

    def ensure_directory(self, path: Path, mode: int) -> bool:
        if path.is_symlink():
            raise RuntimeError(f"Refusing to use a symlink as a directory: {path}")
        if path.exists():
            if not path.is_dir():
                raise RuntimeError(f"Expected a directory: {path}")
            if self._get_mode(path) == mode:
                return False
            self.log(f"Set mode {mode:04o} on {path}")
            self.changed = True
            if not self.dry_run:
                self._set_mode(path, mode)
            return True
        self.log(f"Create directory {path}")
        self.changed = True
        if not self.dry_run:
            path.mkdir(parents=True)
            self._set_mode(path, mode)
        return True

    def ensure_file(self, path: Path, content: str, mode: int) -> bool:
        exists = path.exists()
        current = path.read_text(encoding="utf-8") if exists else None
        correct_mode = exists and self._get_mode(path) == mode
        if current == content and correct_mode and not path.is_symlink():
            return False
        self.log(f"Write {path}")
        self.changed = True
        if not self.dry_run:
            self._atomic_write_text(path, content, mode)
        return True

    def ensure_user(self) -> None:
        import pwd

        try:
            pwd.getpwnam(USER)
            return
        except KeyError:
            pass
        self.log(f"Create system user {USER}")
        self.changed = True
        self.run("useradd", "--system", "--home", str(STATE_DIR), "--shell", "/usr/sbin/nologin", USER)

    def ensure_ownership(self) -> None:
        if self.dry_run:
            return
        import grp
        import pwd

        account = pwd.getpwnam(USER)
        group = grp.getgrnam(USER)
        for path in (STATIC_ROOT, STATE_DIR):
            for item in (path, *path.rglob("*")):
                if item.is_symlink():
                    continue
                if item.stat().st_uid != account.pw_uid or item.stat().st_gid != group.gr_gid:
                    item.chown(account.pw_uid, group.gr_gid)
                    self.changed = True

    def _ensure_static_directory(
        self,
        path: Path,
        mode: int,
        dry_replacements: set[Path],
    ) -> bool:
        changed = False
        if path.is_symlink():
            self.log(f"Replace directory symlink {path}")
            changed = self.changed = True
            if self.dry_run:
                dry_replacements.add(path)
                return changed
            path.unlink()
        if self.dry_run and not path.exists():
            dry_replacements.add(path)
        return self.ensure_directory(path, mode) or changed

    @staticmethod
    def _static_entries(root: Path) -> list[Path]:
        entries = []
        directories = [root]
        while directories:
            directory = directories.pop()
            for item in directory.iterdir():
                entries.append(item)
                if not item.is_symlink() and item.is_dir():
                    directories.append(item)
        return entries

    def ensure_static(self) -> bool:
        source = self.root / "front"
        if not source.is_dir():
            raise RuntimeError(f"Frontend source directory does not exist: {source}")
        expected = {
            origin.relative_to(source) for origin in source.rglob("*") if origin.is_file()
        }
        expected_directories = {
            parent
            for relative in expected
            for parent in relative.parents
            if parent != Path(".")
        }
        dry_replacements: set[Path] = set()
        changed = self._ensure_static_directory(
            STATIC_ROOT, 0o755, dry_replacements
        )
        for relative in sorted(expected_directories, key=lambda path: len(path.parts)):
            directory_changed = self._ensure_static_directory(
                STATIC_ROOT / relative, 0o755, dry_replacements
            )
            changed = directory_changed or changed

        for relative in sorted(expected):
            origin = source / relative
            destination = STATIC_ROOT / relative
            if any(parent in dry_replacements for parent in destination.parents):
                self.log(f"Install {destination}")
                changed = self.changed = True
                continue
            if destination.is_symlink():
                self.log(f"Replace file symlink {destination}")
                changed = self.changed = True
                if self.dry_run:
                    continue
                destination.unlink()
            exists = destination.exists()
            if exists and not destination.is_file():
                raise RuntimeError(f"Expected a regular file: {destination}")
            content_matches = exists and filecmp.cmp(origin, destination, shallow=False)
            correct_mode = exists and self._get_mode(destination) == 0o644
            if content_matches and correct_mode:
                continue
            if content_matches:
                self.log(f"Set mode 0644 on {destination}")
            else:
                self.log(f"Install {destination}")
            changed = self.changed = True
            if not self.dry_run:
                if content_matches:
                    self._set_mode(destination, 0o644)
                else:
                    self._atomic_copy(origin, destination, 0o644)

        if STATIC_ROOT in dry_replacements:
            return changed
        for destination in self._static_entries(STATIC_ROOT):
            relative = destination.relative_to(STATIC_ROOT)
            if destination.is_symlink():
                if relative in expected or relative in expected_directories:
                    continue
            elif destination.is_file():
                if relative in expected:
                    continue
            elif destination.is_dir():
                continue
            else:
                raise RuntimeError(f"Unsupported static-tree entry: {destination}")
            self.log(f"Remove stale file {destination}")
            changed = self.changed = True
            if not self.dry_run:
                destination.unlink()

        directories = sorted(
            (
                path
                for path in self._static_entries(STATIC_ROOT)
                if not path.is_symlink() and path.is_dir()
            ),
            key=lambda path: len(path.parts),
            reverse=True,
        )
        for directory in directories:
            relative = directory.relative_to(STATIC_ROOT)
            if relative in expected_directories or any(directory.iterdir()):
                continue
            self.log(f"Remove empty directory {directory}")
            changed = self.changed = True
            if not self.dry_run:
                directory.rmdir()
        return changed

    def prepare_configuration(self) -> tuple[bytes | None, str, str]:
        example = (self.root / "deploy" / "stereos-task.ini").read_text(encoding="utf-8")
        try:
            existing_bytes = CONFIG_PATH.read_bytes() if CONFIG_PATH.exists() else None
            existing = existing_bytes.decode("utf-8") if existing_bytes is not None else ""
        except UnicodeError as exc:
            raise RuntimeError(
                f"Invalid configuration {CONFIG_PATH}: cannot decode UTF-8: {exc}"
            ) from exc
        try:
            merged = reconcile_ini(existing, example)
        except RuntimeError as exc:
            raise RuntimeError(f"Invalid configuration {CONFIG_PATH}: {exc}") from exc
        self._configuration = (existing_bytes, existing, merged)
        return self._configuration

    def ensure_configuration(self) -> bool:
        existing_bytes, existing, merged = (
            self._configuration or self.prepare_configuration()
        )
        exists = CONFIG_PATH.exists()
        correct_mode = exists and self._get_mode(CONFIG_PATH) == 0o444
        changed = (
            existing_bytes is None
            or existing != merged
            or not correct_mode
            or CONFIG_PATH.is_symlink()
        )
        if not changed:
            return False
        self.ensure_directory(CONFIG_DIR, 0o755)
        if existing_bytes is not None:
            backup = CONFIG_PATH.with_name(CONFIG_PATH.name + ".bak")
            self.log(f"Back up {CONFIG_PATH} to {backup}")
            if not self.dry_run:
                self._atomic_write_bytes(backup, existing_bytes, 0o444)
        self.log(f"Write {CONFIG_PATH}")
        self.changed = True
        if not self.dry_run:
            self._atomic_write_text(CONFIG_PATH, merged, 0o444)
            self._configuration = (merged.encode("utf-8"), merged, merged)
        return True

    def _query_python_version(self, python: Path) -> tuple[int, ...] | None:
        try:
            result = self.query(str(python), "-c", PYTHON_VERSION_SCRIPT)
        except OSError:
            return None
        if result.returncode != 0:
            return None
        try:
            return tuple(
                int(part) for part in (result.stdout or "").strip().split(".")
            )
        except ValueError:
            return None

    @staticmethod
    def _remove_generated_path(path: Path) -> None:
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.exists():
            shutil.rmtree(path)

    def ensure_virtualenv(self) -> bool:
        environment = self.root / ".venv"
        python = environment / "bin" / "python"
        floor = required_python_version(self.root)
        if python.exists():
            version = self._query_python_version(python)
            if version is not None and _version_meets_floor(version, floor):
                return False
            self.log("Rebuild the virtual environment with a supported interpreter")
        else:
            self.log("Create virtual environment")
        self.changed = True
        if self.dry_run:
            return True

        staging = Path(tempfile.mkdtemp(prefix=".venv-", dir=self.root))
        backup = staging.with_name(staging.name + "-previous")
        try:
            self.run(sys.executable, "-m", "venv", str(staging))
            version = self._query_python_version(staging / "bin" / "python")
            if version is None or not _version_meets_floor(version, floor):
                raise RuntimeError("Created virtual environment has an unsupported interpreter")
            if environment.exists() or environment.is_symlink():
                environment.replace(backup)
            try:
                staging.replace(environment)
            except Exception:
                if backup.exists() or backup.is_symlink():
                    backup.replace(environment)
                raise
            if backup.exists() or backup.is_symlink():
                self._remove_generated_path(backup)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        return True

    def ensure_services(self) -> tuple[bool, bool]:
        unit = (self.root / "deploy" / "stereos-task.service").read_text(encoding="utf-8")
        nginx = (self.root / "deploy" / "nginx.conf").read_text(encoding="utf-8")
        unit_changed = self.ensure_file(UNIT_PATH, unit, 0o644)
        nginx_changed = self.ensure_file(NGINX_PATH, nginx, 0o644)
        if not shutil.which("nginx"):
            self.log("Install nginx")
            self.changed = True
            self.run("dnf", "install", "-y", "nginx")
        return unit_changed, nginx_changed

    def ensure_firewall(self) -> bool:
        active = self.query(
            "systemctl", "is-active", "--quiet", "firewalld"
        ).returncode == 0
        if not active:
            return False
        changed = False
        for port in (80, 443):
            allowed = self.query(
                "firewall-cmd", "--permanent", f"--query-port={port}/tcp"
            ).returncode == 0
            if allowed:
                continue
            self.log(f"Allow TCP port {port} through firewalld")
            changed = True
            self.run("firewall-cmd", "--permanent", f"--add-port={port}/tcp")
        if changed:
            self.run("firewall-cmd", "--reload")
        return changed

    def reconcile(self) -> tuple[bool, bool, bool]:
        self.prepare_configuration()
        self.ensure_user()
        self.ensure_directory(STATE_DIR, 0o750)
        self.ensure_virtualenv()
        self.ensure_static()
        config_changed = self.ensure_configuration()
        unit_changed, nginx_changed = self.ensure_services()
        self.ensure_ownership()
        if unit_changed:
            self.run("systemctl", "daemon-reload")
        self.run("systemctl", "enable", "stereos-task.service")
        self.run("systemctl", "enable", "nginx")
        nginx_active = self.query(
            "systemctl", "is-active", "--quiet", "nginx"
        ).returncode == 0
        if nginx_changed or not nginx_active:
            self.run("nginx", "-t")
            if nginx_changed:
                self.run("systemctl", "reload-or-restart", "nginx")
            else:
                self.run("systemctl", "start", "nginx")
        self.ensure_firewall()
        return unit_changed, config_changed, nginx_changed

    def activate(self, restart: bool, start: bool = False) -> None:
        active = self.query(
            "systemctl", "is-active", "--quiet", "stereos-task.service"
        ).returncode == 0
        if restart and active:
            self.run("systemctl", "restart", "stereos-task.service")
        elif start or not active:
            self.run("systemctl", "start", "stereos-task.service")


def require_production_root(root: Path) -> None:
    if root.resolve() != CANONICAL_ROOT:
        raise RuntimeError(f"Run from the canonical checkout {CANONICAL_ROOT}")
    if os.name != "posix" or not hasattr(os, "geteuid") or os.geteuid() != 0:
        raise RuntimeError("Provisioning must run as root on Linux")
