# ============================================================
# ATLAS OS - amazon_scraper_service.py
# Login automatico no Amazon Associates + download do relatorio de
# ganhos, SEM o usuario precisar baixar nada na mao.
#
# A Amazon nao tem API de vendas/ganhos de afiliado. Este servico
# controla um navegador (Playwright/Chromium) que faz o mesmo que uma
# pessoa faria: entra no site, abre "Relatorios", pede o relatorio de
# ganhos do periodo e baixa o arquivo. O arquivo baixado e entao lido
# pelo amazon_report_service (mesmo parser usado no upload manual).
#
# Guarda a sessao (cookies) em storage/amazon_sessions/<mercado>.json
# para nao precisar logar de novo a cada clique em "Atualizar" -
# logins repetidos aumentam a chance da Amazon pedir verificacao extra.
# ============================================================

from __future__ import annotations

import io
import os
import time
import zipfile
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services import amazon_report_service

_SESSION_DIR = Path(os.environ.get("ATLAS_ROOT") or os.getcwd()) / "storage" / "amazon_sessions"

# URLs de login/relatorios por mercado. A Amazon usa o MESMO dominio de
# login (Amazon Associates Central) mas a home muda por marketplace.
_MARKET_URLS = {
    "BR": {
        "login": "https://associados.amazon.com.br/home",
        "reports": "https://associados.amazon.com.br/home/reports",
    },
    "US": {
        "login": "https://affiliate-program.amazon.com/home",
        "reports": "https://affiliate-program.amazon.com/home/reports",
    },
}

# Textos que indicam que a Amazon pediu algo que o robo NAO consegue
# responder sozinho (captcha, verificacao em duas etapas, senha errada).
_BLOCKED_HINTS = (
    "digite os caracteres", "type the characters", "captcha",
    "codigo de verificacao", "verification code", "authentication code",
    "otp", "escolha como deseja receber", "choose how you'd like to receive",
    "algo nao esta certo", "something went wrong", "senha incorreta",
    "incorrect password", "sua conta foi bloqueada", "account has been locked",
)


class AmazonLoginBlocked(Exception):
    """Levantado quando a Amazon pede 2FA/CAPTCHA e o robo nao pode seguir."""


def _get_credentials(market: str) -> Optional[tuple[str, str]]:
    market = (market or "").upper()
    if market == "BR":
        email = settings.ATLAS_AMAZON_BR_EMAIL.strip()
        password = settings.ATLAS_AMAZON_BR_PASSWORD.strip()
    elif market == "US":
        email = settings.ATLAS_AMAZON_US_EMAIL.strip()
        password = settings.ATLAS_AMAZON_US_PASSWORD.strip()
    else:
        return None
    if not email or not password:
        return None
    return email, password


def _session_path(market: str) -> Path:
    _SESSION_DIR.mkdir(parents=True, exist_ok=True)
    return _SESSION_DIR / f"{market.lower()}.json"


def _page_has_block_hint(page) -> Optional[str]:
    try:
        text = page.content().lower()
    except Exception:
        return None
    for hint in _BLOCKED_HINTS:
        if hint in text:
            return hint
    return None


