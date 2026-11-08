import { Wrench } from "lucide-react";
import { useChatTools, useTools } from "../api/hooks";
import { Page } from "../components/Page";
import { ToolList } from "../components/ToolList";
import { Card } from "../components/ui/Card";
import { EmptyState, ErrorState, Loading } from "../components/ui/Spinner";

export default function ToolsPage() {
  const chat = useChatTools();
  const agent = useTools();
  return (
    <Page title="Tools" subtitle="Everything the chat assistant and the web agents can call.">
      <div className="mx-auto max-w-3xl space-y-6">
        <section aria-labelledby="chat-tools">
          <h2 id="chat-tools" className="mb-2 text-sm font-semibold">Chat assistant ({chat.data?.length ?? 0})</h2>
          {chat.isLoading ? <Loading /> : chat.error ? <ErrorState error={chat.error} onRetry={() => void chat.refetch()} /> :
            chat.data?.length ? <ToolList tools={chat.data} /> : <Card><EmptyState icon={Wrench} title="No tools" /></Card>}
        </section>
        <section aria-labelledby="agent-tools">
          <h2 id="agent-tools" className="mb-2 text-sm font-semibold">Web agents ({agent.data?.length ?? 0})</h2>
          {agent.isLoading ? <Loading /> : agent.error ? <ErrorState error={agent.error} onRetry={() => void agent.refetch()} /> :
            agent.data?.length ? <ToolList tools={agent.data} /> : <Card><EmptyState icon={Wrench} title="No tools" /></Card>}
        </section>
      </div>
    </Page>
  );
}
