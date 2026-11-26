"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";

export type ToastTone = "success" | "error" | "info" | "warning";

interface Toast {
  id: number;
  tone: ToastTone;
  title: string;
  detail?: string;
}

type Notify = (tone: ToastTone, title: string, detail?: string) => void;

const ToastContext = createContext<Notify | null>(null);

/** Feedback after an action (upload, review decision, export). No-op outside a provider. */
export function useToast(): Notify {
  return useContext(ToastContext) ?? (() => undefined);
}

const ICON = { success: CheckCircle2, error: XCircle, info: Info, warning: AlertTriangle };
const TONE = {
  success: "border-processed/40 text-processed",
  error: "border-failed/40 text-failed",
  info: "border-sky-500/40 text-sky-300",
  warning: "border-inconsistency/40 text-inconsistency",
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const next = useRef(1);

  const dismiss = useCallback((id: number) => setItems((all) => all.filter((t) => t.id !== id)), []);
  const notify = useCallback<Notify>((tone, title, detail) => {
    const id = next.current++;
    setItems((all) => [...all.slice(-3), { id, tone, title, detail }]);
  }, []);

  return (
    <ToastContext.Provider value={notify}>
      {children}
      {/* Polite live region: screen readers announce feedback without stealing focus. */}
      <div
        aria-live="polite"
        className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2"
      >
        {items.map((t) => (
          <ToastItem key={t.id} toast={t} onDone={() => dismiss(t.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function ToastItem({ toast, onDone }: { toast: Toast; onDone: () => void }) {
  const Icon = ICON[toast.tone];
  useEffect(() => {
    const ms = toast.tone === "error" ? 9000 : 5000;
    const timer = setTimeout(onDone, ms);
    return () => clearTimeout(timer);
  }, [toast, onDone]);
  return (
    <div
      role={toast.tone === "error" ? "alert" : "status"}
      className={clsx(
        "evx-toast pointer-events-auto flex items-start gap-2.5 rounded-lg border bg-navy-900/95 px-3.5 py-3 shadow-xl shadow-black/40 backdrop-blur",
        TONE[toast.tone],
      )}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-slate-100">{toast.title}</p>
        {toast.detail && <p className="mt-0.5 text-xs text-slate-400">{toast.detail}</p>}
      </div>
      <button type="button" onClick={onDone} aria-label="Dismiss" className="text-slate-500 hover:text-slate-200">
        <X className="h-4 w-4" aria-hidden />
      </button>
    </div>
  );
}
