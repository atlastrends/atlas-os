import React, { useEffect, useMemo, useState } from "react";
import Api from "../api/client.js";

// Formata dinheiro conforme a moeda do mercado (BRL/USD).
function money(value, currency = "BRL") {
  const n = Number(value || 0);
  const locale = currency === "BRL" ? "pt-BR" : "en-US";
  try {
    return n.toLocaleString(locale, { style: "currency", currency });
  } catch {
    return `${currency} ${n.toFixed(2)}`;
  }
}

const STATUS_LABEL = {
  draft: { txt: "Rascunho", cls: "badge" },
  review: { txt: "Aguardando revisão", cls: "badge badge-warn" },
  launching: { txt: "Enviando…", cls: "badge" },
  paused: { txt: "Criada (pausada)", cls: "badge badge-ok" },
  active: { txt: "Ativa (gastando)", cls: "badge badge-ok" },
  failed: { txt: "Falhou", cls: "badge badge-err" },
  credentials_missing: { txt: "Falta conta de anúncios", cls: "badge badge-warn" },
};

// -------------------------------------------------------------------
// GUIA DE CONVERSÃO — melhores práticas mundiais de anúncios em vídeo.
// Baseado no que grandes marcas e a própria Meta recomendam para gerar
// mais cliques e reter o público. Escrito de forma simples.
// -------------------------------------------------------------------
const CONVERSION_TIPS = [
  {
    icon: "⚡",
    title: "Gancho nos 3 primeiros segundos",
    text: "90% das pessoas decidem se continuam assistindo no começo. Abra com uma pergunta, um número forte ou o resultado final (\"antes e depois\"). Sem introdução longa.",
  },
  {
    icon: "🎯",
    title: "Um único pedido (CTA claro)",
    text: "Peça só UMA ação: \"Compre agora\", \"Toque no link\" ou \"Siga o canal\". Dois pedidos ao mesmo tempo confundem e derrubam o clique.",
  },
  {
    icon: "⭐",
    title: "Prova social (confiança)",
    text: "Mostre números e avaliações: \"+10 mil vendidos\", \"Nota 4,8\", \"Recomendado por milhares\". Prova reduz o medo de clicar e comprar.",
  },
  {
    icon: "⏳",
    title: "Urgência e escassez (verdadeiras)",
    text: "\"Só hoje\", \"Últimas unidades\", \"Oferta acaba em breve\". Cria motivo para agir agora — mas só use se for real, senão perde a confiança.",
  },
  {
    icon: "💡",
    title: "Benefício antes de característica",
    text: "Diga o que a pessoa GANHA, não só o que o produto TEM. Ex.: em vez de \"1200W\", diga \"fritura crocante em metade do tempo\".",
  },
  {
    icon: "📱",
    title: "Feito para o celular (vertical)",
    text: "Quase todo mundo assiste no celular. Vídeo em pé (9:16), textos grandes e legenda sempre ligada — 85% assistem sem som.",
  },
  {
    icon: "👀",
    title: "Mostre o produto em uso",
    text: "Ver a mão usando, o resultado aparecendo, o \"unboxing\". Demonstração real converte muito mais que só falar sobre o produto.",
  },
  {
    icon: "🔁",
    title: "Reimpacto (retargeting)",
    text: "Quem já viu o vídeo e não comprou é seu público mais quente. Anuncie de novo para ele — costuma custar menos e vender mais.",
  },
  {
    icon: "🧪",
    title: "Teste 2 ou 3 versões",
    text: "Nunca aposte tudo em um texto só. Rode variações de gancho/imagem, veja qual dá mais clique e coloque o dinheiro na vencedora.",
  },
];

