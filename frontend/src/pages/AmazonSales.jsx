import React, { useEffect, useRef, useState } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import Api from "../api/client.js";
import StatCard from "../components/StatCard.jsx";
import Toast from "../components/Toast.jsx";

const TOOLTIP_STYLE = {
  background: "#1a2130",
  border: "1px solid #232c3d",
  borderRadius: 10,
  color: "#e8edf5",
  fontSize: 13,
};

const PERIODS = [
  { label: "7 dias", value: 7 },
  { label: "30 dias", value: 30 },
  { label: "90 dias", value: 90 },
  { label: "Tudo", value: 0 },
];

function money(value, market) {
  const n = Number(value || 0);
  if (market === "US") {
    return n.toLocaleString("en-US", { style: "currency", currency: "USD" });
  }
  return n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function num(value) {
  return Number(value || 0).toLocaleString("pt-BR");
}

export default function AmazonSales() {
  const [stats, setStats] = useState(null);
  const [market, setMarket] = useState(""); // "" = todos
  const [days, setDays] = useState(30);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);
  const fileRef = useRef(null);

  const load = async (refresh = false) => {
    try {
      const s = await Api.amazonSalesStats({
        market: market || undefined,
        days: days || undefined,
        refresh: refresh ? 1 : undefined,
      });
      setStats(s);
      const novos = s?.auto_import?.imported_rows || 0;
      if (novos > 0) {
        setToast({
          type: "success",
          msg: `Encontrei e importei ${novos} venda(s) nova(s) automaticamente.`,
        });
      }
    } catch {
      setToast({ type: "error", msg: "Falha ao carregar as vendas." });
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [market, days]);

  // Atualiza sozinho a cada 60s enquanto a pagina estiver aberta.
  useEffect(() => {
    const id = setInterval(() => load(), 60000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [market, days]);

  const onPickFile = () => fileRef.current?.click();

  const onFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // permite reimportar o mesmo arquivo depois
    if (!file) return;
    setBusy(true);
    setToast({ type: "info", msg: `Importando ${file.name}…` });
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("market", market || "auto");
      const r = await Api.amazonSalesImport(fd);
      setToast({
        type: "success",
        msg: `Importado! ${r.imported} novas linhas, ${r.skipped} já existiam.`,
      });
      await load();
    } catch (err) {
      const detail =
        err?.response?.data?.detail || "Não consegui ler esse arquivo.";
      setToast({ type: "error", msg: detail });
    } finally {
      setBusy(false);
    }
  };

  const clearAll = async () => {
    const ok = window.confirm(
      "Isso apaga os dados de vendas importados" +
        (market ? ` do mercado ${market}` : " (todos os mercados)") +
        ".\nOs relatórios na Amazon NÃO são afetados. Continuar?"
    );
    if (!ok) return;
    setBusy(true);
    try {
      await Api.amazonSalesClear(market || undefined);
      setToast({ type: "success", msg: "Dados apagados." });
      await load();
    } catch {
      setToast({ type: "error", msg: "Falha ao apagar." });
    } finally {
      setBusy(false);
    }
  };

  const t = stats?.totals || {};
  const bm = stats?.by_market || {};
  const hasData = stats?.has_data;
  const periodData = (stats?.by_period || []).map((d) => ({
    name: d.date?.slice(5), // MM-DD
    Itens: d.qty || 0,
  }));

  return (
    <div>
      <div className="page-head">
        <div>
          <h2>Vendas Amazon</h2>
          <p>Ganhos e desempenho dos seus links de afiliado.</p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <input
            ref={fileRef}
            type="file"
            accept=".csv,.xlsx,.txt"
            style={{ display: "none" }}
            onChange={onFile}
          />
          <button className="btn ghost" onClick={() => load(true)} disabled={busy}>
            ↻ Atualizar
          </button>
          <button className="btn" onClick={onPickFile} disabled={busy}>
            {busy ? "Processando…" : "⬆️ Importar relatório"}
          </button>
        </div>
      </div>

      {/* Como baixar o relatório */}
      <div
        className="card"
        style={{ padding: 16, marginBottom: 16, borderLeft: "3px solid #f59e0b" }}
      >
        <b>Tudo automático:</b> baixe o relatório uma vez no{" "}
        <i>Amazon Associates</i> → <b>Relatórios</b> → <b>Baixar relatório</b>{" "}
        (Ganhos / Pedidos / Cliques). O ATLAS procura o arquivo sozinho na sua
        pasta <b>Downloads</b> e importa automaticamente — os números aparecem
        aqui sem você precisar clicar em nada. Os <b>cliques</b> do próprio
        ATLAS também são contados sozinhos. (A Amazon não libera as vendas por
        API; por isso o único passo é aquele download.)
      </div>

      {/* Filtros */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
        <div className="seg">
          {[
            { label: "Todos", value: "" },
            { label: "Brasil", value: "BR" },
            { label: "US", value: "US" },
          ].map((m) => (
            <button
              key={m.value}
              className={market === m.value ? "seg-on" : ""}
              onClick={() => setMarket(m.value)}
            >
              {m.label}
            </button>
          ))}
        </div>
        <div className="seg">
          {PERIODS.map((p) => (
            <button
              key={p.value}
              className={days === p.value ? "seg-on" : ""}
              onClick={() => setDays(p.value)}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {!hasData ? (
        <div className="card" style={{ padding: 32, textAlign: "center" }}>
          <div style={{ fontSize: 40, marginBottom: 8 }}>🧾</div>
          <h3 style={{ margin: "0 0 6px" }}>Nenhuma venda importada ainda</h3>
          <p style={{ color: "var(--text-faint)", marginTop: 0 }}>
            Baixe o relatório no Amazon Associates (ele cai na sua pasta
            Downloads) e o ATLAS importa sozinho. Se preferir, use{" "}
            <b>Importar relatório</b> para escolher o arquivo na mão.
          </p>
          <button className="btn" onClick={onPickFile} disabled={busy}>
            ⬆️ Importar relatório
          </button>
        </div>
      ) : (
        <>
          {/* Ganhos por mercado (moedas diferentes, por isso separado) */}
          <div className="section-title" style={{ marginTop: 0 }}>
            Ganhos por mercado
          </div>
          <div className="grid stats">
            {["BR", "US"].map((mk) => {
              const d = bm[mk];
              if (market && market !== mk) return null;
              return (
                <StatCard
                  key={mk}
                  label={mk === "BR" ? "🇧🇷 Amazon Brasil" : "🇺🇸 Amazon US"}
                  value={money(d?.commission, mk)}
                  foot={`Receita: ${money(d?.revenue, mk)} · ${num(d?.qty)} itens`}
                  tone={mk === "BR" ? "green" : "cyan"}
                />
              );
            })}
          </div>

          {/* Totais gerais (contagens, seguras de somar) */}
          <div className="section-title">Resumo geral (no período)</div>
          <div className="grid stats">
            <StatCard label="Itens vendidos" value={num(t.qty)} icon="📦" />
            <StatCard label="Cliques (relatório)" value={num(t.clicks)} icon="👆" />
            <StatCard
              label="Conversão"
              value={`${num(t.conversion)}%`}
              foot="itens vendidos ÷ cliques"
              icon="🎯"
            />
            <StatCard
              label="Cliques rastreados pelo ATLAS"
              value={num(stats.internal_clicks)}
              foot="contados automaticamente"
              icon="🔗"
            />
            <StatCard label="Devoluções" value={num(t.returns)} icon="↩️" />
          </div>

          {/* Itens vendidos por dia */}
          {periodData.length > 0 && (
            <>
              <div className="section-title">Itens vendidos por dia</div>
              <div className="card" style={{ padding: 16, height: 300 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={periodData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#232c3d" />
                    <XAxis dataKey="name" stroke="#93a1b5" fontSize={12} />
                    <YAxis stroke="#93a1b5" fontSize={12} allowDecimals={false} />
                    <Tooltip contentStyle={TOOLTIP_STYLE} />
                    <Bar dataKey="Itens" fill="#22c55e" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </>
          )}

          {/* Tabelas de ranking */}
          <div className="grid-2" style={{ marginTop: 16 }}>
            <RankTable
              title="🏆 Mais vendidos"
              rows={stats.top_sold}
              valueLabel="Itens"
              render={(r) => num(r.qty)}
            />
            <RankTable
              title="💰 Mais lucrativos"
              rows={stats.top_earnings}
              valueLabel="Ganhos"
              render={(r) => money(r.commission, r.market)}
            />
          </div>
          <div className="grid-2" style={{ marginTop: 16 }}>
            <RankTable
              title="👆 Mais clicados"
              rows={stats.top_clicked}
              valueLabel="Cliques"
              render={(r) => num(r.clicks)}
            />
            <div className="card" style={{ padding: 16 }}>
              <div className="section-title" style={{ marginTop: 0 }}>
                Gerenciar dados
              </div>
              <p style={{ color: "var(--text-faint)", fontSize: 14 }}>
                {stats.last_import?.source_file
                  ? `Último arquivo importado: ${stats.last_import.source_file}`
                  : "Nenhum arquivo importado ainda."}
              </p>
              <button className="btn ghost" onClick={clearAll} disabled={busy}>
                🗑️ Apagar dados importados
              </button>
            </div>
          </div>
        </>
      )}

      {toast && (
        <Toast toast={toast} onClose={() => setToast(null)} />
      )}
    </div>
  );
}

function RankTable({ title, rows, valueLabel, render }) {
  return (
    <div className="card" style={{ padding: 0 }}>
      <div className="section-title" style={{ margin: 16 }}>
        {title}
      </div>
      <table className="table">
        <thead>
          <tr>
            <th>#</th>
            <th>Produto</th>
            <th>Mercado</th>
            <th style={{ textAlign: "right" }}>{valueLabel}</th>
          </tr>
        </thead>
        <tbody>
          {(rows || []).length === 0 ? (
            <tr>
              <td colSpan={4} style={{ color: "var(--text-faint)", padding: 16 }}>
                Sem dados ainda.
              </td>
            </tr>
          ) : (
            rows.map((r, i) => (
              <tr key={(r.asin || r.product_name || i) + "-" + r.market}>
                <td>{i + 1}</td>
                <td title={r.product_name}>
                  {String(r.product_name || "—").slice(0, 60)}
                </td>
                <td>{r.market}</td>
                <td style={{ textAlign: "right", fontWeight: 600 }}>{render(r)}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
