"""Washer descriptor (Samsung WW11DB7B34GWU3-class, DA_WM_TP1_21).

Resource map captured 2026-07-02 with capture_resources.py — same
DA_WM_TP1_21 platform as the dryer, so state/power/lock/remote/energy
handling mirrors dryer.py. Washer-specific surfaces: water temperature,
spin level and rinse cycles on /washer/vs/0 (each with a supported*
list), cumulative water on /water/consumption/vs/0, and the course on
/st/washercourse/vs/0.

Course names: this washer reports Table_02, for which no code→name
mapping has been captured yet (the dryer's Table_03 mapping came from
dialing every course by hand). Until someone does the same here, the
course is surfaced as the raw code, e.g. `Table_02_Course_1C`.

Read-only for now: see WRITES_ENABLED.
"""
import time

from ..descriptor import (
    ApplianceDescriptor,
    avail_base,
    avail_with_remote,
    device_block,
    encode,
)
from smartthings_local.ocf.poll_scheduler import PollTier


# --- Writes ------------------------------------------------------------
# The resource map above is a measurement; the writes below are not. No
# Start/Pause/Stop or option write has been sent to this washer through
# this descriptor, and the Remote-Control gating is carried over from
# the dryer rather than observed here. Until a write has been measured,
# the descriptor publishes the settings as plain sensors, registers no
# command handlers, and retires any button/select a writable build left
# retained on the broker. Flip to True once the readings have been
# checked against the panel and a write has been tried by hand.
WRITES_ENABLED = False


# --- OBSERVE paths -----------------------------------------------------
# Only Samsung's `/<x>/vs/0` siblings actually push notifications; the
# OCF-standard `/<x>/0` paths accept registration silently but never
# fire.
OBSERVE_PATHS = [
    ['operational', 'state', 'vs', '0'],   # state, remainingTime, progress
    ['power',       'vs', '0'],
    ['kidslock',    'vs', '0'],
    ['remotectrl',  'vs', '0'],
    ['energy',      'consumption', 'vs', '0'],
    ['water',       'consumption', 'vs', '0'],
    ['course',      'vs', '0'],
    ['washer',      'vs', '0'],            # waterTemp, spinLevel, rinse
    ['diagnosis',   'vs', '0'],
    ['alarms',      'vs', '0'],
    ['st',          'washercourse', 'vs', '0'],
    ['wm',          'jobbeginingstatus', 'vs', '0'],
]


# --- Option tables -----------------------------------------------------
# supported* lists captured 2026-07-02 from a WW11DB7B34GWU3. Discovery
# payloads are built before the first device contact, so the HA select
# options have to be static; other models may support different values —
# recapture with capture_resources.py if a select shows options the
# machine refuses.
WATER_TEMPS  = ['None', 'Cold', '20', '30', '40', '60', '90']
SPIN_LEVELS  = ['RinseHold', 'NoSpin', '400', '800', '1000', '1200', '1400']
RINSE_CYCLES = ['0', '1', '2', '3', '4', '5']


