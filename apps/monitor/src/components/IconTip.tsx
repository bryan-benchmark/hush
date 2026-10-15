import type { ButtonHTMLAttributes, ReactNode, SVGProps } from "react";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  tip: string;
  active?: boolean;
  danger?: boolean;
  size?: "md" | "lg";
  children: ReactNode;
};

export function IconTip({ tip, active, danger, size = "md", className = "", children, ...rest }: Props) {
  return (
    <button
      type="button"
      className={[
        "icon-tip",
        size === "lg" ? "lg" : "",
        active ? "on" : "",
        danger ? "danger" : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      aria-label={tip}
      data-tip={tip}
      {...rest}
    >
      {children}
      <span className="icon-tip-bubble" role="tooltip">
        {tip}
      </span>
    </button>
  );
}

export function Svg({ children, ...props }: { children: ReactNode } & SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      {children}
    </svg>
  );
}

export const Icons = {
  sports: (
    <Svg>
      <g transform="rotate(-38 12 12)">
        <path d="M2.4 12c0 0 2.6-6.4 9.6-6.4S21.6 12 21.6 12s-2.6 6.4-9.6 6.4S2.4 12 2.4 12z" />
        <path d="M7.2 12c1.6-1.15 8-1.15 9.6 0" />
        <path d="M9.6 10.15v3.7M12 9.9v4.2M14.4 10.15v3.7" />
      </g>
    </Svg>
  ),
  tv: (
    <Svg>
      <rect x="3" y="5" width="18" height="12" rx="2" />
      <path d="M8 20h8M12 17v3" />
    </Svg>
  ),
  movie: (
    <Svg>
      {/* side-view film projector */}
      <circle cx="8.2" cy="11.2" r="4.4" />
      <circle cx="8.2" cy="11.2" r="1.5" />
      <path d="M12.4 9.2h4.2l3.2-2.4v8.8l-3.2-2.4H12.4" />
      <path d="M6.4 15.6 5.2 20M10 15.6l1.2 4.4" />
      <circle cx="15.6" cy="6.2" r="1.1" />
    </Svg>
  ),
  show: (
    <Svg>
      <rect x="3" y="5" width="18" height="12" rx="2" />
      <path d="M8 20h8M12 17v3" />
    </Svg>
  ),
  other: (
    <Svg>
      <circle cx="6.5" cy="12" r="1.35" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1.35" fill="currentColor" stroke="none" />
      <circle cx="17.5" cy="12" r="1.35" fill="currentColor" stroke="none" />
    </Svg>
  ),
  prime: (
    <Svg>
      <rect x="3" y="5" width="18" height="14" rx="3" />
      <path d="M10 9.5l5 2.5-5 2.5v-5z" fill="currentColor" stroke="none" />
    </Svg>
  ),
  netflix: (
    <Svg>
      <rect x="6" y="3" width="3.2" height="18" />
      <rect x="14.8" y="3" width="3.2" height="18" />
      <path d="M6 3l12 18" />
    </Svg>
  ),
  youtube: (
    <Svg>
      <rect x="3" y="6" width="18" height="12" rx="3" />
      <path d="M11 10l4 2-4 2v-4z" fill="currentColor" stroke="none" />
    </Svg>
  ),
  hulu: (
    <Svg>
      <path d="M5 7v10M9 7v10M5 12h4M14 11.5a2.5 2.5 0 1 1 5 0V17" />
    </Svg>
  ),
  cable: (
    <Svg>
      <path d="M4 10h7v8H4zM13 6h7v12h-7z" />
      <path d="M7 10V7h3" />
    </Svg>
  ),
  more: (
    <Svg>
      <circle cx="6" cy="12" r="1.2" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none" />
      <circle cx="18" cy="12" r="1.2" fill="currentColor" stroke="none" />
    </Svg>
  ),
  mic: (
    <Svg>
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M6 11a6 6 0 0 0 12 0M12 17v4M9 21h6" />
    </Svg>
  ),
  speaker: (
    <Svg>
      <path d="M4 9h4l5-4v14l-5-4H4V9z" />
      <path d="M16 9.5a3.5 3.5 0 0 1 0 5M18.5 7a7 7 0 0 1 0 10" />
    </Svg>
  ),
  refresh: (
    <Svg>
      <path d="M20 12a8 8 0 1 1-2.3-5.6" />
      <path d="M20 4v5h-5" />
    </Svg>
  ),
  play: (
    <Svg>
      <circle cx="12" cy="12" r="9" />
      <path d="M10 8.5l6 3.5-6 3.5v-7z" fill="currentColor" stroke="none" />
    </Svg>
  ),
  mute: (
    <Svg>
      <path d="M4 9h4l5-4v14l-5-4H4V9z" />
      <path d="M16 10l5 5M21 10l-5 5" />
    </Svg>
  ),
  silence: (
    <Svg>
      <path d="M5 10h4l4-3v10l-4-3H5v-4z" />
      <path d="M16 9l5 6M21 9l-5 6" />
    </Svg>
  ),
  crowd: (
    <Svg>
      <circle cx="8" cy="9" r="2.2" />
      <circle cx="16" cy="9" r="2.2" />
      <path d="M3.5 18c.8-3 2.8-4.5 4.5-4.5S11 15 11.8 18M12.2 18c.8-3 2.8-4.5 4.5-4.5s3.7 1.5 4.5 4.5" />
    </Svg>
  ),
  rain: (
    <Svg>
      <path d="M7 14a4.5 4.5 0 1 1 1.2-8.8A5.5 5.5 0 0 1 20 9.5 3.5 3.5 0 0 1 18 16H7z" />
      <path d="M9 18l-1 3M13 18l-1 3M17 18l-1 3" />
    </Svg>
  ),
  fire: (
    <Svg>
      <path d="M12 21c4-1.5 6-4.4 6-8.2 0-3.2-1.8-5.2-3.2-6.5-.3 2.2-1.4 3.3-2.8 3.8C12.4 7 12 4.8 12 3c-2.8 2-6 5.2-6 9.8C6 16.6 8 19.5 12 21z" />
    </Svg>
  ),
  pink: (
    <Svg>
      <path d="M4 14c2-4 4-6 8-6s6 2 8 6" />
      <path d="M4 18c2-3 4-4.5 8-4.5s6 1.5 8 4.5" />
      <path d="M4 10c2-3.5 4-5 8-5s6 1.5 8 5" />
    </Svg>
  ),
  brown: (
    <Svg>
      <path d="M4 16c3-1 6-1.5 8-1.5s5 .5 8 1.5" />
      <path d="M4 12c3-.4 6-.6 8-.6s5 .2 8 .6" />
      <path d="M4 8c3 .8 6 1.2 8 1.2s5-.4 8-1.2" />
    </Svg>
  ),
  hush: (
    <Svg>
      <path d="M4 12c2-3 4-4.5 8-4.5s6 1.5 8 4.5" />
      <path d="M6 16c1.5-1.8 3.5-2.6 6-2.6s4.5.8 6 2.6" />
      <path d="M9 9.5c.4-1.2 1.4-2 3-2s2.6.8 3 2" />
    </Svg>
  ),
  neon: (
    <Svg>
      <rect x="3.5" y="14" width="2" height="4" rx="0.5" fill="currentColor" stroke="none" />
      <rect x="6.5" y="9" width="2" height="9" rx="0.5" fill="currentColor" stroke="none" />
      <rect x="9.5" y="11" width="2" height="7" rx="0.5" fill="currentColor" stroke="none" />
      <rect x="12.5" y="6" width="2" height="12" rx="0.5" fill="currentColor" stroke="none" />
      <rect x="15.5" y="10" width="2" height="8" rx="0.5" fill="currentColor" stroke="none" />
      <rect x="18.5" y="8" width="2" height="10" rx="0.5" fill="currentColor" stroke="none" />
    </Svg>
  ),
  charge: (
    <Svg>
      <path d="M11 3 6 13h5l-1 8 7-12h-5l1-6z" fill="currentColor" stroke="none" />
    </Svg>
  ),
  volt: (
    <Svg>
      <path d="M4 16c1.5-5 3-8 4.5-8s2.5 4 4 8 2.5 8 4 8 3-5 4.5-8" />
      <path d="M4 19.5h16" />
    </Svg>
  ),
  drop: (
    <Svg>
      <path d="M12 3c3 5 6 8 6 11a6 6 0 0 1-12 0c0-3 3-6 6-11z" />
    </Svg>
  ),
  pad: (
    <Svg>
      <path d="M4 14c2-5 5-8 8-8s6 3 8 8" />
      <path d="M6 17c1.5-2.5 3.5-3.5 6-3.5s4.5 1 6 3.5" />
    </Svg>
  ),
  ocean: (
    <Svg>
      <path d="M3 14c2 2 3.5 2 5 0s3-2 5 0 3 2 5 0 3-2 5 0" />
      <path d="M3 18c2 2 3.5 2 5 0s3-2 5 0 3 2 5 0 3-2 5 0" />
    </Svg>
  ),
  stream: (
    <Svg>
      <path d="M6 4c0 4 3 4 3 8s-3 4-3 8" />
      <path d="M12 4c0 4 3 4 3 8s-3 4-3 8" />
      <path d="M18 4c0 4 2 4 2 8s-2 4-2 8" />
    </Svg>
  ),
  birds: (
    <Svg>
      <path d="M4 14c2-1 3.5-3 4.5-5 .4 2 1.6 3.5 3.5 4.5-2 .2-3.8 1.2-5 3" />
      <path d="M13 11c2-1 3.2-2.6 4-4.2.3 1.7 1.3 3 3 3.8-1.7.2-3.2 1-4.2 2.6" />
    </Svg>
  ),
  breeze: (
    <Svg>
      <path d="M4 9h10a2.5 2.5 0 1 0-2.2-3.5" />
      <path d="M4 13h13a2.2 2.2 0 1 1-1.8 3.4" />
      <path d="M4 17h8" />
    </Svg>
  ),
  night: (
    <Svg>
      <path d="M14 4a7 7 0 1 0 6 10 6 6 0 0 1-6-10z" />
      <path d="M5 18l.5 1.5L7 20l-1.5.5L5 22l-.5-1.5L3 20l1.5-.5L5 18z" />
    </Svg>
  ),
  chimes: (
    <Svg>
      <path d="M12 3v3" />
      <path d="M8 6h8" />
      <path d="M9 6v11M12 6v13M15 6v10" />
      <path d="M9 17h.01M12 19h.01M15 16h.01" />
    </Svg>
  ),
  piano: (
    <Svg>
      <rect x="3" y="7" width="18" height="10" rx="1.5" />
      <path d="M8 7v10M12 7v10M16 7v10" />
      <path d="M8 7v5h1.2V7M12 7v5h1.2V7M16 7v5h1.2V7" fill="currentColor" stroke="none" />
    </Svg>
  ),
  harp: (
    <Svg>
      <path d="M7 4c5 0 10 3 10 16" />
      <path d="M7 4v16" />
      <path d="M7 8h7M7 12h8.5M7 16h9.2" />
    </Svg>
  ),
  meadow: (
    <Svg>
      <path d="M4 16c2-4 4-6 8-6s6 2 8 6" />
      <path d="M8 16c.5-2.5 1.5-4 4-4s3.5 1.5 4 4" />
      <path d="M12 6v4M10 8h4" />
    </Svg>
  ),
  star: (
    <Svg>
      <path d="M12 3.5l2.4 4.9 5.4.8-3.9 3.8.9 5.4L12 15.8 7.2 18.4l.9-5.4L4.2 9.2l5.4-.8L12 3.5z" />
    </Svg>
  ),
  keep: (
    <Svg>
      <path d="M20 7l-9 9-4-4" />
      <path d="M4 12a8 8 0 1 0 3-6.3" />
    </Svg>
  ),
  skip: (
    <Svg>
      <circle cx="12" cy="12" r="9" />
      <path d="M8 12h8M14 9l3 3-3 3" />
    </Svg>
  ),
  fixShow: (
    <Svg>
      <path d="M5 12l4 4L19 6" />
    </Svg>
  ),
  fixAd: (
    <Svg>
      <path d="M12 7v6M12 17h.01" />
      <path d="M4 8l8-4 8 4v8l-8 4-8-4V8z" />
    </Svg>
  ),
  autoOn: (
    <Svg>
      <path d="M12 3v3M12 18v3M3 12h3M18 12h3" />
      <circle cx="12" cy="12" r="4" />
    </Svg>
  ),
  autoOff: (
    <Svg>
      <circle cx="12" cy="12" r="4" />
      <path d="M4 4l16 16" />
    </Svg>
  ),
  stop: (
    <Svg>
      <rect x="6" y="6" width="12" height="12" rx="2" />
    </Svg>
  ),
  start: (
    <Svg>
      <circle cx="12" cy="12" r="9" />
      <path d="M10 8.5l6 3.5-6 3.5v-7z" fill="currentColor" stroke="none" />
    </Svg>
  ),
  replay: (
    <Svg>
      <path d="M4 12a8 8 0 1 0 2.2-5.5" />
      <path d="M4 4v5h5" />
      <path d="M10 9l5 3-5 3V9z" fill="currentColor" stroke="none" />
    </Svg>
  ),
};
