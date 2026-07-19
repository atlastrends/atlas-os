import React, { useEffect, useState } from "react";
import Api from "../api/client.js";

export default function TopBar() {
  const [online, setOnline] = useState(null);
  const [engine, setEngine] = useState(false);
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const s = await Api.status();
        if (!alive) return;
        setOnline(true);
        // heurística: engine ligado se houver overview
        setEngine(Boolean(s?.overview));
      } catch {
        if (alive) setOnline(false);
      }
    };
    check();
    const t = setInterval(check, 15000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const timeStr = now.toLocaleTimeString("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  const dateStr = now.toLocaleDateString("pt-BR", {
    weekday: "long",
    day: "2-digit",
    month: "long",
  });

  return (
    <header className="topbar">
      <h1>Painel de Controle</h1>
      <div className="top-right">
        <div className="top-clock">
          <span>{timeStr}</span>
          <span className="clock-date">{dateStr}</span>
        </div>
        <div className="status-pill">
          <span className={`dot ${online ? "on" : online === false ? "off" : ""}`} />
          {online === null
            ? "Conectando..."
            : online
            ? engine
              ? "Sistema operante"
              : "API online"
            : "API offline (:8000)"}
        </div>
      </div>
    </header>
  );
}
