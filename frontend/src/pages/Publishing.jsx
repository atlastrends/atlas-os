import React, { useEffect, useState } from "react";
import Api from "../api/client.js";
import { StatusBadge } from "../components/VideoCard.jsx";
import PlatformLogo, { platformName } from "../components/PlatformLogo.jsx";
import Toast from "../components/Toast.jsx";

export default function Publishing() {
  const [pubs, setPubs] = useState(null);
  const [platforms, setPlatforms] = useState([]);
  const [tiktok, setTiktok] = useState(null);
  const [toast, setToast] = useState(null);

  const load = async () => {
    try {
      const [p, s] = await Promise.all([Api.publications(), Api.status()]);
      setPubs(p);
      setPlatforms(s?.platforms || []);
    } catch {
      setPubs([]);
      setToast({ type: "error", msg: "Falha ao carregar publicações." });
    }
    try {
      setTiktok(await Api.tiktokStatus());
    } catch {
      setTiktok(null);
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

  const connectTiktok = (market) => {
    if (!tiktok?.has_client) {
      setToast({
        type: "error",
        msg: "Falta a chave do TikTok no .env (TIKTOK_CLIENT_KEY e TIKTOK_CLIENT_SECRET).",
      });
      return;
    }
    if (!tiktok?.is_public_https) {
      setToast({
        type: "error",
        msg: "Falta o endereço de retorno (ATLAS_TIKTOK_REDIRECT_URI) no .env.",
      });
      return;
    }
    // Abre o login do TikTok numa nova aba.
    window.open(Api.tiktokConnectUrl(market), "_blank");
    setToast({
      type: "info",
      msg: `Abrindo o login do TikTok (${market})… autorize e volte aqui.`,
    });
  };

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

      <div className="section-title">Conectar TikTok</div>
      <div className="card" style={{ padding: 20 }}>
        {!tiktok ? (
          <p style={{ color: "var(--text-faint)" }}>Carregando…</p>
        ) : (
          <>
            {!tiktok.has_client && (
              <p style={{ color: "var(--amber)", marginTop: 0 }}>
                ⚠️ Falta colocar a <b>Client key</b> e o <b>Client secret</b> do
                TikTok no arquivo <code>.env</code>. Sem isso o botão não funciona.
              </p>
            )}
            {tiktok.has_client && !tiktok.is_public_https && (
              <p style={{ color: "var(--amber)", marginTop: 0 }}>
                ⚠️ Falta o <b>endereço de retorno</b> no arquivo <code>.env</code>{" "}
                (<code>ATLAS_TIKTOK_REDIRECT_URI</code>).
              </p>
            )}
            {tiktok.is_public_https && tiktok.redirect_uri && (
              <p style={{ color: "var(--text-faint)", marginTop: 0 }}>
                Endereço de retorno (cole no painel do TikTok em <i>Redirect URI</i>):
                <br />
                <code style={{ userSelect: "all" }}>{tiktok.redirect_uri}</code>
              </p>
            )}
            <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 12 }}>
              {["BR", "US"].map((m) => {
                const info = tiktok.markets?.[m] || {};
                return (
                  <div
                    key={m}
                    className="card"
                    style={{ padding: 16, minWidth: 220, flex: "1 1 220px" }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <PlatformLogo platform="tiktok" size={22} />
                      <b>TikTok {m === "BR" ? "Brasil" : "US"}</b>
                    </div>
                    <div style={{ marginTop: 10, fontSize: 15 }}>
                      {info.connected ? (
                        <span style={{ color: "var(--green)" }}>● Conectado</span>
                      ) : (
                        <span style={{ color: "var(--amber)" }}>● Não conectado</span>
                      )}
                    </div>
                    <button
                      className="btn"
                      style={{ marginTop: 12, width: "100%" }}
                      onClick={() => connectTiktok(m)}
                    >
                      {info.connected ? "Reconectar" : "Conectar"} TikTok {m}
                    </button>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>

      <div className="section-title">Envios</div>
      <div className="card" style={{ padding: 0 }}>
        <table className="table">
          <thead>
            <tr>
              <th>Vídeo</th>
              <th>Plataforma</th>
              <th>Status</th>
              <th>Link</th>
              <th>Atualizado</th>
            </tr>
          </thead>
          <tbody>
            {pubs === null ? (
              <tr>
                <td colSpan={5}>Carregando…</td>
              </tr>
            ) : pubs.length === 0 ? (
              <tr>
                <td colSpan={5} style={{ color: "var(--text-faint)" }}>
                  Nenhuma publicação ainda. Aprove um vídeo para enfileirar.
                </td>
              </tr>
            ) : (
              pubs.map((p, i) => (
                <tr key={i}>
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
