import React, { useEffect, useMemo, useRef, useState } from "react";
import Api from "../api/client.js";

// Sugestoes de comentarios para testar rapido no modo simulacao.
const SUGGESTIONS = {
  pt: [
    "Esse produto serve pra pele oleosa?",
    "Qual o preço?",
    "Tem garantia?",
    "Vale a pena mesmo?",
    "Entrega pra todo Brasil?",
  ],
  en: [
    "Does it work on oily skin?",
    "What's the price?",
    "Is there a warranty?",
    "Is it really worth it?",
    "Do you ship worldwide?",
  ],
};

// Comentarios que o publico "manda sozinho" na live automatica (preview).
const AUTO_COMMENTS = {
  pt: [
    "Boa noite! Acabei de chegar 😍",
    "Quanto custa esse?",
    "Vale a pena mesmo?",
    "Serve pra pele oleosa?",
    "Tem cupom de desconto?",
    "Entrega pra todo Brasil?",
    "Esse é bom pra presente?",
    "Ja comprei o meu! 🛒",
    "Tem garantia?",
    "Qual a cor que vem?",
    "Chega rápido?",
    "Adorei essa live, muito organizada",
    "Faz frete grátis?",
    "Esse produto é original?",
    "Pode mostrar de novo o preço?",
    "Quantas unidades vem?",
    "É melhor que os outros?",
    "Comprando agora, obrigada! ❤️",
    "Recomenda pra iniciante?",
    "Tá na promoção até quando?",
  ],
  en: [
    "Just got here 😍",
    "How much is it?",
    "Is it really worth it?",
    "Any discount code?",
    "Do you ship everywhere?",
    "Is there a warranty?",
    "Just bought mine! 🛒",
    "Which colors are available?",
    "Does it ship fast?",
    "Loving this live!",
    "Is it the original?",
    "Can you show the price again?",
    "Would you recommend for beginners?",
    "How long is the promo?",
  ],
};

// Nomes ficticios so para deixar o chat da simulacao mais realista.
const FAKE_NAMES = [
  "Ana", "Bruno", "Carla", "Diego", "Elaine", "Felipe", "Gabi",
  "Hugo", "Iris", "João", "Kelly", "Lucas", "Marina", "Nina",
  "Otávio", "Paula", "Rafa", "Sofia", "Tiago", "Vitória",
];

function randomName() {
  return FAKE_NAMES[Math.floor(Math.random() * FAKE_NAMES.length)];
}

let _msgId = 0;
function nextId() {
  _msgId += 1;
  return _msgId;
}

