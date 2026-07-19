import React from "react";
import Api from "../api/client.js";
import VideoGrid from "../api/VideoGrid.jsx";

export default function AffiliateVideos() {
  return (
    <VideoGrid
      kind="affiliate"
      title="Vídeos de Afiliados"
      subtitle="Produtos da Amazon com link clicável. Revise, aceite e publique."
      extraAction={
        <button
          className="btn primary"
          onClick={() => Api.fetchAmazon()}
          title="Buscar novos produtos e gerar vídeos"
        >
          🛒 Buscar produtos
        </button>
      }
    />
  );
}
