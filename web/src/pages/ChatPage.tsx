import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderGit2, MessageSquarePlus, MessagesSquare, Pencil, Plus, Trash2 } from "lucide-react";
import { api, streamChat } from "../api/client";
import { qk, useActions, useConversations, useProjects } from "../api/hooks";
import type { ConversationInfo, ConversationSummary, Message, PendingAction, Project } from "../api/types";
import { emptyTurn, turnReducer, type ToolView } from "../lib/chatState";
import { lsGet, lsSet } from "../lib/storage";
import { errMsg, fmtRelative, truncate } from "../lib/format";
import { cn } from "../lib/cn";
import { Page } from "../components/Page";
import { Button, IconButton } from "../components/ui/Button";
import { ConfirmDialog } from "../components/ui/Dialog";
import { EmptyState, ErrorState, Loading } from "../components/ui/Spinner";
import { useToast } from "../components/ui/Toast";
import { AssistantView, type AsstView } from "../components/chat/AssistantView";
import { Composer, type ChatEffort, type ChatPrefs } from "../components/chat/Composer";
import { MessageActions } from "../components/chat/MessageActions";
import { ProjectDialog } from "../components/chat/ProjectDialog";
import { DropOverlay, ImageGrid, useAttachments, useDropImages } from "../components/chat/Attachments";

const PREFS_KEY = "atom-chat-prefs";
function loadPrefs(): ChatPrefs {
  try {
    const p = JSON.parse(lsGet(PREFS_KEY) ?? "null") as Partial<ChatPrefs> | null;
    const effort = p?.effort === "low" || p?.effort === "medium" || p?.effort === "xhigh" ? p.effort : "low";
    const mode = p?.mode === "manual" || p?.mode === "plan" ? p.mode : "auto";
    return { thinking: p?.thinking === true, effort: effort as ChatEffort, workdir: typeof p?.workdir === "string" ? p.workdir : "", mode };
  } catch {
    return { thinking: false, effort: "low" };
  }
}

const SUGGESTIONS = [
  "Every weekday at 8am, check Hacker News and summarize the top 5 stories",
  "Create an agent that monitors a product page for price changes",
  "What do you remember about my preferences?",
];

function parseToolResult(content?: string | null): { ok?: boolean; result: unknown } {
  if (!content) return { result: "" };
  try {
    const j = JSON.parse(content) as unknown;
    const ok = j && typeof j === "object" && "ok" in j && typeof (j as { ok: unknown }).ok === "boolean" ? (j as { ok: boolean }).ok : undefined;
    return { ok, result: j };
  } catch {
    return { result: content };
  }
}

/** Convert persisted messages into render models (tool results folded into their calls). */
const countUsers = (ms?: Message[]) => (ms ?? []).filter((m) => m.role === "user").length;

function toViews(messages: Message[], actions: Map<string, PendingAction>, summary?: ConversationSummary | null): ({ kind: "user"; m: Message } | { kind: "asst"; v: AsstView } | { kind: "summary"; text: string; id: string })[] {
  const toolMsgs = new Map<string, Message>();
  for (const m of messages) if (m.role === "tool" && m.tool_call_id) toolMsgs.set(m.tool_call_id, m);
  const claimed = new Set<string>();
  const out: ({ kind: "user"; m: Message } | { kind: "asst"; v: AsstView } | { kind: "summary"; text: string; id: string })[] = [];
  let divided = !summary?.text;
  let lastAsk: Message | undefined;
  for (const m of messages) {
    if (!divided && (m.seq ?? 0) > (summary?.upto_seq ?? 0)) {
      out.push({ kind: "summary", text: summary?.text ?? "", id: "summary" });
      divided = true;
    }
    if (m.role === "user") { out.push({ kind: "user", m }); lastAsk = m; }
    else if (m.role === "assistant") {
      const tools: ToolView[] = [];
      const actionIds = new Set<string>();
      const runIds = new Set<string>();
      if (m.action_id) actionIds.add(m.action_id);
      if (m.run_id) runIds.add(m.run_id);
      for (const c of m.tool_calls ?? []) {
        const id = c.id ?? `${m.id}-${tools.length}`;
        const tm = c.id ? toolMsgs.get(c.id) : undefined;
        if (c.id) claimed.add(c.id);
        const r = parseToolResult(tm?.content);
        tools.push({ id, name: c.name, args: c.arguments, ok: r.ok, result: r.result, done: true });
        if (tm?.action_id) actionIds.add(tm.action_id);
        if (tm?.run_id) runIds.add(tm.run_id);
      }
      const acts: PendingAction[] = [];
      const missing: string[] = [];
      for (const id of actionIds) {
        const a = actions.get(id);
        if (a) acts.push(a);
        else missing.push(id);
      }
      out.push({
        kind: "asst",
        v: { key: m.id, reasoning: m.reasoning ?? "", content: m.content ?? "", tools, actions: acts, pendingActionIds: missing, runIds: [...runIds], stats: m.stats, at: m.created_at, ask: lastAsk?.content ?? undefined },
      });
    }
  }
  // tool messages that no assistant call claimed: show as standalone result cards
  for (const m of messages) {
    if (m.role === "tool" && !(m.tool_call_id && claimed.has(m.tool_call_id)) && (m.content || m.run_id || m.action_id)) {
      const r = parseToolResult(m.content);
      out.push({
        kind: "asst",
        v: {
          key: m.id, reasoning: "", content: "", tools: m.content ? [{ id: m.id, name: "tool result", ok: r.ok, result: r.result, done: true }] : [],
          actions: m.action_id && actions.get(m.action_id) ? [actions.get(m.action_id) as PendingAction] : [], pendingActionIds: m.action_id && !actions.get(m.action_id) ? [m.action_id] : [],
          runIds: m.run_id ? [m.run_id] : [],
        },
      });
    }
  }
  return out;
}

