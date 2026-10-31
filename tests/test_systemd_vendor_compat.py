"""Preserve XFS scheduling/security while removing a systemd-deprecated no-op."""
import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('vendor_compat', Path(__file__).resolve().parents[1] / 'roles/systemd_compat/files/systemd-vendor-compat.py')
compat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compat)

@pytest.fixture
def tree(tmp_path):
    source, target = tmp_path / 'vendor', tmp_path / 'local'
    source.mkdir(); target.mkdir()
    for name in compat.UNITS:
        (source / name).write_bytes(b'[Service]\nCPUAccounting=true\nCPUQuota=60%\nExecStart=/usr/sbin/xfs_scrub_all\nNoNewPrivileges=true\n')
    return source, target


def test_preserves_every_other_vendor_byte_and_converges(tree):
    source, target = tree
    assert compat.reconcile(source, target, 259)['changed']
    for name in compat.UNITS:
        assert (target / name).read_bytes() == compat.MARKER + (source / name).read_bytes().replace(b'CPUAccounting=true\n', b'')
        assert (target / name).stat().st_mode & 0o777 == 0o644
    assert not compat.reconcile(source, target, 259)['changed']


def test_package_update_refreshes_other_vendor_changes(tree):
    source, target = tree
    compat.reconcile(source, target, 259)
    path = source / compat.UNITS[0]; path.write_bytes(path.read_bytes() + b'ProtectSystem=strict\n')
    assert compat.reconcile(source, target, 259)['changed']
    assert (target / path.name).read_bytes().endswith(b'ProtectSystem=strict\n')


@pytest.mark.parametrize('fixed', ['upstream', 'removed', 'downgrade'])
def test_removes_only_owned_shadows_when_no_longer_needed(tree, fixed):
    source, target = tree
    compat.reconcile(source, target, 259)
    for name in compat.UNITS:
        if fixed == 'upstream':(source / name).write_bytes(b'[Service]\nCPUQuota=60%\n')
        if fixed == 'removed':(source / name).unlink()
    assert compat.reconcile(source, target, 257 if fixed == 'downgrade' else 259)['changed']
    assert not list(target.iterdir())


def test_refuses_unmanaged_override_before_any_mutation(tree):
    source, target = tree
    (target / compat.UNITS[1]).write_bytes(b'operator managed\n')
    with pytest.raises(ValueError, match='unmanaged'):compat.reconcile(source, target, 259)
    assert not (target / compat.UNITS[0]).exists()
    assert (target / compat.UNITS[1]).read_bytes() == b'operator managed\n'


def test_refuses_mask_or_symlink(tree):
    source, target = tree
    (target / compat.UNITS[1]).symlink_to('/dev/null')
    with pytest.raises(ValueError, match='symlink'):compat.reconcile(source, target, 259)
    assert not (target / compat.UNITS[0]).exists()


def test_check_mode_and_older_systemd_do_not_mutate(tree):
    source, target = tree
    assert compat.reconcile(source, target, 259, check=True)['changed']
    assert not list(target.iterdir())
    assert not compat.reconcile(source, target, 257)['changed']
