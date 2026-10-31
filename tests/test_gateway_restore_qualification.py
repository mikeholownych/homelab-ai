"""Restore qualification must preserve chain continuity and reject incomplete/corrupt backups."""
import io
import json

import pytest

from evaluations.qualify_gateway_restore import copy_prefix, restore, snapshot
from orchestrator_runtime.evidence import EvidenceStore


def source_state(tmp_path, monkeypatch):
    monkeypatch.setenv('ORCHESTRATOR_EVIDENCE_SEGMENT_BYTES', '1024')
    source = tmp_path / 'live'
    source.mkdir()
    store = EvidenceStore(source / 'evidence-chain.jsonl', anchor_stream=io.StringIO())
    for i in range(12):
        store.append('test', value='x' * 200, index=i)
    (source / 'client-usage.json').write_text('{"client":2}')
    (source / 'gateway-state.json').write_text('{}')
    return source, store


def test_sealed_backup_restores_continuity_without_modifying_live_state(tmp_path, monkeypatch):
    source, store = source_state(tmp_path, monkeypatch)
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    backup = tmp_path / 'backup'
    manifest = snapshot(source, backup)
    assert any('.sealed-' in name for name in manifest['files'])
    result = restore(backup, tmp_path / 'restored')
    assert result['passed'] and result['continuity_preserved']
    assert store.head == manifest['evidence_head']
    assert before == {p.name: p.read_bytes() for p in source.iterdir()}
    assert (backup.stat().st_mode & 0o777) == 0o700


def test_restore_rejects_tampered_backup(tmp_path, monkeypatch):
    source, _ = source_state(tmp_path, monkeypatch)
    backup = tmp_path / 'backup'
    snapshot(source, backup)
    (backup / 'client-usage.json').write_text('{"client":0}')
    with pytest.raises(ValueError, match='digest mismatch'):
        restore(backup, tmp_path / 'restored')


def test_prefix_omits_only_partial_final_line_and_enforces_budget(tmp_path):
    source = tmp_path / 'source'
    source.write_bytes(b'{"complete":1}\n{"incomplete":')
    target = tmp_path / 'snapshot'
    copy_prefix(source, target, 1024)
    assert target.read_bytes() == b'{"complete":1}\n'
    with pytest.raises(ValueError, match='byte budget'):
        copy_prefix(source, tmp_path / 'too-large', 1)


def test_backup_will_not_overwrite_or_include_credentials(tmp_path, monkeypatch):
    source, _ = source_state(tmp_path, monkeypatch)
    (source / 'clients.json').write_text('{"secret":"do-not-copy"}')
    backup = tmp_path / 'backup'
    manifest = snapshot(source, backup)
    assert 'clients.json' not in manifest['files']
    with pytest.raises(FileExistsError):
        snapshot(source, backup)
    assert 'do-not-copy' not in json.dumps(manifest)


def test_legacy_genesis_attachments_are_preserved_with_honest_provenance(tmp_path):
    import hashlib
    source = tmp_path / 'live'
    source.mkdir()
    old = source / 'legacy.jsonl'
    old.write_bytes(b'old sealed format\n')
    digest = hashlib.sha256(old.read_bytes()).hexdigest()
    EvidenceStore(source / 'evidence-chain.jsonl', anchor_stream=io.StringIO()).genesis(
        sealed_predecessors=[{'path': str(old), 'sha256': digest}])
    manifest = snapshot(source, tmp_path / 'backup')
    attachment = manifest['legacy_attachments'][0]
    assert attachment['genesis_attested'] and attachment['sha256'] == digest
    assert (tmp_path / 'backup' / attachment['snapshot_file']).read_bytes() == old.read_bytes()
    assert restore(tmp_path / 'backup', tmp_path / 'restored')['legacy_attachments'] == 1


def test_legacy_mismatch_and_out_of_root_reference_fail_closed(tmp_path):
    import hashlib
    source = tmp_path / 'live'
    source.mkdir()
    old = source / 'legacy.jsonl'
    old.write_bytes(b'old format\n')
    EvidenceStore(source / 'evidence-chain.jsonl', anchor_stream=io.StringIO()).genesis(
        sealed_predecessors=[{'path': str(old), 'sha256': hashlib.sha256(b'other').hexdigest()}])
    with pytest.raises(ValueError, match='differs from genesis'):
        snapshot(source, tmp_path / 'bad-backup')
    outside = tmp_path / 'other.jsonl'
    outside.write_text('outside\n')
    other = tmp_path / 'other-live'
    other.mkdir()
    EvidenceStore(other / 'evidence-chain.jsonl', anchor_stream=io.StringIO()).genesis(
        sealed_predecessors=[{'path': str(outside), 'unreadable': 'PermissionError'}])
    with pytest.raises(ValueError, match='outside allowed'):
        snapshot(other, tmp_path / 'outside-backup')


def test_previously_unreadable_legacy_file_is_captured_without_historical_attestation(tmp_path):
    source = tmp_path / 'live'
    source.mkdir()
    old = source / 'legacy.jsonl'
    old.write_text('unattested old bytes\n')
    EvidenceStore(source / 'evidence-chain.jsonl', anchor_stream=io.StringIO()).genesis(
        sealed_predecessors=[{'path': str(old), 'unreadable': 'PermissionError'}])
    manifest = snapshot(source, tmp_path / 'backup')
    assert manifest['legacy_attachments'][0]['genesis_attested'] is False
    result = restore(tmp_path / 'backup', tmp_path / 'restored')
    assert result['legacy_attachments'] == 1 and result['genesis_attested_legacy_attachments'] == 0