export default function ChatPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const nav = useNavigate();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const convId = params.get("c");
  const conversations = useConversations();
  const projectsQ = useProjects();
  const [projDialog, setProjDialog] = useState<{ project: Project | null } | null>(null);
  const [projToDelete, setProjToDelete] = useState<Project | null>(null);
  const actionsQ = useActions();
  const convQ = useQuery({ queryKey: qk.conversation(convId ?? ""), queryFn: () => api.conversation(convId as string), enabled: !!convId });
  const [turn, dispatch] = useReducer(turnReducer, emptyTurn);
  const [draft, setDraft] = useState("");
  const attachments = useAttachments();
  const drop = useDropImages(attachments.add, true);
  const [prefs, setPrefs] = useState<ChatPrefs>(loadPrefs);
  const [toDelete, setToDelete] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const turnConv = useRef<string | null>(null);
  const baseUsers = useRef(0); // persisted user-message count when the live turn began

  const updatePrefs = (p: ChatPrefs) => {
    setPrefs(p);
    lsSet(PREFS_KEY, JSON.stringify(p));
  };

  const send = useCallback(
    async (text: string, forConv?: string, images: string[] = []) => {
      const content = text.trim();
      if ((!content && !images.length) || abortRef.current) return;
      let id = forConv ?? convId;
      try {
        if (!id) {
          const c = await api.createConversation(null, params.get("p"));
          id = c.id;
          setParams({ c: id }, { replace: true });
          void qc.invalidateQueries({ queryKey: qk.conversations });
        }
      } catch (e) {
        toast.error(`Could not create conversation: ${errMsg(e)}`);
        return;
      }
      const ctl = new AbortController();
      abortRef.current = ctl;
      turnConv.current = id;
      stick.current = true;
      setDraft("");
      attachments.clear();
      baseUsers.current = countUsers(qc.getQueryData<{ messages?: Message[] }>(qk.conversation(id))?.messages);
      dispatch({ t: "start", user: content, images });
      let error: string | null = null;
      let gotEvent = false;
      let aborted = false;
      try {
        await streamChat(id, { content, thinking: prefs.thinking, effort: prefs.effort, mode: prefs.mode ?? "auto", ...(prefs.workdir ? { workdir: prefs.workdir } : {}), ...(images.length ? { images } : {}) }, (ev) => {
          gotEvent = true;
          if (ev.type === "error") error = ev.detail ?? "The assistant returned an error.";
          dispatch({ t: "ev", ev });
        }, ctl.signal);
      } catch (e) {
        if (!(e instanceof DOMException && e.name === "AbortError") && !ctl.signal.aborted) error = errMsg(e);
      }
      aborted = ctl.signal.aborted;
      // Sync persisted state, then drop the optimistic turn.
      dispatch({ t: "end", error });
      // After Stop the server needs a moment to notice the disconnect and save the partial reply.
      if (aborted) await new Promise((r) => setTimeout(r, 1200));
      try {
        await Promise.all([
          qc.refetchQueries({ queryKey: qk.conversation(id) }),
          qc.invalidateQueries({ queryKey: qk.conversations }),
          qc.invalidateQueries({ queryKey: ["actions"] }),
          qc.invalidateQueries({ queryKey: ["runs"] }),
        ]);
      } catch {
        /* keep going */
      }
      abortRef.current = null;
      dispatch({ t: "clear" });
      if (error) {
        toast.error(error);
        if (!gotEvent) setDraft(content); // nothing was received: let the user retry
      }
    },
    [convId, params, prefs, qc, setParams, toast, attachments],
  );

  // Prefill / auto-send from router state or ?prompt=
  const handled = useRef<string | null>(null);
  useEffect(() => {
    if (handled.current === location.key) return;
    const st = (location.state ?? null) as { prompt?: string; send?: string } | null;
    const qp = params.get("prompt");
    if (st?.send && convId) {
      handled.current = location.key;
      nav(location.pathname + location.search, { replace: true, state: null });
      void send(st.send, convId);
    } else if (st?.prompt || qp) {
      handled.current = location.key;
      setDraft(st?.prompt ?? qp ?? "");
      if (qp) {
        const p = new URLSearchParams(params);
        p.delete("prompt");
        setParams(p, { replace: true });
      } else nav(location.pathname + location.search, { replace: true, state: null });
    }
  }, [location, params, convId, nav, send, setParams]);

  const stop = () => abortRef.current?.abort();
  /** Run an earlier prompt again (sent as a new message at the end of the chat). */
  const resend = (text: string) => { if (!abortRef.current) void send(text); };
  // Deliberately no abort on unmount: navigating to another page must not stop a running reply
  // (the server cancels the run when the client disconnects). Only the Stop button aborts.

  const actionMap = useMemo(() => new Map((actionsQ.data ?? []).map((a) => [a.id, a])), [actionsQ.data]);
  const views = useMemo(() => toViews(convQ.data?.messages ?? [], actionMap, convQ.data?.summary), [convQ.data?.messages, actionMap, convQ.data?.summary]);
  const showTurn = turn.user !== null && turnConv.current === convId;
  // A mid-stream refetch can already contain the persisted user message; don't show it twice.
  const userPersisted = countUsers(convQ.data?.messages) > baseUsers.current;

  // Auto-scroll while streaming (only if the user hasn't scrolled up).
  const sig = `${views.length}|${turn.msgs.map((m) => m.content.length + m.reasoning.length + m.tools.length).join(",")}|${turn.user}`;
  useEffect(() => {
    const el = scroller.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [sig, convId]);
  useEffect(() => {
    stick.current = true;
  }, [convId]);

  const del = async () => {
    if (!toDelete) return;
    try {
      await api.deleteConversation(toDelete);
      void qc.invalidateQueries({ queryKey: qk.conversations });
      if (toDelete === convId) setParams({}, { replace: true });
      toast.success("Conversation deleted");
    } catch (e) {
      toast.error(errMsg(e));
    }
    setToDelete(null);
  };

  const list = conversations.data ?? [];
  const projects = projectsQ.data ?? [];
  const activeProjectId = convId ? (convQ.data?.project_id ?? list.find((c) => c.id === convId)?.project_id ?? null) : params.get("p");
  const activeProject = projects.find((p) => p.id === activeProjectId) ?? null;
  const delProject = async () => {
    if (!projToDelete) return;
    try {
      await api.deleteProject(projToDelete.id);
      void qc.invalidateQueries({ queryKey: qk.projects });
      void qc.invalidateQueries({ queryKey: qk.conversations });
      if (params.get("p") === projToDelete.id) setParams({}, { replace: true });
      toast.success("Project deleted (its chats were kept)");
    } catch (e) {
      toast.error(errMsg(e));
    }
    setProjToDelete(null);
    setProjDialog(null);
  };
  const chatRow = (c: ConversationInfo) => (
    <div key={c.id} className={cn("group flex items-center gap-1 rounded-md pr-1", c.id === convId ? "bg-accent/10" : "hover:bg-surface2")}>
      <button type="button" className="min-w-0 flex-1 px-2 py-1.5 text-left" aria-current={c.id === convId} onClick={() => setParams({ c: c.id })}>
        <div className={cn("truncate text-sm", c.id === convId && "font-medium text-accent")}>{truncate(c.title, 60) || "Untitled chat"}</div>
        <div className="text-[11px] text-muted">{c.message_count ?? 0} msgs · {fmtRelative(c.updated_at)}</div>
      </button>
      <IconButton label="Delete conversation" className="opacity-0 focus-visible:opacity-100 group-hover:opacity-100" onClick={() => setToDelete(c.id)}>
        <Trash2 className="h-3.5 w-3.5" />
      </IconButton>
    </div>
  );
  const loose = list.filter((c) => !c.project_id || !projects.some((p) => p.id === c.project_id));

  return (
    <Page
      title="Chat"
      subtitle="Talk to the model — it can propose schedules, agents, skills and memories, and start web-agent runs."
      fill
    >
      <div className="flex h-full">
        <aside className="flex w-52 shrink-0 flex-col border-r border-line bg-surface xl:w-60" aria-label="Conversations">
          <div className="p-2">
            <Button className="w-full" icon={<MessageSquarePlus className="h-4 w-4" />} onClick={() => setParams({}, { replace: false })}>
              New chat
            </Button>
            <Button className="mt-1.5 w-full" icon={<FolderGit2 className="h-4 w-4" />} onClick={() => setProjDialog({ project: null })}>
              New project
            </Button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-1.5 pb-2">
            {conversations.isLoading && <Loading />}
            {conversations.error && <ErrorState error={conversations.error} onRetry={() => void conversations.refetch()} />}
            {!conversations.isLoading && !conversations.error && list.length === 0 && (
              <p className="px-2 py-6 text-center text-xs text-muted">No conversations yet.</p>
            )}
            {projects.length > 0 && <div className="px-2 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-muted">Projects</div>}
            {projects.map((p) => {
              const chats = list.filter((c) => c.project_id === p.id);
              const selected = !convId && params.get("p") === p.id;
              return (
                <div key={p.id} className="mb-1">
                  <div className={cn("group flex items-center gap-1 rounded-md pr-1", selected ? "bg-accent/10" : "hover:bg-surface2")}>
                    <button type="button" className="flex min-w-0 flex-1 items-center gap-1.5 px-2 py-1.5 text-left" title={p.folder ?? "No project folder"} onClick={() => setParams({ p: p.id })}>
                      <FolderGit2 className="h-3.5 w-3.5 shrink-0 text-muted" aria-hidden />
                      <span className={cn("truncate text-sm font-medium", selected && "text-accent")}>{p.name}</span>
                    </button>
                    <IconButton label={`New chat in ${p.name}`} onClick={() => setParams({ p: p.id })}><Plus className="h-3.5 w-3.5" /></IconButton>
                    <IconButton label={`Edit ${p.name}`} className="opacity-0 focus-visible:opacity-100 group-hover:opacity-100" onClick={() => setProjDialog({ project: p })}>
                      <Pencil className="h-3.5 w-3.5" />
                    </IconButton>
                  </div>
                  <div className="ml-3 border-l border-line pl-1">{chats.map(chatRow)}</div>
                </div>
              );
            })}
            {projects.length > 0 && loose.length > 0 && <div className="px-2 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-muted">Chats</div>}
            {loose.map(chatRow)}
          </div>
        </aside>

        <section className="relative flex min-w-0 flex-1 flex-col" data-testid="chat-pane" {...drop.handlers}>
          <DropOverlay show={drop.over} />
          <div
            ref={scroller}
            className="min-h-0 flex-1 overflow-y-auto"
            onScroll={(e) => {
              const el = e.currentTarget;
              stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
            }}
          >
            <div className="mx-auto max-w-3xl space-y-4 px-4 py-4" data-testid="messages">
              {!convId && !showTurn && (
                <EmptyState
                  icon={MessagesSquare}
                  title={activeProject ? `New chat in ${activeProject.name}` : "Start a conversation"}
                  hint={activeProject ? (activeProject.folder ? `Terminal commands start in ${activeProject.folder}` : "This project has no folder; the global terminal folder is used.") : "Ask a question, or tell Atom what to automate."}
                  action={
                    <div className="flex max-w-md flex-col gap-1.5">
                      {SUGGESTIONS.map((s) => (
                        <button key={s} type="button" className="rounded-md border border-line px-3 py-1.5 text-left text-xs hover:bg-surface2" onClick={() => setDraft(s)}>
                          {s}
                        </button>
                      ))}
                    </div>
                  }
                />
              )}
              {convId && convQ.isLoading && <Loading />}
              {convId && convQ.error && <ErrorState error={convQ.error} onRetry={() => void convQ.refetch()} />}
              {convId && convQ.data && views.length === 0 && !showTurn && (
                <EmptyState icon={MessagesSquare} title="Empty conversation" hint="Send a message to begin." />
              )}
              {views.map((x) =>
                x.kind === "summary" ? (
                  <details key={x.id} className="rounded-md border border-dashed border-line px-3 py-1.5 text-xs text-muted" data-testid="summary-divider">
                    <summary className="cursor-pointer select-none">Earlier messages were summarised to save context. The model sees this summary instead of them.</summary>
                    <div className="mt-2 whitespace-pre-wrap text-fg">{x.text}</div>
                  </details>
                ) : x.kind === "user" ? <UserBubble key={x.m.id} text={x.m.content ?? ""} images={x.m.images} at={x.m.created_at} onResend={resend} busy={turn.streaming} /> : <AssistantView key={x.v.key} v={x.v} onResend={resend} busy={turn.streaming} />,
              )}
              {showTurn && (
                <>
                  {turn.user !== null && !userPersisted && <UserBubble text={turn.user} images={turn.userImages} />}
                  {turn.msgs.map((m, i) => (
                    <AssistantView
                      key={m.key}
                      v={{ ...m, pendingActionIds: [], streaming: turn.streaming && !m.ended && i === turn.msgs.length - 1 }}
                    />
                  ))}
                  {turn.streaming && (turn.msgs.length === 0 || turn.msgs[turn.msgs.length - 1].ended) && (
                    <AssistantView v={{ key: "pending", reasoning: "", content: "", tools: [], actions: [], pendingActionIds: [], runIds: [], streaming: true }} />
                  )}
                  {turn.note && <p className="text-xs text-muted" role="status">{turn.note}</p>}
                  {turn.error && (
                    <div role="alert" className="rounded-md border border-err/40 bg-err/10 px-3 py-2 text-sm text-err">{turn.error}</div>
                  )}
                </>
              )}
            </div>
          </div>
          <Composer
            value={draft}
            onChange={setDraft}
            onSend={() => void send(draft, undefined, attachments.ids)}
            onStop={stop}
            streaming={turn.streaming}
            prefs={prefs}
            onPrefs={updatePrefs}
            autoFocusKey={convId}
            attachments={attachments}
            project={activeProject}
            convId={convId}
            onCompacted={() => void qc.invalidateQueries({ queryKey: qk.conversation(convId ?? "") })}
          />
        </section>
      </div>
      <ProjectDialog
        open={projDialog !== null}
        project={projDialog?.project ?? null}
        onClose={() => setProjDialog(null)}
        onSaved={(p) => { if (!projDialog?.project) setParams({ p: p.id }); }}
        onDelete={(p) => setProjToDelete(p)}
      />
      <ConfirmDialog
        open={projToDelete !== null}
        onClose={() => setProjToDelete(null)}
        onConfirm={() => void delProject()}
        title="Delete project?"
        message="The project is removed. Its chats are kept and move to the main chat list."
      />
      <ConfirmDialog
        open={toDelete !== null}
        onClose={() => setToDelete(null)}
        onConfirm={() => void del()}
        title="Delete conversation?"
        message="The conversation and its messages will be permanently removed."
      />
    </Page>
  );
}

function UserBubble({ text, images, at, onResend, busy }: { text: string; images?: string[]; at?: number; onResend?: (t: string) => void; busy?: boolean }) {
  return (
    <div className="flex justify-end" data-testid="user-msg">
      <div className="flex max-w-[85%] flex-col items-end gap-1.5">
        {images && images.length > 0 && <ImageGrid ids={images} className="justify-end" />}
        {text && <div className="whitespace-pre-wrap break-words rounded-lg rounded-tr-sm bg-accent px-3 py-2 text-sm text-accent-fg">{text}</div>}
        {(text || at) && <MessageActions at={at} text={text} onResend={onResend && text ? () => onResend(text) : undefined} disabled={busy} resendTitle="Send this prompt again" className="justify-end" />}
      </div>
    </div>
  );
}
