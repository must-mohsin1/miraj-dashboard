# Miraj Position Menu Bar

Local macOS 14+ MenuBarExtra app for read-only Miraj position intelligence. It shows one authenticated MEXC position, freshness/offline state, HTF/LTF support-resistance context, and a safe advisory enum: HOLD, REDUCE, CLOSE, or WAIT.

This MVP is local/ad-hoc only. It does not place trades, edit orders, call MEXC/ccxt from the desktop app, deploy anything, change VPS/cron/secrets, or alter existing trading routes.

## Safety boundaries

This README describes a local macOS developer/operator build path only. It is not a production rollout, deployment guide, VPS change, cron change, public endpoint launch, or exchange-integration setup.

The menu-bar app and its documented backend contract are deliberately read-only:

- No API keys, exchange keys, MEXC secrets, ccxt credentials, browser cookies, or backend secret material are stored, requested, logged, or included in examples.
- No plaintext JWT or session-token value is shown in this README. Authentication setup is described by storage location and flow only.
- No unauthenticated or public position/PnL endpoint is added; the connected endpoint remains behind normal Miraj authentication.
- No desktop control places trades, edits orders, changes leverage, executes DCA, creates exchange connections, or mutates portfolio state.
- No deployment, production rollout, production backend selection, exchange-key rotation, or VPS/cron operation is involved.

## What is included

- Native SwiftUI `MenuBarExtra` + popover under `desktop/MirajPositionMenuBar`.
- Optional connected backend endpoint: `GET /api/v1/desktop/position-intelligence?exchange=mexc&symbol=<optional-symbol>`.
- Keychain-backed Miraj session token storage in the app.
- Runtime local JSON fixtures for mock-first rendering.
- File-protected local display cache for offline-with-cache rendering.

## Local build

From the repository root:

```sh
swift build --package-path desktop/MirajPositionMenuBar
```

From the repository root, verify the backend desktop API contract without starting a server:

```sh
python -m pytest -q \
  backend/tests/test_desktop_position_service.py \
  backend/tests/test_desktop_position_route.py \
  backend/tests/test_desktop_position_swift_contract.py
```

On a host with full Xcode installed, verify the Xcode project with:

```sh
xcodebuild -project desktop/MirajPositionMenuBar/MirajPositionMenuBar.xcodeproj -scheme MirajPositionMenuBar -configuration Debug build
xcodebuild -project desktop/MirajPositionMenuBar/MirajPositionMenuBar.xcodeproj -scheme MirajPositionMenuBar -configuration Debug test
```

The shared `MirajPositionMenuBar` scheme builds the menu-bar app and the deterministic harness target that compiles/runs the delivered Swift source and test files.

If `xcodebuild -version` reports CommandLineTools instead of full Xcode, do not use a workaround. Re-run the Xcode build on a full Xcode macOS builder.

## Safe default runtime and mock mode

The app is mock-first by default. A normal local/ad-hoc launch uses `PositionRuntimeMode.mockFixtures`, reads bundled JSON fixtures, requires no Keychain token, and does not create a `URLRequest` or contact Miraj, MEXC, production, ccxt, or any live backend.

Select mock fixtures without network by using either a launch argument or environment variable:

```sh
cd desktop/MirajPositionMenuBar
swift run MirajPositionMenuBar --miraj-position-mock --miraj-position-fixture=position_fresh_long
MIRAJ_POSITION_MODE=mockFixtures MIRAJ_POSITION_FIXTURE=offline_with_cache swift run MirajPositionMenuBar
```

Valid fixture names are:

- `position_fresh_long.json`
- `position_stale_short_contract_size.json`
- `no_open_positions.json`
- `not_connected.json`
- `offline_with_cache.json`
- `critical_stale.json`

`Package.swift` copies `MockFixtures/` into the runtime bundle for SwiftPM builds; the Xcode target also copies the same folder as an app resource. The fixture tests compile deterministic Swift harnesses with `swiftc`; they do not contact Miraj, MEXC, production, or any live backend.

## Connected backend use requires explicit operator configuration

Connected mode is opt-in only. Before using it, an operator must configure a non-secret HTTPS Miraj backend base URL preference, store any Miraj session token only through `PositionKeychainTokenStore`, and launch with connected mode explicitly enabled:

```sh
MIRAJ_POSITION_MODE=connected swift run MirajPositionMenuBar
# or pass --miraj-position-connected from an Xcode/run configuration
```

