import { useEffect, useState } from "react";
import { Bell } from "lucide-react";
import { Button } from "./ui/Button";
import { Card, CardHeader } from "./ui/Card";
import { notify, notifyStatus, requestNotifyPermission, type NotifyStatus } from "../lib/notify";

const TEXT: Record<NotifyStatus, string> = {
  granted: "Enabled. Atom shows a system notification when a chat task of 45 s or more finishes while you are in another tab or app.",
  default: "Not enabled yet. Click the button and choose Allow in the browser prompt.",
  denied: "Blocked by the browser. Click the lock icon in the address bar, set Notifications to Allow, then reload. Also check macOS System Settings → Notifications → your browser and Focus mode.",
  insecure: "This address is not a secure origin, so the browser disables notifications. Open Atom via http://localhost:PORT (or https).",
  unsupported: "This browser does not support notifications.",
};

export function NotificationsCard() {
  const [status, setStatus] = useState<NotifyStatus>(notifyStatus);
  useEffect(() => {
    const refresh = () => setStatus(notifyStatus());
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, []);

  return (
    <Card>
      <CardHeader title="Notifications" icon={<Bell className="h-3.5 w-3.5" />} />
      <div className="flex flex-wrap items-center justify-between gap-3 px-3 py-2.5">
        <p className="min-w-0 flex-1 text-xs text-muted">
          <span className="font-mono">{status}</span> — {TEXT[status]}
        </p>
        <div className="flex gap-2">
          {status === "default" && (
            <Button variant="primary" onClick={() => void requestNotifyPermission().then(setStatus)}>Enable notifications</Button>
          )}
          {status === "granted" && (
            <Button onClick={() => notify("Atom", "Test notification — it works.")}>Send test</Button>
          )}
        </div>
      </div>
    </Card>
  );
}
