import React from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import Sidebar from "./components/Sidebar.jsx";
import TopBar from "./components/TopBar.jsx";
import Overview from "./pages/Overview.jsx";
import Products from "./pages/Products.jsx";
import AffiliateVideos from "./pages/AffiliateVideos.jsx";
import Reels from "./pages/Reels.jsx";
import Live from "./pages/Live.jsx";
import Publishing from "./pages/Publishing.jsx";
import Marketing from "./pages/Marketing.jsx";
import Analytics from "./pages/Analytics.jsx";
import AmazonSales from "./pages/AmazonSales.jsx";
import PlatformDetail from "./pages/PlatformDetail.jsx";

export default function App() {
  return (
    <div className="app-shell">
      <Sidebar />
      <div className="app-main">
        <TopBar />
        <div className="app-content">
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/produtos" element={<Products />} />
            <Route path="/afiliados" element={<AffiliateVideos />} />
            <Route path="/reels" element={<Reels />} />
            <Route path="/live" element={<Live />} />
            <Route path="/publicacoes" element={<Publishing />} />
            <Route path="/marketing" element={<Marketing />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/vendas-amazon" element={<AmazonSales />} />
            <Route path="/analytics/conta/:key" element={<PlatformDetail />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </div>
    </div>
  );
}
