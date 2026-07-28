import React, { useEffect, useMemo, useState } from "react";
import Api from "../api/client.js";
import { StatusBadge } from "../components/VideoCard.jsx";
import PlatformLogo, { platformName } from "../components/PlatformLogo.jsx";
import Toast from "../components/Toast.jsx";

const RESEND_STATUSES = ["failed", "rate_limited", "credentials_missing"];

export default function Publishing() {
  const [pubs, setPubs] = useState(null);
  const [platforms, setPlatforms] = useState([]);
  const [toast, setToast] = useState(null);
  const [tab, setTab] = useState("all"); // "all" | "resend"
  const [busyId, setBusyId] = useState(null);
  const [ttAccounts, setTtAccounts] = useState([]);
  const [ttStatus, setTtStatus] = useState(null);

  const load = async () => {
    try {
      const [p, s] = await Promise.all([Api.publications(), Api.status()]);
      setPubs(p);
      setPlatforms(s?.platforms || []);
    } catch {
      setPubs([]);
      setToast({ type: "error", msg: "Falha ao carregar publicações." });
    }
  };

  const loadTikTok = async () => {
    try {
      const [accRes, st] = await Promise.all([
        Api.tiktokAccounts(),
        Api.tiktokStatus(),
      ]);
      setTtAccounts(accRes?.accounts || []);
      setTtStatus(st || null);
    } catch {
      /* silencioso: o painel funciona mesmo sem contas conectadas */
    }
  };

  function connectTikTok(market) {
    window.open(Api.tiktokConnectUrl(market), "_blank", "noopener,noreferrer");
    setToast({
      type: "success",
      msg: "Abri o login do TikTok em outra aba. Após autorizar, clique em ↻ para atualizar a lista.",
    });
  }

  async function disconnectTikTok(acc) {
    if (
      !window.confirm(
        `Desconectar a conta ${acc.display_name}? Os vídeos desse mercado deixam de publicar automaticamente no TikTok até reconectar.`
      )
    ) {
      return;
    }
    try {
      await Api.tiktokDisconnect(acc.id);
      setToast({ type: "success", msg: "Conta desconectada." });
      await loadTikTok();
    } catch (e) {
      const detail = e?.response?.data?.detail || e?.message || String(e);
      setToast({ type: "error", msg: "Falha ao desconectar: " + detail });
    }
  }

  useEffect(() => {
    load();
    loadTikTok();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

  const resendItems = useMemo(
    () => (pubs || []).filter((p) => RESEND_STATUSES.includes(p.status)),
    [pubs]
  );
  const visibleItems = tab === "resend" ? resendItems : pubs || [];

  async function handleRetry(pub) {
    setBusyId(pub.id);
    try {
      await Api.retryPublication(pub.id);
      setToast({ type: "success", msg: `Reenviado para ${platformName(pub.platform)}.` });
      await load();
    } catch (e) {
      const detail = e?.response?.data?.detail || e?.message || String(e);
      setToast({ type: "error", msg: "Falha ao reenviar: " + detail });
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(pub) {
    if (!window.confirm("Excluir este registro de reenvio? Isso não apaga o vídeo, só o histórico desta plataforma.")) {
      return;
    }
    setBusyId(pub.id);
    try {
      await Api.deletePublication(pub.id);
      setToast({ type: "success", msg: "Registro excluído." });
      await load();
    } catch (e) {
      const detail = e?.response?.data?.detail || e?.message || String(e);
      setToast({ type: "error", msg: "Falha ao excluir: " + detail });
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h2>Publicações</h2>
          <p>Fila e histórico de envios para as plataformas.</p>
        </div>
        <button className="btn ghost" onClick={load}>
          ↻ Atualizar
        </button>
      </div>

      <div className="section-title" style={{ marginTop: 0 }}>
        Conexão das plataformas
      </div>
      <div className="grid stats">
        {platforms.map((p) => (
          <div key={p.platform} className="card stat-card">
            <div className="label" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <PlatformLogo platform={p.platform} size={22} />
              {platformName(p.platform)}
            </div>
            <div className="value" style={{ fontSize: 18, marginTop: 12 }}>
              {p.configured ? (
                <span style={{ color: "var(--green)" }}>● Conectado</span>
              ) : (
                <span style={{ color: "var(--amber)" }}>● Falta credencial</span>
              )}
            </div>
            {!p.configured && p.missing_env?.length > 0 && (
              <div className="foot">Falta: {p.missing_env.join(", ")}</div>
            )}
            <div className="accent" />
          </div>
        ))}
      </div>

      <div
        className="section-title"
        style={{ display: "flex", alignItems: "center", gap: 10 }}
      >
        <span>Contas do TikTok</span>
        <div style={{ display: "flex", gap: 6, marginLeft: "auto" }}>
          <button className="btn btn-sm" onClick={() => connectTikTok("BR")}>
            + Conectar conta (Brasil)
          </button>
          <button className="btn btn-sm" onClick={() => connectTikTok("US")}>
            + Conectar conta (EUA)
          </button>
          <button
            className="btn ghost btn-sm"
            onClick={loadTikTok}
            title="Atualizar lista de contas"
          >
            ↻
          </button>
        </div>
      </div>
      <div className="card" style={{ padding: 16 }}>
        {ttStatus && !ttStatus.has_client ? (
          <div className="foot" style={{ color: "var(--amber)", marginBottom: 10 }}>
            Falta configurar TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET no .env.
          </div>
        ) : ttStatus && !ttStatus.is_public_https ? (
          <div className="foot" style={{ color: "var(--amber)", marginBottom: 10 }}>
            Falta o endereço de retorno HTTPS (ATLAS_TIKTOK_REDIRECT_URI) no .env.
          </div>
        ) : null}
        {ttAccounts.length === 0 ? (
          <div style={{ color: "var(--text-faint)" }}>
            Nenhuma conta conectada. Clique em “Conectar conta” para autorizar uma
            conta do TikTok — cada criador conecta a própria conta.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {ttAccounts.map((a) => (
              <div
                key={a.id}
                style={{ display: "flex", alignItems: "center", gap: 12 }}
              >
                {a.avatar_url ? (
                  <img
                    src={a.avatar_url}
                    alt=""
                    width={40}
                    height={40}
                    style={{ borderRadius: "50%", objectFit: "cover" }}
                  />
                ) : (
                  <div
                    style={{
                      width: 40,
                      height: 40,
                      borderRadius: "50%",
                      background: "var(--panel-2, #1f2937)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                    }}
                  >
                    <PlatformLogo platform="tiktok" size={20} />
                  </div>
                )}
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600 }}>{a.display_name}</div>
                  <div className="foot">
                    {a.market ? `Mercado ${a.market}` : "sem mercado"} ·{" "}
                    {a.connected ? "conectada" : "sem token"}
                  </div>
                </div>
                <button
                  className="btn ghost btn-sm"
                  style={{ color: "#fca5a5" }}
                  onClick={() => disconnectTikTok(a)}
                >
                  Desconectar
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="section-title" style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span>Envios</span>
        <div style={{ display: "flex", gap: 6, marginLeft: "auto" }}>
          <button
            className={tab === "all" ? "btn btn-sm" : "btn ghost btn-sm"}
            onClick={() => setTab("all")}
          >
            Todos
          </button>
          <button
            className={tab === "resend" ? "btn btn-sm" : "btn ghost btn-sm"}
            onClick={() => setTab("resend")}
          >
            ⏳ Aguardando reenvio {resendItems.length > 0 ? `(${resendItems.length})` : ""}
          </button>
        </div>
      </div>
      <div className="card" style={{ padding: 0 }}>
        <table className="table">
          <thead>
            <tr>
              <th>Vídeo</th>
              <th>Plataforma</th>
              <th>Status</th>
              <th>Link</th>
              <th>Atualizado</th>
              {tab === "resend" && <th>Ações</th>}
            </tr>
          </thead>
          <tbody>
            {pubs === null ? (
              <tr>
                <td colSpan={tab === "resend" ? 6 : 5}>Carregando…</td>
              </tr>
            ) : visibleItems.length === 0 ? (
              <tr>
                <td colSpan={tab === "resend" ? 6 : 5} style={{ color: "var(--text-faint)" }}>
                  {tab === "resend"
                    ? "Nenhuma publicação aguardando reenvio no momento. 🎉"
                    : "Nenhuma publicação ainda. Aprove um vídeo para enfileirar."}
                </td>
              </tr>
            ) : (
              visibleItems.map((p, i) => (
                <tr key={p.id ?? i}>
                  <td>#{p.video_asset_id}</td>
                  <td>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                      <PlatformLogo platform={p.platform} size={18} />
                      {platformName(p.platform)}
                    </span>
                  </td>
                  <td>
                    <StatusBadge status={p.status} />
                    {p.error ? (
                      <div className="foot" style={{ color: "#fca5a5" }}>
                        {p.error}
                      </div>
                    ) : null}
                  </td>
                  <td>
                    {p.external_url ? (
                      <a className="link" href={p.external_url} target="_blank" rel="noreferrer">
                        abrir
                      </a>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>{fmtDate(p.updated_at)}</td>
                  {tab === "resend" && (
                    <td>
                      <div style={{ display: "flex", gap: 6 }}>
                        <button
                          className="btn btn-sm"
                          disabled={busyId === p.id}
                          onClick={() => handleRetry(p)}
                        >
                          {busyId === p.id ? "Enviando…" : "↻ Reenviar"}
                        </button>
                        <button
                          className="btn ghost btn-sm"
                          disabled={busyId === p.id}
                          onClick={() => handleDelete(p)}
                          style={{ color: "#fca5a5" }}
                        >
                          🗑 Excluir
                        </button>
                      </div>
                    </td>
                  )}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}

function fmtDate(v) {
  if (!v) return "—";
  try {
    return new Date(v).toLocaleString("pt-BR");
  } catch {
    return v;
  }
}
