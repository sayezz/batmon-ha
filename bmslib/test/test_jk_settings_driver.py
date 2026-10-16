"""JKBt settings driver: refresh_settings / write_setting with read-back, against JKDummy."""

import asyncio
import os

from bmslib.bms import DeviceInfo
from bmslib.models.dummy import JKDummy
from bmslib.models.jikong import JKBt, JKBt_24s, JKBt_32s, WriteResult, calc_crc
from bmslib.models.jk_pb_uart import JkPbUart
from bmslib.models.jk_settings import decode_settings

FIXTURE = os.path.join(os.path.dirname(__file__), 'data', 'jk_settings_b2a8s30p_fw15.26.bin')


def _fixture():
    with open(FIXTURE, 'rb') as f:
        return f.read()


def _make(ignore_writes=False):
    bms = JKBt("00:11:22:33:44:55", name="jk")
    client = JKDummy(is_new_11x=True, settings_frame=_fixture(), ignore_writes=ignore_writes, stream=False)
    bms.client = client
    bms.char_handle_write = JKBt.CHAR_UUID
    bms.is_new_11fw_32s = True
    bms.settings_protocol_confirmed = True
    asyncio.run(client.start_notify(JKBt.CHAR_UUID, bms._notification_handler))
    return bms, client


def test_settings_initialised_to_none():
    bms = JKBt("00:11:22:33:44:55", name="jk")
    assert bms.settings is None


def test_refresh_settings_decodes():
    bms, _ = _make()
    settings = asyncio.run(bms.refresh_settings())
    assert settings['max_charge_current'] == 140.0
    assert settings['charge_utp'] == 2.0
    assert bms.settings == settings
    assert bms.settings_raw == _fixture()


def test_write_setting_ok():
    bms, client = _make()
    res = asyncio.run(bms.write_setting('charge_utp', 3.0))
    assert isinstance(res, WriteResult)
    assert res.ok, res.reason
    assert (res.name, res.before, res.requested, res.after) == ('charge_utp', 2.0, 3.0, 3.0)
    assert [reg for reg, _ in client.writes] == [0x18]
    assert bms.settings['charge_utp'] == 3.0
    # the dummy's patched frame is still a valid settings frame
    frame = client.settings_frame
    assert calc_crc(frame[:-1]) == frame[-1]
    assert decode_settings(frame)['charge_utp'] == 3.0
    assert decode_settings(frame)['charge_utpr'] == 5.0  # neighbours untouched


def test_write_switch_ok():
    bms, client = _make()
    before = asyncio.run(bms.refresh_settings())['display_always_on']
    res = asyncio.run(bms.write_setting('display_always_on', not before))
    assert res.ok, res.reason
    assert (res.before, res.after) == (before, not before)


def test_write_setting_mismatch():
    bms, client = _make(ignore_writes=True)
    res = asyncio.run(bms.write_setting('charge_utp', 3.0))
    assert res.ok is False
    assert res.after == res.before == 2.0
    assert 'read-back' in res.reason
    assert [reg for reg, _ in client.writes] == [0x18]


def test_write_landing_on_another_setting_fails():
    bms, client = _make()
    client.misroute = {0x18: 'charge_utpr'}  # charge_utp's register writes charge_utpr
    res = asyncio.run(bms.write_setting('charge_utp', 3.0))
    assert res.ok is False
    assert 'charge_utpr 5 -> 3°C' in res.reason, res.reason
    assert res.others == {'charge_utpr': (5.0, 3.0)}


def test_write_with_a_side_effect_fails_even_if_the_target_matches():
    bms, client = _make()
    apply = client._apply_write

    def apply_and_flip(setting, payload):
        apply(setting, payload)
        client._settings[282] ^= 0x10  # display_always_on toggles as well
        client._settings[-1] = calc_crc(client._settings[:-1])

    client._apply_write = apply_and_flip
    res = asyncio.run(bms.write_setting('charge_utp', 3.0))
    assert res.after == 3.0
    assert res.ok is False
    assert 'display_always_on OFF -> ON' in res.reason, res.reason
    assert 'read-back' not in res.reason


