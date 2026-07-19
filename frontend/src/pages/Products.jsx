import React, { useEffect, useMemo, useState } from "react";
import Api from "../api/client.js";
import Toast from "../components/Toast.jsx";
import StatCard from "../components/StatCard.jsx";

// Pagina de produtos:
//  1) dispara a busca (scraper) dos produtos EM ALTA;
//  2) mostra as categorias encontradas para o usuario escolher
//     quais quer e quantos videos por categoria;
//  3) dispara a geracao apenas do que foi selecionado.
export default function Products() {
  const [fetchJob, setFetchJob] = useState({ status: "idle" });
  const [genJob, setGenJob] = useState({ status: "idle" });
  const [groups, setGroups] = useState([]);
  const [selection, setSelection] = useState({}); // key -> { checked, quantity }
  const [toast, setToast] = useState(null);

  // Robo automatico de afiliados (busca + gera + publica a cada 2h).
  const [autoAff, setAutoAff] = useState({
    active: false,
    interval_minutes: 120,
    next_run_at: null,
  });
  const [autoBusy, setAutoBusy] = useState(false);
  const [cleaning, setCleaning] = useState(false);

  const keyOf = (g) => `${g.marketplace_code}::${g.category}`;

  const loadJobs = async () => {
    try {
      const jobs = await Api.jobs();
      setFetchJob(jobs?.fetch_amazon_products || { status: "idle" });
      setGenJob(jobs?.generate_selected || { status: "idle" });
    } catch {
      /* ignore */
    }
  };

  const loadAutoAff = async () => {
    try {
      const s = await Api.autoAffiliateStatus();
      if (s) setAutoAff(s);
    } catch {
      /* ignore */
    }
  };

  const loadGroups = async () => {
    try {
      const data = await Api.availableProducts();
      setGroups(Array.isArray(data) ? data : []);
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    loadJobs();
    loadGroups();
    loadAutoAff();
    // Enquanto um trabalho roda, verifica o progresso a cada 2s para a barra
    // de % andar suave. A lista de categorias atualiza mais devagar.
    const jobsTimer = setInterval(loadJobs, 2000);
    const groupsTimer = setInterval(loadGroups, 8000);
    const autoTimer = setInterval(loadAutoAff, 10000);
    return () => {
      clearInterval(jobsTimer);
      clearInterval(groupsTimer);
      clearInterval(autoTimer);
    };
  }, []);

  const fetchRunning = fetchJob?.status === "running";
  const genRunning = genJob?.status === "running";
  const genPct =
    typeof genJob?.progress === "number"
      ? Math.max(0, Math.min(100, genJob.progress))
      : 0;

  const fetchNow = async () => {
    await Api.fetchAmazon();
    setToast({ type: "ok", msg: "Busca iniciada: Mais Vendidos por categoria (BR + US)." });
    loadJobs();
  };

  const toggleAutoAff = async () => {
    setAutoBusy(true);
    try {
      if (autoAff.active) {
        const s = await Api.stopAutoAffiliate();
        setAutoAff(s);
        setToast({ type: "ok", msg: "Robô automático de afiliados DESLIGADO." });
      } else {
        const s = await Api.startAutoAffiliate(120);
        setAutoAff(s);
        setToast({
          type: "ok",
          msg: "Robô LIGADO: busca, gera e publica sozinho a cada 2 horas.",
        });
      }
    } catch {
      setToast({ type: "err", msg: "Não consegui mudar o robô automático." });
    } finally {
      setAutoBusy(false);
    }
  };

  const cleanPublished = async () => {
    if (
      !window.confirm(
        "Apagar do seu computador SÓ os arquivos de vídeo já PUBLICADOS?\n\n" +
          "Os vídeos continuam publicados nas redes e as ESTATÍSTICAS " +
          "(visualizações, curtidas) são mantidas. Isso só libera espaço no PC."
      )
    )
      return;
    setCleaning(true);
    try {
      const r = await Api.clearPublished("affiliate");
      setToast({
        type: "ok",
        msg: `Espaço liberado: ${r?.removed_files ?? 0} arquivo(s), ~${
          r?.freed_mb ?? 0
        } MB. Estatísticas mantidas.`,
      });
    } catch {
      setToast({ type: "err", msg: "Não consegui apagar os arquivos publicados." });
    } finally {
      setCleaning(false);
    }
  };

  const toggle = (g) => {
    const k = keyOf(g);
    setSelection((prev) => {
      const cur = prev[k] || { checked: false, quantity: 1 };
      return { ...prev, [k]: { ...cur, checked: !cur.checked } };
    });
  };

  const allChecked =
    groups.length > 0 && groups.every((g) => selection[keyOf(g)]?.checked);
  const someChecked =
    groups.some((g) => selection[keyOf(g)]?.checked) && !allChecked;

  const toggleAll = () => {
    setSelection((prev) => {
      const next = { ...prev };
      const check = !allChecked;
      groups.forEach((g) => {
        const k = keyOf(g);
        const cur = next[k] || { checked: false, quantity: 1 };
        next[k] = { ...cur, checked: check, quantity: cur.quantity || 1 };
      });
      return next;
    });
  };

  const setQty = (g, value) => {
    const k = keyOf(g);
    const max = g.count || 1;
    let q = parseInt(value, 10);
    if (Number.isNaN(q) || q < 1) q = 1;
    if (q > max) q = max;
    setSelection((prev) => {
      const cur = prev[k] || { checked: true, quantity: 1 };
      return { ...prev, [k]: { ...cur, checked: true, quantity: q } };
    });
  };

  const chosen = useMemo(() => {
    return groups
      .filter((g) => selection[keyOf(g)]?.checked)
      .map((g) => ({
        marketplace_code: g.marketplace_code,
        category: g.category,
        quantity: selection[keyOf(g)]?.quantity || 1,
      }));
  }, [groups, selection]);

  const totalVideos = chosen.reduce((s, c) => s + (c.quantity || 0), 0);

  const summary = useMemo(() => {
    const categorias = groups.length;
    const produtos = groups.reduce((s, g) => s + (g.count || 0), 0);
    const mercados = new Set(groups.map((g) => g.marketplace_code)).size;
    return { categorias, produtos, mercados };
  }, [groups]);

  const generate = async () => {
    if (!chosen.length) {
      setToast({ type: "err", msg: "Selecione ao menos uma categoria." });
      return;
    }
    await Api.generateSelected(chosen);
    setToast({
      type: "ok",
      msg: `Geracao iniciada: ${totalVideos} video(s) selecionado(s).`,
    });
    loadJobs();
  };

  return (
    <div>
      <div className="page-head">
        <div>
          <h2>Produtos Amazon</h2>
          <p>
            Busca os produtos <b>Mais Vendidos</b> por categoria, no Brasil e
            EUA. Depois voce escolhe as categorias e quantos videos quer por
            categoria.
          </p>
        </div>
        <button className="btn primary" onClick={fetchNow} disabled={fetchRunning}>
          {fetchRunning ? <span className="spinner" /> : "🛒"} Buscar produtos agora
        </button>
      </div>

      <div className="grid kpis" style={{ marginBottom: 16 }}>
        <StatCard icon="📦" tone="cyan" label="Produtos disponíveis" value={summary.produtos} foot={`${summary.mercados} mercado(s)`} />
        <StatCard icon="🗂️" tone="pink" label="Categorias" value={summary.categorias} />
        <StatCard icon="🎬" tone="green" label="Vídeos selecionados" value={totalVideos} foot={`${chosen.length} categoria(s)`} />
        <StatCard icon="🤖" tone={autoAff.active ? "green" : "amber"} label="Robô automático" value={autoAff.active ? "Ligado" : "Desligado"} foot={autoAff.active ? "busca e publica a cada 2h" : "clique para ligar abaixo"} />
      </div>

      <div
        className="card"
        style={{
          marginTop: 4,
          border: autoAff.active ? "1px solid #14532d" : "1px solid #334155",
          background: autoAff.active ? "#052e1a" : undefined,
        }}
      >
        <div className="section-title" style={{ margin: 0 }}>
          🤖 Robô automático de afiliados
        </div>
        <p className="foot" style={{ marginTop: 8, color: "var(--text-faint)" }}>
          Quando <b>ligado</b>, sozinho e a cada <b>2 horas</b> ele: busca os{" "}
          <b>mais vendidos</b> por categoria, gera vídeo só dos{" "}
          <b>produtos novos</b> (não repete) e, quando o <b>assunto bate</b> com
          o vídeo, <b>publica automaticamente</b>. Na dúvida, deixa para você
          revisar. Fica ligado até você desligar.
        </p>

        <div
          style={{
            display: "flex",
            gap: 12,
            alignItems: "center",
            flexWrap: "wrap",
            marginTop: 10,
          }}
        >
          <button
            className={`btn ${autoAff.active ? "" : "primary"}`}
            onClick={toggleAutoAff}
            disabled={autoBusy}
          >
            {autoBusy ? (
              <span className="spinner" />
            ) : autoAff.active ? (
              "⏹ Desligar robô"
            ) : (
              "▶ Ligar robô (a cada 2h)"
            )}
          </button>

          <span className={`badge ${autoAff.active ? "ok" : ""}`}>
            {autoAff.active ? "LIGADO" : "desligado"}
          </span>

          {autoAff.active && autoAff.next_run_at ? (
            <span className="foot" style={{ color: "var(--text-faint)" }}>
              Próxima verificação: {fmtDate(autoAff.next_run_at)}
            </span>
          ) : null}
        </div>

        <div
          style={{
            marginTop: 16,
            paddingTop: 14,
            borderTop: "1px solid #334155",
          }}
        >
          <p className="foot" style={{ margin: 0, color: "var(--text-faint)" }}>
            <b>Liberar espaço:</b> apaga do seu computador só os arquivos de
            vídeo <b>já publicados</b>. Os vídeos continuam no ar e as{" "}
            <b>estatísticas são mantidas</b>.
          </p>
          <button
            className="btn ghost"
            onClick={cleanPublished}
            disabled={cleaning}
            style={{ marginTop: 10 }}
          >
            {cleaning ? <span className="spinner" /> : "🧹"} Apagar vídeos já
            publicados (liberar espaço)
          </button>
        </div>
      </div>

      <div className="card">
        <div className="section-title" style={{ margin: 0 }}>
          Status da busca
        </div>
        <table className="table" style={{ marginTop: 12 }}>
          <tbody>
            <tr>
              <th>Situação</th>
              <td>
                <span className={`badge ${statusClass(fetchJob?.status)}`}>
                  {fetchJob?.status || "idle"}
                </span>
              </td>
            </tr>
            <tr>
              <th>Início</th>
              <td>{fmtDate(fetchJob?.started_at)}</td>
            </tr>
            <tr>
              <th>Fim</th>
              <td>{fmtDate(fetchJob?.finished_at)}</td>
            </tr>
            {fetchJob?.error ? (
              <tr>
                <th>Erro</th>
                <td style={{ color: "#fca5a5" }}>{fetchJob.error}</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="section-title" style={{ margin: 0 }}>
          Escolha as categorias e a quantidade de vídeos
        </div>

        {groups.length === 0 ? (
          <p className="foot" style={{ marginTop: 14, color: "var(--text-faint)" }}>
            Nenhum produto disponível ainda. Clique em <b>“Buscar produtos
            agora”</b> e aguarde a busca terminar.
          </p>
        ) : (
          <>
            <table className="table" style={{ marginTop: 12 }}>
              <thead>
                <tr>
                  <th style={{ width: 40 }}>
                    <input
                      type="checkbox"
                      checked={allChecked}
                      ref={(el) => {
                        if (el) el.indeterminate = someChecked;
                      }}
                      onChange={toggleAll}
                      title="Selecionar todas as categorias"
                    />
                  </th>
                  <th>Mercado</th>
                  <th>Categoria</th>
                  <th>Disponíveis</th>
                  <th style={{ width: 140 }}>Qtd. de vídeos</th>
                </tr>
              </thead>
              <tbody>
                {groups.map((g) => {
                  const k = keyOf(g);
                  const sel = selection[k] || { checked: false, quantity: 1 };
                  return (
                    <tr key={k}>
                      <td>
                        <input
                          type="checkbox"
                          checked={!!sel.checked}
                          onChange={() => toggle(g)}
                        />
                      </td>
                      <td>
                        <span className="badge created">
                          {g.marketplace_code === "US" ? "🇺🇸 EUA" : "🇧🇷 Brasil"}
                        </span>
                      </td>
                      <td>{g.category_label || g.category}</td>
                      <td>{g.count}</td>
                      <td>
                        <input
                          type="number"
                          min={1}
                          max={g.count || 1}
                          value={sel.quantity || 1}
                          disabled={!sel.checked}
                          onChange={(e) => setQty(g, e.target.value)}
                          style={{ width: 80 }}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            <div
              style={{
                marginTop: 16,
                display: "flex",
                alignItems: "center",
                gap: 14,
              }}
            >
              <button
                className="btn primary"
                onClick={generate}
                disabled={genRunning || totalVideos === 0}
              >
                {genRunning ? <span className="spinner" /> : "🎬"} Gerar vídeos
                selecionados ({totalVideos})
              </button>
              <span className="foot" style={{ color: "var(--text-faint)" }}>
                A geração leva alguns minutos por vídeo (voz IA + b-roll).
              </span>
            </div>
          </>
        )}
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="section-title" style={{ margin: 0 }}>
          Status da geração
        </div>
        <table className="table" style={{ marginTop: 12 }}>
          <tbody>
            <tr>
              <th>Situação</th>
              <td>
                <span className={`badge ${statusClass(genJob?.status)}`}>
                  {genJob?.status || "idle"}
                </span>
              </td>
            </tr>
            {genRunning ? (
              <tr>
                <th>Progresso</th>
                <td>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <div
                      style={{
                        flex: 1,
                        height: 10,
                        borderRadius: 999,
                        background: "rgba(255,255,255,0.10)",
                        overflow: "hidden",
                      }}
                    >
                      <div
                        style={{
                          width: `${genPct}%`,
                          height: "100%",
                          borderRadius: 999,
                          background:
                            "linear-gradient(90deg,#6366f1,#22c55e)",
                          transition: "width .4s ease",
                        }}
                      />
                    </div>
                    <b style={{ minWidth: 44, textAlign: "right" }}>
                      {genPct}%
                    </b>
                  </div>
                  {genJob?.stage ? (
                    <div
                      className="foot"
                      style={{ marginTop: 6, color: "var(--text-faint)" }}
                    >
                      {genJob.stage}
                    </div>
                  ) : null}
                  {genJob?.current_title ? (
                    <div style={{ marginTop: 4 }}>🎬 {genJob.current_title}</div>
                  ) : null}
                </td>
              </tr>
            ) : null}
            <tr>
              <th>Etapa</th>
              <td>{genJob?.step || "—"}</td>
            </tr>
            <tr>
              <th>Fim</th>
              <td>{fmtDate(genJob?.finished_at)}</td>
            </tr>
            {genJob?.error ? (
              <tr>
                <th>Erro</th>
                <td style={{ color: "#fca5a5" }}>{genJob.error}</td>
              </tr>
            ) : null}
          </tbody>
        </table>
        <p className="foot" style={{ marginTop: 14, color: "var(--text-faint)" }}>
          Os vídeos gerados aparecem em “Vídeos Afiliados”. Produtos que já
          viraram vídeo não são recriados.
        </p>
      </div>

      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}

function statusClass(s) {
  if (s === "running") return "publishing";
  if (s === "done") return "published";
  if (s === "error") return "failed";
  return "created";
}
function fmtDate(v) {
  if (!v) return "—";
  try {
    return new Date(v).toLocaleString("pt-BR");
  } catch {
    return v;
  }
}