# --- Samsung-state → OCF currentMachineState ---------------------------
_SAMSUNG_STATE_TO_OCF = {
    'Ready':   'idle',
    'Run':     'active',
    'Running': 'active',
    'Pause':   'pause',
    'Paused':  'pause',
    'End':     'idle',
}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# --- flatten -----------------------------------------------------------
def flatten(links):
    """Map a /device/0 link dict to the flat sensor dict that's
    published to MQTT. Every field reads from `/<x>/vs/0` paths so push
    updates immediately drive every entity."""
    g = lambda href, k, default=None: (links.get(href) or {}).get(k, default)

    inst_w = _num(g('/energy/consumption/vs/0',
                    'x.com.samsung.da.instantaneousPower'))
    cum_wh = _num(g('/energy/consumption/vs/0',
                    'x.com.samsung.da.cumulativePower'))
    if inst_w is not None and inst_w < 0:
        # Same phantom -500W idle reading as the dryer; HA energy
        # dashboard hates negatives.
        inst_w = 0.0

    # cumulativeWater is in millilitres (2654100 ≈ 2654L lifetime on a
    # 2-year-old machine — litres would be an ocean).
    cum_water_ml = _num(g('/water/consumption/vs/0',
                          'x.com.samsung.da.cumulativeWater'))

    sam_state = g('/operational/state/vs/0', 'x.com.samsung.da.state')
    machine_state = (_SAMSUNG_STATE_TO_OCF.get(sam_state, sam_state)
                     if sam_state is not None
                     else g('/operational/state/0', 'currentMachineState'))

    progress = g('/operational/state/vs/0', 'x.com.samsung.da.progress')
    job_state = progress or g('/operational/state/0', 'currentJobState')
    # HA's value_template treats the literal "None" as null (renders as
    # "Unknown"). Substitute something we can render verbatim.
    if job_state in (None, 'None'):
        job_state = 'Idle'
    if progress in (None, 'None'):
        progress = 'Idle'

    remaining = (g('/operational/state/vs/0',
                   'x.com.samsung.da.remainingTime')
                 or g('/operational/state/0', 'remainingTime'))
    rem_min = None
    if remaining:
        try:
            h, m, s = remaining.split(':')
            rem_min = int(h) * 60 + int(m) + (1 if int(s) > 0 else 0)
        except Exception:
            pass

    sam_power = g('/power/vs/0', 'x.com.samsung.da.power')
    sam_kids  = g('/kidslock/vs/0', 'x.com.samsung.da.kidsLock')
    sam_rc    = g('/remotectrl/vs/0',
                  'x.com.samsung.da.remoteControlEnabled')
    power_bin = (sam_power == 'On') if sam_power is not None else None
    kids_bin  = (sam_kids != 'Ready') if sam_kids is not None else None
    rc_bin    = (str(sam_rc).lower() == 'true') if sam_rc is not None else None

    return {
        'machine_state':         machine_state,
        'job_state':             job_state,
        'progress':              progress,
        'progress_percentage':   _int(g('/operational/state/vs/0',
                                        'x.com.samsung.da.progressPercentage')
                                       or g('/operational/state/0',
                                            'progressPercentage')),
        'completion_time':       remaining,
        'completion_minutes':    rem_min,
        'delay_end_time':        g('/operational/state/vs/0',
                                   'x.com.samsung.da.delayEndTime'),
        'power_state':           sam_power,
        'power_state_binary':    power_bin,
        'child_lock':            sam_kids,
        'child_lock_binary':     kids_bin,
        'remote_control':        sam_rc,
        'remote_control_binary': rc_bin,
        'power_watts':           inst_w,
        'energy_kwh':            round(cum_wh / 1000.0, 2)
                                    if cum_wh is not None else None,
        'energy_wh_cumulative':  int(cum_wh) if cum_wh is not None else None,
        'water_liters':          round(cum_water_ml / 1000.0, 1)
                                    if cum_water_ml is not None else None,
        'washer_course':         g('/st/washercourse/vs/0',
                                   'x.com.samsung.da.st.washerMode'),
        'water_temperature':     g('/washer/vs/0',
                                   'x.com.samsung.da.waterTemperature'),
        'spin_level':            g('/washer/vs/0',
                                   'x.com.samsung.da.spinLevel'),
        'rinse_cycles':          g('/washer/vs/0',
                                   'x.com.samsung.da.rinseCycles'),
        'job_begin_status':      g('/wm/jobbeginingstatus/vs/0',
                                   'x.com.samsung.da.currentStatus'),
        'diagnosis':             g('/diagnosis/vs/0',
                                   'x.com.samsung.da.diagnosisStart'),
        'country_code':          g('/configuration/vs/0',
                                   'x.com.samsung.da.countryCode'),
    }


# --- Remaining-time anchor + extrapolation ----------------------------
# Same firmware behaviour as the dryer: /operational/state/vs/0 pushes
# on state transitions but not on remainingTime ticks.

def on_observation(state, href, rep):
    if href != '/operational/state/vs/0':
        return
    rem = rep.get('x.com.samsung.da.remainingTime')
    if not isinstance(rem, str):
        return
    try:
        h, m, s = rem.split(':')
        state['remaining_anchor'] = (time.time(),
                                     int(h) * 3600 + int(m) * 60 + int(s))
    except (ValueError, AttributeError):
        pass


