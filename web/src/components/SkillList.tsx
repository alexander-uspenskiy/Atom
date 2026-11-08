import type { Skill } from "../api/types";
import { cn } from "../lib/cn";
import { Badge } from "./ui/Badge";

export function SkillList({ skills }: { skills: Skill[] }) {
  return (
    <ul className="divide-y divide-line/70 rounded-md border border-line">
      {skills.map((s) => (
        <li key={s.name} className={cn("px-3 py-2", s.enabled === false && "opacity-50")}>
          <div className="flex items-center gap-2">
            <code className="text-xs font-semibold">{s.name}</code>
            {s.enabled === false && <Badge>disabled</Badge>}
          </div>
          {s.description && <p className="mt-0.5 text-xs text-muted">{s.description}</p>}
          {s.when_to_use && <p className="mt-0.5 text-xs text-muted/80">Use when: {s.when_to_use}</p>}
        </li>
      ))}
      {skills.length === 0 && (
        <li className="px-3 py-4 text-center text-xs text-muted">No skills yet. Create one on the Skills page.</li>
      )}
    </ul>
  );
}