// Pitches prontos: modelos de texto que seguem fórmulas de copywriting
// consagradas (AIDA, PAS). É só copiar, trocar [PRODUTO] e usar.
const PITCHES = {
  sales: [
    {
      name: "Oferta direta (AIDA)",
      framework: "Atenção → Interesse → Desejo → Ação",
      text:
        "🔥 [PRODUTO] que todo mundo está querendo!\n\n" +
        "✅ [benefício principal em 1 linha]\n" +
        "✅ [+10 mil vendidos / nota 4,8]\n" +
        "✅ Entrega rápida e segura\n\n" +
        "⏳ Oferta por tempo limitado — toque em COMPRAR AGORA antes que acabe!",
    },
    {
      name: "Dor e solução (PAS)",
      framework: "Problema → Agitação → Solução",
      text:
        "Cansado de [problema que o produto resolve]? 😩\n\n" +
        "Isso faz você perder tempo e dinheiro todo dia.\n\n" +
        "A solução é o [PRODUTO]: [benefício] em segundos. 🙌\n\n" +
        "👉 Toque no link e resolva isso hoje mesmo.",
    },
    {
      name: "Prova social",
      framework: "Confiança pela multidão",
      text:
        "Mais de [X mil] pessoas já compraram o [PRODUTO] ⭐⭐⭐⭐⭐\n\n" +
        "\"[frase curta de um cliente feliz]\"\n\n" +
        "Se elas aprovaram, você também vai amar.\n" +
        "🛒 Garanta o seu — link na tela!",
    },
  ],
  reach: [
    {
      name: "Retenção de canal",
      framework: "Gancho → Valor → Seguir",
      text:
        "🚀 Você precisa ver isso até o final!\n\n" +
        "[promessa do que a pessoa vai descobrir]\n\n" +
        "Salva esse vídeo e segue o canal pra não perder os próximos. 🔔",
    },
    {
      name: "Curiosidade",
      framework: "Pergunta que prende",
      text:
        "Você sabia que [fato surpreendente]? 🤯\n\n" +
        "A maioria das pessoas erra isso todos os dias.\n\n" +
        "Assiste até o fim que eu te mostro — e segue pra ver mais! 👀",
    },
  ],
};

// Informações que todo anúncio deve conter para reter e converter.
const RETENTION_CHECKLIST = [
  "Gancho forte nos primeiros 3 segundos",
  "Legenda ligada (85% assistem sem som)",
  "Benefício principal dito com clareza",
  "Prova social: número, avaliação ou depoimento",
  "Um único botão/pedido de ação (CTA)",
  "Link visível e fácil de tocar",
  "Vídeo vertical (9:16), pensado para o celular",
  "Motivo para agir agora (urgência real)",
];