export default function Live() {
  const [mode, setMode] = useState("sim"); // "sim" | "real"
  const [language, setLanguage] = useState("pt");
  const [productContext, setProductContext] = useState("");
  const [persona, setPersona] = useState("");
  const [live, setLive] = useState(false); // esta "no ar"?
  const [viewers, setViewers] = useState(0);
  const [messages, setMessages] = useState([]); // {id, role, name, text, engine, audioUrl, pending}
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [brain, setBrain] = useState(null);
  const [speaking, setSpeaking] = useState(false);
  const [caption, setCaption] = useState(""); // fala atual do apresentador (legenda no palco)

  // Produtos REAIS da bio (Amazon) + apresentador realista (foto).
  const [products, setProducts] = useState([]);
  const [productAsin, setProductAsin] = useState(""); // produto selecionado
  const [price, setPrice] = useState(""); // preco opcional mostrado na tela
  const [presenterUrl, setPresenterUrl] = useState(
    () => localStorage.getItem("atlas_live_presenter") || ""
  );
  const [presenterUploaded, setPresenterUploaded] = useState(false);
  const [presenterVer, setPresenterVer] = useState(0); // cache-bust da foto enviada
  const [uploading, setUploading] = useState(false);
  const [videoOn, setVideoOn] = useState(false); // gerar video do apresentador?
  const [videoUrl, setVideoUrl] = useState(""); // clipe atual tocando no palco

  // ----- Live GRAVADA (video pronto que roda como se fosse ao vivo) -----
  const [platformsList, setPlatformsList] = useState([]);
  const [buildPlatform, setBuildPlatform] = useState("amazon");
  const [secondsPer, setSecondsPer] = useState(30);
  const [maxProducts, setMaxProducts] = useState(0);
  const [useAi, setUseAi] = useState(true);
  const [building, setBuilding] = useState(false);
  const [clearingRec, setClearingRec] = useState(false);
  const [buildProg, setBuildProg] = useState(null); // {done,total,label,ok,reason,video}
  const [recorded, setRecorded] = useState([]);
  const [airName, setAirName] = useState(""); // video selecionado para transmitir
  const [airUrl, setAirUrl] = useState(""); // url do video no ar
  const [airManifest, setAirManifest] = useState(null);
  const [recap, setRecap] = useState(""); // frase de recomeco entre as repeticoes

  // ----- Live com VIDEOS JA PRONTOS (montagem, sem avatar) -----
  const [recSource, setRecSource] = useState("videos"); // "videos" | "foto"
  const [sources, setSources] = useState([]); // videos de produto ja gerados
  const [sourcesLoading, setSourcesLoading] = useState(false);
  const [selectedIds, setSelectedIds] = useState([]); // ids escolhidos, em ordem
  const [qaOn, setQaOn] = useState(true); // incluir perguntas/respostas do chat
  const [introOn, setIntroOn] = useState(true); // incluir abertura + encerramento

  // ----- Sala de controle (metricas + auto-comentarios + vendas) -----
  const [autoLive, setAutoLive] = useState(true); // a IA conduz sozinha (comenta + responde)
  const [metrics, setMetrics] = useState({
    peak: 0,
    likes: 0,
    comments: 0,
    follows: 0,
  });

  const audioRef = useRef(null);
  const videoRef = useRef(null);
  const airRef = useRef(null);
  const recapIdx = useRef(0);
  const airingRef = useRef(false);
  const buildTimer = useRef(null);
  const chatBottomRef = useRef(null);
  const viewersTimer = useRef(null);
  const metricsTimer = useRef(null);
  const autoTimer = useRef(null);
  const autoIdx = useRef(0);
  const sendingRef = useRef(false);
  const airingActive = airUrl && live; // true quando o video gravado esta no ar

  // Verifica se o "cerebro" (IA + voz) esta pronto.
  useEffect(() => {
    (async () => {
      try {
        const s = await Api.liveStatus();
        setBrain(s);
        setPresenterUploaded(!!s?.has_presenter);
      } catch {
        setBrain({ brain_ready: false });
      }
    })();
  }, []);

  // Rola o chat para a ultima mensagem.
  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Contador de espectadores "ao vivo" (ficticio na simulacao, so pra dar vida).
  useEffect(() => {
    if (!live) {
      if (viewersTimer.current) clearInterval(viewersTimer.current);
      return;
    }
    viewersTimer.current = setInterval(() => {
      setViewers((v) => Math.max(1, v + Math.floor(Math.random() * 15) - 5));
    }, 2500);
    return () => {
      if (viewersTimer.current) clearInterval(viewersTimer.current);
    };
  }, [live]);

  // Guarda o pico de espectadores.
  useEffect(() => {
    setMetrics((m) => (viewers > m.peak ? { ...m, peak: viewers } : m));
  }, [viewers]);

  // Pulso das metricas (curtidas e seguidores sobem sozinhos no ar).
  useEffect(() => {
    if (!live) return undefined;
    metricsTimer.current = setInterval(() => {
      setMetrics((m) => ({
        ...m,
        likes: m.likes + Math.floor(Math.random() * 9),
        follows: m.follows + (Math.random() < 0.3 ? 1 : 0),
      }));
    }, 2000);
    return () => clearInterval(metricsTimer.current);
  }, [live]);

  // A IA no comando: o publico comenta sozinho e a apresentadora responde.
  // NOTA: nao simulamos mais um "feed de vendas"/pedidos ficticios aqui -
  // mostrar pessoas comprando so faz sentido quando a live estiver REALMENTE
  // no ar e a compra for de verdade (sem isso, e' enganoso).
  useEffect(() => {
    if (!live || !autoLive) return undefined;
    let stop = false;
    const schedule = () => {
      const delay = 8000 + Math.random() * 9000;
      autoTimer.current = setTimeout(() => {
        if (stop) return;
        if (!sendingRef.current) {
          const bank = AUTO_COMMENTS[language] || AUTO_COMMENTS.pt;
          const q = bank[autoIdx.current % bank.length];
          autoIdx.current += 1;
          sendComment(q, { auto: true });
        }
        schedule();
      }, delay);
    };
    schedule();
    return () => {
      stop = true;
      if (autoTimer.current) clearTimeout(autoTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, autoLive, language]);

  const suggestions = useMemo(() => SUGGESTIONS[language] || SUGGESTIONS.pt, [language]);

  // Mercado da bio conforme o idioma (PT -> BR, EN -> US).
  const market = language === "en" ? "US" : "BR";

  // Carrega os produtos reais da bio para o mercado atual.
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await Api.liveProducts(market);
        if (!alive) return;
        const list = res?.products || [];
        setProducts(list);
        setProductAsin((cur) =>
          list.some((p) => p.asin === cur) ? cur : list[0]?.asin || ""
        );
      } catch {
        if (alive) setProducts([]);
      }
    })();
    return () => {
      alive = false;
    };
  }, [market]);

  // Guarda a foto do apresentador (fica salva pro proximo acesso).
  useEffect(() => {
    localStorage.setItem("atlas_live_presenter", presenterUrl);
  }, [presenterUrl]);

  const selectedProduct = useMemo(
    () => products.find((p) => p.asin === productAsin) || null,
    [products, productAsin]
  );

  // Escolher um produto ja preenche o contexto do apresentador com o titulo real.
  function selectProduct(p) {
    setProductAsin(p.asin);
    setProductContext(p.title);
  }

  // Foto que aparece no palco: a enviada (backend) tem prioridade; senao a URL colada.
  const presenterSrc = presenterUploaded
    ? `/api/live/presenter?v=${presenterVer}`
    : presenterUrl || "";

  async function handlePresenterUpload(file) {
    if (!file) return;
    setUploading(true);
    try {
      await Api.livePresenterUpload(file);
      setPresenterUploaded(true);
      setPresenterVer((v) => v + 1);
    } catch (e) {
      window.alert(
        "Não consegui enviar a foto: " + (e?.response?.data?.detail || e?.message || e)
      );
    } finally {
      setUploading(false);
    }
  }

  // -------- Live gravada: carregar plataformas + videos ja montados --------
  useEffect(() => {
    if (mode !== "gravada") return;
    let alive = true;
    (async () => {
      try {
        const p = await Api.livePlatforms();
        if (alive) setPlatformsList(p?.platforms || []);
      } catch {
        if (alive) setPlatformsList([]);
      }
      refreshRecorded(alive);
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  async function refreshRecorded(alive = true) {
    try {
      const r = await Api.liveRecorded();
      if (!alive) return;
      const vids = r?.videos || [];
      setRecorded(vids);
      setAirName((cur) => (vids.some((v) => v.video === cur) ? cur : vids[0]?.video || ""));
    } catch {
      if (alive) setRecorded([]);
    }
  }

  async function clearRecorded() {
    if (recorded.length === 0 || live) return;
    if (
      !window.confirm(
        `Apagar os ${recorded.length} vídeo(s) montado(s)? Eles serão removidos do disco.`
      )
    ) {
      return;
    }
    setClearingRec(true);
    try {
      await Api.liveClearRecorded();
      setAirName("");
      setAirUrl("");
      setAirManifest(null);
      await refreshRecorded(true);
    } catch {
      window.alert("Não consegui limpar os vídeos montados. Tente de novo.");
    } finally {
      setClearingRec(false);
    }
  }

  // Inicia a montagem do video (roda no servidor, pode demorar).
  async function startBuild() {
    if (building) return;
    setBuilding(true);
    setBuildProg({ done: 0, total: 0, label: "iniciando", ok: null });
    try {
      await Api.liveBuild({
        platform: buildPlatform,
        market,
        language,
        persona,
        seconds_per_product: secondsPer,
        max_products: Number(maxProducts) || 0,
        use_ai: useAi,
      });
      pollBuild();
    } catch (e) {
      setBuilding(false);
      setBuildProg({
        ok: false,
        reason: e?.response?.data?.detail || e?.message || "Falha ao iniciar.",
      });
    }
  }

  function pollBuild() {
    if (buildTimer.current) clearInterval(buildTimer.current);
    buildTimer.current = setInterval(async () => {
      try {
        const s = await Api.liveBuildStatus();
        setBuildProg(s);
        if (!s.running) {
          clearInterval(buildTimer.current);
          buildTimer.current = null;
          setBuilding(false);
          if (s.ok) refreshRecorded(true);
        }
      } catch {
        // mantem tentando; erro de rede momentaneo
      }
    }, 1500);
  }

  // ----- Montagem usando os VIDEOS DE PRODUTO ja gerados (sem avatar) -----
  async function loadSources() {
    setSourcesLoading(true);
    try {
      const r = await Api.liveSources(market, language, buildPlatform);
      setSources(r?.videos || []);
    } catch {
      setSources([]);
    } finally {
      setSourcesLoading(false);
    }
  }

  // Carrega os videos ja prontos ao entrar na montagem por video / trocar idioma.
  useEffect(() => {
    if (mode === "gravada" && recSource === "videos") loadSources();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, recSource, market, language, buildPlatform]);

  function toggleSource(id) {
    setSelectedIds((cur) =>
      cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]
    );
  }

  async function startMontage() {
    if (building) return;
    if (selectedIds.length === 0) {
      window.alert("Escolha pelo menos um vídeo de produto para montar a live.");
      return;
    }
    setBuilding(true);
    setBuildProg({ done: 0, total: 0, label: "iniciando", ok: null });
    try {
      await Api.liveBuildMontage({
        video_ids: selectedIds,
        platform: buildPlatform,
        market,
        language,
        persona,
        use_ai: useAi,
        qa: qaOn,
        add_intro: introOn,
      });
      pollBuild();
    } catch (e) {
      setBuilding(false);
      setBuildProg({
        ok: false,
        reason: e?.response?.data?.detail || e?.message || "Falha ao iniciar.",
      });
    }
  }

  useEffect(() => {
    return () => {
      if (buildTimer.current) clearInterval(buildTimer.current);
    };
  }, []);

  // Liga a transmissao de um video ja montado (roda em loop, como live).
  async function startAir(name) {
    const target = name || airName;
    if (!target) {
      window.alert("Monte um vídeo da live primeiro (botão “Gerar vídeo da live”).");
      return;
    }
    let manifest = null;
    try {
      manifest = await Api.liveManifest(target);
    } catch {
      manifest = null;
    }
    recapIdx.current = 0;
    setRecap("");
    setAirManifest(manifest);
    setAirName(target);
    setAirUrl(Api.liveRecordedUrl(target));
    resetLiveStats();
    setViewers(Math.floor(Math.random() * 120) + 40);
    airingRef.current = true;
    setLive(true);
  }

  // Fim de uma passada do video: mostra a frase de recomeco e repete (anti-loop).
  function onAirEnded() {
    const lines = airManifest?.recap_lines || [];
    const restart = () => {
      if (!airingRef.current) return;
      const v = airRef.current;
      if (v) {
        v.currentTime = 0;
        v.play().catch(() => {});
      }
    };
    if (lines.length) {
      const line = lines[recapIdx.current % lines.length];
      recapIdx.current += 1;
      setRecap(line);
      setTimeout(() => {
        setRecap("");
        restart();
      }, 3500);
    } else {
      restart();
    }
  }

  // Toca o clipe de video do apresentador (com a voz embutida) no palco.
  useEffect(() => {
    if (videoUrl && videoRef.current) {
      videoRef.current.currentTime = 0;
      videoRef.current.play().catch(() => {});
    }
  }, [videoUrl]);

  function startLive() {
    if (mode === "real") {
      window.alert(
        "🔴 O modo AO VIVO REAL ainda está em construção.\n\n" +
          "Faltam duas peças: o AVATAR (rosto com a boca mexendo, que roda no " +
          "Dell G15) e a TRANSMISSÃO para a plataforma. Por enquanto use o modo " +
          "SIMULAÇÃO para testar as respostas da IA com a voz."
      );
      return;
    }
    if (mode === "gravada") {
      startAir(airName);
      return;
    }
    setMessages([]);
    setCaption("");
    setVideoUrl("");
    resetLiveStats();
    setViewers(Math.floor(Math.random() * 120) + 40);
    setLive(true);
  }

  // Zera as metricas ao ligar uma nova live.
  function resetLiveStats() {
    setMetrics({ peak: 0, likes: 0, comments: 0, follows: 0 });
    autoIdx.current = 0;
  }

  function stopLive() {
    airingRef.current = false;
    setLive(false);
    setSpeaking(false);
    setCaption("");
    setVideoUrl("");
    setAirUrl("");
    setRecap("");
    if (audioRef.current) {
      audioRef.current.pause();
    }
    if (videoRef.current) {
      videoRef.current.pause();
    }
    if (airRef.current) {
      airRef.current.pause();
    }
  }

  async function sendComment(text, opts = {}) {
    const comment = (text ?? input).trim();
    if (!comment || sending) return;

    const viewerName = randomName();
    const viewerMsg = {
      id: nextId(),
      role: "viewer",
      name: viewerName,
      text: comment,
    };
    const hostMsg = {
      id: nextId(),
      role: "host",
      name: "Apresentadora IA",
      text: "",
      pending: true,
    };
    setMessages((m) => [...m, viewerMsg, hostMsg]);
    setMetrics((mm) => ({ ...mm, comments: mm.comments + 1 }));
    if (!opts.auto) setInput("");
    setSending(true);
    sendingRef.current = true;

    try {
      const res = await Api.liveAnswer({
        comment,
        language,
        product_context: productContext,
        persona,
        with_voice: !airingActive,
        with_video: videoOn && presenterUploaded && !airingActive,
      });

      if (!res?.ok) {
        setMessages((m) =>
          m.map((x) =>
            x.id === hostMsg.id
              ? {
                  ...x,
                  pending: false,
                  error: true,
                  text:
                    res?.reason ||
                    "A IA não respondeu. Verifique se a GROQ_API_KEY está configurada.",
                }
              : x
          )
        );
        return;
      }

      const audioUrl = res.audio_url || "";
      const clipUrl = res.video_url || "";
      setMessages((m) =>
        m.map((x) =>
          x.id === hostMsg.id
            ? { ...x, pending: false, text: res.answer, engine: res.engine, audioUrl }
            : x
        )
      );
      // Enquanto o video gravado esta no ar, a resposta fica so no chat
      // (nao toca voz por cima do audio do video).
      if (!airingActive) {
        setCaption(res.answer);
        if (clipUrl) {
          setSpeaking(true);
          setVideoUrl(clipUrl);
        } else if (audioUrl) {
          playAudio(audioUrl);
        }
      }
    } catch (e) {
      setMessages((m) =>
        m.map((x) =>
          x.id === hostMsg.id
            ? {
                ...x,
                pending: false,
                error: true,
                text: "Erro ao falar com o servidor: " + (e?.message || e),
              }
            : x
        )
      );
    } finally {
      setSending(false);
      sendingRef.current = false;
    }
  }

  function playAudio(url) {
    if (!audioRef.current) return;
    audioRef.current.src = url;
    setSpeaking(true);
    audioRef.current.play().catch(() => setSpeaking(false));
  }

  const brainReady = brain?.brain_ready;

  return (
    <div className="live-page">
      <div className="studio-head">
        <div className="studio-brand">
          <span className="studio-kicker">
            <span className="studio-dot" /> ATLAS LIVE STUDIO
          </span>
          <h2>Sala de controle</h2>
          <p>
            A <b>apresentadora de IA</b> conduz a transmissão, responde os
            comentários e você acompanha as <b>métricas</b> em tempo real.
          </p>
        </div>
        <div className="studio-controls">
          <span className={"onair-pill" + (live ? " live" : "")}>
            <i className="onair-dot" />
            {live ? "NO AR" : "FORA DO AR"}
          </span>
          <div className="toolbar">
            <div className="seg mode-tabs">
              <button
                className={mode === "sim" ? "on" : ""}
                onClick={() => setMode("sim")}
                disabled={live}
              >
                🧪 Simulação
              </button>
              <button
                className={mode === "gravada" ? "on" : ""}
                onClick={() => setMode("gravada")}
                disabled={live}
                title="Monta um vídeo com os produtos e transmite como se fosse ao vivo"
              >
                🎬 Live gravada
              </button>
              <button
                className={mode === "real" ? "on" : ""}
                onClick={() => setMode("real")}
                disabled={live}
                title="Precisa do avatar (Dell G15) e da transmissão — em breve"
              >
                🔴 Ao vivo real
              </button>
            </div>
            {live ? (
              <button className="btn danger golive" onClick={stopLive}>
                ⏹️ Encerrar
              </button>
            ) : (
              <button
                className="btn primary golive"
                onClick={startLive}
                disabled={mode === "gravada" && recorded.length === 0}
              >
                {mode === "gravada" ? "🔴 Ligar transmissão" : "▶️ Entrar ao vivo"}
              </button>
            )}
          </div>
        </div>
      </div>

      {!brainReady && (
        <div className="live-warn">
          ⚠️ O cérebro da IA não está pronto (falta a chave GROQ_API_KEY ou
          GEMINI_API_KEY no .env). As respostas não vão funcionar até configurar.
        </div>
      )}

      {/* -------- MÉTRICAS DA LIVE (sala de controle) -------- */}
      {live && (
        <div className="live-metrics">
          <div className="metric">
            <span className="m-ico">👁️</span>
            <div>
              <b>{viewers.toLocaleString("pt-BR")}</b>
              <small>espectadores · pico {metrics.peak.toLocaleString("pt-BR")}</small>
            </div>
          </div>
          <div className="metric">
            <span className="m-ico">❤️</span>
            <div>
              <b>{metrics.likes.toLocaleString("pt-BR")}</b>
              <small>curtidas</small>
            </div>
          </div>
          <div className="metric">
            <span className="m-ico">💬</span>
            <div>
              <b>{metrics.comments.toLocaleString("pt-BR")}</b>
              <small>comentários</small>
            </div>
          </div>
          <div className="metric">
            <span className="m-ico">➕</span>
            <div>
              <b>{metrics.follows.toLocaleString("pt-BR")}</b>
              <small>novos seguidores</small>
            </div>
          </div>
          <label className="ia-cmd" title="O público comenta sozinho e a IA responde">
            <input
              type="checkbox"
              checked={autoLive}
              onChange={(e) => setAutoLive(e.target.checked)}
            />
            <span>🤖 IA no comando</span>
          </label>
        </div>
      )}

      <div className="live-grid">
        {/* -------- PALCO (o que vai ao ar) -------- */}
        <div className="live-stage-wrap">
          <div className="phone">
            <div className={"stage" + (live ? " on" : "")}>
              <div className="stage-top">
                <span className={"live-badge" + (live ? " on" : "")}>
                  {live ? (mode === "sim" ? "🔴 AO VIVO · SIMULAÇÃO" : "🔴 AO VIVO") : "OFFLINE"}
                </span>
                {live && (
                  <span className="viewers">👁️ {viewers.toLocaleString("pt-BR")}</span>
                )}
              </div>

              <div className="stage-center">
                {mode === "gravada" && airUrl && live ? (
                  <div className="air-wrap">
                    <video
                      ref={airRef}
                      className="air-video"
                      src={airUrl}
                      autoPlay
                      playsInline
                      onEnded={onAirEnded}
                    />
                    {recap && <div className="air-recap">🔁 {recap}</div>}
                  </div>
                ) : (
                <>
                {/* Fundo de estudio profissional */}
                <div className="studio-bg" aria-hidden="true">
                  <span className="studio-glow" />
                  <span className="studio-floor" />
                </div>

                {/* Apresentador realista (video do avatar quando gerado, senao foto) */}
                <div className={"presenter" + (speaking ? " speaking" : "")}>
                  {videoUrl && live ? (
                    <video
                      ref={videoRef}
                      className="presenter-img"
                      src={videoUrl}
                      playsInline
                      autoPlay
                      onPlay={() => setSpeaking(true)}
                      onEnded={() => setSpeaking(false)}
                      onPause={() => setSpeaking(false)}
                    />
                  ) : presenterSrc ? (
                    <img
                      className="presenter-img"
                      src={presenterSrc}
                      alt="Apresentador"
                      onError={(e) => {
                        e.currentTarget.style.display = "none";
                      }}
                    />
                  ) : (
                    <div className="presenter-ph">
                      <div className="presenter-emoji">🧑‍💼</div>
                      <div className="presenter-hint">
                        Envie a foto de uma pessoa realista em{" "}
                        <b>Ajustes → Foto do apresentador</b>
                      </div>
                    </div>
                  )}
                  {speaking && !videoUrl && (
                    <div className="speak-bars">
                      <span></span><span></span><span></span><span></span>
                    </div>
                  )}
                </div>

                {/* Produto REAL da bio em destaque (estilo TV de vendas) */}
                {selectedProduct && live && (
                  <div className="showcase">
                    {selectedProduct.image && (
                      <img
                        className="showcase-img"
                        src={selectedProduct.image}
                        alt={selectedProduct.title}
                        onError={(e) => {
                          e.currentTarget.style.display = "none";
                        }}
                      />
                    )}
                    <div className="showcase-title">{selectedProduct.title}</div>
                    {price.trim() ? (
                      <div className="showcase-price">{price.trim()}</div>
                    ) : (
                      <div className="showcase-cta">🛒 Oferta na Amazon</div>
                    )}
                  </div>
                )}
                </>
                )}
              </div>

              {mode !== "gravada" && caption && live && (
                <div className="stage-caption">{caption}</div>
              )}

              {!live && (
                <div className="stage-idle">
                  <div className="idle-title">Pronto para entrar ao vivo</div>
                  <div className="idle-sub">
                    Clique em <b>Entrar ao vivo</b> para começar a{" "}
                    {mode === "real" ? "transmissão" : "simulação"}.
                  </div>
                </div>
              )}
            </div>
          </div>

          <audio
            ref={audioRef}
            onEnded={() => setSpeaking(false)}
            onPause={() => setSpeaking(false)}
            hidden
          />

          {/* Ajustes da live */}
          <div className="card live-config">
            <div className="cfg-title">⚙️ Ajustes da live</div>
            <label className="cfg-row">
              <span>Idioma</span>
              <div className="seg sm">
                <button
                  className={language === "pt" ? "on" : ""}
                  onClick={() => setLanguage("pt")}
                >
                  🇧🇷 Português
                </button>
                <button
                  className={language === "en" ? "on" : ""}
                  onClick={() => setLanguage("en")}
                >
                  🇺🇸 English
                </button>
              </div>
            </label>
            <div className="cfg-row">
              <span>Produto real da bio ({market})</span>
              <div className="prod-grid">
                {products.length === 0 && (
                  <div className="prod-empty">
                    Nenhum produto encontrado na bio para {market}.
                  </div>
                )}
                {products.map((p) => (
                  <button
                    key={p.asin || p.url}
                    type="button"
                    className={"prod-chip" + (p.asin === productAsin ? " on" : "")}
                    title={p.title}
                    onClick={() => selectProduct(p)}
                  >
                    {p.image ? (
                      <img
                        src={p.image}
                        alt=""
                        onError={(e) => {
                          e.currentTarget.style.visibility = "hidden";
                        }}
                      />
                    ) : (
                      <span className="prod-noimg">📦</span>
                    )}
                  </button>
                ))}
              </div>
            </div>
            <label className="cfg-row">
              <span>Fala do apresentador sobre o produto</span>
              <input
                type="text"
                placeholder="Escolha um produto acima ou escreva aqui"
                value={productContext}
                onChange={(e) => setProductContext(e.target.value)}
              />
            </label>
            <label className="cfg-row">
              <span>Preço na tela (opcional)</span>
              <input
                type="text"
                placeholder="Ex.: R$ 89,90"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
              />
            </label>
            <div className="cfg-row">
              <span>Foto do apresentador (pessoa realista)</span>
              <div className="presenter-upload">
                <label className="file-btn">
                  {uploading
                    ? "Enviando…"
                    : presenterUploaded
                    ? "Trocar foto"
                    : "Enviar foto"}
                  <input
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    hidden
                    disabled={uploading}
                    onChange={(e) => handlePresenterUpload(e.target.files?.[0])}
                  />
                </label>
                {presenterUploaded && <span className="ok-tag">✓ foto enviada</span>}
              </div>
              <input
                type="text"
                className="url-alt"
                placeholder="…ou cole a URL de uma foto (só pré-visualiza)"
                value={presenterUrl}
                onChange={(e) => setPresenterUrl(e.target.value)}
              />
            </div>
            <label className="cfg-row toggle-row">
              <span>
                Vídeo do apresentador (avatar)
                {brain?.avatar_engine ? ` · motor: ${brain.avatar_engine}` : ""}
              </span>
              <input
                type="checkbox"
                checked={videoOn}
                disabled={!presenterUploaded}
                onChange={(e) => setVideoOn(e.target.checked)}
              />
            </label>
            {!presenterUploaded && (
              <div className="cfg-note">
                Para ligar o vídeo do avatar, envie uma foto do apresentador acima.
              </div>
            )}
            {videoOn && brain?.avatar_engine === "ffmpeg" && (
              <div className="cfg-note">
                ℹ️ Motor <b>ffmpeg</b>: gera o vídeo com a foto + voz (ainda sem a boca
                mexendo). No G15 com <b>Wav2Lip</b> a boca passa a sincronizar.
              </div>
            )}
            <label className="cfg-row">
              <span>Estilo do apresentador (opcional)</span>
              <input
                type="text"
                placeholder="Ex.: animado e simpático, fala como amigo"
                value={persona}
                onChange={(e) => setPersona(e.target.value)}
              />
            </label>
          </div>
        </div>

        {/* -------- CHAT AO VIVO / PAINEL DA LIVE GRAVADA -------- */}
        {mode === "gravada" ? (
          <div className="card live-record">
            <div className="chat-head">
              <span>🎬 Live gravada</span>
              <span className="chat-engine">grava agora, transmite depois</span>
            </div>

            <div className="rec-body">
              {/* Fonte da live: vídeos já prontos (recomendado) ou foto + card */}
              <div className="rec-field">
                <span>Como montar a live</span>
                <div className="seg sm rec-src-seg">
                  <button
                    className={recSource === "videos" ? "on" : ""}
                    onClick={() => setRecSource("videos")}
                    disabled={building}
                  >
                    🎞️ Vídeos já prontos
                  </button>
                  <button
                    className={recSource === "foto" ? "on" : ""}
                    onClick={() => setRecSource("foto")}
                    disabled={building}
                  >
                    🖼️ Foto + card
                  </button>
                </div>
              </div>

              {recSource === "videos" && (
                <div className="montage">
                  <p className="rec-help">
                    Usa os <b>vídeos de produto que você já gerou</b> (com narração
                    real) e junta tudo numa <b>live</b>, sem avatar. Entre um vídeo e
                    outro, a IA <b>responde perguntas do chat</b>. Escolha os vídeos na
                    ordem que quiser:
                  </p>

                  <div className="rec-list-head">
                    <span>
                      🎬 Vídeos disponíveis ({market})
                      {selectedIds.length ? ` · ${selectedIds.length} escolhido(s)` : ""}
                    </span>
                    <span className="rec-head-actions">
                      {selectedIds.length > 0 && (
                        <button
                          className="mini-btn text"
                          onClick={() => setSelectedIds([])}
                          disabled={building}
                          title="Tirar a seleção de todos os vídeos"
                        >
                          Limpar seleção
                        </button>
                      )}
                      <button
                        className="mini-btn"
                        onClick={loadSources}
                        disabled={sourcesLoading}
                        title="Recarregar a lista"
                      >
                        ↻
                      </button>
                    </span>
                  </div>

                  <div className="src-list">
                    {sourcesLoading && <div className="rec-empty">Carregando vídeos…</div>}
                    {!sourcesLoading && sources.length === 0 && (
                      <div className="rec-empty">
                        Nenhum vídeo de produto encontrado para {market}. Gere vídeos de
                        afiliado primeiro. 🎬
                      </div>
                    )}
                    {sources.map((s) => {
                      const idx = selectedIds.indexOf(s.id);
                      const on = idx >= 0;
                      return (
                        <button
                          key={s.id}
                          type="button"
                          className={"src-item" + (on ? " on" : "")}
                          onClick={() => toggleSource(s.id)}
                          disabled={building}
                          title={s.title}
                        >
                          <span className="src-check">{on ? idx + 1 : ""}</span>
                          {s.image ? (
                            <img className="src-thumb" src={s.image} alt="" loading="lazy" />
                          ) : (
                            <span className="src-thumb ph" />
                          )}
                          <span className="src-info">
                            <b>{s.title}</b>
                            <small>
                              {s.category_label ? s.category_label + " · " : ""}
                              {s.language ? s.language.toUpperCase() + " · " : ""}
                              {s.size_mb}MB
                            </small>
                          </span>
                          <span
                            className={"src-badge" + (s.has_live ? " live" : "")}
                            title={
                              s.has_live
                                ? "Tem narração de live (áudio de apresentadora, sem gancho de reels)"
                                : "Usa o áudio do reels (gere de novo para ter a versão de live)"
                            }
                          >
                            {s.has_live ? "🎙️ LIVE" : "REELS"}
                          </span>
                        </button>
                      );
                    })}
                  </div>

                  <label className="rec-toggle">
                    <input
                      type="checkbox"
                      checked={introOn}
                      disabled={building}
                      onChange={(e) => setIntroOn(e.target.checked)}
                    />
                    <span>Abertura + encerramento que volta ao 1º produto (loop)</span>
                  </label>
                  <label className="rec-toggle">
                    <input
                      type="checkbox"
                      checked={qaOn}
                      disabled={building}
                      onChange={(e) => setQaOn(e.target.checked)}
                    />
                    <span>Perguntas do chat respondidas pela IA entre os produtos</span>
                  </label>
                  <label className="rec-toggle">
                    <input
                      type="checkbox"
                      checked={useAi}
                      disabled={building}
                      onChange={(e) => setUseAi(e.target.checked)}
                    />
                    <span>
                      Respostas escritas pela IA (mais naturais; sem IA é mais rápido)
                    </span>
                  </label>

                  <button
                    className="btn primary rec-build-btn"
                    onClick={startMontage}
                    disabled={building || selectedIds.length === 0}
                  >
                    {building
                      ? "🎬 Montando…"
                      : `🎬 Gerar live com estes vídeos${
                          selectedIds.length ? ` (${selectedIds.length})` : ""
                        }`}
                  </button>
                </div>
              )}

              {recSource === "foto" && (
              <>
              <p className="rec-help">
                O Atlas monta <b>um vídeo só</b> com todos os produtos (fala + card
                de cada um) e depois você <b>liga a transmissão</b> — roda em loop,
                como se fosse ao vivo.
              </p>

              <div className="rec-field">
                <span>Plataforma dos produtos</span>
                <div className="plat-grid">
                  {platformsList.map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      className={
                        "plat-chip" +
                        (p.id === buildPlatform ? " on" : "") +
                        (p.ready ? "" : " off")
                      }
                      disabled={!p.ready || building}
                      title={p.ready ? p.name : `${p.name} — em breve`}
                      onClick={() => p.ready && setBuildPlatform(p.id)}
                    >
                      {p.name}
                      {!p.ready && <span className="soon">em breve</span>}
                    </button>
                  ))}
                </div>
              </div>

              <div className="rec-field">
                <span>Tempo por produto</span>
                <div className="seg sm">
                  <button
                    className={secondsPer === 30 ? "on" : ""}
                    onClick={() => setSecondsPer(30)}
                    disabled={building}
                  >
                    30s
                  </button>
                  <button
                    className={secondsPer === 45 ? "on" : ""}
                    onClick={() => setSecondsPer(45)}
                    disabled={building}
                  >
                    45s
                  </button>
                  <button
                    className={secondsPer === 60 ? "on" : ""}
                    onClick={() => setSecondsPer(60)}
                    disabled={building}
                  >
                    60s
                  </button>
                </div>
              </div>

              <label className="rec-field">
                <span>Quantos produtos (0 = todos)</span>
                <input
                  type="number"
                  min="0"
                  max="100"
                  value={maxProducts}
                  disabled={building}
                  onChange={(e) => setMaxProducts(e.target.value)}
                />
              </label>

              <label className="rec-toggle">
                <input
                  type="checkbox"
                  checked={useAi}
                  disabled={building}
                  onChange={(e) => setUseAi(e.target.checked)}
                />
                <span>
                  Falas escritas pela IA (mais naturais; sem IA é mais rápido)
                </span>
              </label>

              <button
                className="btn primary rec-build-btn"
                onClick={startBuild}
                disabled={building}
              >
                {building ? "🎬 Montando…" : "🎬 Gerar vídeo da live"}
              </button>
              </>
              )}

              {buildProg && (
                <div className="rec-prog">
                  {buildProg.ok === false ? (
                    <div className="rec-err">⚠️ {buildProg.reason}</div>
                  ) : buildProg.ok ? (
                    <div className="rec-ok">✅ Vídeo pronto! Escolha abaixo e ligue.</div>
                  ) : (
                    <>
                      <div className="rec-bar">
                        <span
                          style={{
                            width: buildProg.total
                              ? `${Math.round((buildProg.done / buildProg.total) * 100)}%`
                              : "8%",
                          }}
                        />
                      </div>
                      <div className="rec-bar-label">
                        {buildProg.total
                          ? `bloco ${buildProg.done}/${buildProg.total}`
                          : "iniciando…"}{" "}
                        {buildProg.label ? `· ${buildProg.label}` : ""}
                      </div>
                    </>
                  )}
                </div>
              )}

              <div className="rec-list-head">
                <span>📼 Vídeos montados</span>
                <span className="rec-head-actions">
                  {recorded.length > 0 && (
                    <button
                      className="mini-btn text danger"
                      onClick={clearRecorded}
                      disabled={live || clearingRec}
                      title="Apagar todos os vídeos montados (libera espaço)"
                    >
                      {clearingRec ? "Limpando…" : "🗑️ Limpar"}
                    </button>
                  )}
                  <button
                    className="mini-btn"
                    onClick={() => refreshRecorded(true)}
                    title="Recarregar"
                  >
                    ↻
                  </button>
                </span>
              </div>
              <div className="rec-list">
                {recorded.length === 0 && (
                  <div className="rec-empty">
                    Nenhum vídeo ainda. Gere o primeiro acima. 🎬
                  </div>
                )}
                {recorded.map((v) => (
                  <div
                    key={v.video}
                    className={"rec-item" + (v.video === airName ? " on" : "")}
                  >
                    <button className="rec-pick" onClick={() => setAirName(v.video)}>
                      <b>{v.platform_name || v.platform || "Live"}</b>
                      <small>
                        {v.market ? v.market + " · " : ""}
                        {v.product_count} produtos ·{" "}
                        {Math.round((v.total_seconds || 0) / 60)}min
                      </small>
                    </button>
                    <button
                      className="btn primary sm"
                      disabled={live}
                      onClick={() => startAir(v.video)}
                    >
                      🔴 Transmitir
                    </button>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : (
        <div className="card live-chat">
          <div className="chat-head">
            <span>💬 Comentários ao vivo</span>
            {brain?.gemini_ready || brain?.groq_ready ? (
              <span className="chat-engine">
                IA: {brain?.gemini_ready ? "Gemini" : ""}
                {brain?.gemini_ready && brain?.groq_ready ? " + " : ""}
                {brain?.groq_ready ? "Groq" : ""}
              </span>
            ) : null}
          </div>

          <div className="chat-body">
            {messages.length === 0 && (
              <div className="chat-empty">
                {live
                  ? mode === "sim"
                    ? "Digite um comentário abaixo para simular o público. A IA responde e fala."
                    : "Aguardando comentários da plataforma…"
                  : "Entre ao vivo para começar."}
              </div>
            )}
            {messages.map((m) => (
              <div key={m.id} className={"chat-msg " + m.role}>
                <div className="msg-name">
                  {m.role === "host" ? "🤖 " : "👤 "}
                  {m.name}
                  {m.engine && <span className="msg-engine"> · {m.engine}</span>}
                </div>
                {m.pending ? (
                  <div className="msg-text pending">digitando resposta…</div>
                ) : (
                  <div className={"msg-text" + (m.error ? " error" : "")}>
                    {m.text}
                    {m.audioUrl && (
                      <button
                        className="msg-play"
                        onClick={() => playAudio(m.audioUrl)}
                        title="Ouvir de novo"
                      >
                        🔊
                      </button>
                    )}
                  </div>
                )}
              </div>
            ))}
            <div ref={chatBottomRef} />
          </div>

          {/* Entrada de comentario (so no modo simulacao) */}
          {mode === "sim" ? (
            <div className="chat-input-area">
              <div className="chat-suggests">
                {suggestions.map((s) => (
                  <button
                    key={s}
                    className="sugg"
                    disabled={!live || sending}
                    onClick={() => sendComment(s)}
                  >
                    {s}
                  </button>
                ))}
              </div>
              <div className="chat-input-row">
                <input
                  type="text"
                  placeholder={
                    live ? "Escreva um comentário do público…" : "Entre ao vivo primeiro"
                  }
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && sendComment()}
                  disabled={!live || sending}
                />
                <button
                  className="btn primary"
                  onClick={() => sendComment()}
                  disabled={!live || sending || !input.trim()}
                >
                  {sending ? "…" : "Enviar"}
                </button>
              </div>
            </div>
          ) : (
            <div className="chat-real-note">
              No modo <b>ao vivo real</b> os comentários chegam sozinhos da
              plataforma. (Leitura de comentários e transmissão: próxima etapa.)
            </div>
          )}
        </div>
        )}
      </div>
    </div>
  );
}
