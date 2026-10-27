"""Washer descriptor: readings mapped, writes held back.

The washer's resource map was measured; none of its writes has been. So
the class ships with WRITES_ENABLED off, and these tests pin what that
has to mean on the wire: no command reaches the appliance, the settings
still show in HA, and a button or select left retained by a writable
build is cleared rather than left pointing at a dead command topic.
"""
import json

import pytest

from mqtt_demo.samples import get_descriptor
from mqtt_demo.samples import washer


def _discovery(writes):
    old = washer.WRITES_ENABLED
    washer.WRITES_ENABLED = writes
    try:
        return dict(washer.build_discovery('wm', 'homeassistant', 'Washer'))
    finally:
        washer.WRITES_ENABLED = old


def test_registered():
    assert get_descriptor('washer') is washer.WASHER


def test_writes_off_by_default():
    assert washer.WRITES_ENABLED is False
    assert washer.WASHER.command_handlers({}) == {}


def test_read_only_discovery_retires_controls():
    disc = _discovery(writes=False)
    for key in ('start', 'pause', 'stop'):
        assert disc[f'homeassistant/button/wm/{key}/config'] == b''
    for key in ('water_temperature', 'spin_level', 'rinse_cycles'):
        assert disc[f'homeassistant/select/wm/{key}/config'] == b''
        cfg = json.loads(disc[f'homeassistant/sensor/wm/{key}/config'])
        assert 'command_topic' not in cfg
    assert not any(b'command_topic' in v for v in disc.values())


def test_writable_discovery_retires_setting_sensors():
    disc = _discovery(writes=True)
    for key in ('water_temperature', 'spin_level', 'rinse_cycles'):
        assert disc[f'homeassistant/sensor/wm/{key}/config'] == b''
        assert disc[f'homeassistant/select/wm/{key}/config'] != b''


def test_flatten():
    s = washer.flatten({
        '/operational/state/vs/0': {'x.com.samsung.da.state': 'Run',
                                    'x.com.samsung.da.remainingTime': '01:05:30'},
        '/energy/consumption/vs/0': {'x.com.samsung.da.instantaneousPower': '-500',
                                     'x.com.samsung.da.cumulativePower': '123456'},
        '/water/consumption/vs/0': {'x.com.samsung.da.cumulativeWater': '2654100'},
        '/washer/vs/0': {'x.com.samsung.da.spinLevel': '1200'},
    })
    assert s['machine_state'] == 'active'
    assert s['completion_minutes'] == 66
    assert s['power_watts'] == 0.0
    assert s['energy_kwh'] == pytest.approx(123.46)
    assert s['water_liters'] == pytest.approx(2654.1)
    assert s['spin_level'] == '1200'
    assert washer.flatten({})['job_state'] == 'Idle'
