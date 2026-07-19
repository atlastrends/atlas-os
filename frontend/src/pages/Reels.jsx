import React, { useEffect, useRef, useState } from "react";
import Api from "../api/client.js";
import VideoGrid from "../api/VideoGrid.jsx";

export default function Reels() {
  const [notice, setNotice] = useState(null);
  const [refreshSignal, setRefreshSignal] = useState(0);
  const [auto, setAuto] = useState({ active: false, interval_minutes: 30, next_run_at: null });
  const pollRef = useRef(null);
  const autoPollRef = useRef(null);

  // Limpa o polling quando a pagina e fechada.
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (autoPollRef.current) clearInterval(autoPollRef.current);
    };
  }, []);

  // Acompanha o estado da criacao automatica (ligada/desligada + proximo ciclo).
  useEffect(() => {
    async function refreshAuto() {
      try {
        const st = await Api.autoReelsStatus();
        setAuto(st || { active: false, interval_minutes: 30, next_run_at: null });
      } catch {
        /* servidor iniciando; ignora */
      }
    }
    refreshAuto();
    autoPollRef.current = setInterval(refreshAuto, 15000);
    return () => {
      if (autoPollRef.current) clearInterval(autoPollRef.current);
    };
  }, []);

  // Ao abrir a aba, verifica se ja existe um reel sendo gerado no servidor.
  // Se existir, retoma a faixa de progresso automaticamente. Assim o usuario
  // pode navegar para outras abas e voltar sem "perder" o status.
  useEffect(() => {
    (async () => {
      try {
        const jobs = await Api.jobs();
        const job = jobs?.generate_reels || {};
        if (job.status === "running") {
          setNotice(buildRunningNotice(job));
          watchJob();
        }
      } catch {
        /* servidor pode estar iniciando; ignora silenciosamente */
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  // Monta a mensagem de progresso: porcentagem + titulo do video atual.
  function buildRunningNotice(job) {
    const pct =
      typeof job.progress === "number" ? Math.max(0, Math.min(100, job.progress)) : 0;
    const title = (job.current_title || "").trim();
    const stage = (job.stage || "").trim();

    let msg =
      "⏳ Gerando reels… isso pode levar alguns minutos. Você pode navegar em outras abas; o vídeo continua sendo criado.";
    let progressLine = `📊 ${pct}% concluído`;
    if (title) progressLine += ` — 🎬 ${title}`;
    if (stage) progressLine += `\n${stage}`;

    return {
      type: "info",
      busy: true,
      progress: pct,
      msg: msg + "\n\n" + progressLine,
    };
  }

  // Fica verificando o status do job "generate_reels" no servidor e
  // atualiza a faixa de status do painel para o usuario acompanhar.
  function watchJob() {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const jobs = await Api.jobs();
        const job = jobs?.generate_reels || {};
        if (job.status === "running") {
          setNotice(buildRunningNotice(job));
        } else if (job.status === "done") {
          stopPolling();
          setNotice({
            type: "success",
            msg:
              "✅ " +
              (job.result || "Reels gerados com sucesso!") +
              " A lista foi atualizada abaixo.",
          });
          setRefreshSignal((n) => n + 1);
        } else if (job.status === "error") {
          stopPolling();
          setNotice({
            type: "error",
            msg: "❌ Erro ao gerar reels: " + (job.error || "falha desconhecida."),
          });
        }
      } catch (e) {
        stopPolling();
        setNotice({
          type: "error",
          msg: "❌ Perdi a conexão com o servidor. Verifique se o programa ainda está rodando.",
        });
      }
    }, 3000);
  }

  async function generate() {
    setNotice({
      type: "info",
      busy: true,
      msg: "⏳ Iniciando geração de reels… você pode navegar em outras abas; o vídeo continua sendo criado.",
    });
    try {
      await Api.generateReels();
      watchJob();
    } catch (e) {
      setNotice({
        type: "error",
        msg: "❌ Não consegui iniciar a geração: " + (e?.message || e),
      });
    }
  }

  async function startAuto() {
    setNotice({
      type: "info",
      busy: true,
      msg: "▶️ Ligando a criação automática… o primeiro ciclo começa em instantes.",
    });
    try {
      const st = await Api.startAutoReels(30);
      setAuto(st || { active: true, interval_minutes: 30, next_run_at: null });
      setNotice({
        type: "success",
        msg:
          "✅ Criação automática LIGADA. A cada 30 minutos o sistema verifica os assuntos mais falados no Brasil e nos EUA e cria 1 vídeo de cada, sem repetir tema. Continua rodando até você clicar em Parar.",
      });
      watchJob();
    } catch (e) {
      setNotice({
        type: "error",
        msg: "❌ Não consegui ligar a criação automática: " + (e?.message || e),
      });
    }
  }

  async function stopAuto() {
    setNotice({ type: "info", busy: true, msg: "⏹️ Parando a criação automática…" });
    try {
      const st = await Api.stopAutoReels();
      setAuto(st || { active: false, interval_minutes: 30, next_run_at: null });
      setNotice({
        type: "success",
        msg: "🛑 Criação automática PARADA. Nenhum novo ciclo será iniciado. (Um vídeo que já estava sendo criado termina normalmente.)",
      });
    } catch (e) {
      setNotice({
        type: "error",
        msg: "❌ Não consegui parar a criação automática: " + (e?.message || e),
      });
    }
  }

  async function clearReels() {
    const ok = window.confirm(
      "Apagar TODOS os reels de assuntos em alta? Os vídeos e metadados serão removidos. Os vídeos de afiliados NÃO são afetados."
    );
    if (!ok) return;
    setNotice({ type: "info", busy: true, msg: "🗑️ Apagando reels…" });
    try {
      const res = await Api.clearReels();
      setNotice({
        type: "success",
        msg: `✅ Reels apagados: ${res.removed_assets} registro(s) e ${res.removed_files} arquivo(s).`,
      });
      setRefreshSignal((n) => n + 1);
    } catch (e) {
      setNotice({
        type: "error",
        msg: "❌ Falha ao apagar os reels: " + (e?.message || e),
      });
    }
  }

  const baseSubtitle =
    "1 vídeo em português + 1 em inglês por ciclo. Revise, aceite e publique.";
  let subtitle = baseSubtitle;
  if (auto.active) {
    let quando = "";
    if (auto.next_run_at) {
      try {
        quando =
          " — próximo ciclo às " +
          new Date(auto.next_run_at).toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          });
      } catch {
        /* ignora formato invalido */
      }
    }
    subtitle =
      `♻️ Criação automática LIGADA (a cada ${auto.interval_minutes} min)${quando}. ` +
      baseSubtitle;
  }

  return (
    <VideoGrid
      kind="reel"
      title="Reels de Assuntos em Alta"
      subtitle={subtitle}
      notice={notice}
      refreshSignal={refreshSignal}
      extraAction={
        <>
          {auto.active ? (
            <button
              className="btn danger"
              onClick={stopAuto}
              title="Parar a criação automática de reels"
            >
              ⏹️ Parar criação automática
            </button>
          ) : (
            <button
              className="btn primary"
              onClick={startAuto}
              title="Criar 1 BR + 1 US a cada 30 minutos, sem repetir assunto, até você parar"
            >
              ♻️ Ligar criação automática (30 min)
            </button>
          )}
          <button
            className="btn"
            onClick={generate}
            title="Gerar 1 vez agora (1 BR + 1 US)"
          >
            🔥 Gerar Reels agora
          </button>
          <button
            className="btn"
            onClick={clearReels}
            title="Apagar todos os reels de assuntos em alta"
          >
            🗑️ Limpar reels
          </button>
        </>
      }
    />
  );
}
