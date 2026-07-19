import React from "react";

export function StatusBadge({ status }) {
  const map = {
    created: "Novo",
    approved: "Aprovado",
    published: "Publicado",
    rejected: "Rejeitado",
    failed: "Falhou",
    publishing: "Publicando",
    credentials_missing: "Sem login",
    retry_pending: "Aguardando reenvio",
  };
  const label = map[status] || (status || "").replace(/_/g, " ");
  return <span className={`badge ${status}`}>{label}</span>;
}

function flagOf(code) {
  const c = (code || "").toUpperCase();
  if (c.startsWith("BR") || c === "PT") return "🇧🇷";
  if (c.startsWith("US") || c === "EN") return "🇺🇸";
  return "";
}

function shortLang(lang) {
  const l = (lang || "").toLowerCase();
  if (l.startsWith("pt") || l.includes("portug")) return "PT";
  if (l.startsWith("en") || l.includes("engl")) return "EN";
  return (lang || "").slice(0, 12);
}

export default function VideoCard({ video, onOpen }) {
  const hasVideo = Boolean(video.video_url);
  const flag = flagOf(video.country_code);
  return (
    <div className="video-card">
      <div className="video-thumb" onClick={() => onOpen(video)}>
        {hasVideo ? (
          <>
            <video src={video.video_url} preload="metadata" muted />
            <div className="thumb-grad" />
            <div className="play">▶</div>
          </>
        ) : (
          <div className="placeholder">
            Arquivo de vídeo indisponível
            <br />
            <small>{video.video_path || "sem caminho"}</small>
          </div>
        )}
        <div className="thumb-badges tl">
          {flag ? <span className="thumb-chip">{flag} {video.country_code}</span> : null}
        </div>
        <div className="thumb-badges tr">
          <StatusBadge status={video.status} />
        </div>
      </div>
      <div className="video-body">
        <div className="video-title">{video.title || video.topic || "Sem título"}</div>
        <div className="video-meta">
          {video.language ? <span>🗣️ {shortLang(video.language)}</span> : null}
          {video.performance_score ? <span>⭐ {video.performance_score}</span> : null}
        </div>
        <div className="video-actions">
          <button className="btn sm primary" onClick={() => onOpen(video)}>
            Revisar
          </button>
        </div>
      </div>
    </div>
  );
}
