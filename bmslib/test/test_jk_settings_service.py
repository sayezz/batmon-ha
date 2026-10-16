"""JkSettingsService: queue, validation, write, backup/audit, against a JKBt wired to JKDummy."""

import asyncio
import json
import os

from bmslib.jk_settings_service import JkSettingsService, NullSettingsPublisher, build_settings_service
from bmslib.models.dummy import JKDummy
from bmslib.models.jikong import JKBt

FIXTURE = os.path.join(os.path.dirname(__file__), 'data', 'jk_settings_b2a8s30p_fw15.26.bin')
T0 = 1_800_000_000.0  # 2027-01-15T08:00:00Z


def _fixture():
    with open(FIXTURE, 'rb') as f:
        return f.read()


def _make(ignore_writes=False):
    bms = JKBt("00:11:22:33:44:55", name="jk1")
    client = JKDummy(is_new_11x=True, settings_frame=_fixture(), ignore_writes=ignore_writes, stream=False)
    bms.client = client
    bms.char_handle_write = JKBt.CHAR_UUID
    bms.is_new_11fw_32s = True
    bms.settings_protocol_confirmed = True
    asyncio.run(client.start_notify(JKBt.CHAR_UUID, bms._notification_handler))
    return bms, client


class FakePublish:
    def __init__(self):
        self.calls = []

    def states(self, settings):
        self.calls.append(('states', dict(settings)))

    def last_change(self, text):
        self.calls.append(('last_change', text))

    @property
    def texts(self):
        return [c[1] for c in self.calls if c[0] == 'last_change']

    @property
    def states_calls(self):
        return [c[1] for c in self.calls if c[0] == 'states']


def _service(tmp_path, writable=frozenset(), **kw):
    kw.setdefault('clock', lambda: T0)
    return JkSettingsService('jk1', frozenset(writable), workdir=str(tmp_path), **kw)


def _tick(svc, bms, pub):
    asyncio.run(svc.tick(bms, pub))


def test_tick_loads_and_publishes_states(tmp_path):
    bms, _ = _make()
    svc, pub = _service(tmp_path), FakePublish()
    _tick(svc, bms, pub)
    assert len(pub.states_calls) == 1
    assert pub.states_calls[0]['charge_utp'] == 2.0
    assert pub.texts == []
    # not refreshed again inside the refresh period
    _tick(svc, bms, pub)
    assert len(pub.states_calls) == 1


def test_periodic_refresh(tmp_path):
    bms, _ = _make()
    now = [T0]
    svc, pub = _service(tmp_path, clock=lambda: now[0], refresh_period=300), FakePublish()
    _tick(svc, bms, pub)
    now[0] += 299
    _tick(svc, bms, pub)
    assert len(pub.states_calls) == 1
    now[0] += 1
    _tick(svc, bms, pub)
    assert len(pub.states_calls) == 2


def test_not_whitelisted_rejected(tmp_path):
    bms, client = _make()
    svc, pub = _service(tmp_path, writable=frozenset()), FakePublish()
    svc.enqueue('cell_uvp', '2.7')
    _tick(svc, bms, pub)
    assert client.writes == []
    assert pub.texts[-1].startswith('Rejected cell_uvp 2.7: ')
    assert 'not writable' in pub.texts[-1]
    assert pub.calls[-2][0] == 'states'  # field snapped back


def test_garbage_payload_rejected(tmp_path):
    bms, client = _make()
    svc = _service(tmp_path, writable={'cell_uvp', 'display_always_on'})
    for name, payload in [('cell_uvp', '2,65'), ('cell_uvp', 'abc'), ('cell_uvp', ''),
                          ('cell_uvp', 'nan'), ('display_always_on', 'maybe')]:
        pub = FakePublish()
        svc.enqueue(name, payload)
        _tick(svc, bms, pub)
        assert client.writes == [], payload
        assert pub.texts[-1].startswith('Rejected %s %s:' % (name, payload.strip())), pub.texts
        assert pub.calls[-2][0] == 'states'
        assert pub.calls[-2][1]['cell_uvp'] == 2.65


def test_same_value_unchanged(tmp_path):
    bms, client = _make()
    svc, pub = _service(tmp_path, writable={'cell_uvp', 'display_always_on'}), FakePublish()
    svc.enqueue('cell_uvp', '2.6504')
    svc.enqueue('display_always_on', 'off')
    _tick(svc, bms, pub)
    assert client.writes == []
    assert pub.texts == ['Unchanged cell_uvp 2.65V', 'Unchanged display_always_on OFF']
    assert not os.path.exists(tmp_path / 'settings_backup')


def test_ordered_dependent_changes(tmp_path):
    bms, client = _make()
    svc, pub = _service(tmp_path, writable={'charge_utp', 'charge_utpr'}), FakePublish()
    svc.enqueue('charge_utpr', '7')
    svc.enqueue('charge_utp', '6')
    _tick(svc, bms, pub)
    assert pub.texts == ['OK charge_utpr 5 -> 7°C', 'OK charge_utp 2 -> 6°C']
    assert bms.settings['charge_utpr'] == 7.0
    assert bms.settings['charge_utp'] == 6.0
    assert [reg for reg, _ in client.writes] == [0x19, 0x18]
    assert pub.states_calls[-1]['charge_utp'] == 6.0


