import subprocess
import sys
from pathlib import Path

import pytest

import install
import update
from runtime import provision
from runtime.provision import (
    NGINX_PATH,
    Provisioner,
    format_command_error,
    reconcile_ini,
    require_supported_interpreter,
    required_python_version,
)


def fake_modes(monkeypatch, provisioner):
    modes = {}

    def get_mode(path):
        if path in modes:
            return modes[path]
        return 0o755 if path.is_dir() else 0o644

    monkeypatch.setattr(provisioner, "_get_mode", get_mode)
    monkeypatch.setattr(
        provisioner, "_set_mode", lambda path, mode: modes.__setitem__(path, mode)
    )
    original_replace = provision.os.replace

    def replace(source, destination):
        original_replace(source, destination)
        source_path = Path(source)
        if source_path in modes:
            modes[Path(destination)] = modes.pop(source_path)

    monkeypatch.setattr(provision.os, "replace", replace)
    return modes


def write_example(root, content="[service]\nport = 61070\n"):
    example = root / "deploy" / "stereos-task.ini"
    example.parent.mkdir(parents=True, exist_ok=True)
    example.write_text(content, encoding="utf-8")
    return example


def configure_paths(monkeypatch, tmp_path):
    directory = tmp_path / "etc" / "stereos-task"
    path = directory / "stereos-task.ini"
    monkeypatch.setattr(provision, "CONFIG_DIR", directory)
    monkeypatch.setattr(provision, "CONFIG_PATH", path)
    return directory, path


