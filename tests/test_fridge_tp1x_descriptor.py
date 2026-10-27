"""TP1X fridge descriptor: readings mapped, writes held back.

Same arrangement as the washer (see test_washer_descriptor.py): the
resource map was measured, the writes were not, so WRITES_ENABLED ships
off and these tests pin what that means on the wire.
"""
import json

import pytest

from mqtt_demo.samples import get_descriptor
from mqtt_demo.samples import fridge_tp1x as ref


def _discovery(writes):
    old = ref.WRITES_ENABLED
    ref.WRITES_ENABLED = writes
    try:
        return dict(ref.build_discovery('rf', 'homeassistant', 'Fridge'))
    finally:
        ref.WRITES_ENABLED = old


def test_registered_separately_from_fridge():
    assert get_descriptor('fridge_tp1x') is ref.FRIDGE_TP1X
    assert get_descriptor('fridge') is not ref.FRIDGE_TP1X


def test_writes_off_by_default():
    assert ref.WRITES_ENABLED is False
    assert ref.FRIDGE_TP1X.command_handlers({}) == {}


def test_read_only_discovery_retires_controls():
    disc = _discovery(writes=False)
    for key in ('rapid_fridge', 'rapid_freezing', 'ice_maker'):
        assert disc[f'homeassistant/switch/rf/{key}/config'] == b''
    for key in ('fridge_temp', 'freezer_temp'):
        assert disc[f'homeassistant/number/rf/{key}/config'] == b''
    for key in ('fridge_target_c', 'freezer_target_c', 'rapid_fridge'):
        cfg = json.loads(disc[f'homeassistant/sensor/rf/{key}/config'])
        assert 'command_topic' not in cfg
    assert not any(b'command_topic' in v for v in disc.values())


def test_writable_discovery_retires_setting_sensors():
    disc = _discovery(writes=True)
    assert disc['homeassistant/sensor/rf/fridge_target_c/config'] == b''
    assert disc['homeassistant/number/rf/fridge_temp/config'] != b''


def test_flatten():
    s = ref.flatten({
        '/temperature/current/cooler/0': {'temperature': 4.0},
        '/temperatures/vs/0': {'x.com.samsung.da.items': [
            {'x.com.samsung.da.description': 'Freezer',
             'x.com.samsung.da.current': '-18', 'x.com.samsung.da.desired': '-19'},
        ]},
        '/door/cooler/0': {'openState': 'Closed'},
        '/door/freezer/0': {'openState': 'Open'},
        '/energy/consumption/vs/0': {'x.com.samsung.da.cumulativePower': '250000'},
    })
    assert s['fridge_temp_c'] == 4.0
    assert s['freezer_temp_c'] == -18.0
    assert s['freezer_target_c'] == -19
    assert s['any_door_open'] is True
    assert s['energy_kwh'] == pytest.approx(250.0)
    assert ref.flatten({})['any_door_open'] is None
