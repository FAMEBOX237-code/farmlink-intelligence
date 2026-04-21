# ============================================================
# services/alert_dispatcher.py — FarmLink Intelligence
#
# Classifies notifications into display-ready alert dicts
# for the dashboard and notifications page.
#
# Public API:
#   build_alerts_display(notifications) -> list[dict]
#     Each dict: message, time, dot_css
# ============================================================


# Notification type -> dot CSS class mapping
_DANGER_TYPES  = {'sensor_offline', 'account_suspended'}
_WARN_TYPES    = {'quality_change', 'harvest_alert'}
_SUCCESS_TYPES = {'transaction_completed', 'listing_published', 'account_verified'}


def _dot_css(notification_type):
    """Returns the CSS class string for a notification dot badge."""
    t = notification_type or ''
    if t in _DANGER_TYPES:    return 'd-danger'
    if t in _WARN_TYPES:      return 'd-warn'
    if t in _SUCCESS_TYPES:   return 'd-success'
    return 'd-info'


def build_alerts_display(notifications):
    """
    Converts a list of Notification ORM objects into a list of
    pre-computed display dicts ready for the template.

    Args:
        notifications: list of Notification model instances,
                       already sorted (e.g. newest first).

    Returns:
        list of dicts with keys:
          message  str  -- notification message text
          time     str  -- formatted sent_at e.g. 'Apr 20, 14:32'
          dot_css  str  -- 'd-danger'|'d-warn'|'d-success'|'d-info'
    """
    display = []
    for n in notifications:
        display.append({
            'message': n.message,
            'time':    n.sent_at.strftime('%b %d, %H:%M') if n.sent_at else '',
            'dot_css': _dot_css(n.type),
        })
    return display