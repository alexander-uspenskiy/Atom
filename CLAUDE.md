# Atom project rules

- **Always bump the build version** with every change that is committed. Keep these two in sync:
  `VERSION` in `atom/server/app.py` (shown in the UI sidebar as `vX.Y.Z`) and `"version"` in `web/package.json`.
  Patch (Z) for fixes, minor (Y) for features.
- **Record what each version supports** in `docs/VERSIONS.md` (newest first), so "which version has X?" is answerable.
- Then: rebuild the web UI (`cd web && pnpm build`), commit, push, and restart the server (`python -m atom serve`).
