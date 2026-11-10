# Version history

Newest first. The running version is shown at the bottom of the dashboard sidebar and in `GET /api/status`.

| Version | Date | Highlights |
|---|---|---|
| 0.5.1 | 2026-11-10 | **Model switcher can stop servers started from a terminal** (ops/start.sh or by hand): Atom finds the llama-server on the profile's port and stops it, so every running model shows a Stop button. |
| 0.5.0 | 2026-11-10 | **Uncensored model profile**: huihui-ai abliterated Qwen3.8-27B (Q4_K, :8082) selectable in the model switcher, per agent, and via `ops/llama-server.sh uncensored`. |
| 0.4.0 | 2026-11-10 | **Chat page**: every message shows its date and time; **Copy** on user and assistant messages; **Run again** re-sends the prompt a reply answered. Images page also shows date/time. |
| 0.3.0 | 2026-11-10 | Images page: **Copy prompt**, **Run again** (same settings, new random seed), **Retry** on failures, "Reuse settings" renamed **Edit in box**. LUSTIFY V10 (Krea 2) service and image-to-image. |
| 0.2.0 | 2026-11-09 | SDXL image service, Images page, sandboxed file tools, clickable file paths in chat, Z-Image generate_image tool. |
