// briefbot mark — a rounded "bot" tile (accent→accent2 gradient) with an antenna
// signal dot and three brief lines: a little bot that hands you a brief. Pure SVG
// so it stays crisp at any size and adapts to the active theme. Colors are driven
// from CSS (see topbar.css `.brand-logo …`) rather than inline `var()` — `var()`
// doesn't resolve inside SVG presentation attributes, only in CSS properties.
export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 28 28"
      fill="none"
      role="img"
      aria-label="briefbot logo"
      className="brand-logo"
    >
      <defs>
        <linearGradient
          id="bb-grad"
          x1="4"
          y1="6"
          x2="24"
          y2="25"
          gradientUnits="userSpaceOnUse"
        >
          <stop className="bb-g1" />
          <stop offset="1" className="bb-g2" />
        </linearGradient>
      </defs>

      {/* antenna — stem + signal dot */}
      <path className="bb-antenna" d="M14 6.2V3.4" strokeWidth="1.7" strokeLinecap="round" />
      <circle className="bb-dot" cx="14" cy="2.4" r="1.8" />

      {/* body / screen */}
      <rect x="4" y="6" width="20" height="19.4" rx="6" fill="url(#bb-grad)" />

      {/* the brief on screen */}
      <g fill="#fff">
        <rect x="8" y="11.6" width="12" height="2.1" rx="1.05" />
        <rect x="8" y="15.5" width="12" height="2.1" rx="1.05" fillOpacity="0.85" />
        <rect x="8" y="19.4" width="7.5" height="2.1" rx="1.05" fillOpacity="0.7" />
      </g>
    </svg>
  );
}
