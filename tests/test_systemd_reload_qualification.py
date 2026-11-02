from evaluations.qualify_systemd_reload import assess, window
import pytest


def test_kernel_generator_warning_fails_even_with_clean_pid1():
    records = [{'_PID': '1', 'MESSAGE': 'Reload requested from client PID 9 (systemctl)'},
               {'_PID': '1', 'MESSAGE': 'Reloading finished in 378 ms.'},
               {'_TRANSPORT': 'kernel', 'SYSLOG_IDENTIFIER': 'kernel',
                'MESSAGE': 'systemd-sysv-generator[99]: ! This compatibility logic is deprecated, expect removal soon. !'}]
    result = assess(records, 1)
    assert not result['passed'] and len(result['obsolete_diagnostics']) == 1
    assert result['obsolete_diagnostics'][0]['_TRANSPORT'] == 'kernel'


def test_no_reload_window_and_explicit_change_window():
    assert not assess([])['passed']
    assert assess([{'MESSAGE': 'ordinary information'}])['passed']
    pair = [{'_PID': '1', 'MESSAGE': 'Reload requested from client PID 4'},
            {'_PID': '1', 'MESSAGE': 'Reloading finished in 1 ms.'}]
    assert assess(pair, 1)['passed']
    assert not assess(pair, 0)['passed']
    assert not assess(pair[:1], 1)['passed']


def test_package_and_application_deprecations_are_not_hidden():
    messages = ['Support for option CPUAccounting= has been removed and it is ignored',
                'DeprecationWarning: obsolete API', "Unknown key 'Example' in section Service"]
    result = assess([{'MESSAGE': m} for m in messages])
    assert not result['passed'] and len(result['obsolete_diagnostics']) == 3


def test_audit_command_text_does_not_become_a_fake_diagnostic():
    assert assess([{'SYSLOG_IDENTIFIER': 'sudo', 'MESSAGE': 'COMMAND=journalctl --grep deprecated'}])['passed']
    assert not assess([{'SYSLOG_IDENTIFIER': 'sudo', 'MESSAGE': 'Deprecated configuration option'}])['passed']
    assert not assess([{'_TRANSPORT': 'audit', 'MESSAGE': 'Deprecated configuration option'}])['passed']


@pytest.mark.parametrize('since,until', [('2026-10-31T00:00:00','2026-10-31T00:01:00'),
    ('2026-10-31T00:00:00Z','2026-10-31T02:00:00Z'), ('2026-10-31T00:01:00Z','2026-10-31T00:00:00Z')])
def test_rejects_ambiguous_or_unbounded_windows(since, until):
    with pytest.raises(ValueError):window(since, until)
