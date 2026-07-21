# Phase 2 — Self-Contained TarzanIQ.app — Design Spec

- **Date:** 2026-07-20
- **Status:** Approved (owner picked "window now, bundle later" in the Phase-1 brainstorm; "later" green-lit today)
- **Branch:** `feat/bundled-app-2026-07-20`
- **Builds on:** Phase 1 (`tarzaniq/app_window.py`, PR #8).

## 1. Goal

One `TarzanIQ.app` the user drags into `/Applications` and opens. No installer, no Terminal,
no system Python — the bundle carries CPython, every package, the SPA, and the four face
models. This deletes the entire failure class that produced every live incident so far
(Homebrew removing the app's Python; installer PATH blindness; silent-sudo dead ends).

## 2. Decisions

| Decision | Choice | Why |
|---|---|---|
| Bundler | **PyInstaller** (`--windowed` .app) | Mature hooks for the heavy deps (cv2, pyobjc/pywebview, PIL); spike-verified on this Mac. py2app is the fallback if the spike had failed. |
| Entry | `tarzaniq.app_window.main` | Phase 1's window is exactly the bundle's UX; one code path for source + frozen. |
| Models | **Bundled in the .app** (`Contents/…/models`), copied to `~/Documents/TarzanIQ Data/models` on first run (`_ensure_models`) | First launch works offline; the data dir stays the single place the engine (and the classic installer) read from; deleting the app never deletes models/data. |
| Verification | `TarzanIQ --selftest` (headless: heavy imports, engine serves, **real FaceEngine loads**) | Build script + future CI can prove a bundle without opening a window. |
| Logging | Frozen app redirects stdout/stderr to `…/TarzanIQ Data/logs/app.log` | Double-clicked .apps have no terminal; client problems must leave a trail. |
| Signing | Ad-hoc (`codesign -s -`) now; Developer ID + notarization as a follow-up when the owner buys the certificate | Ad-hoc keeps the one-time "Open Anyway"; notarization removes it entirely. |
| Distribution | `dist/TarzanIQ-<version>-mac.zip` via `ditto` (preserves signatures/permissions) | Attach to private GitHub Releases; send the zip to clients directly. |
| Drag-a-folder-onto-the-Dock-icon | **Deferred** | Frozen .apps receive drops via Apple Events, not argv; needs an NSApplicationDelegate hook through pywebview. The in-app "+ Add day folder" picker and the Finder Quick Action cover the workflow. |
| Installer | **Kept** | Still the from-source path (and the self-repair target) for the owner's own Mac; the bundle is the client-distribution path. |

## 3. Build pipeline (`scripts/build_app.sh`)

fresh build venv (3.11–3.13) → `pip install -r requirements.txt pyinstaller` → download + sha256-verify
the 4 models (same pins as install.sh — keep in lockstep) → build `TarzanIQ.icns` from the icon set →
PyInstaller (`--windowed --icon --osx-bundle-identifier com.tarzaniq.app --add-data static + models`) →
`codesign --force --deep -s -` → **`--selftest` must pass** → `ditto` zip.

## 4. Risks / caveats (honest)

- PyInstaller bundles are macOS-version-forward-compatible but built per-arch: this Mac builds
  **arm64**; Intel clients would need an Intel build (build script runs anywhere; CI matrix later).
- Ad-hoc signed → recipients still do the one-time Gatekeeper "Open Anyway". Notarization (paid)
  removes it.
- First open is slower (~seconds) while macOS verifies the bundle; subsequent opens are normal.
- The GUI itself renders on the destination Mac — selftest proves engine + models + imports, not pixels.

## 5. Tests

`--selftest` inside the built bundle (build gate). Existing `tests/test_app_window.py` still covers
the source path (webview stubbed). Full suite must stay green — no engine code paths change when
running from source (`FROZEN` guards everything new).