The built-in default backend URL is a non-routable placeholder (`https://localhost.invalid`), not production. Do not use connected mode against production, staging, or any shared backend until separately approved.

The only desktop network request in connected mode is `GET /api/v1/desktop/position-intelligence?exchange=mexc&symbol=<optional-symbol>` with the Miraj Bearer session credential loaded from Keychain. The backend service builds schema_version=1 output from cached portfolio position, scan, DCA recommendation, and position-alert inputs; it does not refresh exchange data or call trading/execution endpoints.

## Auth setup

The app expects a Miraj session token issued by the normal authenticated Miraj login flow. Store the token only through `PositionKeychainTokenStore`; do not paste it into shell commands, source files, fixtures, logs, README examples, UserDefaults, or cache files.

This README intentionally does not provide a JWT/token literal, export command, curl header, or copy/paste authentication example. Use the app’s login/connect flow or a local developer-only token-entry path that writes directly to Keychain.

The desktop client sends the token as a Bearer credential to the Miraj backend endpoint. The desktop app never stores or requests MEXC API keys, MEXC secrets, exchange credentials, browser cookies, or raw backend secret material.

The debug backend base URL preference accepts HTTPS URLs only. Non-secret preferences such as selected symbol, hide-amounts mode, redacted menu-bar mode, refresh preference, runtime mode, and debug base URL may live in UserDefaults.

## Keychain behavior

`PositionKeychainTokenStore` stores the Miraj session token as a generic password item using `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`. It supports read, save/update, and clear/logout operations. The token store is intentionally separate from preferences and cache so private credentials are never persisted in app settings or display snapshots.

## Privacy mode

Two privacy controls are available:

- Hide amounts: masks size, entry price, mark price, liquidation price/distance, absolute PnL, and support/resistance prices in the popover while preserving allowed context such as symbol, side, PnL percent, freshness, and advisory enum.
- Redacted menu bar: displays neutral “Miraj” text only, with no symbol, size, PnL, price, or advisory text in the menu bar.

The not-connected and unauthorized states do not display cached private position data.

## Refresh and runtime behavior

Mock mode renders local fixtures only. Connected mode calls only the authenticated read-only desktop endpoint after it is explicitly enabled. Automatic connected refresh is throttled to at most once every 60 seconds by `PositionRefreshCoordinator`; default preferences are manual-only. Manual connected refresh shows an in-flight state and still calls only the read-only endpoint.

Offline-with-cache renders the last schema_version=1 display snapshot as offline/stale. Offline-without-cache renders “Unable to load position” and no private position details.

## Manual QA checklist

Before any local/ad-hoc operator trial:

1. Run backend pytest for the desktop service/route/Swift contract tests.
2. Run the Swift deterministic harnesses.
3. On a full Xcode host, run the shared `MirajPositionMenuBar` scheme build and test actions.
4. Launch mock mode and render each `MockFixtures/*.json` state with no network proxy/logged URL requests.
5. Only after separate approval for connected mode, start a local authenticated Miraj backend and set the explicit HTTPS backend preference.
6. Confirm an unauthenticated request to the desktop endpoint returns 401 and no position/PnL data.
7. With a valid Miraj session, compare symbol, side, mark price, PnL, and PnL percent against the authenticated dashboard within the documented stale window.
8. Toggle hide-amounts and redacted menu-bar modes and verify no private numeric data appears where it should be masked.
9. Confirm “Open Miraj” only opens the dashboard/portfolio route and no popover control performs a trade, order, leverage, DCA execution, exchange-key, or mutation action.

Stop rollout if stale data displays as fresh, private numeric data leaks in privacy mode, credential material is stored outside Keychain, or executable trading CTA copy appears in the app.

## Rollback / removal

Rollback is local and does not require production data deletion, MEXC key rotation, exchange credential edits, VPS edits, cron edits, deployment-script edits, or changes to existing portfolio refresh behavior.

1. Quit the Miraj Position Menu Bar app.
2. Remove the local/ad-hoc app from Applications and login items if installed.
3. Clear the app’s Miraj session token via the logout/clear-token flow, which deletes the `pk.miraj.position-menubar.auth` / `miraj-session-token` generic-password item from Keychain; revoke the session server-side if the device is lost.
4. Delete the local display cache under `~/Library/Application Support/MirajPosition/display-snapshot-v1.json` if desired.
5. Revert the backend desktop route/service commit if this local branch is no longer wanted.
6. Re-run existing portfolio/dashboard smoke tests to confirm existing behavior is unchanged.