export default function Marketing() {
  const [status, setStatus] = useState(null);
  const [videos, setVideos] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [rec, setRec] = useState(null);
  const [budget, setBudget] = useState("");
  const [period, setPeriod] = useState("weekly");
  const [campaigns, setCampaigns] = useState([]);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState(null);
  const [recLoading, setRecLoading] = useState(false);
  const [roiRanking, setRoiRanking] = useState([]);

  async function loadAll() {
    setLoading(true);
    try {
      const [st, best, list, camps, roi] = await Promise.all([
        Api.marketingStatus(),
        Api.marketingBestVideo(),
        Api.listVideos({}),
        Api.marketingCampaigns(),
        Api.marketingRoiRanking(10).catch(() => ({ items: [] })),
      ]);
      setStatus(st);
      setCampaigns(camps || []);
      setRoiRanking(roi?.items || []);
      const vids = (list?.items || list || []).filter((v) => v?.id);
      setVideos(vids);
      const pick = best?.id || vids[0]?.id || null;
      setSelectedId(pick);
    } catch (e) {
      setMsg({ type: "err", text: "Erro ao carregar: " + (e?.message || e) });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAll();
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setRec(null);
      return;
    }
    setRecLoading(true);
    setRec(null);
    Api.marketingRecommendation(selectedId)
      .then((r) => {
        setRec(r);
        // Sugere automaticamente o pacote "Recomendado".
        const sug = (r?.budget_suggestions || []).find((s) => s.recommended);
        if (sug && !budget) {
          setBudget(String(sug.amount));
          setPeriod(sug.period);
        }
      })
      .catch(() => setRec(null))
      .finally(() => setRecLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  const daily = useMemo(() => {
    const amt = Number(budget || 0);
    if (!amt) return 0;
    return amt / (period === "monthly" ? 30 : 7);
  }, [budget, period]);

  const currency = rec?.currency || "BRL";

  async function submit(publish) {
    if (!selectedId) return;
    const amt = Number(budget || 0);
    if (!amt || amt <= 0) {
      setMsg({ type: "err", text: "Digite um valor de orçamento maior que zero." });
      return;
    }
    setLoading(true);
    setMsg(null);
    try {
      const res = await Api.createCampaign({
        video_id: selectedId,
        budget_amount: amt,
        budget_period: period,
        publish,
      });
      const st = STATUS_LABEL[res.status]?.txt || res.status;
      if (res.status === "credentials_missing") {
        setMsg({ type: "warn", text: res.error || "Falta a conta de anúncios." });
        window.alert(
          "⚠️ Plano salvo, mas ainda falta conectar a conta de anúncios da Meta.\n\n" +
            (res.error || "Configure a Conta de Anúncios no .env para publicar.")
        );
      } else if (res.status === "failed") {
        setMsg({ type: "err", text: res.error || "Falha ao publicar." });
        window.alert("❌ Falha: " + (res.error || "não consegui concluir."));
      } else if (publish) {
        setMsg({ type: "ok", text: `Campanha enviada. Status: ${st}.` });
        window.alert(`🚀 Anúncio enviado!\n\nStatus atual: ${st}.`);
      } else {
        setMsg({
          type: "ok",
          text: "✅ Plano salvo! Veja na seção \"Campanhas\" mais abaixo e clique em \"Publicar\" quando quiser.",
        });
        window.alert(
          "✅ Plano salvo para revisão!\n\n" +
            "Ele NÃO foi publicado ainda — ficou guardado.\n\n" +
            "Role a página até a seção \"Campanhas\" (mais abaixo) para conferir " +
            "os detalhes e clicar em \"Publicar\" quando estiver pronto."
        );
      }
      const camps = await Api.marketingCampaigns();
      setCampaigns(camps || []);
    } catch (e) {
      const detail = e?.response?.data?.detail || e?.message || String(e);
      setMsg({ type: "err", text: detail });
    } finally {
      setLoading(false);
    }
  }

  async function launchExisting(id) {
    setLoading(true);
    setMsg(null);
    try {
      const res = await Api.launchCampaign(id);
      if (res.status === "credentials_missing") {
        setMsg({ type: "warn", text: res.error });
      } else if (res.status === "failed") {
        setMsg({ type: "err", text: res.error });
      } else {
        setMsg({ type: "ok", text: "Campanha enviada ao Gerenciador de Anúncios." });
      }
      const camps = await Api.marketingCampaigns();
      setCampaigns(camps || []);
    } catch (e) {
      setMsg({ type: "err", text: e?.message || String(e) });
    } finally {
      setLoading(false);
    }
  }

  const selected = videos.find((v) => v.id === selectedId);

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      setMsg({ type: "ok", text: "Texto copiado! É só colar no seu anúncio." });
    } catch {
      setMsg({ type: "warn", text: "Não consegui copiar automaticamente. Selecione e copie na mão." });
    }
  }

  async function regeneratePitches() {
    if (!selectedId) return;
    setRecLoading(true);
    setMsg(null);
    try {
      const r = await Api.marketingRecommendation(selectedId, true);
      setRec(r);
      setMsg({ type: "ok", text: "IA gerou novos pitches para este vídeo. ✨" });
    } catch (e) {
      setMsg({ type: "err", text: "Não consegui gerar novos pitches agora. Tente de novo." });
    } finally {
      setRecLoading(false);
    }
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>📣 Marketing / Anúncios</h1>
          <p className="muted">
            Escolha um vídeo, defina o orçamento e o painel monta o melhor
            anúncio automaticamente. O valor e a publicação são sempre seus.
          </p>
        </div>
        <button className="btn" onClick={loadAll} disabled={loading}>
          ↻ Atualizar
        </button>
      </div>

      {/* Prontidão */}
      {status && (
        <div className="card readiness">
          <ReadyItem
            ok={status.meta_token}
            label="Token da Meta"
          />
          <ReadyItem
            ok={status.ad_account_br || status.ad_account_us}
            label="Conta de anúncios"
            hint="Necessária para publicar de verdade"
          />
          <ReadyItem
            ok={status.public_url_ready}
            label="Link público (https)"
            hint="Necessário para o Instagram/Facebook baixarem o vídeo"
          />
        </div>
      )}

      {msg && <div className={`alert alert-${msg.type}`}>{msg.text}</div>}

      <RoiRanking
        items={roiRanking}
        selectedId={selectedId}
        onPick={(id) => {
          setSelectedId(id);
          setMsg(null);
        }}
      />

      <div className="grid-2">
        {/* Coluna: escolher vídeo + orçamento */}
        <div className="card">
          <h3>1. Vídeo do anúncio</h3>
          <p className="muted small">
            Já sugerimos o vídeo com os melhores números. Você pode trocar.
          </p>
          <select
            className="input"
            value={selectedId || ""}
            onChange={(e) => {
              setSelectedId(Number(e.target.value));
              setMsg(null);
            }}
          >
            {videos.map((v) => (
              <option key={v.id} value={v.id}>
                {v.kind === "affiliate" ? "🛒" : "🔥"} {v.title || v.topic || `Vídeo ${v.id}`}
              </option>
            ))}
          </select>

          {selected?.video_url && (
            <video
              className="preview"
              src={selected.video_url}
              controls
              muted
              playsInline
            />
          )}

          <h3 style={{ marginTop: 18 }}>2. Orçamento (manual)</h3>
          <div className="budget-row">
            <input
              className="input"
              type="number"
              min="0"
              step="1"
              placeholder="Ex.: 150"
              value={budget}
              onChange={(e) => setBudget(e.target.value)}
            />
            <div className="seg">
              <button
                className={period === "weekly" ? "seg-on" : ""}
                onClick={() => setPeriod("weekly")}
              >
                Por semana
              </button>
              <button
                className={period === "monthly" ? "seg-on" : ""}
                onClick={() => setPeriod("monthly")}
              >
                Por mês
              </button>
            </div>
          </div>
          {rec?.budget_suggestions && (
            <div className="chips">
              {rec.budget_suggestions.map((s) => (
                <button
                  key={s.label}
                  className={`chip ${s.recommended ? "chip-rec" : ""}`}
                  onClick={() => {
                    setBudget(String(s.amount));
                    setPeriod(s.period);
                  }}
                >
                  {s.label}: {money(s.amount, currency)}/sem
                </button>
              ))}
            </div>
          )}
          <p className="muted small">
            Gasto diário estimado: <b>{money(daily, currency)}</b>
            {rec?.min_daily_budget
              ? ` (mínimo recomendado ${money(rec.min_daily_budget, currency)}/dia)`
              : ""}
          </p>

          <div className="actions">
            <button
              className="btn btn-ghost"
              onClick={() => submit(false)}
              disabled={loading}
            >
              💾 Revisar antes de publicar
            </button>
            <button
              className="btn btn-primary"
              onClick={() => submit(true)}
              disabled={loading}
            >
              🚀 Publicar anúncio
            </button>
          </div>
          {msg && (
            <div className={`alert alert-${msg.type}`} style={{ marginTop: 10 }}>
              {msg.text}
            </div>
          )}
        </div>

        {/* Coluna: plano automático */}
        <div className="card">
          <div className="plan-head">
            <h3>Plano do anúncio (automático)</h3>
            {rec?.ai_generated && <span className="ai-tag">✨ IA</span>}
          </div>
          {recLoading && (
            <div className="ai-loading">
              <span className="spinner" /> A IA está analisando este vídeo e
              escrevendo os melhores pitches…
            </div>
          )}
          {!recLoading && !rec && (
            <p className="muted">Selecione um vídeo para ver o plano.</p>
          )}
          {!recLoading && rec && (
            <div className="plan">
              <PlanRow k="Objetivo" v={rec.goal_label} />
              <PlanRow k="Mercado" v={rec.market === "BR" ? "🇧🇷 Brasil" : "🇺🇸 EUA"} />
              <PlanRow
                k="Público"
                v={`${rec.audience?.age_min}-${rec.audience?.age_max} anos · ${(rec.audience?.countries || []).join(", ")}`}
              />
              <PlanRow k="Interesses" v={(rec.audience?.interests || []).join(", ")} />
              <PlanRow
                k="Posicionamentos"
                v={(rec.placements?.recomendados || []).join(", ")}
              />
              <PlanRow k="Botão (CTA)" v={ctaLabel(rec.cta)} />
              {rec.link_url && <PlanRow k="Link" v={rec.link_url} />}
              <div className="plan-copy">
                <div className="copy-head">
                  <div className="muted small">
                    Texto do anúncio{rec.ai_generated ? " (gerado por IA)" : ""}:
                  </div>
                  <button
                    className="btn btn-sm"
                    onClick={() => copyText(rec.primary_text)}
                  >
                    📋 Copiar
                  </button>
                </div>
                <pre>{rec.primary_text}</pre>
                <div className="muted small">
                  Título: <b>{rec.headline}</b>
                </div>
                {rec.description && (
                  <div className="muted small">
                    Apoio: {rec.description}
                  </div>
                )}
              </div>

              {/* Pitches gerados por IA para ESTE vídeo */}
              {Array.isArray(rec.pitches) && rec.pitches.length > 0 && (
                <div className="ai-pitches">
                  <div className="pitch-group-title">
                    ✨ Pitches da IA para este vídeo
                  </div>
                  <div className="pitch-grid">
                    {rec.pitches.map((p, i) => (
                      <PitchCard
                        key={`${p.name}-${i}`}
                        pitch={{
                          name: p.name,
                          framework: p.angle,
                          text: p.text,
                        }}
                        onCopy={copyText}
                      />
                    ))}
                  </div>
                </div>
              )}

              <button
                className="btn btn-ghost"
                style={{ marginTop: 14 }}
                onClick={regeneratePitches}
                disabled={recLoading}
              >
                🔄 Gerar novos pitches com IA
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Campanhas criadas */}
      <div className="card">
        <h3>Campanhas</h3>
        {campaigns.length === 0 && (
          <p className="muted">Nenhuma campanha ainda.</p>
        )}
        {campaigns.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>Vídeo</th>
                <th>Objetivo</th>
                <th>Mercado</th>
                <th>Orçamento</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {campaigns.map((c) => {
                const s = STATUS_LABEL[c.status] || { txt: c.status, cls: "badge" };
                return (
                  <tr key={c.id}>
                    <td>{c.video_title || `#${c.video_id}`}</td>
                    <td>{c.goal === "sales" ? "Vendas" : "Alcance"}</td>
                    <td>{c.market}</td>
                    <td>
                      {money(c.budget_amount, c.currency)}/
                      {c.budget_period === "monthly" ? "mês" : "sem"}
                    </td>
                    <td>
                      <span className={s.cls}>{s.txt}</span>
                    </td>
                    <td>
                      {c.external_url ? (
                        <a href={c.external_url} target="_blank" rel="noreferrer">
                          Abrir
                        </a>
                      ) : (
                        <button
                          className="btn btn-sm"
                          onClick={() => launchExisting(c.id)}
                          disabled={loading}
                        >
                          Publicar
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* GUIA DE CONVERSÃO — melhores práticas mundiais */}
      <div className="card">
        <h3>🌍 Guia de conversão — o que faz o cliente clicar</h3>
        <p className="muted small">
          Práticas usadas pelas maiores marcas do mundo para ganhar mais
          cliques e reter o público. Aplique no vídeo e no texto do anúncio.
        </p>
        <div className="tips-grid">
          {CONVERSION_TIPS.map((t) => (
            <div className="tip-card" key={t.title}>
              <div className="tip-icon">{t.icon}</div>
              <div>
                <div className="tip-title">{t.title}</div>
                <div className="muted small">{t.text}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* PITCHES PRONTOS — copiar e colar */}
      <div className="card">
        <h3>✍️ Modelos prontos (genéricos)</h3>
        <p className="muted small">
          Modelos de texto que seguem fórmulas de vendas consagradas. A IA já
          cria pitches sob medida para o vídeo escolhido acima; use estes como
          apoio. Troque as partes entre [colchetes] pelas informações do produto.
        </p>

        <div className="pitch-group-title">🛒 Para vender (afiliados)</div>
        <div className="pitch-grid">
          {PITCHES.sales.map((p) => (
            <PitchCard key={p.name} pitch={p} onCopy={copyText} />
          ))}
        </div>

        <div className="pitch-group-title" style={{ marginTop: 18 }}>
          🔥 Para crescer o canal (reels)
        </div>
        <div className="pitch-grid">
          {PITCHES.reach.map((p) => (
            <PitchCard key={p.name} pitch={p} onCopy={copyText} />
          ))}
        </div>
      </div>

      {/* CHECKLIST DE RETENÇÃO */}
      <div className="card">
        <h3>✅ Checklist do anúncio perfeito</h3>
        <p className="muted small">
          Antes de publicar, confira se o vídeo e o texto têm tudo isto. Quanto
          mais itens marcados, maior a chance de clique e venda.
        </p>
        <div className="checklist">
          {RETENTION_CHECKLIST.map((item) => (
            <div className="check-item" key={item}>
              <span className="check-mark">✓</span> {item}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function PitchCard({ pitch, onCopy }) {
  return (
    <div className="pitch-card">
      <div className="pitch-head">
        <div>
          <div className="pitch-name">{pitch.name}</div>
          <div className="muted small">{pitch.framework}</div>
        </div>
        <button className="btn btn-sm" onClick={() => onCopy(pitch.text)}>
          📋 Copiar
        </button>
      </div>
      <pre className="pitch-text">{pitch.text}</pre>
    </div>
  );
}

// -------------------------------------------------------------------
// RANKING DE ROI — qual vídeo vale mais a pena anunciar.
// -------------------------------------------------------------------
function RoiRanking({ items, selectedId, onPick }) {
  if (!items || items.length === 0) return null;

  const withData = items.filter((v) => v.views > 0);
  const list = withData.length ? withData : items;
  const top = list[0];

  function roasLabel(v) {
    if (v.kind !== "affiliate") return "—";
    if (!v.est_roas) return "sem dados";
    return `${v.est_roas.toFixed(1)}x`;
  }

  function confBadge(c) {
    if (c === "alta") return "badge badge-ok";
    if (c === "media") return "badge badge-warn";
    return "badge";
  }

  return (
    <div className="card">
      <h3>🏆 Qual vídeo tem o maior ROI para anunciar</h3>
      <p className="muted small">
        Ranking automático por <b>potencial de retorno</b>. Combina cliques no
        link (CTR), engajamento e valor do produto. O ROI é uma{" "}
        <b>estimativa</b> — quanto maior, mais vale a pena colocar dinheiro.
      </p>

      {top && (
        <div className="alert alert-ok" style={{ marginTop: 8 }}>
          👉 <b>Melhor aposta agora:</b>{" "}
          {top.kind === "affiliate" ? "🛒" : "🔥"}{" "}
          {top.title || `Vídeo ${top.id}`} — ROI estimado{" "}
          <b>{roasLabel(top)}</b>. {top.reason}
        </div>
      )}

      <div className="table-wrap" style={{ marginTop: 10 }}>
        <table className="table">
          <thead>
            <tr>
              <th>#</th>
              <th>Vídeo</th>
              <th>Views</th>
              <th>Cliques</th>
              <th>CTR</th>
              <th>ROI est.</th>
              <th>Confiança</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {list.map((v, i) => (
              <tr
                key={v.id}
                className={v.id === selectedId ? "row-sel" : undefined}
              >
                <td>{i + 1}</td>
                <td>
                  {v.kind === "affiliate" ? "🛒 " : "🔥 "}
                  {v.title || `Vídeo ${v.id}`}
                </td>
                <td>{Number(v.views || 0).toLocaleString("pt-BR")}</td>
                <td>{Number(v.clicks || 0).toLocaleString("pt-BR")}</td>
                <td>{v.ctr_pct ? `${v.ctr_pct}%` : "—"}</td>
                <td>
                  <b>{roasLabel(v)}</b>
                </td>
                <td>
                  <span className={confBadge(v.confidence)}>
                    {v.confidence}
                  </span>
                </td>
                <td>
                  <button
                    className="btn btn-sm"
                    onClick={() => onPick(v.id)}
                    disabled={v.id === selectedId}
                  >
                    {v.id === selectedId ? "Selecionado" : "Anunciar este"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small" style={{ marginTop: 8 }}>
        Dica: no afiliado, o melhor ROI costuma vir do vídeo que <b>já</b>{" "}
        recebe muitos cliques organicamente e promove um produto de comissão
        maior. Anunciar um vencedor validado rende mais que apostar num vídeo
        sem dados.
      </p>
    </div>
  );
}

function ReadyItem({ ok, label, hint }) {
  return (
    <div className="ready-item">
      <span className={ok ? "dot dot-ok" : "dot dot-off"} />
      <div>
        <div>{label}</div>
        {hint && !ok && <div className="muted small">{hint}</div>}
      </div>
    </div>
  );
}

function PlanRow({ k, v }) {
  return (
    <div className="plan-row">
      <div className="plan-k">{k}</div>
      <div className="plan-v">{v}</div>
    </div>
  );
}

function ctaLabel(cta) {
  const map = {
    SHOP_NOW: "Comprar agora",
    LEARN_MORE: "Saiba mais",
    WATCH_MORE: "Assistir mais",
    SIGN_UP: "Cadastrar",
  };
  return map[cta] || cta;
}
