# autoclys

tauri shell + local python desktop service for hermes.

## shape

- `src-ui/` is the desktop frontend.
- `src-tauri/` is the native shell and service bridge.
- `../../hermes_desktop_service.py` is the local backend service that reuses `AIAgent`, `SessionDB`, and hermes config/toolset loading.

## expected runtime

- the app starts hermes through the repo-local `.venv`.
- sessions are backed by the existing hermes sqlite store in `~/.hermes/state.db`.
- each app session carries its own cwd, model, toolsets, and message history.

## current scope

- session list and tabbed chat workspaces
- config editor for `~/.hermes/config.yaml`
- toolset and resolved tool surface display
- local backend service bootstrapped by the tauri shell

desktop-control tools and richer streaming/intervention flows can layer on top next.
