import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { cn } from "../../lib/cn";
import { prettyJSON } from "../../lib/format";

export function CodeBlock({
  code, lang, className, maxHeight = "20rem", wrap = true,
}: { code: string; lang?: string; className?: string; maxHeight?: string; wrap?: boolean }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard?.writeText(code).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1200);
      },
      () => undefined,
    );
  };
  return (
    <div className={cn("group relative my-2 rounded-md border border-line bg-surface2", className)}>
      {lang && <span className="absolute left-2 top-1 text-[10px] uppercase tracking-wide text-muted">{lang}</span>}
      <button
        type="button"
        onClick={copy}
        aria-label="Copy code"
        className="absolute right-1.5 top-1.5 rounded p-1 text-muted opacity-0 hover:bg-surface hover:text-fg focus-visible:opacity-100 group-hover:opacity-100"
      >
        {copied ? <Check className="h-3.5 w-3.5 text-ok" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
      <pre
        className={cn("overflow-auto p-2.5 font-mono text-xs leading-relaxed", lang && "pt-5", wrap ? "whitespace-pre-wrap break-words" : "whitespace-pre")}
        style={{ maxHeight }}
      >
        <code>{code}</code>
      </pre>
    </div>
  );
}

export function JsonBlock({ value, className, maxHeight }: { value: unknown; className?: string; maxHeight?: string }) {
  return <CodeBlock code={prettyJSON(value)} lang="json" className={className} maxHeight={maxHeight} />;
}
