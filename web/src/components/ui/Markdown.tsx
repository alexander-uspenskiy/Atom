import { memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { CodeBlock } from "./CodeBlock";

const EXT = "png|jpe?g|gif|webp|pdf|txt|md|json|csv|log";
const PATH_RE = new RegExp(`(^|[\\s("'])(/(?:Users|home|tmp|private|var|opt|Volumes)/[^\\s)"'\`<>]+\\.(?:${EXT}))(?![\\w/])`, "gi");
const ONLY_PATH_RE = new RegExp(`^/(?:Users|home|tmp|private|var|opt|Volumes)/[^\\s]+\\.(?:${EXT})$`, "i");
const fileUrl = (path: string) => `/api/local-file?path=${encodeURIComponent(path)}`;

/** Turn bare absolute file paths (outside code spans/fences and existing links) into preview links. */
function linkifyPaths(text: string): string {
  return text.split(/(```[\s\S]*?```|`[^`\n]*`|\]\([^)]*\))/g).map((part, i) =>
    i % 2 === 1 ? part : part.replace(PATH_RE, (_m, pre: string, path: string) => `${pre}[${path}](${fileUrl(path).replace(/\)/g, "%29")})`),
  ).join("");
}

export const Markdown = memo(function Markdown({ text }: { text: string }) {
  text = linkifyPaths(text);
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer noopener">{children}</a>
          ),
          pre: ({ children }) => <>{children}</>,
          code: ({ className, children }) => {
            const raw = String(children ?? "");
            const m = /language-([\w-]+)/.exec(className ?? "");
            if (m || raw.includes("\n")) return <CodeBlock code={raw.replace(/\n$/, "")} lang={m?.[1]} maxHeight="24rem" />;
            if (ONLY_PATH_RE.test(raw)) return <a href={fileUrl(raw)} target="_blank" rel="noreferrer noopener"><code>{raw}</code></a>;
            return <code>{children}</code>;
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
});
