# ============================================================
# services/forecast_engine.py — FarmLink Intelligence
#
# Computes all forecast display data for a farmer.
# Called by routes/farmer.py -> forecast_detail() route.
#
# Public API:
#   compute_forecast_context(forecast, farmer_user) -> dict
# ============================================================

from datetime import datetime, timedelta
from models.models import Farm, SensorReading, HarvestForecast


def _ago(dt):
    """Human-readable time since dt (UTC)."""
    if not dt:
        return 'never'
    s = (datetime.utcnow() - dt).total_seconds()
    if s < 60:     return 'just now'
    if s < 3600:   m = int(s // 60);   return f'{m} minute{"s" if m != 1 else ""} ago'
    if s < 86400:  h = int(s // 3600); return f'{h} hour{"s" if h != 1 else ""} ago'
    if s < 172800: return 'yesterday'
    return f'{int(s // 86400)} days ago'


def compute_forecast_context(forecast, farmer):
    """
    Full display context for the Harvest Forecast detail page.

    Returns a dict ready to be **-unpacked into render_template().

    Keys:
      farm                Farm
      days_to_start       int   -- days until harvest window opens (0 if past)
      days_to_end         int   -- days until harvest window closes (0 if past)
      window_label        str   -- e.g. '15 - 22 Jun 2025'
      confidence_pct      int   -- 0-100
      confidence_css      str   -- 'conf-high' | 'conf-mid' | 'conf-low'
      data_points         int
      data_points_pct     int   -- progress toward 28-day target (0-100)
      buyers_alerted      int
      is_active           bool
      created_display     str
      history             list[dict]
        Each dict: id, window_label, confidence_pct, created_display,
                   is_active, days_label, buyers_alerted
      sensor_readings_7d  int   -- readings in last 7 days (data freshness)
      latest_reading_ago  str
    """
    farm  = Farm.query.get(forecast.farm_id)
    today = datetime.utcnow().date()

    # Days until harvest window
    days_to_start = max((forecast.predicted_harvest_start - today).days, 0)
    days_to_end   = max((forecast.predicted_harvest_end   - today).days, 0)

    # Human-readable window label
    start_str    = forecast.predicted_harvest_start.strftime('%-d %b %Y')
    end_str      = forecast.predicted_harvest_end.strftime('%-d %b %Y')
    window_label = f'{start_str} \u2013 {end_str}'

    # Confidence display
    confidence_pct = round(float(forecast.confidence_score))
    if confidence_pct >= 75:   confidence_css = 'conf-high'
    elif confidence_pct >= 50: confidence_css = 'conf-mid'
    else:                      confidence_css = 'conf-low'

    # Data points progress (28-day target)
    data_points     = forecast.data_points_used or 0
    data_points_pct = min(round(data_points / 28 * 100), 100)

    # Sensor readings in last 7 days
    week_ago = datetime.utcnow() - timedelta(days=7)
    sensor_readings_7d = SensorReading.query.filter(
        SensorReading.farm_id == farm.id,
        SensorReading.timestamp >= week_ago
    ).count()

    # Latest reading age
    latest_reading = (SensorReading.query
                      .filter_by(farm_id=farm.id)
                      .order_by(SensorReading.timestamp.desc())
                      .first())
    latest_reading_ago = _ago(latest_reading.timestamp) if latest_reading else 'never'

    # Forecast history -- all forecasts for this farm, newest first
    all_forecasts = (HarvestForecast.query
                     .filter_by(farm_id=farm.id)
                     .order_by(HarvestForecast.created_at.desc())
                     .all())

    history = []
    for fc in all_forecasts:
        fc_start = fc.predicted_harvest_start.strftime('%-d %b %Y')
        fc_end   = fc.predicted_harvest_end.strftime('%-d %b %Y')
        d_start  = (fc.predicted_harvest_start - today).days
        if d_start > 0:
            days_lbl = f'In {d_start} days'
        elif d_start == 0:
            days_lbl = 'Starts today'
        else:
            days_lbl = f'{abs(d_start)} days ago'
        history.append({
            'id':             fc.id,
            'window_label':   f'{fc_start} \u2013 {fc_end}',
            'confidence_pct': round(float(fc.confidence_score)),
            'created_display':(fc.created_at.strftime('%-d %b %Y')
                               if fc.created_at else '\u2014'),
            'is_active':      fc.is_active,
            'days_label':     days_lbl,
            'buyers_alerted': fc.buyers_alerted or 0,
        })

    return dict(
        farm               = farm,
        days_to_start      = days_to_start,
        days_to_end        = days_to_end,
        window_label       = window_label,
        confidence_pct     = confidence_pct,
        confidence_css     = confidence_css,
        data_points        = data_points,
        data_points_pct    = data_points_pct,
        buyers_alerted     = forecast.buyers_alerted or 0,
        is_active          = forecast.is_active,
        created_display    = (forecast.created_at.strftime('%-d %b %Y')
                              if forecast.created_at else '\u2014'),
        history            = history,
        sensor_readings_7d = sensor_readings_7d,
        latest_reading_ago = latest_reading_ago,
    )