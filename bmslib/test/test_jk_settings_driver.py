"""JKBt settings driver: refresh_settings / write_setting with read-back, against JKDummy."""

import asyncio
import os

from bmslib.models.dummy import JKDummy
from bmslib.models.jikong import JKBt, WriteResult, calc_crc
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


def test_supports_settings():
    bms = JKBt("00:11:22:33:44:55", name="jk")
    assert bms.supports_settings() is False  # unknown firmware
    bms.is_new_11fw_32s = False
    assert bms.supports_settings() is False
    bms.is_new_11fw_32s = True
    assert bms.supports_settings() is True
    # constructing a real JkPbUart opens a serial wrapper; the answer must not depend on state
    pb = JkPbUart.__new__(JkPbUart)
    pb.is_new_11fw_32s = True  # PB is always 32s, still no settings writes over RS485
    assert pb.supports_settings() is False
