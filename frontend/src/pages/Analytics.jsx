import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  CartesianGrid,
  Legend,
  RadialBarChart,
  RadialBar,
} from "recharts";
import Api from "../api/client.js";
import StatCard from "../components/StatCard.jsx";
import PlatformLogo, { platformName } from "../components/PlatformLogo.jsx";

const COLORS = ["#6366f1", "#06b6d4", "#22c55e", "#f59e0b", "#ef4444"];
const TOOLTIP_STYLE = {
  background: "#1a2130",
  border: "1px solid #232c3d",
  borderRadius: 10,
  color: "#e8edf5",
  fontSize: 13,
};

export default function Analytics() {
  const nav = useNavigate();
  const [ov, setOv] = useState(null);
  const [platforms, setPlatforms] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [collecting, setCollecting] = useState(false);
  const [msg, setMsg] = useState("");

  const load = async () => {
    const [o, p, a] = await Promise.all([
      Api.overview(),
      Api.platforms(),
      Api.accounts(),
    ]);
    setOv(o);
    setPlatforms(p);
    setAccounts(Array.isArray(a) ? a : []);
  };

  const collect = async () => {
    setCollecting(true);
    setMsg("Coleta iniciada…");
    try {
      await Api.collectMetrics();
      // A coleta roda em segundo plano no servidor. Ficamos checando o
      // estado do job até ele terminar, para manter o botão travado.
      let state = null;
      for (let i = 0; i < 120; i++) {
        await new Promise((res) => setTimeout(res, 1500));
        const jobs = await Api.jobs();
        state = jobs?.collect_metrics;
        if (!state || state.status !== "running") break;
      }
      if (state?.status === "error") {
        setMsg("Falha ao coletar métricas: " + (state.error || ""));
      } else if (state?.result) {
        setMsg(
          `Coleta concluída: ${state.result.video_snapshots ?? 0} vídeos, ${
            state.result.platform_snapshots ?? 0
          } contas.`
        );
      } else {
        setMsg("Coleta concluída.");
      }
      await load();
    } catch (e) {
      setMsg("Falha ao coletar métricas.");
    } finally {
      setCollecting(false);
    }
  };

  useEffect(() => {
    load().catch(() => {});
    const t = setInterval(() => load().catch(() => {}), 20000);
    return () => clearInterval(t);
  }, []);

  const followersData = platforms.map((p) => ({
    name: platformName(p.platform),
    Seguidores: p.followers || 0,
    Views: p.total_views || 0,
  }));
  const publishedData = platforms
    .map((p, i) => ({
      name: platformName(p.platform),
      value: p.published_videos || 0,
      color: COLORS[i % COLORS.length],
    }))
    .filter((d) => d.value > 0);
  const publishedTotal = publishedData.reduce((a, b) => a + b.value, 0);

  const interactionData = [
    { name: "Curtidas", value: ov?.likes ?? 0, color: "#ec4899" },
    { name: "Comentários", value: ov?.comments ?? 0, color: "#06b6d4" },
    { name: "Compart.", value: ov?.shares ?? 0, color: "#6366f1" },
  ].filter((d) => d.value > 0);
  const interactionTotal = interactionData.reduce((a, b) => a + b.value, 0);

  const engagement = Number(ov?.engagement_rate ?? 0);
  const gaugeData = [
    {
      name: "Engajamento",
      value: Math.min(engagement, 100),
      fill: engagement >= 6 ? "#22c55e" : engagement >= 3 ? "#06b6d4" : "#f59e0b",
    },
  ];

  return (
    <div>
      <div className="page-head">
        <div>
          <h2>Analytics</h2>
          <p>Desempenho por plataforma e por vídeo.</p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {msg && <span style={{ color: "#93a1b5", fontSize: 13 }}>{msg}</span>}
          <button
            className="btn"
            onClick={collect}
            disabled={collecting}
            style={
              collecting
                ? { background: "#f59e0b", borderColor: "#f59e0b", color: "#1a1205" }
                : undefined
            }
          >
            {collecting ? "Coletando..." : "Coletar métricas"}
          </button>
        </div>
      </div>

      <div className="grid kpis">
        <StatCard icon="👁️" tone="cyan" label="Visualizações" value={fmt(ov?.views)} />
        <StatCard icon="❤️" tone="pink" label="Curtidas" value={fmt(ov?.likes)} />
        <StatCard icon="💬" tone="cyan" label="Comentários" value={fmt(ov?.comments)} />
        <StatCard icon="🔁" tone="cyan" label="Compartilhamentos" value={fmt(ov?.shares)} />
        <StatCard icon="🔗" tone="amber" label="Cliques afiliados" value={fmt(ov?.affiliate_clicks)} foot={`CTR ${pct(ov?.click_through_rate)}`} />
        <StatCard icon="👥" tone="pink" label="Seguidores" value={fmt(ov?.followers)} />
      </div>

      <div className="charts-3">
        <div className="card chart-card">
          <div className="chart-head">Publicações por plataforma</div>
          {publishedTotal === 0 ? (
            <EmptyChart text="Nenhum vídeo publicado ainda." />
          ) : (
            <div className="chart-wrap">
              <ResponsiveContainer width="100%" height={210}>
                <PieChart>
                  <Pie
                    data={publishedData}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={62}
                    outerRadius={90}
                    paddingAngle={2}
                    stroke="none"
                  >
                    {publishedData.map((d) => (
                      <Cell key={d.name} fill={d.color} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={TOOLTIP_STYLE} />
                </PieChart>
              </ResponsiveContainer>
              <div className="chart-center">
                <div className="chart-center-value">{publishedTotal}</div>
                <div className="chart-center-label">publicados</div>
              </div>
            </div>
          )}
          <div className="chart-legend">
            {publishedData.map((d) => (
              <span key={d.name} className="legend-item">
                <i style={{ background: d.color }} />
                {d.name} <b>{d.value}</b>
              </span>
            ))}
          </div>
        </div>

        <div className="card chart-card">
          <div className="chart-head">Engajamento médio</div>
          <div className="chart-wrap">
            <ResponsiveContainer width="100%" height={210}>
              <RadialBarChart
                innerRadius="72%"
                outerRadius="100%"
                data={gaugeData}
                startAngle={220}
                endAngle={-40}
              >
                <RadialBar
                  dataKey="value"
                  cornerRadius={12}
                  background={{ fill: "#1c2434" }}
                  domain={[0, 100]}
                />
              </RadialBarChart>
            </ResponsiveContainer>
            <div className="chart-center">
              <div className="chart-center-value">{pct(ov?.engagement_rate)}</div>
              <div className="chart-center-label">interações ÷ views</div>
            </div>
          </div>
          <div className="chart-legend center">
            <span className="legend-item">
              <i style={{ background: "#f59e0b" }} />🔗 CTR {pct(ov?.click_through_rate)}
            </span>
            <span className="legend-item">
              <i style={{ background: "#06b6d4" }} />🔗 {fmt(ov?.affiliate_clicks)} cliques
            </span>
          </div>
        </div>

        <div className="card chart-card">
          <div className="chart-head">Interações</div>
          {interactionTotal === 0 ? (
            <EmptyChart text="Sem interações ainda." />
          ) : (
            <div className="chart-wrap">
              <ResponsiveContainer width="100%" height={210}>
                <PieChart>
                  <Pie
                    data={interactionData}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={62}
                    outerRadius={90}
                    paddingAngle={2}
                    stroke="none"
                  >
                    {interactionData.map((d) => (
                      <Cell key={d.name} fill={d.color} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={TOOLTIP_STYLE} />
                </PieChart>
              </ResponsiveContainer>
              <div className="chart-center">
                <div className="chart-center-value">{fmt(interactionTotal)}</div>
                <div className="chart-center-label">total</div>
              </div>
            </div>
          )}
          <div className="chart-legend">
            {interactionData.map((d) => (
              <span key={d.name} className="legend-item">
                <i style={{ background: d.color }} />
                {d.name} <b>{fmt(d.value)}</b>
              </span>
            ))}
          </div>
        </div>
      </div>

      <div className="card chart-card" style={{ marginBottom: 16 }}>
        <div className="chart-head">Seguidores &amp; views por plataforma</div>
        {followersData.length === 0 ? (
          <EmptyChart text="Conecte as plataformas para ver os números." />
        ) : (
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={followersData} barGap={6}>
              <CartesianGrid strokeDasharray="3 3" stroke="#232c3d" vertical={false} />
              <XAxis dataKey="name" stroke="#93a1b5" fontSize={12} tickLine={false} />
              <YAxis stroke="#93a1b5" fontSize={12} tickLine={false} axisLine={false} tickFormatter={fmt} />
              <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => fmt(v)} cursor={{ fill: "rgba(99,102,241,.08)" }} />
              <Legend />
              <Bar dataKey="Seguidores" fill="#6366f1" radius={[6, 6, 0, 0]} />
              <Bar dataKey="Views" fill="#06b6d4" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="section-title">Contas conectadas</div>
      <div className="card" style={{ padding: 0 }}>
        <div
          style={{
            padding: "14px 16px 4px",
            fontSize: 13,
            color: "#93a1b5",
          }}
        >
          Todas as contas de todas as plataformas. Clique numa conta para ver os
          vídeos publicados nela e seus números.
        </div>
        {accounts.length === 0 ? (
          <EmptyChart text="Nenhuma conta conectada ainda." />
        ) : (
          <table className="table">
          <thead>
            <tr>
              <th>Conta</th>
              <th>Seguidores</th>
              <th>Views</th>
              <th>Curtidas</th>
              <th>Comentários</th>
              <th>Publicados</th>
            </tr>
          </thead>
          <tbody>
            {accounts.map((a) => (
              <tr
                key={a.key}
                onClick={() => nav(`/analytics/conta/${a.key}`)}
                style={{ cursor: "pointer" }}
                title={`Ver vídeos publicados em ${a.label}`}
              >
                <td>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                    <PlatformLogo platform={a.platform} size={18} />
                    <span>{a.label}</span>
                    {!a.connected && (
                      <span
                        style={{
                          fontSize: 11,
                          color: "#f59e0b",
                          border: "1px solid #3a2f17",
                          background: "#241d0e",
                          borderRadius: 6,
                          padding: "1px 6px",
                        }}
                      >
                        sem login
                      </span>
                    )}
                  </span>
                </td>
                <td>{fmt(a.followers)}</td>
                <td>{fmt(a.total_views)}</td>
                <td>{fmt(a.total_likes)}</td>
                <td>{fmt(a.total_comments)}</td>
                <td>{a.published_videos}</td>
              </tr>
            ))}
          </tbody>
        </table>
        )}
      </div>
    </div>
  );
}

function EmptyChart({ text }) {
  return (
    <div className="chart-empty">
      <span>{text}</span>
    </div>
  );
}

function pct(n) {
  if (n === undefined || n === null) return "—";
  return `${n}%`;
}

function fmt(n) {
  if (n === undefined || n === null) return "—";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
  return String(n);
}
