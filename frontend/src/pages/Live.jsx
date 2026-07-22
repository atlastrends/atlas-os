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

  const audioRef = useRef(null);
  const videoRef = useRef(null);
  const chatBottomRef = useRef(null);
  const viewersTimer = useRef(null);

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
      setViewers((v) => Math.max(1, v + Math.floor(Math.random() * 7) - 2));
    }, 2500);
    return () => {
      if (viewersTimer.current) clearInterval(viewersTimer.current);
    };
  }, [live]);

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
    setMessages([]);
    setCaption("");
    setVideoUrl("");
    setViewers(Math.floor(Math.random() * 40) + 12);
    setLive(true);
  }

  function stopLive() {
    setLive(false);
    setSpeaking(false);
    setCaption("");
    setVideoUrl("");
    if (audioRef.current) {
      audioRef.current.pause();
    }
    if (videoRef.current) {
      videoRef.current.pause();
    }
  }

  async function sendComment(text) {
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
      name: "Apresentador (IA)",
      text: "",
      pending: true,
    };
    setMessages((m) => [...m, viewerMsg, hostMsg]);
    setInput("");
    setSending(true);

    try {
      const res = await Api.liveAnswer({
        comment,
        language,
        product_context: productContext,
        persona,
        with_voice: true,
        with_video: videoOn && presenterUploaded,
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
      setCaption(res.answer);
      // Se veio video do apresentador, toca o video (com a voz embutida);
      // senao, cai na voz + foto estatica.
      if (clipUrl) {
        setSpeaking(true);
        setVideoUrl(clipUrl);
      } else if (audioUrl) {
        playAudio(audioUrl);
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
      <div className="page-head">
        <div>
          <h2>🔴 Live (Ao Vivo)</h2>
          <p>
            Canal de lives com apresentador de IA. Tela pronta para transmitir —
            use o modo <b>Simulação</b> para testar digitando comentários manuais.
          </p>
        </div>
        <div className="toolbar">
          <div className="seg">
            <button
              className={mode === "sim" ? "on" : ""}
              onClick={() => setMode("sim")}
              disabled={live}
            >
              🧪 Simulação
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
            <button className="btn danger" onClick={stopLive}>
              ⏹️ Encerrar
            </button>
          ) : (
            <button className="btn primary" onClick={startLive}>
              ▶️ Entrar ao vivo
            </button>
          )}
        </div>
      </div>

      {!brainReady && (
        <div className="live-warn">
          ⚠️ O cérebro da IA não está pronto (falta a chave GROQ_API_KEY ou
          GEMINI_API_KEY no .env). As respostas não vão funcionar até configurar.
        </div>
      )}

      <div className="live-grid">
        {/* -------- PALCO (o que vai ao ar) -------- */}
        <div className="live-stage-wrap">
          <div className="phone">
            <div className={"stage" + (live ? " on" : "")}>
              <div className="stage-top">
                <span className={"live-badge" + (live ? " on" : "")}>
                  {live ? (mode === "real" ? "🔴 AO VIVO" : "🔴 AO VIVO · SIMULAÇÃO") : "OFFLINE"}
                </span>
                {live && (
                  <span className="viewers">👁️ {viewers.toLocaleString("pt-BR")}</span>
                )}
              </div>

              <div className="stage-center">
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
              </div>

              {caption && live && (
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

        {/* -------- CHAT AO VIVO -------- */}
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
      </div>
    </div>
  );
}
