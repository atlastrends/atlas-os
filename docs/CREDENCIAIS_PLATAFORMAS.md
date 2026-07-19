# ATLAS OS — Passo a passo para obter as credenciais das plataformas

Este guia mostra como conseguir cada credencial usada pelo painel para
**publicar automaticamente** e **coletar métricas** (curtidas, views, seguidores).

Depois de obter cada valor, coloque no arquivo `.env` (nunca faça commit dele).
O painel mostra em **Publicações → Conexão das plataformas** quais credenciais
ainda faltam.

---

## 1. YouTube (YouTube Data API v3 — upload de Shorts + métricas)

Variáveis no `.env`:
```
YOUTUBE_CLIENT_ID=
YOUTUBE_CLIENT_SECRET=
YOUTUBE_REFRESH_TOKEN=
YOUTUBE_API_KEY=        # já existe (usado para tendências)
```

Passos:
1. Acesse https://console.cloud.google.com/ e crie/selecione um projeto.
2. Menu **APIs e Serviços → Biblioteca** → habilite **YouTube Data API v3**.
3. **APIs e Serviços → Tela de consentimento OAuth**: configure (tipo "Externo"),
   adicione seu e-mail como usuário de teste.
4. **Credenciais → Criar credenciais → ID do cliente OAuth** → tipo
   **App para computador (Desktop)**. Copie **Client ID** e **Client Secret**.
5. Gere o **refresh token** com o escopo
   `https://www.googleapis.com/auth/youtube.upload`
   (use o OAuth Playground em https://developers.google.com/oauthplayground,
   engrenagem → marque "Use your own OAuth credentials" e cole ID/Secret).
6. Preencha as variáveis no `.env`.

Observações: o canal precisa estar verificado para enviar vídeos > 15 min
(Shorts não precisam). Publique como `private` até validar.

---

## 2. Meta — Instagram Reels + Facebook (Graph API)

Variáveis no `.env`:
```
META_APP_ID=
META_APP_SECRET=
META_ACCESS_TOKEN=                 # token de longa duração (Page/User)
INSTAGRAM_BUSINESS_ACCOUNT_ID=
FACEBOOK_PAGE_ID=
```

Passos:
1. Crie uma conta de desenvolvedor em https://developers.facebook.com/.
2. **Meus Apps → Criar App** → tipo **Business**.
3. Adicione os produtos **Instagram Graph API** e **Facebook Login**.
4. Sua conta do Instagram precisa ser **Profissional/Business** e estar
   **vinculada a uma Página do Facebook**.
5. Descubra os IDs:
   - `FACEBOOK_PAGE_ID`: em Graph API Explorer, chame `GET /me/accounts`.
   - `INSTAGRAM_BUSINESS_ACCOUNT_ID`: `GET /{page-id}?fields=instagram_business_account`.
6. Gere um **token de longa duração** (60 dias) e configure renovação.
   Permissões necessárias: `instagram_content_publish`,
   `pages_read_engagement`, `pages_manage_posts`, `business_management`.
7. Preencha o `.env`.

Importante: a publicação no Instagram exige que o vídeo esteja acessível por
uma **URL pública** (o painel serve os vídeos em `/media/...`; exponha o
`ATLAS_PUBLIC_BASE_URL` com um domínio/HTTPS acessível pela Meta).

---

## 3. TikTok (Content Posting API)

Variáveis no `.env`:
```
TIKTOK_CLIENT_KEY=
TIKTOK_CLIENT_SECRET=
TIKTOK_ACCESS_TOKEN=
```

Passos:
1. Acesse https://developers.tiktok.com/ e crie um app.
2. Solicite o produto **Content Posting API** (requer aprovação do TikTok e,
   para publicação direta, o app pode precisar de auditoria).
3. Configure o **Login Kit** (OAuth) com o escopo `video.publish`.
4. Faça o fluxo OAuth para obter `access_token` (e `refresh_token`).
5. Preencha o `.env`.

Observação: enquanto o app estiver em modo sandbox, os vídeos podem ir para
rascunho/privado. A publicação pública exige app aprovado.

---

## 4. Onde colocar e como ativar

1. Edite `.env` e preencha as variáveis das plataformas desejadas.
2. Reinicie a API (`docker compose restart api`).
3. No painel, veja **Publicações → Conexão das plataformas**: a plataforma
   fica **verde (Conectado)** quando todas as variáveis estão preenchidas.
4. Ative o upload real implementando o método `_do_publish` do conector
   correspondente em `app/publishing/<plataforma>/publisher.py`
   (os conectores já validam as credenciais e recebem o vídeo + legenda com o
   link clicável pronto).

---

## Coleta de métricas (curtidas, views, seguidores)

As mesmas credenciais acima habilitam a leitura de métricas:
- **YouTube**: `videos.list(part=statistics)` e `channels.list(part=statistics)`.
- **Meta**: Insights de `/{ig-media-id}/insights` e `/{page-id}/insights`.
- **TikTok**: endpoints de Video/User Analytics.

Implemente os coletores para gravar em `video_metrics` e `platform_stats`
(um job periódico pode rodar a cada X horas). O painel já lê e agrega esses
dados automaticamente em **Analytics**.
