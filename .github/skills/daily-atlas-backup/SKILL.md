---
name: daily-atlas-backup
description: Cria e valida a versão diária recuperável do Atlas, com prompts sanitizados e sem credenciais.
---

# Backup diário do Atlas

Use esta skill ao final de cada dia ou antes de mudanças estruturais.

## Procedimento

1. Confirme que as mudanças de código foram testadas e commitadas.
2. Execute:

   ```powershell
   C:\atlas-os\scripts\run_daily_backup.ps1
   ```

3. Localize o manifesto em `C:\atlas-os\backups\daily\AAAA\AAAA-MM-DD\manifest.json`.
4. Valide o arquivo:

   ```powershell
   C:\atlas-os\.venv-dash\Scripts\python.exe `
     C:\atlas-os\scripts\atlas_daily_backup.py verify `
     --manifest C:\atlas-os\backups\daily\AAAA\AAAA-MM-DD\manifest.json
   ```

5. Crie uma tag Git diária somente após a validação.
6. Se `ATLAS_BACKUP_MIRROR` estiver configurado, confirme que a cópia externa possui os mesmos hashes.

## Conteúdo

- bundle Git completo;
- hash e estado do commit;
- prompts e respostas sanitizados;
- banco SQLite sanitizado, sem tokens;
- nomes das variáveis de ambiente, sem valores;
- versões de runtime;
- inventário SHA-256 dos assets locais.

## Restrições

- Nunca arquive o `.env` original.
- Nunca copie o banco original para nuvem sem criptografia.
- Nunca publique prompts privados em `docs/`.
- Tokens precisam ser reautorizados após restauração em outra máquina.