def project(state, sensors):
    anchor = state.get('remaining_anchor')
    if sensors.get('machine_state') != 'active' or anchor is None:
        return sensors
    ts, total = anchor
    remaining = max(0, int(total - (time.time() - ts)))
    h, rest = divmod(remaining, 3600)
    m, s = divmod(rest, 60)
    sensors = dict(sensors)
    sensors['completion_time'] = f"{h}:{m:02d}:{s:02d}"
    sensors['completion_minutes'] = h * 60 + m + (1 if s > 0 else 0)
    return sensors


# --- Log-line ----------------------------------------------------------
def log_state_change(sensors):
    return (f"machine={sensors.get('machine_state')} "
            f"power={sensors.get('power_watts')}W "
            f"energy={sensors.get('energy_kwh')}kWh")


# --- HA discovery ------------------------------------------------------
MODEL = 'OCF washer (TizenRT-iotivity)'

# (key, friendly name, extra-config-dict)
_SENSORS = [
    ('machine_state',       'Machine state',       {'icon': 'mdi:washing-machine'}),
    ('job_state',           'Job state',           {}),
    ('progress',            'Progress',            {}),
    ('progress_percentage', 'Progress percent',
        {'unit_of_measurement': '%', 'state_class': 'measurement'}),
    ('completion_time',     'Completion time',     {'icon': 'mdi:timer-sand'}),
    ('completion_minutes',  'Remaining minutes',
        {'unit_of_measurement': 'min', 'device_class': 'duration',
         'state_class': 'measurement'}),
    ('delay_end_time',      'Delay end time',      {'icon': 'mdi:timer'}),
    ('power_state',         'Power state',         {}),
    ('power_watts',         'Power',
        {'unit_of_measurement': 'W', 'device_class': 'power',
         'state_class': 'measurement'}),
    ('energy_kwh',          'Energy',
        {'unit_of_measurement': 'kWh', 'device_class': 'energy',
         'state_class': 'total_increasing'}),
    ('water_liters',        'Water',
        {'unit_of_measurement': 'L', 'device_class': 'water',
         'state_class': 'total_increasing'}),
    ('washer_course',       'Course',              {'icon': 'mdi:format-list-bulleted'}),
    ('job_begin_status',    'Job begin status',    {}),
    ('diagnosis',           'Diagnosis',           {}),
    ('country_code',        'Country code',        {}),
]

# The /washer/vs/0 settings as plain sensors, published in place of the
# selects while WRITES_ENABLED is off.
_SETTING_SENSORS = [
    ('water_temperature', 'Water temperature', {'icon': 'mdi:thermometer-water'}),
    ('spin_level',        'Spin level',        {'icon': 'mdi:rotate-right'}),
    ('rinse_cycles',      'Rinse cycles',      {'icon': 'mdi:water-sync'}),
]

# (key, friendly name, value_template, device_class)
_BINARY_SENSORS = [
    ('running', 'Running',
        "{{ 'ON' if value_json.machine_state == 'active' else 'OFF' }}",
        'running'),
    ('power_switch', 'Power switch',
        "{{ 'ON' if value_json.power_state_binary else 'OFF' }}",
        'power'),
    ('child_lock_active', 'Child lock',
        "{{ 'ON' if value_json.child_lock_binary else 'OFF' }}",
        'lock'),
    ('remote_control_enabled', 'Remote control',
        "{{ 'ON' if value_json.remote_control_binary else 'OFF' }}",
        'connectivity'),
]

# MQTT command-topic suffixes. The bridge subscribes to <prefix>/cmd/#
# and dispatches by suffix.
CMD_OPERATIONAL  = 'cmd/operational_state'
CMD_WATER_TEMP   = 'cmd/water_temperature'
CMD_SPIN_LEVEL   = 'cmd/spin_level'
CMD_RINSE_CYCLES = 'cmd/rinse_cycles'

