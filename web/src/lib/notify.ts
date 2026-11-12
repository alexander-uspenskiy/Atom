/** Browser notification helpers for long-running chat tasks. */
export const LONG_TASK_MS = 45_000;

export type NotifyStatus = "granted" | "default" | "denied" | "insecure" | "unsupported";

/** Why a system notification can or cannot be shown right now. */
export function notifyStatus(): NotifyStatus {
  try {
    if (!("Notification" in window)) return (window as Window).isSecureContext === false ? "insecure" : "unsupported";
    if (window.isSecureContext === false) return "insecure";
    return Notification.permission;
  } catch {
    return "unsupported";
  }
}

/** Ask for permission. Call this directly from a click handler so Chrome shows the prompt. */
export async function requestNotifyPermission(): Promise<NotifyStatus> {
  try {
    if (notifyStatus() === "default") await Notification.requestPermission();
  } catch {
    /* unsupported */
  }
  return notifyStatus();
}

/** True when the user is not looking at this tab (hidden tab or window without focus). */
export function userAway(): boolean {
  return document.hidden || !document.hasFocus();
}

/** Show a system notification. Returns false when it could not be shown (no permission / unsupported). */
export function notify(title: string, body: string): boolean {
  try {
    if (notifyStatus() !== "granted") return false;
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
