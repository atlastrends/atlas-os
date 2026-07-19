import React, { useEffect, useState, useCallback, useMemo } from "react";
import Api from "./client.js";
import VideoCard from "../components/VideoCard.jsx";
import VideoModal from "../components/VideoModal.jsx";
import Toast from "../components/Toast.jsx";

const FILTERS = [
  { key: "", label: "Todos" },
  { key: "created", label: "Novos" },
  { key: "approved", label: "Aprovados" },
  { key: "published", label: "Publicados" },
  { key: "retry_pending", label: "Aguardando reenvio" },
  { key: "rejected", label: "Rejeitados" },
];

// Grade reutilizável para reels (kind="reel") e afiliados (kind="affiliate").
// notice: { type: "info"|"success"|"error", msg: string } => faixa de status.
// refreshSignal: muda de valor para forçar recarregar a lista.
export default function VideoGrid({
  kind,
  title,
  subtitle,
  extraAction,
  notice,
  refreshSignal,
}) {
  const [videos, setVideos] = useState(null);
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState(null);
  const [toast, setToast] = useState(null);

  // Carrega TODOS os vídeos e filtra no cliente, assim os contadores de cada
  // situação ficam sempre visíveis nos filtros.
  const load = useCallback(async () => {
    try {
      const data = await Api.listVideos({ kind });
      setVideos(Array.isArray(data) ? data : []);
    } catch {
      setVideos([]);
      setToast({ type: "error", msg: "Falha ao carregar vídeos (API offline?)." });
    }
  }, [kind]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (refreshSignal !== undefined) load();
  }, [refreshSignal, load]);

  const counts = useMemo(() => {
    const c = { "": videos?.length || 0, created: 0, approved: 0, published: 0, retry_pending: 0, rejected: 0 };
    (videos || []).forEach((v) => {
      if (c[v.status] !== undefined) c[v.status] += 1;
    });
    return c;
  }, [videos]);

  const shown = useMemo(() => {
    if (videos === null) return null;
    if (!status) return videos;
    return videos.filter((v) => v.status === status);
  }, [videos, status]);

  const clearRejected = async () => {
    if (
      !window.confirm(
        "Apagar todos os vídeos rejeitados? Os arquivos serão removidos do disco."
      )
    )
      return;
    try {
      const r = await Api.clearRejected(kind);
      setToast({
        type: "success",
        msg: `Rejeitados apagados: ${r?.removed_assets ?? 0} vídeo(s).`,
      });
      load();
    } catch {
      setToast({ type: "error", msg: "Falha ao apagar os rejeitados." });
    }
  };

  const [retrying, setRetrying] = useState(false);
  const pendingCount = counts.retry_pending || 0;
  const retryPending = async () => {
    if (
      !window.confirm(
        `Reenviar ${pendingCount} vídeo(s) que ficaram aguardando por limite da ` +
          `plataforma?\n\nUse isto no dia seguinte, quando o limite já liberou.`
      )
    )
      return;
    setRetrying(true);
    try {
      const r = await Api.retryPending(kind);
      const publicados = r?.published ?? 0;
      const aguardando = r?.still_pending ?? 0;
      const tentados = r?.retried ?? 0;

      if (tentados === 0) {
        setToast({ type: "info", msg: "Nenhum vídeo aguardando reenvio." });
      } else if (publicados > 0 && aguardando === 0) {
        window.alert(
          `✅ Tudo certo! ${publicados} vídeo(s) foram publicados agora.`
        );
        setToast({ type: "success", msg: `${publicados} vídeo(s) publicado(s)!` });
      } else if (publicados > 0) {
        window.alert(
          `✅ ${publicados} vídeo(s) publicados!\n\n` +
            `⏳ ${aguardando} ainda estão bloqueados pela plataforma (o limite ` +
            `do dia ainda não liberou). Tente de novo mais tarde ou amanhã.`
        );
        setToast({
          type: "success",
          msg: `${publicados} publicado(s), ${aguardando} ainda aguardando.`,
        });
      } else {
        // Nada subiu: a plataforma continua bloqueando por limite.
        window.alert(
          `⏳ Tentei reenviar ${tentados} vídeo(s), mas a plataforma ainda está ` +
            `bloqueando por limite (o limite do dia ainda não liberou).\n\n` +
            `Eles continuam em "Aguardando reenvio". Isso é normal: tente de novo ` +
            `mais tarde ou amanhã, que costuma liberar.`
        );
        setToast({
          type: "info",
          msg: `Plataforma ainda no limite. ${tentados} vídeo(s) seguem aguardando.`,
        });
      }
      load();
    } catch {
      window.alert("❌ Falha ao reenviar os pendentes. Tente novamente.");
      setToast({ type: "error", msg: "Falha ao reenviar os pendentes." });
    } finally {
      setRetrying(false);
    }
  };

  const noticeStyle = {
    info: { background: "#1e293b", border: "1px solid #334155", color: "#e2e8f0" },
    success: { background: "#052e1a", border: "1px solid #14532d", color: "#bbf7d0" },
    error: { background: "#3b0d0d", border: "1px solid #7f1d1d", color: "#fecaca" },
  };

  return (
    <div>
      <div className="page-head">
        <div>
          <h2>{title}</h2>
          <p>{subtitle}</p>
        </div>
        <div className="toolbar">
          {extraAction}
          {pendingCount > 0 && (
            <button
              className="btn"
              onClick={retryPending}
              disabled={retrying}
              title="Reenviar os vídeos que ficaram aguardando por limite da plataforma"
            >
              {retrying
                ? "Reenviando…"
                : `↑ Reenviar pendentes (${pendingCount})`}
            </button>
          )}
          <button className="btn ghost" onClick={clearRejected}>
            🗑 Apagar rejeitados
          </button>
          <button className="btn ghost" onClick={load}>
            ↻ Atualizar
          </button>
        </div>
      </div>

      {notice && notice.msg && (
        <div
          style={{
            ...(noticeStyle[notice.type] || noticeStyle.info),
            borderRadius: 10,
            padding: "12px 16px",
            marginBottom: 16,
            fontSize: 15,
            display: "flex",
            alignItems: "flex-start",
            gap: 10,
          }}
        >
          {notice.busy && (
            <span
              style={{
                width: 14,
                height: 14,
                border: "2px solid currentColor",
                borderTopColor: "transparent",
                borderRadius: "50%",
                display: "inline-block",
                marginTop: 4,
                flex: "0 0 auto",
                animation: "atlas-spin 0.8s linear infinite",
              }}
            />
          )}
          <span style={{ flex: 1 }}>
            <span style={{ whiteSpace: "pre-line" }}>{notice.msg}</span>
            {typeof notice.progress === "number" && (
              <span
                style={{
                  display: "block",
                  marginTop: 8,
                  height: 8,
                  width: "100%",
                  background: "rgba(0,0,0,0.12)",
                  borderRadius: 6,
                  overflow: "hidden",
                }}
              >
                <span
                  style={{
                    display: "block",
                    height: "100%",
                    width: `${Math.max(0, Math.min(100, notice.progress))}%`,
                    background: "currentColor",
                    borderRadius: 6,
                    transition: "width 0.4s ease",
                  }}
                />
              </span>
            )}
          </span>
          <style>{"@keyframes atlas-spin{to{transform:rotate(360deg)}}"}</style>
        </div>
      )}

      <div className="chips" style={{ marginBottom: 18 }}>
        {FILTERS.map((f) => (
          <span
            key={f.key}
            className={`chip ${status === f.key ? "active" : ""}`}
            onClick={() => setStatus(f.key)}
          >
            {f.label}
            <b>{counts[f.key] ?? 0}</b>
          </span>
        ))}
      </div>

      {shown === null ? (
        <div className="empty">Carregando…</div>
      ) : shown.length === 0 ? (
        <div className="empty">
          {status
            ? "Nenhum vídeo nesta situação."
            : "Nenhum vídeo encontrado. Gere conteúdo pelos botões e clique em Atualizar."}
        </div>
      ) : (
        <div className="grid videos">
          {shown.map((v) => (
            <VideoCard key={v.id} video={v} onOpen={setOpen} />
          ))}
        </div>
      )}

      {open && (
        <VideoModal
          video={open}
          onClose={() => setOpen(null)}
          onChanged={load}
          notify={setToast}
        />
      )}
      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}
