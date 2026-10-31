"""Backups must fail closed on corruption and never extract links or traversal members."""
import io
import tarfile

import pytest

from evaluations.backup_gateway_state import extract_snapshot, prune, verify_snapshot
from evaluations.qualify_gateway_restore import snapshot
from orchestrator_runtime.evidence import EvidenceStore


def make_backup(root, name):
    source = root / ('source-' + name)
    source.mkdir()
    EvidenceStore(source / 'evidence-chain.jsonl', anchor_stream=io.StringIO()).append('probe')
    target = root / name
    snapshot(source, target)
    return target


def test_verify_detects_evidence_tampering(tmp_path):
    backup = make_backup(tmp_path, '20261031T010000Z-aaaaaaaaaaaa')
    verify_snapshot(backup)
    with (backup / 'evidence-chain.jsonl').open('ab') as stream:
        stream.write(b'{}\n')
    with pytest.raises(ValueError, match='hash/size'):
        verify_snapshot(backup)


@pytest.mark.parametrize('name,kind', [('../escape', tarfile.REGTYPE), ('./clients.json', tarfile.REGTYPE),
                                      ('./evidence-chain.jsonl', tarfile.SYMTYPE)])
def test_archive_rejects_traversal_credentials_and_links(tmp_path, name, kind):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w') as archive:
        member = tarfile.TarInfo(name)
        member.type = kind
        if kind == tarfile.SYMTYPE:
            member.linkname = '/etc/passwd'
        else:
            member.size = 2
        archive.addfile(member, io.BytesIO(b'{}') if kind == tarfile.REGTYPE else None)
    raw.seek(0)
    with tarfile.open(fileobj=raw, mode='r|') as archive, pytest.raises(ValueError):
        extract_snapshot(archive, tmp_path)


def test_retention_only_removes_whole_verified_owned_snapshots(tmp_path):
    names = ['20261031T010000Z-aaaaaaaaaaaa', '20261031T020000Z-bbbbbbbbbbbb', '20261031T030000Z-cccccccccccc']
    for name in names:
        make_backup(tmp_path, name)
    unrelated = tmp_path / 'operator-archive'
    unrelated.mkdir()
    removed = prune(tmp_path, 2)
    assert removed == names[:1]
    assert unrelated.exists()
    for name in names[1:]:
        verify_snapshot(tmp_path / name)
