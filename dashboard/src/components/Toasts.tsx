import { useEffect } from "react";
import { useToasts, type Toast } from "../state/toasts";

const DISMISS_MS = 5000;

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  useEffect(() => {
    const t = setTimeout(onDismiss, DISMISS_MS);
    return () => clearTimeout(t);
  }, [onDismiss]);

  return (
    <div className={`toast ${toast.tone}`} role="status" onClick={onDismiss}>
      {toast.message}
    </div>
  );
}

export function Toasts() {
  const toasts = useToasts((s) => s.toasts);
  const dismiss = useToasts((s) => s.dismiss);
  if (toasts.length === 0) return null;
  return (
    <div className="toasts">
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />
      ))}
    </div>
  );
}
