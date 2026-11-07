# Atom web dashboard

Vite + React 18 + TypeScript (strict) + Tailwind + react-router + TanStack Query + Recharts + lucide-react.
The API contract is `docs/DASHBOARD_API.md`; the app talks to `/api/*` only.

## Run (development)

```sh
pnpm install            # pnpm is pinned via "packageManager" in package.json (corepack)
pnpm dev                # http://localhost:5173, proxies /api -> http://127.0.0.1:8787
```

Against the bundled mock API (no backend needed):

```sh
pnpm mock                                   # mock API on http://127.0.0.1:8788
ATOM_API=http://127.0.0.1:8788 pnpm dev     # in a second terminal
```

The proxy sends `Accept-Encoding: identity` and marks event streams `no-transform`, so SSE is never buffered or gzipped.
Mock extras for testing the live run view: `GET /api/__mock/drop?on=1` makes the run stream drop every ~5 s so the
client reconnects and the replay is de-duplicated by `seq`; `GET /api/__mock/stops` counts stop requests.

## Build

```sh
pnpm build              # tsc --noEmit && vite build  -> web/dist (served by the backend at "/")
pnpm typecheck          # tsc --noEmit only
```

## Layout

- `src/api/` typed client (`client.ts`), contract types (`types.ts`), SSE helpers (`sse.ts`: `readSSE` for fetch streams,
  `useSSE` for EventSource), TanStack Query hooks + global `/api/events` subscription (`hooks.ts`)
- `src/lib/` formatting, theme, schedule helpers, live-run reducer (`runState.ts`), chat stream reducer (`chatState.ts`)
- `src/components/ui/` hand-written primitives (Button, Card, Badge, Tabs, Switch, Dialog, Toast, Select, Spinner, CodeBlock, Markdown...)
- `src/pages/` one file per route

Theme: follows `prefers-color-scheme`; the sidebar toggle persists the choice in `localStorage` (`atom-theme`).