def _login(page, market: str, email: str, password: str) -> None:
    """Preenche o formulario de login padrao da Amazon (mesma tela usada
    em amazon.com/amazon.com.br). Reaproveita sessao salva quando possivel;
    isso so roda quando a sessao salva expirou ou nao existe."""
    urls = _MARKET_URLS[market]
    page.goto(urls["login"], wait_until="domcontentloaded", timeout=45000)

    # Se ja tem sessao valida (cookie reaproveitado), o site pode ja abrir
    # logado direto no painel - nesse caso nao ha campo de email.
    email_field = page.locator("#ap_email, input[name='email']").first
    try:
        email_field.wait_for(state="visible", timeout=8000)
    except Exception:
        return  # provavelmente ja esta logado (sessao valida)

    block = _page_has_block_hint(page)
    if block:
        raise AmazonLoginBlocked(f"Amazon pediu verificacao extra na tela de login ({block}).")

    email_field.fill(email)
    continue_btn = page.locator("#continue, input#continue").first
    if continue_btn.count() > 0:
        continue_btn.click()
        page.wait_for_timeout(1200)

    password_field = page.locator("#ap_password, input[name='password']").first
    password_field.wait_for(state="visible", timeout=15000)

    block = _page_has_block_hint(page)
    if block:
        raise AmazonLoginBlocked(f"Amazon pediu verificacao extra apos o email ({block}).")

    password_field.fill(password)
    submit_btn = page.locator("#signInSubmit, input#signInSubmit").first
    submit_btn.click()

    page.wait_for_load_state("domcontentloaded", timeout=30000)
    page.wait_for_timeout(1500)

    block = _page_has_block_hint(page)
    if block:
        raise AmazonLoginBlocked(f"Amazon pediu verificacao extra apos a senha ({block}).")

    # Confirma que saiu da tela de login (nao ha mais campo de senha).
    if page.locator("#ap_password").count() > 0:
        raise AmazonLoginBlocked(
            "Login nao foi aceito. Confira o email/senha em ATLAS_AMAZON_"
            f"{market}_EMAIL / _PASSWORD no .env."
        )


