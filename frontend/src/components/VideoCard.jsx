import React, { useState } from "react";

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

// Miniatura leve: 1 frame do proprio video (gerado pelo backend e cacheado em
// disco) ou a imagem do produto, se houver. Nunca carrega o arquivo de video
// inteiro, entao as telas abrem bem mais rapido.
export function thumbOf(video) {
  const p = video.payload || {};
  const prod = p.product || {};
  return (
    video.thumbnail_url ||
    p.image_url ||
    p.image ||
    prod.image_url ||
    prod.image ||
    null
  );
}

// Diz se o video JA subiu (publicado) para alguma plataforma.
export function isUploaded(video) {
  if ((video.status || "") === "published") return true;
  return (video.publications || []).some(
    (p) => (p.status || "") === "published" || Boolean(p.external_url)
  );
}

// Link para ASSISTIR o video que ja subiu.
// 1) Preferimos o link DIRETO de uma publicacao que deu certo (YouTube de
//    preferencia, depois Instagram, Facebook, TikTok) — assim abre o proprio
//    video, sem carregar o arquivo local.
// 2) Se nenhuma publicacao guardou link, caimos numa BUSCA no YouTube pelo
//    titulo.
const PLATFORM_LABELS = {
  youtube: "YouTube",
  instagram: "Instagram",
  facebook: "Facebook",
  tiktok: "TikTok",
};

export function watchInfoOf(video) {
  const pubs = video.publications || [];
  for (const plat of ["youtube", "instagram", "facebook", "tiktok"]) {
    const p = pubs.find(
      (x) => (x.platform || "").toLowerCase() === plat && x.external_url
    );
    if (p) {
      return {
        url: p.external_url,
        label: `Assistir no ${PLATFORM_LABELS[plat] || plat}`,
        isSearch: false,
      };
    }
  }
  const q = encodeURIComponent(video.title || video.topic || "");
  if (!q) return null;
  return {
    url: `https://www.youtube.com/results?search_query=${q}`,
    label: "Buscar no YouTube",
    isSearch: true,
  };
}

export default function VideoCard({ video, onOpen }) {
  const flag = flagOf(video.country_code);
  const uploaded = isUploaded(video);
  const watch = uploaded ? watchInfoOf(video) : null;
  const thumb = thumbOf(video);
  const [imgOk, setImgOk] = useState(true);

  // Ao clicar na miniatura/play:
  // - se o video JA subiu, abre direto onde ele foi publicado (ou busca no
  //   YouTube pelo titulo), sem carregar o arquivo local — a tela fica bem
  //   mais rapida;
  // - se ainda NAO subiu, abre a revisao para aceitar/rejeitar.
  const handlePlay = () => {
    if (watch) {
      window.open(watch.url, "_blank", "noopener,noreferrer");
    } else {
      onOpen(video);
    }
  };

  return (
    <div className="video-card">
      <div
        className="video-thumb"
        onClick={handlePlay}
        title={watch ? watch.label : "Revisar vídeo"}
      >
        {thumb && imgOk ? (
          <img
            className="thumb-img"
            src={thumb}
            alt={video.title || "vídeo"}
            loading="lazy"
            onError={() => setImgOk(false)}
          />
        ) : (
          <div className="placeholder">
            {video.title || video.topic || "Vídeo"}
          </div>
        )}
        <div className="thumb-grad" />
        <div className={`play ${uploaded ? "show" : ""}`}>▶</div>
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
        {watch ? (
          <a
            className="link yt-link"
            href={watch.url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            title={watch.label}
          >
            ▶ {watch.label}
          </a>
        ) : null}
        <div className="video-actions">
          <button className="btn sm primary" onClick={() => onOpen(video)}>
            Revisar
          </button>
        </div>
      </div>
    </div>
  );
}
