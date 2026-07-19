import React, { useEffect, useState } from "react";
import Api from "../api/client.js";
import { StatusBadge } from "./VideoCard.jsx";
import PlatformLogo, { platformName } from "./PlatformLogo.jsx";

const PLATFORMS = ["youtube", "tiktok", "instagram", "facebook"];

export default function VideoModal({ video, onClose, onChanged, notify }) {
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState(PLATFORMS);
  const [metrics, setMetrics] = useState(null);

  useEffect(() => {
    if (!video) return;
    Api.videoMetrics(video.id).then(setMetrics).catch(() => setMetrics(null));
  }, [video]);

  if (!video) return null;

  const toggle = (p) =>
    setSelected((s) => (s.includes(p) ? s.filter((x) => x !== p) : [...s, p]));

  const approve = async () => {
    setBusy(true);
    try {
      const res = await Api.approveVideo(video.id, { notes, platforms: selected });
      notify?.({ type: "ok", msg: `Aprovado. Status: ${res.status}` });
      onChanged?.();
      onClose();
    } catch (e) {
      notify?.({ type: "error", msg: "Falha ao aprovar." });
    } finally {
      setBusy(false);
    }
  };

  const reject = async () => {
    setBusy(true);
    try {
      await Api.rejectVideo(video.id, { notes });
      notify?.({ type: "ok", msg: "Vídeo rejeitado." });
      onChanged?.();
      onClose();
    } catch (e) {
      notify?.({ type: "error", msg: "Falha ao rejeitar." });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <span className="close-x" onClick={onClose}>
          ✕
        </span>
        <div className="m-video">
          {video.video_url ? (
            <video src={video.video_url} controls autoPlay />
          ) : (
            <div className="placeholder" style={{ padding: 30 }}>
              Vídeo indisponível
            </div>
          )}
        </div>
        <div className="m-body">
          <h3>{video.title || video.topic}</h3>
          <div>
            <StatusBadge status={video.status} />{" "}
            <span className="badge">{video.kind}</span>
          </div>
          <div className="kv">
            {video.country_code && (
              <>
                <b>Região:</b> {video.country_code} &nbsp;
              </>
            )}
            {video.language && (
              <>
                <b>Idioma:</b> {video.language}
              </>
            )}
          </div>

          {video.kind === "affiliate" && video.short_url && (
            <div className="kv">
              <b>Link clicável:</b>{" "}
              <a className="link" href={video.short_url} target="_blank" rel="noreferrer">
                {video.short_url}
              </a>
            </div>
          )}

          {metrics?.platforms?.length > 0 && (
            <div className="kv">
              <b>Métricas:</b>
              <ul style={{ margin: "6px 0", paddingLeft: 18 }}>
                {metrics.platforms.map((m) => (
                  <li key={m.platform}>
                    {m.platform}: 👁 {m.views} · ❤️ {m.likes} · 🔗 {m.clicks}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div>
            <div className="kv" style={{ marginBottom: 6 }}>
              <b>Publicar em:</b>
            </div>
            <div className="chips">
              {PLATFORMS.map((p) => (
                <span
                  key={p}
                  className={`chip ${selected.includes(p) ? "active" : ""}`}
                  onClick={() => toggle(p)}
                  style={{ display: "inline-flex", alignItems: "center", gap: 7 }}
                >
                  <PlatformLogo platform={p} size={16} />
                  {platformName(p)}
                </span>
              ))}
            </div>
          </div>

          <textarea
            placeholder="Notas de revisão (opcional)"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />

          <div className="m-actions">
            <button className="btn success" disabled={busy} onClick={approve}>
              {busy ? <span className="spinner" /> : "✓"} Aceitar e publicar
            </button>
            <button className="btn danger" disabled={busy} onClick={reject}>
              ✕ Rejeitar
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
