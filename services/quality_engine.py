# ============================================================
# services/quality_engine.py — FarmLink Intelligence
#
# Computes quality and sensor display data from SensorReading rows.
# Called by routes/farmer.py for dashboard, farms, and listings.
#
# Public API:
#   sensor_status(reading)          -> str   'online'|'warning'|'offline'|'no-data'
#   sensor_status_label(status_str) -> str   human-readable label
#   quality_detail(reading)         -> dict  per-sensor Good/Fair/Poor
#   sensor_rows(reading)            -> list  full bar-chart rows for dashboard
#   sensor_cells(reading)           -> list  mini emoji cells for farms card
# ============================================================

from datetime import datetime


def sensor_status(reading):
    """
    Returns 'online' | 'warning' | 'offline' | 'no-data'
    based on how long ago the last reading was taken.
    """
    if not reading:
        return 'no-data'
    minutes = (datetime.utcnow() - reading.timestamp).total_seconds() / 60
    if minutes <= 35:  return 'online'
    if minutes <= 65:  return 'warning'
    return 'offline'


def sensor_status_label(status_str):
    """Human-readable label for a sensor status string."""
    return {
        'online':  'Online',
        'warning': 'Intermittent',
        'offline': 'Offline',
        'no-data': 'No sensor linked',
    }.get(status_str, '\u2014')


def quality_detail(reading):
    """
    Per-sensor Good / Fair / Poor rating dict.
    Always fully populated when reading is not None.
    Keys: 'Soil moisture', 'Temperature', 'Humidity', 'Light'
    """
    if not reading:
        return {}
    d = {}
    sm  = float(reading.soil_moisture)    if reading.soil_moisture   is not None else None
    tmp = float(reading.temperature)      if reading.temperature     is not None else None
    hum = float(reading.humidity)         if reading.humidity        is not None else None
    lux = float(reading.light_intensity)  if reading.light_intensity is not None else None

    if sm  is not None:
        d['Soil moisture'] = ('Good' if 40 <= sm  <= 80
                              else 'Fair' if sm  >= 25 else 'Poor')
    if tmp is not None:
        d['Temperature']   = ('Good' if 18 <= tmp <= 32
                              else 'Fair' if 12 <= tmp <= 38 else 'Poor')
    if hum is not None:
        d['Humidity']      = ('Good' if 50 <= hum <= 85
                              else 'Fair' if hum >= 35 else 'Poor')
    if lux is not None:
        d['Light']         = ('Good' if 2000 <= lux <= 8000
                              else 'Fair' if 500 <= lux <= 12000 else 'Poor')
    return d


def sensor_rows(reading):
    """
    Full list of sensor display rows for the dashboard sensor card.
    Each dict: label, display, pct (int|None), bar_css (str).
    Template does ZERO math.
    """
    if not reading:
        return []
    rows = []

    sm = float(reading.soil_moisture) if reading.soil_moisture is not None else None
    rows.append({
        'label':   'Soil moisture',
        'display': f'{round(sm)}%' if sm is not None else '\u2014',
        'pct':     round(sm) if sm is not None else 0,
        'bar_css': ('b-danger' if sm is not None and sm < 30
                    else 'b-warn' if sm is not None and sm < 45
                    else ''),
    })

    tmp = float(reading.temperature) if reading.temperature is not None else None
    tmp_pct = min(max(round((tmp - 10) / 35 * 100), 0), 100) if tmp is not None else 0
    rows.append({
        'label':   'Temperature',
        'display': f'{round(tmp, 1)}\u00b0C' if tmp is not None else '\u2014',
        'pct':     tmp_pct,
        'bar_css': 'b-teal',
    })

    hum = float(reading.humidity) if reading.humidity is not None else None
    rows.append({
        'label':   'Humidity',
        'display': f'{round(hum)}%' if hum is not None else '\u2014',
        'pct':     round(hum) if hum is not None else 0,
        'bar_css': 'b-warn' if hum is not None and hum > 90 else '',
    })

    lux = float(reading.light_intensity) if reading.light_intensity is not None else None
    lux_pct = min(max(round(lux / 10000 * 100), 0), 100) if lux is not None else 0
    rows.append({
        'label':   'Light intensity',
        'display': f'{round(lux)} lx' if lux is not None else '\u2014',
        'pct':     lux_pct,
        'bar_css': 'b-teal',
    })

    rows.append({
        'label':   'Rainfall',
        'display': 'Raining' if reading.is_raining else 'No rain',
        'pct':     None,
        'bar_css': 'raining' if reading.is_raining else 'dry',
    })

    return rows


def sensor_cells(reading):
    """
    Pre-computed mini sensor cells for the My Farms card.
    Returns list of dicts: emoji, value, name.
    Template does ZERO math.
    """
    if not reading:
        return []
    cells = []
    if reading.soil_moisture is not None:
        cells.append({'emoji': '\U0001f4a7', 'value': f'{round(float(reading.soil_moisture))}%', 'name': 'Soil'})
    if reading.temperature is not None:
        cells.append({'emoji': '\U0001f321', 'value': f'{round(float(reading.temperature), 1)}\u00b0', 'name': 'Temp'})
    if reading.humidity is not None:
        cells.append({'emoji': '\U0001f4a8', 'value': f'{round(float(reading.humidity))}%', 'name': 'Humid'})
    if reading.light_intensity is not None:
        cells.append({'emoji': '\u2600\ufe0f', 'value': f'{round(float(reading.light_intensity)/1000, 1)}k', 'name': 'Light'})
    cells.append({
        'emoji': '\U0001f327' if reading.is_raining else '\U0001f324',
        'value': 'Yes' if reading.is_raining else 'No',
        'name':  'Rain'
    })
    return cells