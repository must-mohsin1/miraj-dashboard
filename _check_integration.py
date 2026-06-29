"""Quick integration health check — verify all modules import and helpers work."""
import sys
sys.path.insert(0, '.')

from backend.auth import get_current_user
print('auth.py  OK')

from backend.routes.scan import scan_symbol
print('scan.py  OK')

from backend.services.analysis_service import (
    _build_flat_trade_plan, _extract_category_scores, _normalize_obs
)
print('analysis_service.py  OK')

# Test _build_flat_trade_plan
tp = {
    'direction': 'LONG',
    'entry_zone': {'low': 100.0, 'high': 105.0},
    'stop_loss': 98.0,
    'take_profit_targets': [{'level': 110.0}, {'level': 120.0}],
    'reasoning': 'Test',
}
flat = _build_flat_trade_plan(tp)
assert flat['direction'] == 'LONG'
assert flat['entry'] == 100.0
assert flat['stop_loss'] == 98.0
assert flat['target_1'] == 110.0
assert flat['target_2'] == 120.0
print('_build_flat_trade_plan  OK')

# Test _extract_category_scores
sb = {
    'regime': {'score': 7.0}, 'location': {'score': 5.0},
    'confirmation': {'score': 6.0}, 'volume_retest': {'score': 2.0},
    'risk': {'score': 3.0},
}
scores = _extract_category_scores(sb)
assert scores['regime'] == 7.0
assert scores['risk'] == 3.0
print('_extract_category_scores  OK')

# Test _normalize_obs
obs_in = [{'zone': (100.0, 105.0), 'type': 'bullish', 'start_time': '2024-01-01'}]
obs_out = _normalize_obs(obs_in)
assert len(obs_out) == 1
assert obs_out[0]['price_low'] == 100.0
assert obs_out[0]['price_high'] == 105.0
print('_normalize_obs  OK')

print('\nAll integration checks passed!')
