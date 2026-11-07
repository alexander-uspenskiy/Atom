import { ShieldCheck } from "lucide-react";
import { useActions } from "../api/hooks";
import { Page } from "../components/Page";
import { ApprovalCard } from "../components/ApprovalCard";
import { Badge } from "../components/ui/Badge";
import { EmptyState, ErrorState, Loading } from "../components/ui/Spinner";

export default function ApprovalsPage() {
  const pending = useActions("pending");
  const all = useActions();
  const decided = (all.data ?? []).filter((a) => a.status !== "pending").sort((a, b) => (b.decided_at ?? b.created_at ?? 0) - (a.decided_at ?? a.created_at ?? 0)).slice(0, 20);

  return (
    <Page title="Approvals" subtitle="Actions the assistant proposed. Nothing happens until you approve it.">
      <div className="mx-auto max-w-3xl space-y-6">
        <section aria-label="Pending approvals" className="space-y-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            Pending {pending.data && <Badge tone={pending.data.length ? "warn" : "neutral"}>{pending.data.length}</Badge>}
          </h2>
          {pending.isLoading && <Loading />}
          {pending.error && <ErrorState error={pending.error} onRetry={() => void pending.refetch()} />}
          {pending.data?.length === 0 && (
            <div className="rounded-lg border border-dashed border-line">
              <EmptyState icon={ShieldCheck} title="Nothing waiting for approval" hint="When the assistant proposes a schedule, agent, skill or memory, it shows up here and in the chat." />
            </div>
          )}
          {pending.data?.map((a) => <ApprovalCard key={a.id} action={a} />)}
        </section>

        <section aria-label="Recently decided" className="space-y-3">
          <h2 className="text-sm font-semibold">Recently decided</h2>
          {all.isLoading && <Loading />}
          {all.error && <ErrorState error={all.error} onRetry={() => void all.refetch()} />}
          {all.data && decided.length === 0 && <p className="text-sm text-muted">No decided actions yet.</p>}
          {decided.map((a) => <ApprovalCard key={a.id} action={a} compact />)}
        </section>
      </div>
    </Page>
  );
}
