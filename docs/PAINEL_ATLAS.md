# ATLAS OS — Painel Web

Painel profissional para monitorar e operar a fábrica de conteúdo:
buscar produtos na Amazon, gerar reels, revisar/aceitar/rejeitar vídeos,
publicar nas plataformas e acompanhar métricas.

## Arquitetura

- **Backend**: FastAPI (já existente) + novas rotas em `/api` (`app/routers/dashboard_api.py`).
- **Frontend**: React + Vite em `frontend/` (app separado).
- **Links clicáveis**: `/go/{code}` redireciona para o produto e conta cliques.
- **Mídia**: `/media/{path}` serve os vídeos com allow-list de pastas.

## Como rodar

### 1) Backend (API)
```powershell
# na raiz do projeto (com Docker Desktop aberto)
docker compose up -d postgres redis api
# As tabelas do painel são criadas automaticamente no startup.
```
API em http://localhost:8000 — documentação em http://localhost:8000/docs

### 2) Frontend (painel)
```powershell
cd frontend
npm install      # só na primeira vez
npm run dev      # abre em http://localhost:5173
```
O Vite faz proxy de `/api`, `/media` e `/go` para a API em :8000.

### Build de produção do painel
```powershell
cd frontend
npm run build    # gera frontend/dist
```

## Fluxo de uso

1. **Produtos Amazon** → botão *Buscar produtos* (TOP 10 por categoria, BR+US).
2. **Vídeos Afiliados** / **Reels** → pré-visualize, *Aceitar e publicar* ou *Rejeitar*.
   - Ao aceitar, o vídeo é enfileirado para as plataformas selecionadas.
   - Para afiliados, o **link clicável** já entra na legenda/descrição.
3. **Publicações** → acompanhe a fila e quais plataformas estão conectadas.
4. **Analytics** → métricas por plataforma e por vídeo.

## Automação

- **Reels automáticos (1 PT + 1 EN a cada 15 min):** defina no `docker-compose.yml`
  (serviço `api`) `ATLAS_ENGINE_ENABLED: "true"`.
- **Busca de produtos automática:** agende o scraper (ex.: Agendador de Tarefas do
  Windows chamando o pipeline, ou um job APScheduler/Celery).

## Credenciais das plataformas

Veja `docs/CREDENCIAIS_PLATAFORMAS.md` para o passo a passo de YouTube, Meta
(Instagram/Facebook) e TikTok. Enquanto não houver credenciais, o painel funciona
e mostra "Falta credencial" — o upload real ativa quando as chaves forem preenchidas.