def test_cross_field_rejected_message(tmp_path):
    bms, client = _make()
    svc, pub = _service(tmp_path, writable={'charge_utp'}), FakePublish()
    svc.enqueue('charge_utp', '6')
    _tick(svc, bms, pub)
    assert client.writes == []
    text = pub.texts[-1]
    assert text.startswith('Rejected charge_utp 6: ')
    assert 'charge_utpr' in text and text.endswith('first')


def test_out_of_range_rejected(tmp_path):
    bms, client = _make()
    svc, pub = _service(tmp_path, writable={'cell_uvp'}), FakePublish()
    svc.enqueue('cell_uvp', '9')
    _tick(svc, bms, pub)
    assert client.writes == []
    assert pub.texts[-1].startswith('Rejected cell_uvp 9: ') and 'out of range' in pub.texts[-1]


def test_backup_once_and_audit(tmp_path):
    bms, _ = _make()
    svc, pub = _service(tmp_path, writable={'charge_utp', 'display_always_on'}), FakePublish()
    svc.enqueue('charge_utp', '3')
    svc.enqueue('display_always_on', 'ON')
    _tick(svc, bms, pub)
    assert pub.texts == ['OK charge_utp 2 -> 3°C', 'OK display_always_on OFF -> ON']

    backups = os.listdir(tmp_path / 'settings_backup')
    assert backups == ['jk1-20270115T080000Z.json']
    with open(tmp_path / 'settings_backup' / backups[0]) as f:
        backup = json.load(f)
    assert set(backup) == {'alias', 'time', 'settings', 'raw_hex'}
    assert backup['alias'] == 'jk1'
    assert backup['settings']['charge_utp'] == 2.0  # state before the first write
    assert len(backup['raw_hex']) == 600
    assert bytes.fromhex(backup['raw_hex']) == _fixture()

    with open(tmp_path / 'settings_audit.jsonl') as f:
        lines = [json.loads(l) for l in f]
    assert len(lines) == 2
    for line in lines:
        assert set(line) == {'time', 'alias', 'name', 'before', 'requested', 'after', 'ok', 'reason', 'source'}
        assert line['source'] == 'mqtt' and line['ok'] is True and line['alias'] == 'jk1'
    assert (lines[0]['name'], lines[0]['before'], lines[0]['requested'], lines[0]['after']) == \
           ('charge_utp', 2.0, 3.0, 3.0)
    assert (lines[1]['name'], lines[1]['before'], lines[1]['after']) == ('display_always_on', False, True)


def test_mismatch_locks(tmp_path):
    bms, client = _make(ignore_writes=True)
    svc, pub = _service(tmp_path, writable={'charge_utp'}), FakePublish()
    svc.enqueue('charge_utp', '3')
    _tick(svc, bms, pub)
    assert pub.texts[-1] == 'FAILED charge_utp 3 read back 2; writes locked'
    svc.enqueue('charge_utp', '4')
    _tick(svc, bms, pub)
    assert pub.texts[-1] == 'Rejected charge_utp 4: writes locked after a failed read-back; restart batmon'
    assert len(client.writes) == 1
    with open(tmp_path / 'settings_audit.jsonl') as f:
        lines = [json.loads(l) for l in f]
    assert len(lines) == 1 and lines[0]['ok'] is False and 'read-back' in lines[0]['reason']


def test_other_setting_changed_locks(tmp_path):
    bms, client = _make()
    client.misroute = {0x18: 'charge_utpr'}
    svc, pub = _service(tmp_path, writable={'charge_utp'}), FakePublish()
    svc.enqueue('charge_utp', '3')
    _tick(svc, bms, pub)
    assert svc.locked is True
    assert pub.texts[-1] == ('FAILED charge_utp 3 read back 2; also changed: charge_utpr 5 -> 3°C; '
                             'writes locked')
    with open(tmp_path / 'settings_audit.jsonl') as f:
        line = json.loads(f.readline())
    assert line['ok'] is False and 'charge_utpr 5 -> 3°C' in line['reason']


def test_queue_limit(tmp_path):
    bms, _ = _make()
    svc, pub = _service(tmp_path), FakePublish()
    for i in range(21):
        svc.enqueue('cell_uvp', '2.%d' % (60 + i))
    _tick(svc, bms, pub)
    full = [t for t in pub.texts if t.endswith('queue full')]
    assert full == ['Rejected cell_uvp 2.80: queue full']
    assert len(pub.texts) == 21  # 20 processed (not whitelisted) + 1 dropped


