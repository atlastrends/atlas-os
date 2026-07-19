import React, { useEffect, useMemo, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import Api from "../api/client.js";
import PlatformLogo from "../components/PlatformLogo.jsx";

// Colunas ordenaveis da tabela de videos.
const COLUMNS = [
  { key: "views", label: "Views" },
  { key: "likes", label: "Curtidas" },
  { key: "comments", label: "Comentários" },
  { key: "shares", label: "Compart." },
  { key: "clicks", label: "Cliques afil." },
];

export default function PlatformDetail() {
  const { key } = useParams();
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sortKey, setSortKey] = useState("views");
  const [sortDir, setSortDir] = useState("desc"); // "desc" | "asc"

  const load = async () => {
    try {
      const d = await Api.accountVideos(key);
      setData(d);
      setError("");
    } catch {
      setError("Não foi possível carregar os vídeos desta conta.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setLoading(true);
    load();
    const t = setInterval(load, 20000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const sorted = useMemo(() => {
    const list = [...(data?.videos || [])];
    // Para a data de publicacao ordenamos pelo horario (dia + hora);
    // para as demais colunas ordenamos pelo numero.
    const valueOf = (row) => {
      if (sortKey === "published_at") {
        const t = row.published_at ? Date.parse(row.published_at) : 0;
        return Number.isNaN(t) ? 0 : t;
      }
      return row[sortKey] ?? 0;
    };
    list.sort((a, b) => {
      const av = valueOf(a);
      const bv = valueOf(b);
      return sortDir === "desc" ? bv - av : av - bv;
    });
    return list;
  }, [data, sortKey, sortDir]);

  const toggleSort = (key) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const arrow = (key) =>
    key === sortKey ? (sortDir === "desc" ? " ▼" : " ▲") : "";

  return (
    <div>
      <div className="page-head">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button
            className="btn ghost"
            onClick={() => nav("/analytics")}
            style={{ padding: "6px 12px" }}
          >
            ← Voltar
          </button>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
            <PlatformLogo platform={data?.platform || "web"} size={28} />
            <div>
              <h2 style={{ margin: 0 }}>{data?.label || "Conta"}</h2>
              <p style={{ margin: 0 }}>
                {fmt(data?.followers)} seguidores ·{" "}
                {data?.published_videos ?? 0} vídeos publicados
                {data && data.connected === false ? " · sem login" : ""}
              </p>
            </div>
          </span>
        </div>
      </div>

      {loading && <div className="card">Carregando…</div>}
      {error && !loading && (
        <div className="card" style={{ color: "#ef4444" }}>
          {error}
        </div>
      )}

      {!loading && !error && sorted.length === 0 && (
        <div className="card">
          Nenhum vídeo publicado nesta conta ainda. Depois de publicar, clique
          em "Coletar métricas" no Analytics para ver os números aqui.
        </div>
      )}

      {!loading && !error && sorted.length > 0 && (
        <div className="card" style={{ padding: 0 }}>
          <table className="table">
            <thead>
              <tr>
                <th>Vídeo</th>
                {COLUMNS.map((c) => (
                  <th
                    key={c.key}
                    onClick={() => toggleSort(c.key)}
                    style={{ cursor: "pointer", userSelect: "none", whiteSpace: "nowrap" }}
                    title="Clique para ordenar"
                  >
                    {c.label}
                    {arrow(c.key)}
                  </th>
                ))}
                <th
                  onClick={() => toggleSort("published_at")}
                  style={{ cursor: "pointer", userSelect: "none", whiteSpace: "nowrap" }}
                  title="Clique para ordenar por data e hora"
                >
                  Publicado{arrow("published_at")}
                </th>
                <th>Link</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((v, i) => (
                <tr key={v.id}>
                  <td>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                      <span style={{ color: "#93a1b5", minWidth: 20 }}>{i + 1}.</span>
                      <span>{v.title}</span>
                      {v.language && (
                        <span
                          style={{
                            fontSize: 11,
                            color: "#93a1b5",
                            border: "1px solid #232c3d",
                            borderRadius: 6,
                            padding: "1px 6px",
                          }}
                        >
                          {(v.country_code || v.language || "").toUpperCase()}
                        </span>
                      )}
                    </span>
                  </td>
                  <td>{fmt(v.views)}</td>
                  <td>{fmt(v.likes)}</td>
                  <td>{fmt(v.comments)}</td>
                  <td>{fmt(v.shares)}</td>
                  <td>{fmt(v.clicks)}</td>
                  <td style={{ whiteSpace: "nowrap", color: "#93a1b5" }}>
                    {fmtDate(v.published_at)}
                  </td>
                  <td>
                    {v.external_url ? (
                      <a
                        href={v.external_url}
                        target="_blank"
                        rel="noreferrer"
                        style={{ color: "#06b6d4" }}
                      >
                        Abrir
                      </a>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function fmt(n) {
  if (n === undefined || n === null) return "—";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
  return String(n);
}

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    // Mostra o dia E o horario (hora:minuto), no fuso do computador.
    const dia = d.toLocaleDateString("pt-BR");
    const hora = d.toLocaleTimeString("pt-BR", {
      hour: "2-digit",
      minute: "2-digit",
    });
    return `${dia} ${hora}`;
  } catch {
    return "—";
  }
}
