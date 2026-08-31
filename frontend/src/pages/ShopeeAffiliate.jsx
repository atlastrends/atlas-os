import React, { useEffect, useMemo, useState } from "react";
import Api from "../api/client.js";
import Toast from "../components/Toast.jsx";
import StatCard from "../components/StatCard.jsx";

const money = (value) =>
  Number(value || 0).toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
  });

export default function ShopeeAffiliate() {
  const [status, setStatus] = useState(null);
  const [products, setProducts] = useState([]);
  const [file, setFile] = useState(null);
  const [rightsConfirmed, setRightsConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [quantity, setQuantity] = useState(1);
  const [toast, setToast] = useState(null);

  const load = async () => {
    const [nextStatus, nextProducts] = await Promise.all([
      Api.shopeeStatus(),
      Api.shopeeProducts(),
    ]);
    setStatus(nextStatus);
    setProducts(Array.isArray(nextProducts) ? nextProducts : []);
  };

  useEffect(() => {
    load().catch(() =>
      setToast({ type: "err", msg: "Nao consegui carregar o catalogo Shopee." })
    );
  }, []);

  const categories = useMemo(
    () => [...new Set(products.map((product) => product.category || "outros"))],
    [products]
  );

  const importCatalog = async () => {
    if (!file) {
      setToast({ type: "err", msg: "Selecione o CSV exportado do portal Shopee." });
      return;
    }
    if (!rightsConfirmed) {
      setToast({
        type: "err",
        msg: "Confirme a autorizacao de uso das imagens e videos.",
      });
      return;
    }
    setBusy(true);
    try {
      const result = await Api.shopeeImport(file, rightsConfirmed);
      await load();
      setToast({
        type: "ok",
        msg: `${result.imported} produto(s) importado(s); ${result.ready} pronto(s) para video.`,
      });
    } catch (error) {
      setToast({
        type: "err",
        msg: error?.response?.data?.detail || "Falha ao importar o catalogo.",
      });
    } finally {
      setBusy(false);
    }
  };

  const generate = async () => {
    if (!categories.length) {
      setToast({ type: "err", msg: "Importe produtos antes de gerar videos." });
      return;
    }
    const selections = categories.flatMap((category) => [
      {
        platform: "shopee",
        marketplace_code: "BR",
        category,
        quantity,
      },
      {
        platform: "shopee",
        marketplace_code: "US",
        category,
        quantity,
      },
    ]);
    setBusy(true);
    try {
      await Api.generateSelected(selections);
      setToast({
        type: "ok",
        msg: "Geracao PT + EN iniciada. As versoes de Live serao criadas pelo mesmo pipeline.",
      });
    } catch (error) {
      setToast({
        type: "err",
        msg: error?.response?.data?.detail || "Nao consegui iniciar a geracao.",
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div className="page-head">
        <div>
          <h2>Afiliados Shopee</h2>
          <p>
            Cadastro oficial, ranking por vendas e comissao, midia autorizada do
            produto exato e videos em portugues e ingles.
          </p>
        </div>
        <a
          className="btn primary"
          href={status?.affiliate_url || "https://affiliate.shopee.com.br/"}
          target="_blank"
          rel="noopener noreferrer"
        >
          Abrir portal oficial
        </a>
      </div>

      <div className="grid kpis" style={{ marginBottom: 16 }}>
        <StatCard icon="🛍️" tone="pink" label="Produtos" value={products.length} />
        <StatCard
          icon="✅"
          tone="green"
          label="Prontos para video"
          value={status?.ready_count || 0}
        />
        <StatCard
          icon="🗂️"
          tone="cyan"
          label="Categorias"
          value={categories.length}
        />
        <StatCard
          icon="🌐"
          tone="amber"
          label="Idiomas"
          value="PT + EN"
          foot="inclui versao Live"
        />
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="section-title">Passo a passo: afiliacao e pagina Shopee</div>
        <ol style={{ lineHeight: 1.8, marginBottom: 0 }}>
          {(status?.workflow || []).map((step, index) => (
            <li key={step}>
              <b>Passo {index + 1}:</b> {step}
            </li>
          ))}
        </ol>
        <p style={{ marginBottom: 0, marginTop: 12, color: "#fbbf24" }}>
          O login, os dados pessoais/bancarios e o aceite dos termos devem ser
          feitos por voce no portal oficial. O Atlas nao armazena sua senha.
        </p>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="section-title">Importar ofertas oficiais</div>
        <p>
          CSV aceito: product_id, title, category, price, affiliate_url,
          image_url, video_url, commission_rate, commission_amount e sold_count.
          Para melhorar o roteiro, inclua também description, features
          (separadas por |), rating, review_count e official_url.
          {" "}
          <a href="/api/shopee/catalog/template">Baixar modelo CSV</a>
        </p>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={(event) => setFile(event.target.files?.[0] || null)}
          />
          <label style={{ maxWidth: 680 }}>
            <input
              type="checkbox"
              checked={rightsConfirmed}
              onChange={(event) => setRightsConfirmed(event.target.checked)}
            />{" "}
            Confirmo que a midia veio da Shopee/vendedor e pode ser reutilizada
            para divulgacao afiliada. Nao usar downloads de terceiros sem licenca.
          </label>
          <button className="btn primary" onClick={importCatalog} disabled={busy}>
            Importar e validar
          </button>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="section-title">Gerar videos e Live Video</div>
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <label>
            Produtos por categoria:{" "}
            <input
              type="number"
              min="1"
              max="10"
              value={quantity}
              onChange={(event) =>
                setQuantity(Math.max(1, Math.min(10, Number(event.target.value) || 1)))
              }
              style={{ width: 70 }}
            />
          </label>
          <button className="btn primary" onClick={generate} disabled={busy}>
            Gerar PT + EN
          </button>
          <span>
            A ordem prioriza vendidos + percentual de comissao + valor de comissao.
          </span>
        </div>
      </div>

      <div className="card">
        <div className="section-title">Ranking Shopee</div>
        {!products.length ? (
          <p>Nenhum produto importado. Conclua a afiliacao e importe o CSV oficial.</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th align="left">#</th>
                  <th align="left">Produto</th>
                  <th align="left">Categoria</th>
                  <th align="right">Vendidos</th>
                  <th align="right">Comissao</th>
                  <th align="right">Valor</th>
                  <th align="center">Midia</th>
                </tr>
              </thead>
              <tbody>
                {products.map((product, index) => (
                  <tr key={product.product_id}>
                    <td>{index + 1}</td>
                    <td>
                      <a href={product.affiliate_url} target="_blank" rel="noreferrer">
                        {product.title}
                      </a>
                    </td>
                    <td>{product.category}</td>
                    <td align="right">{Number(product.sold_count || 0).toLocaleString("pt-BR")}</td>
                    <td align="right">{Number(product.commission_rate || 0).toFixed(2)}%</td>
                    <td align="right">{money(product.commission_amount)}</td>
                    <td align="center">{product.ready_for_video ? "✅" : "⚠️"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {toast && <Toast {...toast} onClose={() => setToast(null)} />}
    </div>
  );
}
