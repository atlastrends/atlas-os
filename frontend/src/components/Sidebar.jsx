import React, { useState } from "react";
import { NavLink } from "react-router-dom";
import Api from "../api/client.js";

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
  const [upd, setUpd] = useState(null);
  const [updBusy, setUpdBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const checkUpdate = async () => {
    setUpdBusy(true);
    setMsg("Verificando…");
    try {
      const r = await Api.updateCheck();
      setUpd(r);
      if (!r?.configured) {
        setMsg("Atualizações não configuradas.");
      } else if (r?.error) {
        setMsg(r.error);
      } else if (r?.update_available) {
        setMsg("Nova versão disponível!");
      } else {
        setMsg("Você já está na versão mais recente. 👍");
      }
    } catch {
      setMsg("Não consegui verificar agora.");
    } finally {
      setUpdBusy(false);
    }
  };

  const applyUpdate = async () => {
    const ok = window.confirm(
      "Vou baixar e instalar a versão mais nova.\n\n" +
        "O painel vai fechar e voltar sozinho em alguns instantes numa janela nova. " +
        "Seus dados e senhas NÃO são apagados.\n\nDeseja continuar?"
    );
    if (!ok) return;
    setUpdBusy(true);
    try {
      const r = await Api.updateApply();
      if (r?.started) {
        window.alert(
          "🔄 Atualização iniciada em uma janela nova!\n\n" +
            "Aguarde ela terminar (baixa, instala e reinicia). " +
            "Quando o painel voltar, aperte F5 para recarregar."
        );
      } else {
        setMsg(r?.error || "Não consegui iniciar a atualização.");
      }
    } catch {
      setMsg("Falha ao iniciar a atualização.");
    } finally {
      setUpdBusy(false);
    }
  };

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
      <div className="sidebar-update">
        <div className="su-title">🔄 Atualizações</div>
        <div className="su-line">
          Versão: <b>{upd?.current || "—"}</b>
          {upd?.update_available && <span className="su-badge">nova!</span>}
        </div>
        {msg && <div className="su-msg">{msg}</div>}
        <button className="su-btn" onClick={checkUpdate} disabled={updBusy}>
          {updBusy ? "Verificando…" : "🔎 Procurar atualizações"}
        </button>
        {upd?.update_available && (
          <button className="su-btn primary" onClick={applyUpdate} disabled={updBusy}>
            ⬇️ Atualizar agora
          </button>
        )}
      </div>
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
