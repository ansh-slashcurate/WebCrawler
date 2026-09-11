// Shared visual primitives for the control panel - a consistent white/blue
// SaaS look built directly on Tailwind utility classes, kept in one place so
// every screen shares the same card/button/input/badge styling instead of
// re-deriving it per component.

export function Card({ children, className = "" }) {
  return (
    <div
      className={`rounded-xl border border-slate-200 bg-white shadow-sm shadow-slate-200/50 dark:border-slate-800 dark:bg-slate-900 dark:shadow-none ${className}`}
    >
      {children}
    </div>
  );
}

export function CardHeader({ title, action, icon: Icon }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4 dark:border-slate-800">
      <div className="flex items-center gap-2">
        {Icon && <Icon className="h-4 w-4 text-blue-600 dark:text-blue-400" />}
        <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</h2>
      </div>
      {action}
    </div>
  );
}

export function Eyebrow({ children }) {
  return (
    <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">{children}</h2>
  );
}

const BUTTON_VARIANTS = {
  primary:
    "bg-blue-600 text-white shadow-sm hover:bg-blue-500 focus-visible:ring-blue-500/40 disabled:hover:bg-blue-600",
  secondary:
    "border border-slate-300 bg-white text-slate-700 shadow-sm hover:bg-slate-50 focus-visible:ring-blue-500/30 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700",
  ghost:
    "text-slate-600 hover:bg-slate-100 focus-visible:ring-blue-500/30 dark:text-slate-300 dark:hover:bg-slate-800",
  danger:
    "text-red-600 hover:bg-red-50 focus-visible:ring-red-500/30 dark:text-red-400 dark:hover:bg-red-900/20",
};

const BUTTON_SIZES = {
  sm: "px-2.5 py-1.5 text-xs",
  md: "px-4 py-2 text-sm",
};

export function Button({ variant = "primary", size = "md", className = "", children, ...props }) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors focus-visible:outline-none focus-visible:ring-4 disabled:cursor-not-allowed disabled:opacity-50 ${BUTTON_VARIANTS[variant]} ${BUTTON_SIZES[size]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

export const inputClass =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-4 focus:ring-blue-500/15 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100";

export const labelClass = "mb-1.5 block text-xs font-medium text-slate-600 dark:text-slate-400";

const BADGE_TONES = {
  default: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
  blue: "bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
  success: "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300",
  danger: "bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300",
  warning: "bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300",
};

export function Badge({ tone = "default", className = "", children }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${BADGE_TONES[tone]} ${className}`}
    >
      {children}
    </span>
  );
}

export function Spinner({ className = "h-4 w-4" }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
    </svg>
  );
}

export function EmptyState({ icon: Icon, title, description }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-slate-200 px-6 py-10 text-center dark:border-slate-800">
      {Icon && <Icon className="h-6 w-6 text-slate-300 dark:text-slate-600" />}
      <p className="text-sm font-medium text-slate-600 dark:text-slate-300">{title}</p>
      {description && <p className="max-w-sm text-xs text-slate-400 dark:text-slate-500">{description}</p>}
    </div>
  );
}
