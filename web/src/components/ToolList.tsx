import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import type { ToolInfo } from "../api/types";
import { Badge } from "./ui/Badge";

export function ToolList({ tools, filterable = true }: { tools: ToolInfo[]; filterable?: boolean }) {
  const [q, setQ] = useState("");
  const shown = useMemo(() => {
    const n = q.trim().toLowerCase();
    return n ? tools.filter((t) => t.name.toLowerCase().includes(n) || (t.description ?? "").toLowerCase().includes(n)) : tools;
  }, [tools, q]);
  return (
    <div className="space-y-2">
      {filterable && tools.length > 8 && (
        <label className="relative block">
          <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-muted" aria-hidden />
          <input
            aria-label="Filter tools"
            className="h-7 w-full rounded-md border border-line bg-bg pl-8 pr-2 text-xs outline-none focus:border-accent"
            placeholder="Filter tools…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </label>
      )}
      <ul className="divide-y divide-line/70 rounded-md border border-line">
        {shown.map((t) => (
          <li key={t.name} className="px-3 py-2">
            <div className="flex items-center gap-2">
              <code className="text-xs font-semibold">{t.name}</code>
              {t.side_effect && <Badge tone="warn">side effects</Badge>}
            </div>
            {t.description && <p className="mt-0.5 text-xs text-muted">{t.description}</p>}
          </li>
        ))}
        {shown.length === 0 && <li className="px-3 py-4 text-center text-xs text-muted">No tools match.</li>}
      </ul>
    </div>
  );
}