# (key, friendly name, payload_press, icon)
_BUTTONS = [
    ('start', 'Start cycle', 'Run',   'mdi:play'),
    ('pause', 'Pause cycle', 'Pause', 'mdi:pause'),
    ('stop',  'Stop cycle',  'Ready', 'mdi:stop'),
]

# (key, friendly name, sensor key, command suffix, options, icon)
_SELECTS = [
    ('water_temperature', 'Water temperature', 'water_temperature',
     CMD_WATER_TEMP,   WATER_TEMPS,  'mdi:thermometer-water'),
    ('spin_level',        'Spin level',        'spin_level',
     CMD_SPIN_LEVEL,   SPIN_LEVELS,  'mdi:rotate-right'),
    ('rinse_cycles',      'Rinse cycles',      'rinse_cycles',
     CMD_RINSE_CYCLES, RINSE_CYCLES, 'mdi:water-sync'),
]


def _retire(ha_prefix, topic_prefix, platform, key):
    # An empty retained payload tells HA to remove the entity; without
    # it the broker keeps serving the old config forever.
    return (f"{ha_prefix}/{platform}/{topic_prefix}/{key}/config", b'')


def build_discovery(topic_prefix, ha_prefix, device_name):
    """Return list of (discovery_topic, payload_bytes) tuples ready to
    publish (retained) on MQTT connect."""
    state_topic   = f"{topic_prefix}/state"
    avail_topic   = f"{topic_prefix}/availability"
    remote_topic  = f"{topic_prefix}/remote_available"
    dev = device_block(topic_prefix, device_name, MODEL)
    out = []

    # read-only sensors
    sensors = _SENSORS if WRITES_ENABLED else _SENSORS + _SETTING_SENSORS
    for key, name, extra in sensors:
        cfg = {
            'name':           name,
            'unique_id':      f"{topic_prefix}_{key}",
            'object_id':      f"{topic_prefix}_{key}",
            'state_topic':    state_topic,
            'value_template': f"{{{{ value_json.{key} }}}}",
            'availability':   avail_base(avail_topic),
            'device':         dev,
        }
        cfg.update(extra)
        out.append((f"{ha_prefix}/sensor/{topic_prefix}/{key}/config",
                    encode(cfg)))

    for key, name, template, dclass in _BINARY_SENSORS:
        cfg = {
            'name':           name,
            'unique_id':      f"{topic_prefix}_{key}",
            'object_id':      f"{topic_prefix}_{key}",
            'state_topic':    state_topic,
            'value_template': template,
            'payload_on':     'ON',
            'payload_off':    'OFF',
            'device_class':   dclass,
            'availability':   avail_base(avail_topic),
            'device':         dev,
        }
        out.append((f"{ha_prefix}/binary_sensor/{topic_prefix}/{key}/config",
                    encode(cfg)))

    if not WRITES_ENABLED:
        for key, *_ in _BUTTONS:
            out.append(_retire(ha_prefix, topic_prefix, 'button', key))
        for key, *_ in _SELECTS:
            out.append(_retire(ha_prefix, topic_prefix, 'select', key))
        return out

    for key, *_ in _SETTING_SENSORS:
        out.append(_retire(ha_prefix, topic_prefix, 'sensor', key))

    # buttons: Start / Pause / Stop (gated on remote control)
    for key, name, payload_press, icon in _BUTTONS:
        cfg = {
            'name':              name,
            'unique_id':         f"{topic_prefix}_{key}",
            'object_id':         f"{topic_prefix}_{key}",
            'command_topic':     f"{topic_prefix}/{CMD_OPERATIONAL}",
            'payload_press':     payload_press,
            'icon':               icon,
            'availability':      avail_with_remote(avail_topic, remote_topic),
            'availability_mode': 'all',
            'device':            dev,
        }
        out.append((f"{ha_prefix}/button/{topic_prefix}/{key}/config",
                    encode(cfg)))

    # selects: water temp / spin / rinse (gated on remote control — the
    # dryer only honours option writes with RC enabled; assumed, not yet
    # measured, to hold here too)
    for key, name, sensor_key, cmd, options, icon in _SELECTS:
        cfg = {
            'name':              name,
            'unique_id':         f"{topic_prefix}_{key}_select",
            'object_id':         f"{topic_prefix}_{key}_select",
            'state_topic':       state_topic,
            'value_template':    f"{{{{ value_json.{sensor_key} }}}}",
            'command_topic':     f"{topic_prefix}/{cmd}",
            'options':           options,
            'icon':              icon,
            'availability':      avail_with_remote(avail_topic, remote_topic),
            'availability_mode': 'all',
            'device':            dev,
        }
        out.append((f"{ha_prefix}/select/{topic_prefix}/{key}/config",
                    encode(cfg)))

    return out


