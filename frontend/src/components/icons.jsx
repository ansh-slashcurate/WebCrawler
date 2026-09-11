// Small hand-rolled icon set (stroke-based, 24x24 viewBox, currentColor) so
// the UI doesn't need an icon-library dependency for a handful of glyphs.
const base = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.75,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  viewBox: "0 0 24 24",
  "aria-hidden": "true",
};

export function IconGrid({ className }) {
  return (
    <svg className={className} {...base}>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </svg>
  );
}

export function IconLayers({ className }) {
  return (
    <svg className={className} {...base}>
      <path d="M12 3l8.5 5-8.5 5-8.5-5L12 3z" />
      <path d="M3.5 13l8.5 5 8.5-5" />
      <path d="M3.5 17.5l8.5 5 8.5-5" />
    </svg>
  );
}

export function IconLock({ className }) {
  return (
    <svg className={className} {...base}>
      <rect x="4.5" y="10.5" width="15" height="10" rx="2" />
      <path d="M7.5 10.5V7a4.5 4.5 0 019 0v3.5" />
    </svg>
  );
}

export function IconRefresh({ className }) {
  return (
    <svg className={className} {...base}>
      <path d="M20 11A8 8 0 105.5 16.5" />
      <path d="M20 4v7h-7" />
    </svg>
  );
}

export function IconPlay({ className }) {
  return (
    <svg className={className} {...base}>
      <path d="M7 4.5l13 7.5-13 7.5V4.5z" />
    </svg>
  );
}

export function IconSearch({ className }) {
  return (
    <svg className={className} {...base}>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="M20 20l-4.8-4.8" />
    </svg>
  );
}

export function IconChevronDown({ className }) {
  return (
    <svg className={className} {...base}>
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

export function IconExternalLink({ className }) {
  return (
    <svg className={className} {...base}>
      <path d="M14 4h6v6" />
      <path d="M10 14L20 4" />
      <path d="M18 13v6a1 1 0 01-1 1H6a1 1 0 01-1-1V7a1 1 0 011-1h6" />
    </svg>
  );
}

export function IconTrash({ className }) {
  return (
    <svg className={className} {...base}>
      <path d="M4 7h16" />
      <path d="M9 7V5a1 1 0 011-1h4a1 1 0 011 1v2" />
      <path d="M6 7l1 13a1 1 0 001 1h8a1 1 0 001-1l1-13" />
    </svg>
  );
}

export function IconCheckCircle({ className }) {
  return (
    <svg className={className} {...base}>
      <circle cx="12" cy="12" r="9" />
      <path d="M8.5 12.5l2.3 2.3L15.5 9" />
    </svg>
  );
}

export function IconXCircle({ className }) {
  return (
    <svg className={className} {...base}>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.5 9.5l5 5" />
      <path d="M14.5 9.5l-5 5" />
    </svg>
  );
}

export function IconArrowLeft({ className }) {
  return (
    <svg className={className} {...base}>
      <path d="M19 12H5" />
      <path d="M11 6l-6 6 6 6" />
    </svg>
  );
}

export function IconArrowRight({ className }) {
  return (
    <svg className={className} {...base}>
      <path d="M5 12h14" />
      <path d="M13 6l6 6-6 6" />
    </svg>
  );
}

export function IconAlertTriangle({ className }) {
  return (
    <svg className={className} {...base}>
      <path d="M12 4l9.5 16H2.5L12 4z" />
      <path d="M12 10v4" />
      <path d="M12 17.5v.01" />
    </svg>
  );
}

export function IconMessageCircle({ className }) {
  return (
    <svg className={className} {...base}>
      <path d="M4 12a8 8 0 1114.6 4.6L20 20l-3.6-1.4A8 8 0 014 12z" />
    </svg>
  );
}

export function IconTable({ className }) {
  return (
    <svg className={className} {...base}>
      <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
      <path d="M3.5 10h17" />
      <path d="M9.5 4.5v15" />
    </svg>
  );
}

export function IconVideo({ className }) {
  return (
    <svg className={className} {...base}>
      <rect x="3" y="6" width="13" height="12" rx="2" />
      <path d="M16 10l5-3v10l-5-3" />
    </svg>
  );
}