def test_ok_write_reports_no_other_changes():
    bms, _ = _make()
    res = asyncio.run(bms.write_setting('charge_utp', 3.0))
    assert res.ok and res.others == {}


def test_connect_count_counts_completed_connects(monkeypatch):
    from bmslib.bt import BtBms

    async def link_up(self, timeout=20):
        pass

    monkeypatch.setattr(BtBms, 'connect', link_up)  # no Bluetooth; JKBt.connect does the rest
    bms = JKBt("00:11:22:33:44:55", name="jk")
    client = bms.client = JKDummy(is_new_11x=True, settings_frame=_fixture(), stream=False)
    write = client.write_gatt_char

    async def write_and_stream_once(char, data, response=False):
        await write(char, data, response)
        if bytes(data[:5]) == b'\xaaU\x90\xeb\x96':  # connect waits for a status frame too
            client._callbacks[JKBt.CHAR_UUID](client, client.MSGS[1])

    client.write_gatt_char = write_and_stream_once
    assert bms.connect_count == 0
    asyncio.run(bms.connect())
    assert bms.connect_count == 1
    asyncio.run(bms.connect())
    assert bms.connect_count == 2

    async def no_answer(cmd, resp):
        raise TimeoutError('no device info')

    bms._q = no_answer  # connect fails half-way: not counted
    try:
        asyncio.run(bms.connect())
    except TimeoutError:
        pass
    assert bms.connect_count == 2


def _fetch_with_fw(sw_version):
    """JKBt.fetch() with firmware detection answering `sw_version` (None: detection fails)."""
    bms = JKBt("00:11:22:33:44:55", name="jk")
    client = JKDummy(is_new_11x=True, settings_frame=_fixture(), stream=False)
    bms.client = client
    bms.char_handle_write = JKBt.CHAR_UUID
    asyncio.run(client.start_notify(JKBt.CHAR_UUID, bms._notification_handler))
    asyncio.run(bms._q(cmd=0x96, resp=0x01))
    bms._notification_handler(None, client.MSGS[1])  # one status frame
    bms._has_float_charger = False

    async def device_info():
        if sw_version is None:
            raise TimeoutError('no device info')
        return DeviceInfo(mnf='JK', model='JK-B2A8S30P', hw_version='15A', sw_version=sw_version, name='jk')

    bms.fetch_device_info = device_info
    asyncio.run(bms.fetch(wait=False))
    return bms


def test_supports_settings_unknown_firmware():
    bms = JKBt("00:11:22:33:44:55", name="jk")
    assert bms.supports_settings() is False
    # detection failed: _decode_sample falls back to the 32S layout for sampling,
    # but that guess must not enable settings writes (24S registers mean other things)
    bms = _fetch_with_fw(None)
    assert bms.is_new_11fw_32s is True
    assert bms.supports_settings() is False


def test_supports_settings_detected_firmware():
    assert _fetch_with_fw('15.26').supports_settings() is True
    assert _fetch_with_fw('10.02').supports_settings() is False


def test_supports_settings_forced_type():
    assert JKBt_32s("00:11:22:33:44:55", name="jk").supports_settings() is True
    assert JKBt_24s("00:11:22:33:44:55", name="jk").supports_settings() is False


def test_supports_settings():
    bms = JKBt("00:11:22:33:44:55", name="jk")
    assert bms.supports_settings() is False  # unknown firmware
    bms.is_new_11fw_32s = True  # e.g. the _decode_sample fallback: not enough
    assert bms.supports_settings() is False
    bms.settings_protocol_confirmed = True
    assert bms.supports_settings() is True
    # constructing a real JkPbUart opens a serial wrapper; the answer must not depend on state
    pb = JkPbUart.__new__(JkPbUart)
    pb.is_new_11fw_32s = True  # PB is always 32s, still no settings writes over RS485
    assert pb.supports_settings() is False
