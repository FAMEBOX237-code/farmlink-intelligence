# ============================================================
# services/trust_engine.py — FarmLink Intelligence
#
# Computes all trust-score display data for a farmer.
# Called by routes/farmer.py → trust_score() route.
#
# Public API:
#   compute_trust_context(farmer_user)  → dict  (template-ready)
#   trust_display(user)                 → (display_str, css_class)
# ============================================================

from models.models import Rating, Transaction, User, ProduceListing


def trust_display(user):
    """
    Returns (display_str, css_class) for the mini trust-score badge
    shown on dashboard / listing cards.
    Returns (None, None) when no score has been set yet.
    """
    ts = float(user.trust_score) if user.trust_score else 0
    if ts <= 0:
        return None, None
    css = 'kv-teal' if ts >= 4.0 else ('kv-amber' if ts >= 2.5 else 'kv-danger')
    return f'{ts:.1f}', css


def compute_trust_context(farmer):
    """
    Full trust-score breakdown for the Trust Score page.

    Trust score components (each 0-100, averaged -> 0-5 scale):
      1. Transaction completion rate -- completed / total
      2. On-time delivery rate       -- is_on_time=True / completed
      3. Average buyer rating        -- avg of Rating.score (1-5)
      4. Profile completeness        -- named fields filled in

    Returns a dict ready to be **-unpacked into render_template().

    Keys:
      trust_score_display  str        -- '4.2'
      trust_score_pct      int        -- 0-100 for progress bar
      trust_css            str        -- 'ts-high'|'ts-mid'|'ts-low'|'ts-none'
      total_transactions   int
      completed_tx         int
      completion_rate_pct  int        -- 0-100
      on_time_count        int
      on_time_rate_pct     int        -- 0-100
      avg_rating           str        -- '4.2' or '--'
      avg_rating_pct       int        -- 0-100
      rating_count         int
      profile_pct          int        -- 0-100
      profile_missing      list[str]  -- field names not yet filled
      recent_ratings       list[dict] -- score,comment,created_display,
                                         buyer_initial,stars_full,stars_empty
      total_revenue        str        -- formatted XAF total
      active_listings_count int
    """
    # Trust score display
    ts_raw = float(farmer.trust_score) if farmer.trust_score else 0.0
    trust_score_display = f'{ts_raw:.1f}'
    trust_score_pct     = min(round(ts_raw / 5.0 * 100), 100)

    if ts_raw >= 4.0:   trust_css = 'ts-high'
    elif ts_raw >= 2.5: trust_css = 'ts-mid'
    elif ts_raw > 0:    trust_css = 'ts-low'
    else:               trust_css = 'ts-none'

    # Transaction stats
    all_tx = Transaction.query.filter_by(farmer_id=farmer.id).all()
    total_transactions = len(all_tx)
    completed_tx  = sum(1 for t in all_tx if t.status == 'completed')
    on_time_count = sum(1 for t in all_tx
                        if t.status == 'completed' and t.is_on_time)

    completion_rate_pct = (round(completed_tx / total_transactions * 100)
                           if total_transactions > 0 else 0)
    on_time_rate_pct    = (round(on_time_count / completed_tx * 100)
                           if completed_tx > 0 else 0)

    # Total revenue from completed transactions
    total_rev = sum(float(t.total_amount)
                    for t in all_tx if t.status == 'completed')
    if total_rev >= 1_000_000:
        total_revenue = f'XAF\u00a0{total_rev / 1_000_000:.1f}M'
    elif total_rev >= 1_000:
        total_revenue = f'XAF\u00a0{total_rev / 1_000:.0f}k'
    elif total_rev > 0:
        total_revenue = f'XAF\u00a0{total_rev:,.0f}'
    else:
        total_revenue = '\u2014'

    # Rating stats
    ratings = (Rating.query
               .filter_by(farmer_id=farmer.id)
               .order_by(Rating.created_at.desc())
               .all())
    rating_count   = len(ratings)
    avg_rating_raw = (sum(r.score for r in ratings) / rating_count
                      if rating_count > 0 else 0)
    avg_rating     = f'{avg_rating_raw:.1f}' if rating_count > 0 else '\u2014'
    avg_rating_pct = min(round(avg_rating_raw / 5.0 * 100), 100)

    # Recent ratings (last 5)
    recent_ratings = []
    for r in ratings[:5]:
        buyer   = User.query.get(r.buyer_id)
        initial = buyer.full_name[:2].upper() if buyer else 'B?'
        recent_ratings.append({
            'score':           r.score,
            'comment':         r.comment or '',
            'created_display': (r.created_at.strftime('%-d %b %Y')
                                if r.created_at else '\u2014'),
            'buyer_initial':   initial,
            'stars_full':      r.score,
            'stars_empty':     5 - r.score,
        })

    # Profile completeness
    profile_fields = {
        'Full name':    bool(farmer.full_name and farmer.full_name.strip()),
        'Phone number': bool(farmer.phone),
        'Region':       bool(farmer.region),
        'Primary crop': bool(farmer.primary_crop),
        'Profile photo':bool(farmer.profile_photo_url),
    }
    filled          = sum(1 for v in profile_fields.values() if v)
    profile_pct     = round(filled / len(profile_fields) * 100)
    profile_missing = [k for k, v in profile_fields.items() if not v]

    # Active listings count
    active_listings_count = ProduceListing.query.filter_by(
        farmer_id=farmer.id, status='active'
    ).count()

    return dict(
        trust_score_display   = trust_score_display,
        trust_score_pct       = trust_score_pct,
        trust_css             = trust_css,
        total_transactions    = total_transactions,
        completed_tx          = completed_tx,
        completion_rate_pct   = completion_rate_pct,
        on_time_count         = on_time_count,
        on_time_rate_pct      = on_time_rate_pct,
        avg_rating            = avg_rating,
        avg_rating_pct        = avg_rating_pct,
        rating_count          = rating_count,
        profile_pct           = profile_pct,
        profile_missing       = profile_missing,
        recent_ratings        = recent_ratings,
        total_revenue         = total_revenue,
        active_listings_count = active_listings_count,
    )