import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  RadialBarChart,
  RadialBar,
} from "recharts";
import Api from "../api/client.js";
import StatCard from "../components/StatCard.jsx";
import PlatformLogo, { platformName } from "../components/PlatformLogo.jsx";
import Toast from "../components/Toast.jsx";

const TOOLTIP_STYLE = {
  background: "#1a2130",
  border: "1px solid #232c3d",
  borderRadius: 10,
  color: "#e8edf5",
  fontSize: 13,
};

export default function Overview() {
  const [ov, setOv] = useState(null);
  const [platforms, setPlatforms] = useState([]);
  const [jobs, setJobs] = useState({});
  const [top, setTop] = useState([]);
  const [toast, setToast] = useState(null);
  const nav = useNavigate();

  const load = async () => {
    try {
      const [o, p, j, t] = await Promise.all([
        Api.overview(),
        Api.platforms(),
        Api.jobs(),
        Api.topVideos(5),
      ]);
      setOv(o);
      setPlatforms(p);
      setJobs(j);
      setTop(Array.isArray(t) ? t : []);
    } catch {
      setToast({ type: "error", msg: "Não foi possível carregar (API offline?)." });
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 20000);
    return () => clearInterval(t);
  }, []);

  const fetchAmazon = async () => {
    await Api.fetchAmazon();
    setToast({ type: "ok", msg: "Busca de produtos iniciada em segundo plano." });
    load();
  };
  const generateReels = async () => {
    await Api.generateReels();
    setToast({ type: "ok", msg: "Geração de reels iniciada (3 PT + 3 EN)." });
    load();
  };
  const autoApprove = async () => {
    const r = await Api.autoApprove();
    setToast({
      type: "ok",
      msg: r?.result
        ? `Aprovação automática: ${r.result.approved ?? 0} aprovados, ${
            r.result.published ?? 0
          } publicados, ${r.result.skipped ?? 0} ignorados.`
        : "Aprovação automática iniciada.",
    });
    load();
  };
  const collectMetrics = async () => {
    await Api.collectMetrics();
    setToast({ type: "ok", msg: "Atualização de estatísticas iniciada." });
    load();
  };

  const jobBadge = (name) => {
    const s = jobs?.[name]?.status;
    if (!s || s === "idle") return null;
    const map = {
      running: { cls: "publishing", txt: "em andamento" },
      done: { cls: "approved", txt: "concluído" },
      error: { cls: "failed", txt: "erro" },
    };
    const info = map[s] || { cls: "created", txt: s };
    return (
      <span className={`badge ${info.cls}`} style={{ marginLeft: 8 }}>
        {s === "running" ? <span className="spinner" style={{ width: 11, height: 11 }} /> : null}
        {info.txt}
      </span>
    );
  };

  // ---- dados dos gráficos ----
  const statusData = [
    { name: "Publicados", value: ov?.published ?? 0, color: "#22c55e" },
    { name: "Aguardando", value: ov?.pending_review ?? 0, color: "#f59e0b" },
    { name: "Aprovados", value: ov?.approved ?? 0, color: "#06b6d4" },
    { name: "Rejeitados", value: ov?.rejected ?? 0, color: "#ef4444" },
    { name: "Falhas", value: ov?.failed ?? 0, color: "#8b5cf6" },
  ].filter((d) => d.value > 0);
  const statusTotal = statusData.reduce((a, b) => a + b.value, 0);

  const contentData = [
    { name: "Reels", value: ov?.total_reels ?? 0, color: "#6366f1" },
    { name: "Afiliados", value: ov?.total_affiliate ?? 0, color: "#06b6d4" },
  ].filter((d) => d.value > 0);
  const contentTotal = contentData.reduce((a, b) => a + b.value, 0);

  const engagement = Number(ov?.engagement_rate ?? 0);
  const gaugeData = [
    {
      name: "Engajamento",
      value: Math.min(engagement, 100),
      fill: engagement >= 6 ? "#22c55e" : engagement >= 3 ? "#06b6d4" : "#f59e0b",
    },
  ];

  const platformData = platforms.map((p) => ({
    name: platformName(p.platform),
    Seguidores: p.followers || 0,
    Views: p.total_views || 0,
  }));

  return (
    <div>
      <div className="page-head">
        <div>
          <h2>Visão Geral</h2>
          <p>Monitoramento em tempo real da fábrica de conteúdo ATLAS OS.</p>
        </div>
        <div className="toolbar">
          <button className="btn primary" onClick={fetchAmazon}>
            🛒 Buscar produtos {jobBadge("fetch_amazon_products")}
          </button>
          <button className="btn" onClick={generateReels}>
            🔥 Gerar Reels {jobBadge("generate_reels")}
          </button>
          <button className="btn" onClick={autoApprove}>
            ✅ Aprovar {jobBadge("auto_approval")}
          </button>
          <button className="btn" onClick={collectMetrics}>
            📊 Estatísticas {jobBadge("collect_metrics")}
          </button>
        </div>
      </div>

      {/* KPIs principais — poucos e diretos */}
      <div className="grid kpis">
        <StatCard icon="🎞️" tone="cyan" label="Vídeos totais" value={ov?.total_videos ?? "—"} foot={`${ov?.total_reels ?? 0} reels · ${ov?.total_affiliate ?? 0} afiliados`} />
        <StatCard icon="🚀" tone="green" label="Publicados" value={ov?.published ?? "—"} foot={`${ov?.pending_review ?? 0} aguardando revisão`} />
        <StatCard icon="👁️" tone="cyan" label="Visualizações" value={fmt(ov?.views)} foot={`${fmt(ov?.followers)} seguidores`} />
        <StatCard icon="📊" tone="pink" label="Engajamento" value={pct(ov?.engagement_rate)} foot={`CTR afiliados ${pct(ov?.click_through_rate)}`} />
      </div>

      {/* Gráficos principais */}
      <div className="charts-3">
        <div className="card chart-card">
          <div className="chart-head">Status da produção</div>
          {statusTotal === 0 ? (
            <EmptyChart text="Sem vídeos ainda." />
          ) : (
            <div className="chart-wrap">
              <ResponsiveContainer width="100%" height={210}>
                <PieChart>
                  <Pie
                    data={statusData}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={62}
                    outerRadius={90}
                    paddingAngle={2}
                    stroke="none"
                  >
                    {statusData.map((d) => (
                      <Cell key={d.name} fill={d.color} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={TOOLTIP_STYLE} />
                </PieChart>
              </ResponsiveContainer>
              <div className="chart-center">
                <div className="chart-center-value">{statusTotal}</div>
                <div className="chart-center-label">vídeos</div>
              </div>
            </div>
          )}
          <div className="chart-legend">
            {statusData.map((d) => (
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
                <defs />
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
            <span className="legend-item"><i style={{ background: "#ec4899" }} />❤️ {fmt(ov?.likes)}</span>
            <span className="legend-item"><i style={{ background: "#06b6d4" }} />💬 {fmt(ov?.comments)}</span>
            <span className="legend-item"><i style={{ background: "#6366f1" }} />🔁 {fmt(ov?.shares)}</span>
          </div>
        </div>

        <div className="card chart-card">
          <div className="chart-head">Reels x Afiliados</div>
          {contentTotal === 0 ? (
            <EmptyChart text="Sem vídeos ainda." />
          ) : (
            <div className="chart-wrap">
              <ResponsiveContainer width="100%" height={210}>
                <PieChart>
                  <Pie
                    data={contentData}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={62}
                    outerRadius={90}
                    paddingAngle={2}
                    stroke="none"
                  >
                    {contentData.map((d) => (
                      <Cell key={d.name} fill={d.color} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={TOOLTIP_STYLE} />
                </PieChart>
              </ResponsiveContainer>
              <div className="chart-center">
                <div className="chart-center-value">{fmt(ov?.affiliate_clicks)}</div>
                <div className="chart-center-label">cliques afiliados</div>
              </div>
            </div>
          )}
          <div className="chart-legend">
            {contentData.map((d) => (
              <span key={d.name} className="legend-item">
                <i style={{ background: d.color }} />
                {d.name} <b>{d.value}</b>
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* Desempenho por plataforma */}
      <div className="grid" style={{ gridTemplateColumns: "1.6fr 1fr", alignItems: "stretch" }}>
        <div className="card chart-card">
          <div className="chart-head">Desempenho por plataforma</div>
          {platformData.length === 0 ? (
            <EmptyChart text="Conecte as plataformas para ver os números." />
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={platformData} barGap={6}>
                <CartesianGrid strokeDasharray="3 3" stroke="#232c3d" vertical={false} />
                <XAxis dataKey="name" stroke="#93a1b5" fontSize={12} tickLine={false} />
                <YAxis stroke="#93a1b5" fontSize={12} tickLine={false} axisLine={false} tickFormatter={fmt} />
                <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => fmt(v)} cursor={{ fill: "rgba(99,102,241,.08)" }} />
                <Bar dataKey="Seguidores" fill="#6366f1" radius={[6, 6, 0, 0]} />
                <Bar dataKey="Views" fill="#06b6d4" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="card chart-card">
          <div className="chart-head">Plataformas</div>
          <div className="platform-list">
            {platforms.length === 0 ? (
              <EmptyChart text="Nenhuma plataforma conectada." />
            ) : (
              platforms.map((p) => (
                <div
                  key={p.platform}
                  className="platform-row"
                  onClick={() => nav("/analytics")}
                >
                  <PlatformLogo platform={p.platform} size={26} />
                  <div className="platform-info">
                    <div className="platform-name">{platformName(p.platform)}</div>
                    <div className="platform-sub">{p.published_videos} publicados · {fmt(p.total_views)} views</div>
                  </div>
                  <div className="platform-value">{fmt(p.followers)}</div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Top vídeos */}
      <div className="section-title">Top vídeos</div>
      <div className="card">
        {top.length === 0 ? (
          <p className="foot" style={{ color: "var(--text-faint)" }}>
            Ainda sem métricas. Assim que os vídeos forem publicados, as
            estatísticas são coletadas automaticamente a cada 1 hora.
          </p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Vídeo</th>
                <th>Tipo</th>
                <th>Views</th>
                <th>Curtidas</th>
                <th>Coment.</th>
                <th>Cliques</th>
              </tr>
            </thead>
            <tbody>
              {top.map((v) => (
                <tr
                  key={v.id}
                  style={{ cursor: "pointer" }}
                  onClick={() => nav("/analytics")}
                >
                  <td>{v.title || `#${v.id}`}</td>
                  <td>
                    <span className="badge created">
                      {v.kind === "affiliate" ? "Afiliado" : "Reel"}
                    </span>
                  </td>
                  <td>{fmt(v.views)}</td>
                  <td>{fmt(v.likes)}</td>
                  <td>{fmt(v.comments)}</td>
                  <td>{fmt(v.clicks)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <Toast toast={toast} onClose={() => setToast(null)} />
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

function fmt(n) {
  if (n === undefined || n === null) return "—";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
  return String(n);
}

function pct(n) {
  if (n === undefined || n === null) return "—";
  return `${n}%`;
}
