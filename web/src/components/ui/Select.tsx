import type { SelectHTMLAttributes } from "react";
import { cn } from "../../lib/cn";

export interface Option { value: string; label: string }

export function Select({
  options, className, ...rest
}: { options: (Option | string)[] } & SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cn("input pr-7", className)} {...rest}>
      {options.map((o) => {
        const opt = typeof o === "string" ? { value: o, label: o } : o;
        return <option key={opt.value} value={opt.value}>{opt.label}</option>;
      })}
    </select>
  );
}
