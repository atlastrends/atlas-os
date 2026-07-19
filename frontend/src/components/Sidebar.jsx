import React from "react";
import { NavLink } from "react-router-dom";

const groups = [
  {
    title: "Painel",
    items: [{ to: "/", icon: "📊", label: "Visão Geral", end: true }],
  },
  {
    title: "Produção",
    items: [
      { to: "/produtos", icon: "🛒", label: "Produtos Amazon" },
      { to: "/afiliados", icon: "🎬", label: "Vídeos Afiliados" },
      { to: "/reels", icon: "🔥", label: "Reels Trending" },
    ],
  },
  {
    title: "Distribuição",
    items: [
      { to: "/publicacoes", icon: "🚀", label: "Publicações" },
      { to: "/marketing", icon: "📣", label: "Marketing" },
      { to: "/analytics", icon: "📈", label: "Analytics" },
    ],
  },
];

export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="brand">
        <img src="/atlas.svg" alt="ATLAS" />
        <div>
          <div className="brand-name">ATLAS OS</div>
          <div className="brand-sub">Control Center</div>
        </div>
      </div>
      <nav className="nav">
        {groups.map((g) => (
          <React.Fragment key={g.title}>
            <div className="nav-group">{g.title}</div>
            {g.items.map((it) => (
              <NavLink key={it.to} to={it.to} end={it.end}>
                <span className="ico">{it.icon}</span>
                {it.label}
              </NavLink>
            ))}
          </React.Fragment>
        ))}
      </nav>
      <div className="sidebar-foot">
        <div className="foot-row">
          <span className="dot on" />
          Fábrica de conteúdo automatizada
        </div>
        <div>v1.0 · BR + US · IA</div>
      </div>
    </aside>
  );
}