def make_symlink(link, target, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Symlinks are unavailable on this host: {exc}")


def test_ini_reconciliation_preserves_values_comments_and_order():
    existing = "# retained\n[service]\nport = 62000\ncustom = retained\n"
    example = "[service]\nhost = 127.0.0.1\nport = 61070\nnew_key = default\n"
    merged = reconcile_ini(existing, example)
    assert merged.startswith("# retained\n[service]\nport = 62000\ncustom = retained\n")
    assert merged.endswith("host = 127.0.0.1\nnew_key = default\n")
    assert "port = 61070" not in merged
    assert reconcile_ini(merged, example) == merged


@pytest.mark.parametrize(
    "existing",
    [
        "[service]\nport = 1\nport = 2\n",
        "[other]\nport = 1\n",
    ],
)
def test_invalid_ini_has_a_controlled_error(existing):
    with pytest.raises(RuntimeError, match="Cannot reconcile"):
        reconcile_ini(existing, "[service]\nport = 61070\n")


def test_fedora_nginx_configuration_contains_https_and_required_headers():
    config = (Path(__file__).parent.parent / "deploy" / "nginx.conf").read_text(
        encoding="utf-8"
    )
    assert NGINX_PATH.as_posix() == "/etc/nginx/conf.d/stereos.filestreamcloud.org.conf"
    assert "listen 443 ssl;" in config
    assert "return 301 https://$host$request_uri;" in config
    assert "ssl_certificate /etc/letsencrypt/live/stereos.filestreamcloud.org/fullchain.pem" in config
    assert 'add_header Strict-Transport-Security "max-age=31536000" always;' in config
    assert 'add_header Cache-Control "no-cache" always;' in config
    assert "proxy_set_header X-Real-IP $remote_addr;" in config
    assert "proxy_read_timeout 60s;" in config


def test_static_frontend_is_mirrored_idempotently(monkeypatch, tmp_path):
    root = tmp_path / "checkout"
    source = root / "front"
    source.mkdir(parents=True)
    (source / "index.html").write_text("index", encoding="utf-8")
    (source / "assets").mkdir()
    (source / "assets" / "app.js").write_text("app", encoding="utf-8")
    target = tmp_path / "www"
    monkeypatch.setattr(provision, "STATIC_ROOT", target)
    provisioner = Provisioner(root)
    fake_modes(monkeypatch, provisioner)

    assert provisioner.ensure_static() is True
    assert (target / "index.html").read_text(encoding="utf-8") == "index"
    assert provisioner.ensure_static() is False

    (source / "assets" / "app.js").unlink()
    (source / "assets").rmdir()
    assert provisioner.ensure_static() is True
    assert not (target / "assets" / "app.js").exists()
    assert not (target / "assets").exists()
    assert (target / "index.html").exists()


def test_static_permissions_are_reconciled_without_rewriting_content(monkeypatch, tmp_path):
    root = tmp_path / "checkout"
    source = root / "front"
    source.mkdir(parents=True)
    (source / "index.html").write_text("index", encoding="utf-8")
    target = tmp_path / "www"
    monkeypatch.setattr(provision, "STATIC_ROOT", target)
    provisioner = Provisioner(root)
    modes = fake_modes(monkeypatch, provisioner)
    provisioner.ensure_static()
    modes[target] = 0o777
    modes[target / "index.html"] = 0o600

    assert provisioner.ensure_static() is True
    assert modes[target] == 0o755
    assert modes[target / "index.html"] == 0o644
    assert provisioner.ensure_static() is False


def test_existing_directory_modes_are_reconciled_and_dry_run_is_read_only(monkeypatch, tmp_path):
    target = tmp_path / "state"
    target.mkdir()
    provisioner = Provisioner(tmp_path)
    modes = fake_modes(monkeypatch, provisioner)
    modes[target] = 0o777
    assert provisioner.ensure_directory(target, 0o750) is True
    assert modes[target] == 0o750
    assert provisioner.ensure_directory(target, 0o750) is False

    dry_run = Provisioner(tmp_path, dry_run=True)
    dry_modes = fake_modes(monkeypatch, dry_run)
    dry_modes[target] = 0o777
    assert dry_run.ensure_directory(target, 0o750) is True
    assert dry_modes[target] == 0o777


def test_static_file_symlink_branch_does_not_write_an_outside_file(monkeypatch, tmp_path):
    root = tmp_path / "checkout"
    source = root / "front"
    source.mkdir(parents=True)
    (source / "index.html").write_text("new", encoding="utf-8")
    target = tmp_path / "www"
    target.mkdir()
    destination = target / "index.html"
    destination.write_text("old", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(provision, "STATIC_ROOT", target)
    provisioner = Provisioner(root)
    fake_modes(monkeypatch, provisioner)
    original_is_symlink = Path.is_symlink

    def fake_is_symlink(path):
        if path == destination:
            return True
        return original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)
    provisioner.ensure_static()
    assert outside.read_text(encoding="utf-8") == "keep"
    assert destination.read_text(encoding="utf-8") == "new"


def test_real_static_symlinks_are_replaced_without_touching_targets(monkeypatch, tmp_path):
    root = tmp_path / "checkout"
    source = root / "front"
    (source / "assets").mkdir(parents=True)
    (source / "index.html").write_text("new", encoding="utf-8")
    (source / "assets" / "app.js").write_text("app", encoding="utf-8")
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("keep", encoding="utf-8")
    outside_directory = tmp_path / "outside-directory"
    outside_directory.mkdir()
    sentinel = outside_directory / "sentinel"
    sentinel.write_text("keep", encoding="utf-8")
    target = tmp_path / "www"
    target.mkdir()
    make_symlink(target / "index.html", outside_file)
    make_symlink(target / "assets", outside_directory, directory=True)
    monkeypatch.setattr(provision, "STATIC_ROOT", target)
    provisioner = Provisioner(root)
    fake_modes(monkeypatch, provisioner)

    provisioner.ensure_static()
    assert outside_file.read_text(encoding="utf-8") == "keep"
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert not (outside_directory / "app.js").exists()
    assert not (target / "index.html").is_symlink()
    assert not (target / "assets").is_symlink()
    assert (target / "index.html").read_text(encoding="utf-8") == "new"
    assert (target / "assets" / "app.js").read_text(encoding="utf-8") == "app"


def test_static_root_symlink_is_replaced_not_followed(monkeypatch, tmp_path):
    root = tmp_path / "checkout"
    source = root / "front"
    source.mkdir(parents=True)
    (source / "index.html").write_text("index", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("keep", encoding="utf-8")
    target = tmp_path / "www"
    make_symlink(target, outside, directory=True)
    monkeypatch.setattr(provision, "STATIC_ROOT", target)
    provisioner = Provisioner(root)
    fake_modes(monkeypatch, provisioner)

    provisioner.ensure_static()
    assert not target.is_symlink()
    assert (target / "index.html").read_text(encoding="utf-8") == "index"
    assert not (outside / "index.html").exists()
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_empty_existing_ini_is_backed_up_before_replacement(monkeypatch, tmp_path):
    root = tmp_path / "checkout"
    write_example(root)
    directory, path = configure_paths(monkeypatch, tmp_path)
    directory.mkdir(parents=True)
    path.write_bytes(b"")
    provisioner = Provisioner(root)
    fake_modes(monkeypatch, provisioner)

    assert provisioner.ensure_configuration() is True
    assert path.with_name(path.name + ".bak").read_bytes() == b""
    assert path.read_text(encoding="utf-8") == "[service]\nport = 61070\n"
    assert provisioner.ensure_configuration() is False


def test_backup_failure_leaves_live_ini_unchanged(monkeypatch, tmp_path):
    root = tmp_path / "checkout"
    write_example(root, "[service]\nhost = 127.0.0.1\nport = 61070\n")
    directory, path = configure_paths(monkeypatch, tmp_path)
    directory.mkdir(parents=True)
    original = b"[service]\nport = 62000\n"
    path.write_bytes(original)
    backup = path.with_name(path.name + ".bak")
    backup.mkdir()
    provisioner = Provisioner(root)
    fake_modes(monkeypatch, provisioner)

    with pytest.raises(OSError):
        provisioner.ensure_configuration()
    assert path.read_bytes() == original


def test_configuration_dry_run_writes_neither_ini_nor_backup(monkeypatch, tmp_path):
    root = tmp_path / "checkout"
    write_example(root, "[service]\nhost = 127.0.0.1\nport = 61070\n")
    directory, path = configure_paths(monkeypatch, tmp_path)
    directory.mkdir(parents=True)
    original = b"[service]\nport = 62000\n"
    path.write_bytes(original)
    provisioner = Provisioner(root, dry_run=True)
    fake_modes(monkeypatch, provisioner)

    assert provisioner.ensure_configuration() is True
    assert path.read_bytes() == original
    assert not path.with_name(path.name + ".bak").exists()


@pytest.mark.parametrize("content", [b"[service]\nport = 1\nport = 2\n", b"[other]\nport = 1\n", b"\xff"])
def test_invalid_existing_ini_prevents_all_provisioning_mutations(monkeypatch, tmp_path, content):
    root = tmp_path / "checkout"
    write_example(root)
    directory, path = configure_paths(monkeypatch, tmp_path)
    directory.mkdir(parents=True)
    path.write_bytes(content)
    provisioner = Provisioner(root)
    called = False

    def ensure_user():
        nonlocal called
        called = True

    monkeypatch.setattr(provisioner, "ensure_user", ensure_user)
    with pytest.raises(RuntimeError, match="Invalid configuration"):
        provisioner.reconcile()
    assert called is False


def test_python_floor_is_read_from_pyproject_and_enforced(monkeypatch, tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python = ">=9.8"\n', encoding="utf-8"
    )
    assert required_python_version(tmp_path) == (9, 8)
    monkeypatch.setattr(provision.sys, "version_info", (9, 7, 9))
    with pytest.raises(RuntimeError, match="Python >= 9.8"):
        require_supported_interpreter(tmp_path)


def test_install_rejects_old_interpreter_before_provisioning(monkeypatch, capsys):
    monkeypatch.setattr(install, "require_production_root", lambda root: None)

    def reject(root):
        raise RuntimeError("old interpreter")

    monkeypatch.setattr(install, "require_supported_interpreter", reject)

    class ForbiddenProvisioner:
        def __init__(self, *args, **kwargs):
            raise AssertionError("provisioning must not start")

    monkeypatch.setattr(install, "Provisioner", ForbiddenProvisioner)
    monkeypatch.setattr(sys, "argv", ["install", "--dry-run"])
    with pytest.raises(SystemExit):
        install.main()
    assert "old interpreter" in capsys.readouterr().err


def test_update_rejects_old_interpreter_before_git(monkeypatch, capsys):
    monkeypatch.setattr(update, "require_production_root", lambda root: None)

    def reject(root):
        raise RuntimeError("old interpreter")

    monkeypatch.setattr(update, "require_supported_interpreter", reject)

    def forbidden_git(*args):
        raise AssertionError("git must not run")

    monkeypatch.setattr(update, "git", forbidden_git)
    monkeypatch.setattr(sys, "argv", ["update", "--dry-run"])
    with pytest.raises(SystemExit):
        update.main()
    assert "old interpreter" in capsys.readouterr().err


def test_existing_venv_is_executed_and_accepted_only_when_healthy(monkeypatch, tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python = ">=9.8"\n', encoding="utf-8"
    )
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("python", encoding="utf-8")
    provisioner = Provisioner(tmp_path)
    monkeypatch.setattr(
        provisioner,
        "query",
        lambda *args: subprocess.CompletedProcess(args, 0, "9.8.1\n", ""),
    )
    assert provisioner.ensure_virtualenv() is False


def test_broken_venv_dry_run_does_not_rebuild(monkeypatch, tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python = ">=9.8"\n', encoding="utf-8"
    )
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("old", encoding="utf-8")
    provisioner = Provisioner(tmp_path, dry_run=True)
    monkeypatch.setattr(
        provisioner,
        "query",
        lambda *args: subprocess.CompletedProcess(args, 1, "", "broken"),
    )

    def forbidden_run(*args, **kwargs):
        raise AssertionError("dry-run must not build")

    monkeypatch.setattr(provisioner, "run", forbidden_run)
    assert provisioner.ensure_virtualenv() is True
    assert python.read_text(encoding="utf-8") == "old"


def test_venv_replacement_is_staged(monkeypatch, tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python = ">=9.8"\n', encoding="utf-8"
    )
    old = tmp_path / ".venv" / "old"
    old.parent.mkdir()
    old.write_text("old", encoding="utf-8")
    provisioner = Provisioner(tmp_path)

    def fake_run(*args, check=True):
        if "venv" in args:
            python = Path(args[-1]) / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("new", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(provisioner, "run", fake_run)
    monkeypatch.setattr(
        provisioner,
        "query",
        lambda *args: subprocess.CompletedProcess(args, 0, "9.8.1\n", ""),
    )
    assert provisioner.ensure_virtualenv() is True
    assert not old.exists()
    assert (tmp_path / ".venv" / "bin" / "python").read_text(encoding="utf-8") == "new"


def test_failed_venv_build_preserves_previous_environment(monkeypatch, tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python = ">=9.8"\n', encoding="utf-8"
    )
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("old", encoding="utf-8")
    provisioner = Provisioner(tmp_path)
    monkeypatch.setattr(
        provisioner,
        "query",
        lambda *args: subprocess.CompletedProcess(args, 1, "", "broken"),
    )

    def fail_build(*args, check=True):
        raise subprocess.CalledProcessError(1, args, stderr="build failed")

    monkeypatch.setattr(provisioner, "run", fail_build)
    with pytest.raises(subprocess.CalledProcessError):
        provisioner.ensure_virtualenv()
    assert python.read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob(".venv-*"))


def prepare_reconcile(monkeypatch, provisioner, nginx_changed=False, nginx_active=True):
    commands = []
    monkeypatch.setattr(provisioner, "prepare_configuration", lambda: None)
    monkeypatch.setattr(provisioner, "ensure_user", lambda: None)
    monkeypatch.setattr(provisioner, "ensure_directory", lambda *args: False)
    monkeypatch.setattr(provisioner, "ensure_virtualenv", lambda: False)
    monkeypatch.setattr(provisioner, "ensure_static", lambda: False)
    monkeypatch.setattr(provisioner, "ensure_configuration", lambda: False)
    monkeypatch.setattr(
        provisioner, "ensure_services", lambda: (False, nginx_changed)
    )
    monkeypatch.setattr(provisioner, "ensure_ownership", lambda: None)
    monkeypatch.setattr(provisioner, "ensure_firewall", lambda: False)
    monkeypatch.setattr(
        provisioner,
        "query",
        lambda *args: subprocess.CompletedProcess(args, 0 if nginx_active else 3, "", ""),
    )

    def run(*args, check=True):
        commands.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(provisioner, "run", run)
    return commands


@pytest.mark.parametrize(
    "nginx_changed,nginx_active,expected",
    [
        (False, False, "start"),
        (False, True, None),
        (True, True, "reload-or-restart"),
        (True, False, "reload-or-restart"),
    ],
)
def test_nginx_lifecycle_recovers_inactive_service(monkeypatch, tmp_path, nginx_changed, nginx_active, expected):
    provisioner = Provisioner(tmp_path)
    commands = prepare_reconcile(
        monkeypatch, provisioner, nginx_changed=nginx_changed, nginx_active=nginx_active
    )
    provisioner.reconcile()
    lifecycle = [command for command in commands if command[0] == "nginx" or "nginx" in command[-1:]]
    if expected is None:
        assert ("nginx", "-t") not in commands
        assert not any(command[:2] == ("systemctl", "start") for command in commands)
    else:
        assert ("nginx", "-t") in commands
        assert ("systemctl", expected, "nginx") in commands
    assert ("systemctl", "enable", "nginx") in lifecycle


@pytest.mark.parametrize(
    "unit_changed,config_changed,extra_args,expected_restart,expected_start",
    [
        (False, False, [], False, False),
        (True, False, [], True, False),
        (False, True, [], True, False),
        (False, False, ["--reexecuted"], True, False),
        (True, False, ["--no-restart"], False, False),
        (False, False, ["--start"], False, True),
    ],
)
def test_update_restart_matrix_ignores_generic_provisioning_changes(
    monkeypatch,
    unit_changed,
    config_changed,
    extra_args,
    expected_restart,
    expected_start,
):
    monkeypatch.setattr(update, "require_production_root", lambda root: None)
    monkeypatch.setattr(update, "require_supported_interpreter", lambda root: None)
    monkeypatch.setattr(update, "git", lambda *args: "same-head")
    calls = []

    class FakeProvisioner:
        def __init__(self, *args, **kwargs):
            self.changed = True

        def reconcile(self):
            return unit_changed, config_changed, False

        def activate(self, restart, start=False):
            calls.append((restart, start))

    monkeypatch.setattr(update, "Provisioner", FakeProvisioner)
    monkeypatch.setattr(sys, "argv", ["update", "--dry-run", *extra_args])
    assert update.main() == 0
    assert calls == [(expected_restart, expected_start)]


@pytest.mark.parametrize("config_changed,expected", [(False, False), (True, True)])
def test_install_restart_ignores_generic_provisioning_changes(monkeypatch, config_changed, expected):
    monkeypatch.setattr(install, "require_production_root", lambda root: None)
    monkeypatch.setattr(install, "require_supported_interpreter", lambda root: None)
    calls = []

    class FakeProvisioner:
        def __init__(self, *args, **kwargs):
            self.changed = True

        def reconcile(self):
            return False, config_changed, False

        def activate(self, restart, start=False):
            calls.append((restart, start))

    monkeypatch.setattr(install, "Provisioner", FakeProvisioner)
    monkeypatch.setattr(sys, "argv", ["install", "--dry-run"])
    assert install.main() == 0
    assert calls == [(expected, False)]


def test_failed_commands_expose_captured_stderr(monkeypatch, capsys):
    error = subprocess.CalledProcessError(
        1, ("nginx", "-t"), output="", stderr="certificate missing"
    )
    assert "certificate missing" in format_command_error(error)
    monkeypatch.setattr(install, "require_production_root", lambda root: None)
    monkeypatch.setattr(install, "require_supported_interpreter", lambda root: None)

    class FailingProvisioner:
        def __init__(self, *args, **kwargs):
            pass

        def reconcile(self):
            raise error

    monkeypatch.setattr(install, "Provisioner", FailingProvisioner)
    monkeypatch.setattr(sys, "argv", ["install", "--dry-run"])
    with pytest.raises(SystemExit):
        install.main()
    assert "certificate missing" in capsys.readouterr().err


def test_firewall_adds_only_missing_ports_without_triggering_backend_restart(monkeypatch, tmp_path):
    provisioner = Provisioner(tmp_path)
    commands = []

    def query(*args):
        if args[0] == "systemctl":
            return subprocess.CompletedProcess(args, 0)
        code = 1 if "--query-port=80/tcp" in args else 0
        return subprocess.CompletedProcess(args, code)

    def run(*args, check=True):
        commands.append(args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(provisioner, "query", query)
    monkeypatch.setattr(provisioner, "run", run)
    assert provisioner.ensure_firewall() is True
    assert ("firewall-cmd", "--permanent", "--add-port=80/tcp") in commands
    assert ("firewall-cmd", "--permanent", "--add-port=443/tcp") not in commands
    assert commands[-1] == ("firewall-cmd", "--reload")
    assert provisioner.changed is False


def test_inactive_firewall_is_left_unchanged(monkeypatch, tmp_path):
    provisioner = Provisioner(tmp_path)
    monkeypatch.setattr(
        provisioner,
        "query",
        lambda *args: subprocess.CompletedProcess(args, 3),
    )
    assert provisioner.ensure_firewall() is False


def test_unexecutable_venv_interpreter_is_treated_as_broken(monkeypatch, tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python = ">=9.8"\n', encoding="utf-8"
    )
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("old", encoding="utf-8")
    provisioner = Provisioner(tmp_path, dry_run=True)

    def fail_query(*args):
        raise PermissionError("not executable")

    monkeypatch.setattr(provisioner, "query", fail_query)
    assert provisioner.ensure_virtualenv() is True
