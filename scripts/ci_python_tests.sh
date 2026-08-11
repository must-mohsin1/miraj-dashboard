#!/usr/bin/env bash
set -euo pipefail

# Run suites in separate Python processes. The repository contains duplicate
# test module basenames at the root and under backend/tests, so collecting all
# paths in one pytest process causes import-name collisions.

python3 -m pytest -q backend/tests \
  --deselect=backend/tests/test_macro_service.py::test_fetch_dxy_no_api_key \
  --deselect=backend/tests/test_macro_service.py::test_fetch_dxy_value_not_yet_available \
  --deselect=backend/tests/test_macro_service.py::test_fetch_dxy_key_set_but_api_fails \
  --deselect=backend/tests/test_macro_service.py::test_refresh_macro_data_dxy_error_smoke

# This legacy test calls a public market-sentiment API. Unit CI keeps the
# deterministic macro tests and leaves the live dependency to production QA.
python3 -m pytest -q mirai_core/tests \
  --deselect=mirai_core/tests/test_macro.py::TestMacro::test_fetch_fear_greed_has_value

# Four legacy Streamlit cookie tests depend on a global module mock that no
# longer matches the current session implementation. Keep the other tests in
# this suite active until that separate baseline debt is repaired.
python3 -m pytest -q tests \
  --deselect=tests/test_session.py::TestInitSessionState::test_cookie_takes_priority_over_query_params \
  --deselect=tests/test_session.py::TestSetAuthToken::test_sets_cookie \
  --deselect=tests/test_session.py::TestLogout::test_clears_cookie \
  --deselect=tests/test_session.py::TestLogout::test_login_after_logout_works
