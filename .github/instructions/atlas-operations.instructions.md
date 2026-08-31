---
description: Regras operacionais permanentes do Atlas OS
applyTo: '**'
---

# Operação segura do Atlas

- Ao encerrar um dia de trabalho, execute `scripts\run_daily_backup.ps1`, valide o manifesto e crie uma versão Git identificável.
- Nunca coloque `.env`, tokens, banco original, telefone, cartão, e-mails privados ou prompts sem redação em GitHub Pages ou em repositório público.
- Nunca renove, reative, duplique, publique ou crie campanha paga sem autorização explícita do usuário para aquela operação e orçamento.
- Orçamentos pagos devem ter período fechado e proteção contra renovação. Uma autorização não vale para campanhas futuras.
- Vídeos de produto só podem usar mídia fiel ao produto/ASIN exato. Não use fallback genérico, variante diferente ou mídia patrocinada desconectada.
- TikTok BR é `@achadosatlasbr`; TikTok US é `@atlasfindsus`. Nunca roteie os dois mercados para a mesma conta.
- Enquanto o aplicativo TikTok não for auditado, use `video.upload` e finalização pela caixa de entrada. Não contorne `unaudited_client_can_only_post_to_private_accounts`.
- O produto comercial público deve ser separado do painel administrativo privado. Nunca exponha tokens, automações internas ou banco local no frontend público.
- Integrações e plugins devem falhar de forma explícita quando credenciais, licenças ou permissões estiverem ausentes.
