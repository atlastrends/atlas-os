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

  const audioRef = useRef(null);
  const chatBottomRef = useRef(null);
  const viewersTimer = useRef(null);

  // Verifica se o "cerebro" (IA + voz) esta pronto.
  useEffect(() => {
    (async () => {
      try {
        setBrain(await Api.liveStatus());
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
    setViewers(Math.floor(Math.random() * 40) + 12);
    setLive(true);
  }

  function stopLive() {
    setLive(false);
    setSpeaking(false);
    setCaption("");
    if (audioRef.current) {
      audioRef.current.pause();
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
      setMessages((m) =>
        m.map((x) =>
          x.id === hostMsg.id
            ? { ...x, pending: false, text: res.answer, engine: res.engine, audioUrl }
            : x
        )
      );
      setCaption(res.answer);
      if (audioUrl) playAudio(audioUrl);
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
                <div className={"avatar-ph" + (speaking ? " speaking" : "")}>
                  <div className="avatar-face">🧑‍💼</div>
                  <div className="avatar-label">
                    {live ? "Apresentador de IA" : "Avatar entra aqui"}
                  </div>
                  {speaking && (
                    <div className="speak-bars">
                      <span></span><span></span><span></span><span></span>
                    </div>
                  )}
                </div>
              </div>

              {productContext.trim() && live && (
                <div className="stage-product">🛍️ {productContext.trim()}</div>
              )}

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
            <label className="cfg-row">
              <span>Produto em destaque</span>
              <input
                type="text"
                placeholder="Ex.: Sérum de vitamina C para o rosto"
                value={productContext}
                onChange={(e) => setProductContext(e.target.value)}
              />
            </label>
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
