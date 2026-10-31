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