def test_ble_error_propagates_and_keeps_queue(tmp_path):
    bms, client = _make()
    svc, pub = _service(tmp_path, writable={'charge_utp', 'charge_utpr'}), FakePublish()
    _tick(svc, bms, pub)

    async def broken(*a, **kw):
        raise OSError('link lost')

    orig = bms.write_setting
    bms.write_setting = broken
    svc.enqueue('charge_utp', '3')
    svc.enqueue('charge_utpr', '6')
    try:
        _tick(svc, bms, pub)
        assert False, 'BLE error must propagate'
    except OSError:
        pass
    assert pub.texts[-1] == 'Rejected charge_utp 3: BLE error: link lost'
    with open(tmp_path / 'settings_audit.jsonl') as f:
        lines = [json.loads(l) for l in f]
    assert lines[-1]['ok'] is False and lines[-1]['name'] == 'charge_utp'

    bms.write_setting = orig
    _tick(svc, bms, pub)  # the second request stayed queued
    assert pub.texts[-1] == 'OK charge_utpr 5 -> 6°C'


def test_refresh_failure_backs_off(tmp_path):
    bms, client = _make()
    now = [T0]
    svc = _service(tmp_path, writable={'charge_utp'}, clock=lambda: now[0], refresh_retry_s=60)
    pub = FakePublish()
    calls = []
    orig = bms.refresh_settings

    async def broken():
        calls.append(now[0])
        raise TimeoutError('no settings frame')

    bms.refresh_settings = broken
    svc.enqueue('charge_utp', '3')
    try:
        _tick(svc, bms, pub)
        assert False, 'refresh error must propagate'
    except TimeoutError:
        pass
    assert len(calls) == 1

    now[0] += 59  # inside the backoff window: no refresh, no raise, request stays queued
    _tick(svc, bms, pub)
    assert len(calls) == 1
    assert pub.calls == [] and client.writes == []

    now[0] += 1  # window over: tries again
    try:
        _tick(svc, bms, pub)
        assert False, 'refresh error must propagate'
    except TimeoutError:
        pass
    assert len(calls) == 2

    bms.refresh_settings = orig  # link recovers: the queued request is handled
    now[0] += 60
    _tick(svc, bms, pub)
    assert pub.texts == ['OK charge_utp 2 -> 3°C']


def test_audit_failure_still_locks_and_reports(tmp_path, monkeypatch):
    bms, client = _make(ignore_writes=True)
    svc, pub = _service(tmp_path, writable={'charge_utp'}), FakePublish()
    import builtins
    real_open = builtins.open

    def failing_open(path, *a, **kw):
        if str(path).endswith('settings_audit.jsonl'):
            raise OSError(28, 'No space left on device')
        return real_open(path, *a, **kw)

    monkeypatch.setattr(builtins, 'open', failing_open)
    svc.enqueue('charge_utp', '3')
    _tick(svc, bms, pub)
    assert svc.locked is True
    assert pub.texts[-1] == 'FAILED charge_utp 3 read back 2; writes locked'
    svc.enqueue('charge_utp', '4')
    _tick(svc, bms, pub)
    assert pub.texts[-1].endswith('writes locked after a failed read-back; restart batmon')
    assert len(client.writes) == 1


def test_no_settings_support_noop(tmp_path):
    bms, client = _make()
    bms.settings_protocol_confirmed = False
    svc, pub = _service(tmp_path, writable={'charge_utp'}), FakePublish()
    svc.enqueue('charge_utp', '3')
    _tick(svc, bms, pub)
    assert pub.calls == []
    assert bms.settings is None
    assert client.writes == []


def test_null_publisher():
    p = NullSettingsPublisher()
    p.states({'a': 1})
    p.last_change('x')


def test_build_service(tmp_path):
    bms, _ = _make()
    assert build_settings_service(bms, {'jk_settings': False}, {'settings_write': 'all'}, str(tmp_path)) is None
    assert build_settings_service(bms, {}, {'settings_write': 'all'}, str(tmp_path)) is None
    assert build_settings_service(object(), {'jk_settings': True}, {}, str(tmp_path)) is None

    svc = build_settings_service(bms, {'jk_settings': True}, {'settings_write': 'charge_utp'}, str(tmp_path))
    assert isinstance(svc, JkSettingsService)
    assert svc.writable == frozenset({'charge_utp'})
    assert svc.alias == 'jk1'


def test_build_service_config_error(tmp_path, caplog):
    bms, client = _make()
    svc = build_settings_service(bms, {'jk_settings': True}, {'settings_write': 'charge_utp,bogus'},
                                 str(tmp_path))
    assert svc is not None and svc.writable == frozenset()
    assert any('jk1' in r.getMessage() and 'bogus' in r.getMessage() and r.levelname == 'ERROR'
               for r in caplog.records)
    pub = FakePublish()
    svc.enqueue('charge_utp', '3')
    asyncio.run(svc.tick(bms, pub))
    assert pub.texts[0].startswith('Config error: ') and 'bogus' in pub.texts[0]
    assert pub.texts[1].startswith('Rejected charge_utp 3:')
    assert client.writes == []
