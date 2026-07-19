import React from "react";

// Logos oficiais (SVG embutido, sem depender de internet) de cada plataforma.
// Uso: <PlatformLogo platform="youtube" size={20} />

const TIKTOK_PATH =
  "M12.53.02C13.84 0 15.14.01 16.44 0c.08 1.53.63 3.09 1.75 4.17 1.12 1.11 2.7 1.62 4.24 1.79v4.03c-1.44-.05-2.89-.35-4.2-.97-.57-.26-1.1-.59-1.62-.93-.01 2.92.01 5.84-.02 8.75-.08 1.4-.54 2.79-1.35 3.94-1.31 1.92-3.58 3.17-5.91 3.21-1.43.08-2.86-.31-4.08-1.03-2.02-1.19-3.44-3.37-3.65-5.71-.02-.5-.03-1-.01-1.49.18-1.9 1.12-3.72 2.58-4.96 1.66-1.44 3.98-2.13 6.15-1.72.02 1.48-.04 2.96-.04 4.44-.99-.32-2.15-.23-3.02.37-.63.41-1.11 1.04-1.36 1.75-.21.51-.15 1.08-.14 1.62.24 1.64 1.82 3.02 3.5 2.87 1.12-.01 2.19-.66 2.77-1.61.19-.33.4-.67.41-1.06.1-1.79.06-3.57.07-5.36.01-4.03-.01-8.05.02-12.07z";

export default function PlatformLogo({ platform, size = 20 }) {
  const key = String(platform || "").toLowerCase();
  const igId = React.useId();
  const common = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    style: { display: "block", flexShrink: 0 },
  };

  if (key.includes("youtube")) {
    return (
      <svg {...common} aria-label="YouTube" role="img">
        <rect x="1" y="4.5" width="22" height="15" rx="4.2" fill="#FF0000" />
        <path d="M10 8.4l6.2 3.6L10 15.6z" fill="#fff" />
      </svg>
    );
  }

  if (key.includes("tiktok")) {
    return (
      <svg {...common} aria-label="TikTok" role="img">
        <rect width="24" height="24" rx="6" fill="#000" />
        <g transform="translate(2 1.7) scale(0.83)">
          <path d={TIKTOK_PATH} fill="#25F4EE" transform="translate(-0.7 0.5)" />
          <path d={TIKTOK_PATH} fill="#FE2C55" transform="translate(0.7 -0.4)" />
          <path d={TIKTOK_PATH} fill="#fff" />
        </g>
      </svg>
    );
  }

  if (key.includes("instagram")) {
    return (
      <svg {...common} aria-label="Instagram" role="img">
        <defs>
          <radialGradient id={igId} cx="30%" cy="107%" r="150%">
            <stop offset="0%" stopColor="#fdf497" />
            <stop offset="5%" stopColor="#fdf497" />
            <stop offset="45%" stopColor="#fd5949" />
            <stop offset="60%" stopColor="#d6249f" />
            <stop offset="90%" stopColor="#285AEB" />
          </radialGradient>
        </defs>
        <rect width="24" height="24" rx="6" fill={`url(#${igId})`} />
        <rect x="5" y="5" width="14" height="14" rx="4.5" fill="none" stroke="#fff" strokeWidth="1.8" />
        <circle cx="12" cy="12" r="3.4" fill="none" stroke="#fff" strokeWidth="1.8" />
        <circle cx="16.5" cy="7.5" r="1.15" fill="#fff" />
      </svg>
    );
  }

  if (key.includes("facebook")) {
    return (
      <svg {...common} aria-label="Facebook" role="img">
        <rect width="24" height="24" rx="6" fill="#1877F2" />
        <path
          d="M15.6 12.3h-2v6.7h-2.75v-6.7H9.3V10h1.55V8.55c0-1.9 1.13-3.05 2.95-3.05.85 0 1.6.12 1.6.12v2.1h-1.05c-.9 0-1.25.6-1.25 1.2V10h2.15l-.55 2.3z"
          fill="#fff"
        />
      </svg>
    );
  }

  // Fallback genérico para plataformas desconhecidas.
  return (
    <span
      aria-hidden="true"
      style={{
        width: size,
        height: size,
        borderRadius: 6,
        background: "var(--bg-elev-2)",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: size * 0.6,
        flexShrink: 0,
      }}
    >
      🌐
    </span>
  );
}

// Nome com a primeira letra maiúscula (ex.: "youtube" -> "Youtube").
export function platformName(platform) {
  const p = String(platform || "").trim();
  if (!p) return "—";
  return p.charAt(0).toUpperCase() + p.slice(1);
}
