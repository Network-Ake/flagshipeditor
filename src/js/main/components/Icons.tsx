// Inline stroke icons.
//
// A CEP panel cannot load a webfont or a CDN sprite, and emoji render at a
// different weight and baseline on every host. Everything here is a 16×16
// stroke path on `currentColor`, so an icon inherits the colour and the
// disabled state of the control it sits in.

import React from "react";

export interface IconProps {
  size?: number;
  className?: string;
}

const BASE: React.SVGProps<SVGSVGElement> = {
  viewBox: "0 0 16 16",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.4,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  focusable: false,
  "aria-hidden": true,
};

function icon(path: React.ReactNode) {
  const Component: React.FC<IconProps> = ({ size = 14, className }) => (
    <svg {...BASE} width={size} height={size} className={className ? `icon ${className}` : "icon"}>
      {path}
    </svg>
  );
  return Component;
}

export const IconFolder = icon(
  <path d="M1.75 3.75a1 1 0 0 1 1-1h3.1l1.4 1.6h5a1 1 0 0 1 1 1v6.9a1 1 0 0 1-1 1h-9.5a1 1 0 0 1-1-1z" />
);

export const IconFilm = icon(
  <>
    <rect x="1.75" y="3.25" width="12.5" height="9.5" rx="1" />
    <path d="M4.75 3.25v9.5M11.25 3.25v9.5M1.75 8h12.5" />
  </>
);

export const IconMusic = icon(
  <>
    <path d="M6 12.25V4.4l7-1.65v7.6" />
    <circle cx="4.25" cy="12.25" r="1.75" />
    <circle cx="11.25" cy="10.35" r="1.75" />
  </>
);

export const IconSliders = icon(
  <>
    <path d="M3.25 13.25V9.5M3.25 6.5V2.75M8 13.25v-5.5M8 4.75V2.75M12.75 13.25v-2.5M12.75 7.75V2.75" />
    <path d="M1.75 8h3M6.5 6.25h3M11.25 9.25h3" />
  </>
);

export const IconEye = icon(
  <>
    <path d="M.9 8S3.5 3.6 8 3.6 15.1 8 15.1 8 12.5 12.4 8 12.4.9 8 .9 8" />
    <circle cx="8" cy="8" r="2.1" />
  </>
);

export const IconActivity = icon(<path d="M.9 8h3l2-5.4 4 10.8 2-5.4h3" />);

export const IconLock = icon(
  <>
    <rect x="3.25" y="7" width="9.5" height="6.5" rx="1" />
    <path d="M5.5 7V5.25a2.5 2.5 0 0 1 5 0V7" />
  </>
);

export const IconUnlock = icon(
  <>
    <rect x="3.25" y="7" width="9.5" height="6.5" rx="1" />
    <path d="M5.5 7V5.25a2.5 2.5 0 0 1 4.85-.85" />
  </>
);

export const IconRefresh = icon(
  <>
    <path d="M13.6 6.9a5.75 5.75 0 1 0 .15 2.9" />
    <path d="M13.75 2.75v4.15H9.6" />
  </>
);

export const IconPlus = icon(<path d="M8 3.25v9.5M3.25 8h9.5" />);

export const IconClose = icon(<path d="M4 4l8 8M12 4l-8 8" />);

export const IconPlay = icon(<path d="M5 3.4l7 4.6-7 4.6z" />);

export const IconPause = icon(<path d="M5.75 3.5v9M10.25 3.5v9" />);

export const IconSearch = icon(
  <>
    <circle cx="7.1" cy="7.1" r="4.35" />
    <path d="M10.4 10.4l3 3" />
  </>
);

export const IconCode = icon(<path d="M5.5 4.5L2 8l3.5 3.5M10.5 4.5L14 8l-3.5 3.5" />);

export const IconSparkle = icon(
  <path d="M8 2.25l1.45 3.9 3.9 1.45-3.9 1.45L8 13.75 6.55 9.05 2.65 7.6l3.9-1.45z" />
);

export const IconTarget = icon(
  <>
    <circle cx="8" cy="8" r="5.5" />
    <circle cx="8" cy="8" r="1.75" />
  </>
);

export const IconDice = icon(
  <>
    <rect x="2.75" y="2.75" width="10.5" height="10.5" rx="1.5" />
    <path d="M5.6 5.6h.01M10.4 5.6h.01M8 8h.01M5.6 10.4h.01M10.4 10.4h.01" strokeWidth={2} />
  </>
);

export const IconScissors = icon(
  <>
    <circle cx="4" cy="4" r="1.75" />
    <circle cx="4" cy="12" r="1.75" />
    <path d="M5.35 5.15L13 12.25M13 3.75L5.35 10.85" />
  </>
);

export const IconCamera = icon(
  <>
    <rect x="1.75" y="4.5" width="9" height="7" rx="1" />
    <path d="M10.75 8l3.5-2.25v4.5L10.75 8" />
  </>
);

export const IconLayers = icon(
  <>
    <path d="M8 1.9l6.1 3.1L8 8.1 1.9 5z" />
    <path d="M1.9 8.65L8 11.75l6.1-3.1M1.9 11.4l6.1 3.1 6.1-3.1" />
  </>
);

export const IconDroplet = icon(<path d="M8 1.9l3.6 4.35a4.65 4.65 0 1 1-7.2 0z" />);

export const IconClock = icon(
  <>
    <circle cx="8" cy="8" r="5.85" />
    <path d="M8 4.6V8l2.4 1.6" />
  </>
);

export const IconChevronRight = icon(<path d="M6.25 3.5L10.75 8l-4.5 4.5" />);

export const IconBolt = icon(<path d="M9 1.75L3.5 9.15h3.9l-.4 5.1L12.5 6.85H8.6z" />);