def _download_earnings_report(page, market: str) -> tuple[str, bytes]:
    """Abre a pagina de 'Relatorios', pede um relatorio de ganhos (CSV, por
    produto) do periodo padrao (ultimos 30 dias) e baixa o arquivo assim
    que a Amazon terminar de gera-lo.

    O fluxo real da Amazon Associates e assincrono:
      1. Clica em "Fazer download de relatorios" (abre um popover/modal).
      2. Marca o formato CSV e pelo menos um tipo de relatorio (usamos
         "Produto relacionado", que traz o detalhamento por produto/ASIN).
      3. Clica em "Gerar Relatorios".
      4. A Amazon processa em segundo plano; o modal mostra uma tabela
         "Relatorios Disponiveis" com o status ("Preparando...", depois um
         link "Fazer download"). Precisamos clicar em "Atualizar" ate o
         link aparecer.
      5. O arquivo baixado e um .zip com um unico CSV dentro - extraimos
         esse CSV e devolvemos os bytes (o amazon_report_service ja sabe
         ler CSV puro).
    """
    urls = _MARKET_URLS[market]
    page.goto(urls["reports"], wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(2000)

    block = _page_has_block_hint(page)
    if block:
        raise AmazonLoginBlocked(f"Amazon pediu verificacao extra na pagina de relatorios ({block}).")

    launcher = page.locator("#ac-report-download-launcher-osp")
    if launcher.count() == 0:
        raise RuntimeError(
            "Nao encontrei o botao 'Fazer download de relatorios' na pagina "
            "da Amazon. O layout do site pode ter mudado."
        )
    launcher.click()
    page.wait_for_timeout(1000)

    # Formato CSV (o clique no <label> evita o icone customizado da Amazon
    # que fica por cima do <input type=radio> de verdade).
    csv_label = page.locator("#report-download-export-format-csv label")
    csv_label.click()

    # Tipo de relatorio: "Produto relacionado" (detalhamento por produto).
    product_checkbox = page.locator("#report-download-program-commission-creativeasin label")
    product_checkbox.click()

    generate_btn = page.locator("#ac-reports-download-generate-osp-announce")
    generate_btn.click()
    page.wait_for_timeout(2000)

    refresh_link = page.locator("#ac-report-download-refresh-link-osp")
    download_link = page.locator('a[title="Fazer download"]').first

    ready = False
    for _ in range(20):  # ate ~60s de espera (3s por tentativa)
        if download_link.count() > 0:
            ready = True
            break
        if refresh_link.count() > 0:
            refresh_link.click()
        page.wait_for_timeout(3000)

    if not ready:
        raise RuntimeError(
            "A Amazon nao terminou de gerar o relatorio a tempo (ou a "
            "solicitacao foi limitada - 'THROTTLED'). Tente de novo em "
            "alguns minutos."
        )

    with page.expect_download(timeout=60000) as download_info:
        download_link.click()
    download = download_info.value
    tmp_path = download.path()
    raw = Path(tmp_path).read_bytes() if tmp_path else b""
    if not raw:
        tmp_target = _SESSION_DIR / f"_tmp_{market.lower()}_{int(time.time())}"
        download.save_as(str(tmp_target))
        raw = tmp_target.read_bytes()
        try:
            tmp_target.unlink()
        except Exception:
            pass

    suggested = download.suggested_filename or f"amazon_{market.lower()}_earnings.zip"
    if suggested.lower().endswith(".zip") or raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names = z.namelist()
            if not names:
                raise RuntimeError("O relatorio baixado da Amazon veio vazio (zip sem arquivos).")
            filename = names[0]
            data = z.read(filename)
    else:
        filename = suggested
        data = raw

    return filename, data



def fetch_report_for_market(db: Session, market: str) -> dict:
    """Loga (ou reaproveita sessao), baixa o relatorio de ganhos e importa
    para o banco. Retorna um dict com o resultado (nunca levanta excecao
    para o chamador - erros vem no campo 'error')."""
    market = (market or "").upper()
    creds = _get_credentials(market)
    if not creds:
        return {"market": market, "ok": False, "skipped": True, "error": None}

    email, password = creds

    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return {
            "market": market,
            "ok": False,
            "error": (
                "Playwright nao instalado. Rode: pip install playwright && "
                "playwright install chromium"
            ),
        }

    session_file = _session_path(market)
    storage_state = str(session_file) if session_file.exists() else None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                storage_state=storage_state,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                ),
                locale="pt-BR" if market == "BR" else "en-US",
            )
            page = context.new_page()
            try:
                _login(page, market, email, password)
                filename, data = _download_earnings_report(page, market)
                # Sessao deu certo: salva os cookies para o proximo clique
                # em "Atualizar" nao precisar logar de novo.
                context.storage_state(path=str(session_file))
            finally:
                context.close()
                browser.close()
    except AmazonLoginBlocked as exc:
        # Sessao pode ter ficado invalida - apaga para tentar login limpo
        # na proxima vez.
        try:
            session_file.unlink(missing_ok=True)
        except Exception:
            pass
        return {"market": market, "ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"market": market, "ok": False, "error": f"Falha ao acessar a Amazon: {exc}"}

    if not data:
        return {"market": market, "ok": False, "error": "O download do relatorio veio vazio."}

    try:
        result = amazon_report_service.import_report(db, filename, data, default_market=market)
    except ValueError as exc:
        return {"market": market, "ok": False, "error": str(exc)}

    return {
        "market": market,
        "ok": True,
        "error": None,
        "imported": result["imported"],
        "skipped": result["skipped"],
        "total_rows": result["total_rows"],
    }


def fetch_all_configured_markets(db: Session) -> dict:
    """Roda o download automatico para cada mercado que tenha login
    configurado no .env. Mercados sem credencial sao ignorados (o
    usuario simplesmente nao usa aquele mercado ainda)."""
    results = []
    for market in ("BR", "US"):
        res = fetch_report_for_market(db, market)
        if not res.get("skipped"):
            results.append(res)

    imported_rows = sum(r.get("imported", 0) for r in results if r.get("ok"))
    errors = [f"{r['market']}: {r['error']}" for r in results if r.get("error")]

    return {
        "ran": len(results) > 0,
        "imported_rows": imported_rows,
        "results": results,
        "errors": errors,
    }


def run_manual_login_setup(market: str) -> None:
    """Configuracao unica (feita a mao, uma vez so) para contas com 2FA
    ativado. A Amazon pede verificacao extra no PRIMEIRO login de um
    navegador novo; depois que esse navegador fica "conhecido"/confiavel,
    os proximos logins (feitos sozinhos pelo robo, sem tela) normalmente
    nao pedem 2FA de novo - por isso basta fazer isso uma vez por mercado.

    Abre uma janela de navegador DE VERDADE (headless=False) para voce
    fazer o login manualmente (usuario, senha e o codigo de verificacao).
    Quando terminar de logar, volte no terminal e aperte ENTER: o ATLAS
    salva a sessao (cookies) e a partir dai o clique em "Atualizar" no
    painel funciona 100% sozinho, sem precisar repetir isso.
    """
    market = (market or "").upper()
    if market not in _MARKET_URLS:
        raise ValueError("Mercado invalido. Use BR ou US.")

    from playwright.sync_api import sync_playwright

    urls = _MARKET_URLS[market]
    session_file = _session_path(market)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            locale="pt-BR" if market == "BR" else "en-US",
        )
        page = context.new_page()
        page.goto(urls["login"], wait_until="domcontentloaded", timeout=45000)

        print()
        print(f"=== Configuracao unica do login Amazon ({market}) ===")
        print("1. Uma janela do navegador foi aberta, ja na tela de login.")
        print("2. Faca o login normalmente (email, senha e o codigo de verificacao/2FA).")
        print("3. Quando estiver logado e vendo o painel do Amazon Associates")
        print("   (nao mais a tela de login), volte aqui no terminal e aperte ENTER.")
        print()
        while True:
            input("Aperte ENTER depois de logar com sucesso na janela do navegador... ")
            # da um tempinho para qualquer redirecionamento final terminar
            page.wait_for_timeout(2000)
            current_url = page.url
            print(f"(url atual: {current_url})")
            if "/ap/signin" in current_url or "/ap/cvf" in current_url or "/ap/mfa" in current_url:
                print()
                print("Ainda estou vendo uma tela de login/verificacao nessa janela.")
                print("Termine o login na janela do navegador e aperte ENTER de novo.")
                continue
            break

        context.storage_state(path=str(session_file))
        context.close()
        browser.close()

    print(f"Sessao salva em {session_file}. Pode fechar esta janela.")
    print("A partir de agora, o botao 'Atualizar' no painel deve logar sozinho.")


