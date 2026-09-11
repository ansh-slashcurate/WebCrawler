import { IconCheckCircle, IconXCircle } from "./icons";

export default function StatusDot({ ok, label }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-sm">
      {ok ? (
        <IconCheckCircle className="h-4 w-4 shrink-0 text-emerald-500" />
      ) : (
        <IconXCircle className="h-4 w-4 shrink-0 text-red-500" />
      )}
      <span className="text-slate-700 dark:text-slate-300">{label}</span>
    </span>
  );
}
