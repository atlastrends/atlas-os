import React, { useEffect, useState } from "react";
import Api from "../api/client.js";
import { StatusBadge } from "../components/VideoCard.jsx";
import PlatformLogo, { platformName } from "../components/PlatformLogo.jsx";
import Toast from "../components/Toast.jsx";

export default function Publishing() {
  const [pubs, setPubs] = useState(null);
  const [platforms, setPlatforms] = useState([]);
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
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

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
