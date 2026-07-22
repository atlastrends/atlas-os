import axios from "axios";

// Cliente central da API do ATLAS OS.
const api = axios.create({
  baseURL: "/api",
  timeout: 60000,
});

export const Api = {
  status: () => api.get("/status").then((r) => r.data),

  overview: () => api.get("/analytics/overview").then((r) => r.data),
  platforms: () => api.get("/analytics/platforms").then((r) => r.data),
  accounts: () => api.get("/analytics/accounts").then((r) => r.data),
  videoMetrics: (id) => api.get(`/analytics/video/${id}`).then((r) => r.data),
  topVideos: (limit = 5) =>
    api.get("/analytics/top-videos", { params: { limit } }).then((r) => r.data),
  platformVideos: (platform) =>
    api.get(`/analytics/platform/${platform}/videos`).then((r) => r.data),
  accountVideos: (key) =>
    api.get(`/analytics/account/${key}/videos`).then((r) => r.data),

  listVideos: (params = {}) =>
    api.get("/videos", { params }).then((r) => r.data),
  getVideo: (id) => api.get(`/videos/${id}`).then((r) => r.data),
  videoCaption: (id, platform = "tiktok") =>
    api
      .get(`/videos/${id}/caption`, { params: { platform } })
      .then((r) => r.data),
  syncVideos: () => api.post("/videos/sync").then((r) => r.data),
  clearReels: () => api.post("/videos/clear-reels").then((r) => r.data),
  clearRejected: (kind) =>
    api
      .post("/videos/clear-rejected", null, { params: kind ? { kind } : {} })
      .then((r) => r.data),

  approveVideo: (id, body = {}) =>
    api.post(`/videos/${id}/approve`, body).then((r) => r.data),
  rejectVideo: (id, body = {}) =>
    api.post(`/videos/${id}/reject`, body).then((r) => r.data),

  publications: () => api.get("/publications").then((r) => r.data),

  // ----- Vendas Amazon (afiliado) -----
  amazonSalesStats: (params = {}) =>
    api.get("/affiliate/amazon-sales/stats", { params }).then((r) => r.data),
  amazonSalesImport: (formData) =>
    api
      .post("/affiliate/amazon-sales/import", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      })
      .then((r) => r.data),
  amazonSalesClear: (market) =>
    api
      .delete("/affiliate/amazon-sales/clear", {
        params: market ? { market } : {},
      })
      .then((r) => r.data),

  jobs: () => api.get("/jobs").then((r) => r.data),
  fetchAmazon: () => api.post("/jobs/fetch-amazon-products").then((r) => r.data),
  availableProducts: () => api.get("/products/available").then((r) => r.data),
  generateSelected: (selections) =>
    api.post("/jobs/generate-selected", { selections }).then((r) => r.data),
  generateReels: () => api.post("/jobs/generate-reels").then((r) => r.data),
  startAutoReels: (intervalMinutes = 30) =>
    api
      .post("/jobs/auto-reels/start", { interval_minutes: intervalMinutes })
      .then((r) => r.data),
  stopAutoReels: () => api.post("/jobs/auto-reels/stop").then((r) => r.data),
  autoReelsStatus: () =>
    api.get("/jobs/auto-reels/status").then((r) => r.data),
  startAutoAffiliate: (intervalMinutes = 120) =>
    api
      .post("/jobs/auto-affiliate/start", { interval_minutes: intervalMinutes })
      .then((r) => r.data),
  stopAutoAffiliate: () =>
    api.post("/jobs/auto-affiliate/stop").then((r) => r.data),
  autoAffiliateStatus: () =>
    api.get("/jobs/auto-affiliate/status").then((r) => r.data),
  clearPublished: (kind) =>
    api
      .post("/videos/clear-published", null, { params: kind ? { kind } : {} })
      .then((r) => r.data),
  pendingCount: (kind) =>
    api
      .get("/videos/pending-count", { params: kind ? { kind } : {} })
      .then((r) => r.data),
  retryPending: (kind) =>
    api
      .post("/videos/retry-pending", null, { params: kind ? { kind } : {} })
      .then((r) => r.data),
  collectMetrics: () => api.post("/jobs/collect-metrics").then((r) => r.data),
  autoApprove: () => api.post("/jobs/auto-approve").then((r) => r.data),

  // ----- Atualizacao do aplicativo -----
  updateCheck: () => api.get("/update/check").then((r) => r.data),
  updateApply: () => api.post("/update/apply").then((r) => r.data),

  // ----- TikTok (conexao das contas) -----
  tiktokStatus: () => api.get("/tiktok/status").then((r) => r.data),
  tiktokConnectUrl: (market = "BR") => `/api/tiktok/connect?market=${market}`,

  // ----- Marketing / Anuncios -----
  marketingStatus: () => api.get("/marketing/status").then((r) => r.data),
  marketingBestVideo: () => api.get("/marketing/best-video").then((r) => r.data),
  marketingRoiRanking: (limit = 10) =>
    api.get("/marketing/roi-ranking", { params: { limit } }).then((r) => r.data),
  marketingRecommendation: (videoId, force = false) =>
    api
      .get(`/marketing/recommendation/${videoId}`, {
        params: force ? { force: true } : {},
      })
      .then((r) => r.data),
  marketingCampaigns: () =>
    api.get("/marketing/campaigns").then((r) => r.data),
  createCampaign: (body) =>
    api.post("/marketing/campaigns", body).then((r) => r.data),
  launchCampaign: (id) =>
    api.post(`/marketing/campaigns/${id}/launch`).then((r) => r.data),
};

export default Api;
