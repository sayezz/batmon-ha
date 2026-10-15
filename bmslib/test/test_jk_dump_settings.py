"""tools/jk_dump_settings.py: settings-frame sanity check and read-only guarantee."""

import pathlib

import pytest

from bmslib.models.dummy import JKDummy
from bmslib.models.jikong import calc_crc
from tools.jk_dump_settings import check_settings_frame

TOOL_SRC = pathlib.Path(__file__).resolve().parents[2] / 'tools' / 'jk_dump_settings.py'


def _valid_frame() -> bytes:
    # JKDummy's 0x01 message is the 300-byte frame followed by a 20-byte command echo
    frame = bytes(JKDummy(is_new_11x=True).MSGS[0][:300])
    assert len(frame) == 300 and calc_crc(frame[:-1]) == frame[-1]
    return frame


def _with_crc(body: bytes) -> bytes:
    return body + bytes([calc_crc(body)])


def test_valid_frame_passes():
    check_settings_frame(_valid_frame())


def test_wrong_header_rejected():
    f = _valid_frame()
    bad = _with_crc(bytes([0x55, 0xAA, 0xEB, 0x90, 0x02]) + f[5:299])  # 0x02 = cell data, not settings
    with pytest.raises(ValueError, match='header'):
        check_settings_frame(bad)


@pytest.mark.parametrize('n', [0, 299, 301, 320])
def test_wrong_length_rejected(n):
    f = _valid_frame()
    body = (f[:299] + bytes(n))[:max(n - 1, 0)]
    bad = _with_crc(body) if n else b''
    assert len(bad) == n
    with pytest.raises(ValueError, match='length'):
        check_settings_frame(bad)


def test_bad_crc_rejected():
    f = bytearray(_valid_frame())
    f[-1] = (f[-1] + 1) & 0xFF
    with pytest.raises(ValueError, match='CRC'):
        check_settings_frame(bytes(f))


def test_tool_never_writes_to_bms():
    src = TOOL_SRC.read_text()
    for forbidden in ('_write', 'set_switch', 'set_soc'):
        assert forbidden not in src, forbidden
