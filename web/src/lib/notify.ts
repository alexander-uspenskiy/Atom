/** Browser notification helpers for long-running chat tasks. */
export const LONG_TASK_MS = 45_000;

export function requestNotifyPermission(): void {
  try {
    if ("Notification" in window && Notification.permission === "default") void Notification.requestPermission();
  } catch {
    /* unsupported */
  }
}

/** Show a system notification. Returns false when it could not be shown (no permission / unsupported). */
export function notify(title: string, body: string): boolean {
  try {
    if (!("Notification" in window) || Notification.permission !== "granted") return false;
    const n = new Notification(title, { body, tag: "atom-chat-done" });
    n.onclick = () => {
      window.focus();
      n.close();
    };
    return true;
  } catch {
    return false;
  }
}