# --- MQTT command handlers --------------------------------------------
def command_handlers(state=None):
    """topic_suffix → fn(payload, links) → (path_segs, body_dict) | None.

    `None` means refuse the command (caller logs & drops). All washer
    handlers are single-field writes; validation is against the static
    option tables the selects were built from. `state` is accepted and
    ignored: this class keeps no cross-command state.

    Empty while WRITES_ENABLED is off, so the bridge drops every
    command topic as unknown."""
    if not WRITES_ENABLED:
        return {}

    def _operational(p, _links):
        if p not in ('Run', 'Pause', 'Ready'):
            return None
        return ['operational', 'state', 'vs', '0'], {'x.com.samsung.da.state': p}

    def _water_temp(p, _links):
        if p not in WATER_TEMPS:
            return None
        return ['washer', 'vs', '0'], {'x.com.samsung.da.waterTemperature': p}

    def _spin(p, _links):
        if p not in SPIN_LEVELS:
            return None
        return ['washer', 'vs', '0'], {'x.com.samsung.da.spinLevel': p}

    def _rinse(p, _links):
        if p not in RINSE_CYCLES:
            return None
        return ['washer', 'vs', '0'], {'x.com.samsung.da.rinseCycles': p}

    return {
        CMD_OPERATIONAL:  _operational,
        CMD_WATER_TEMP:   _water_temp,
        CMD_SPIN_LEVEL:   _spin,
        CMD_RINSE_CYCLES: _rinse,
    }


# --- Poll tiers --------------------------------------------------------
# Same DA_WM_TP1_21 platform as the dryer (~14 req/s ceiling measured
# there); identical cadence structure keeps us well under it.
WASHER_POLL_TIERS = [
    PollTier(
        name='hot',
        interval_s=1.0,
        active_interval_s=0.5,
        timeout_s=2.0,
        paths=(
            ('operational', 'state', 'vs', '0'),
        ),
    ),
    PollTier(
        name='warm',
        interval_s=15.0,
        timeout_s=4.0,
        paths=(
            ('power', 'vs', '0'),
            ('kidslock', 'vs', '0'),
            ('remotectrl', 'vs', '0'),
            ('alarms', 'vs', '0'),
            ('course', 'vs', '0'),
            ('washer', 'vs', '0'),
            ('st', 'washercourse', 'vs', '0'),
            ('wm', 'jobbeginingstatus', 'vs', '0'),
            ('energy', 'consumption', 'vs', '0'),
            ('water', 'consumption', 'vs', '0'),
            ('diagnosis', 'vs', '0'),
        ),
    ),
    PollTier(
        name='sweep',
        interval_s=300.0,
        timeout_s=15.0,
        paths=(('device', '0'),),
        is_sweep=True,
    ),
]


def _is_active(links: dict) -> bool:
    rep = links.get('/operational/state/vs/0') or {}
    sam_state = rep.get('x.com.samsung.da.state')
    return _SAMSUNG_STATE_TO_OCF.get(sam_state) == 'active'


# --- Descriptor --------------------------------------------------------
WASHER = ApplianceDescriptor(
    name='washer',
    default_observe_port=49154,
    observe_paths=OBSERVE_PATHS,
    seed_path=['device', '0'],
    flatten=flatten,
    build_discovery=build_discovery,
    command_handlers=command_handlers,
    on_observation=on_observation,
    project=project,
    remote_available_field='remote_control_binary',
    log_state_change=log_state_change,
    poll_tiers=WASHER_POLL_TIERS,
    is_active=_is_active,
)
