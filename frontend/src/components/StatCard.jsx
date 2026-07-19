import React from "react";

export default function StatCard({
  label,
  value,
  foot,
  icon,
  tone,
  accent = true,
}) {
  const toneClass = tone ? ` tone-${tone}` : "";
  return (
    <div className={`card stat-card${toneClass}`}>
      <div className="stat-top">
        <div className="label">{label}</div>
        {icon ? <div className="stat-ico">{icon}</div> : null}
      </div>
      <div className="value">{value}</div>
      {foot ? <div className="foot">{foot}</div> : null}
      {accent ? <div className="accent" /> : null}
    </div>
  );
}