if __name__ == "__main__":
    import sys

    def _debug_reports_page(market: str) -> None:
        """So para diagnostico: reaproveita a sessao salva, abre a pagina
        de relatorios e salva screenshot + HTML em storage/amazon_sessions/
        para o desenvolvedor ver o layout real da pagina."""
        from playwright.sync_api import sync_playwright

        market = market.upper()
        session_file = _session_path(market)
        if not session_file.exists():
            print(f"Nao ha sessao salva para {market}. Rode o setup primeiro.")
            raise SystemExit(1)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(storage_state=str(session_file))
            page = context.new_page()
            page.goto(_MARKET_URLS[market]["login"], wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3000)
            shot_path = _SESSION_DIR / f"debug_home_{market.lower()}.png"
            html_path = _SESSION_DIR / f"debug_home_{market.lower()}.html"
            page.screenshot(path=str(shot_path), full_page=True)
            html_path.write_text(page.content(), encoding="utf-8")
            print(f"URL atual: {page.url}")
            print(f"Screenshot: {shot_path}")
            print(f"HTML: {html_path}")
            context.close()
            browser.close()

    if len(sys.argv) == 3 and sys.argv[1] == "--debug" and sys.argv[2].upper() in ("BR", "US"):
        _debug_reports_page(sys.argv[2])
    elif len(sys.argv) == 2 and sys.argv[1].upper() in ("BR", "US"):
        run_manual_login_setup(sys.argv[1])
    else:
        print("Uso: python -m app.services.amazon_scraper_service BR|US")
        print("     python -m app.services.amazon_scraper_service --debug BR|US")
        raise SystemExit(1)
