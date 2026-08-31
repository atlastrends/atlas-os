# Configurar geração de vídeo por IA no Dell G15 (RTX 3060, 6 GB VRAM)

Este guia liga o **Diário da Bela** à sua GPU dedicada, para gerar clipes de
vídeo com **movimento real** (não imagem parada com zoom) em cada cena, no
Dell G15 (AMD Ryzen 7 5800H + RTX 3060 Laptop 6GB).

> Sem esta configuração, o ATLAS continua funcionando normalmente em
> qualquer computador (incluindo este onde o código foi escrito) usando o
> modo de imagem parada + zoom/pan — é o *fallback* automático e seguro.
> Esta configuração é só para ativar o modo de vídeo com movimento de
> verdade, que exige GPU dedicada.

## Visão geral do que vamos instalar

1. **ComfyUI** — motor gratuito e de código aberto que roda modelos de IA
   generativa localmente, usando sua GPU.
2. **ComfyUI-VideoHelperSuite** — extensão (nó) que junta os quadros
   gerados num arquivo de vídeo `.mp4`.
3. **Modelo Wan 2.1** (image-to-video) — o modelo de IA que efetivamente
   gera o movimento a partir da imagem-chave da cena.
4. Configuração no `.env` do ATLAS apontando para o ComfyUI local.

Com 6 GB de VRAM, espere clipes **curtos por cena** (poucos segundos de
movimento cada) e tempos de geração relativamente longos por episódio,
principalmente no primeiro uso. Isso é normal para essa faixa de GPU.

---

## 1. Instalar o ComfyUI

1. Acesse **https://www.comfy.org/download** e baixe o instalador do
   **ComfyUI Desktop para Windows** (tem detecção automática de GPU
   NVIDIA).
2. Instale normalmente. Na primeira abertura, ele já detecta a RTX 3060.
3. Deixe o ComfyUI abrir — ele sobe um servidor local, normalmente em
   `http://127.0.0.1:8188`.

## 2. Instalar o ComfyUI Manager (se não vier incluso)

O ComfyUI Desktop mais recente já vem com o **Manager** embutido (ícone de
gerenciador de pacotes na barra lateral). Se não tiver:
1. Vá em **Menu → Custom Nodes → ComfyUI Manager** (ou instale manualmente
   seguindo https://github.com/Comfy-Org/ComfyUI-Manager).

## 3. Instalar a extensão de vídeo (VideoHelperSuite)

1. Abra o **Manager** dentro do ComfyUI.
2. Vá em **"Install Custom Nodes"**.
3. Procure por **"ComfyUI-VideoHelperSuite"** e clique em instalar.
4. Reinicie o ComfyUI quando pedir.

## 4. Baixar os modelos do Wan 2.1

Baixe os arquivos abaixo (todos gratuitos, sem cadastro) e salve exatamente
nestas pastas dentro da instalação do ComfyUI:

| Arquivo | Salvar em | Link |
|---|---|---|
| `wan2.1_i2v_480p_14B_fp16.safetensors` | `ComfyUI/models/diffusion_models/` | https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/diffusion_models/wan2.1_i2v_480p_14B_fp16.safetensors |
| `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | `ComfyUI/models/text_encoders/` | https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors |
| `wan_2.1_vae.safetensors` | `ComfyUI/models/vae/` | https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors |
| `clip_vision_h.safetensors` | `ComfyUI/models/clip_vision/` | https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/clip_vision/clip_vision_h.safetensors |

> ⚠️ **Sobre a memória (6 GB é pouco para o modelo 14B):** o arquivo acima
> (`14B`) é o modelo "grande" oficial e pode não caber nos 6GB da RTX 3060
> sozinho. Se der erro de **"CUDA out of memory"** ao testar (passo 6),
> troque para uma versão **quantizada (GGUF)** do mesmo modelo, bem menor:
> 1. No Manager, instale o custom node **"ComfyUI-GGUF"**.
> 2. Baixe uma versão GGUF do Wan 2.1 I2V 480p (procure por
>    `wan2.1-i2v-14b-480p` no HuggingFace, pasta `city96` ou
>    `QuantStack` costumam ter versões GGUF Q4/Q5 — essas cabem em 6GB).
> 3. Salve em `ComfyUI/models/unet/` (ou `diffusion_models/`, conforme o
>    node pedir).
> 4. No workflow (próximo passo), troque o nó **"Load Diffusion Model"**
>    (`UNETLoader`) por **"Unet Loader (GGUF)"** e aponte para o arquivo
>    `.gguf` baixado.

## 5. Testar o modelo manualmente na interface do ComfyUI

**Faça este teste manual ANTES de conectar ao ATLAS** — garante que o
ComfyUI e a GPU estão funcionando corretamente.

1. Na página inicial do ComfyUI, vá em **Workflow → Browse Templates**.
2. Procure **"Wan 2.1 Image to Video"** (categoria Video).
3. Carregue o template — ele já vem com os nós certos.
4. Confirme que os 4 arquivos baixados no passo 4 estão selecionados nos
   respectivos nós (`Load Diffusion Model`, `Load CLIP`, `Load VAE`,
   `Load CLIP Vision`).
5. Carregue qualquer imagem de teste no nó **"Load Image"**.
6. Clique em **Run** (ou `Ctrl+Enter`).
7. Aguarde — a primeira geração é mais lenta (carrega os modelos na GPU).
   Se terminar e mostrar um vídeo com movimento, está tudo funcionando.

Se der erro de memória, volte ao aviso do passo 4 (versão GGUF).

## 6. Exportar o workflow em formato API e usar o do ATLAS

O ATLAS já vem com um workflow de referência pronto em:
```
app/assets/comfyui_workflows/teen_diary_wan21_i2v.json
```

Esse arquivo já está no formato certo (API JSON) e com os nomes de modelo
do passo 4. Ele deve funcionar como está, mas se você precisar ajustar
(nomes de arquivo diferentes, versão GGUF, resolução), o caminho é:

1. Abra o `teen_diary_wan21_i2v.json` no ComfyUI: **Workflow → Open** (ou
   arraste o arquivo para a janela do ComfyUI).
2. Ajuste o que precisar (nome do modelo, etc.) diretamente na interface.
3. Exporte de novo: **Workflow → Export (API)** e salve por cima do mesmo
   arquivo (ou em outro caminho, e aponte `ATLAS_LOCAL_VIDEO_WORKFLOW` no
   `.env` para ele).

> ⚠️ Os campos `__POSITIVE_PROMPT__`, `__IMAGE_FILENAME__`, `__SEED__`,
> `__FRAMES__`, `__FPS__`, `__WIDTH__`, `__HEIGHT__` são preenchidos
> AUTOMATICAMENTE pelo ATLAS a cada cena — não apague esses textos ao
> reexportar, ou digite-os de volta manualmente nos campos correspondentes
> depois de exportar (texto do prompt positivo, nome da imagem, seed,
> comprimento/length, frame rate, largura, altura).

## 7. Configurar o `.env` do ATLAS

Deixe o ComfyUI aberto e rodando, depois edite o `.env` do ATLAS (na pasta
`C:\atlas-os`, ou onde você clonou o projeto neste notebook):

```env
ATLAS_LOCAL_VIDEO_URL=http://127.0.0.1:8188
ATLAS_LOCAL_VIDEO_WORKFLOW=app/assets/comfyui_workflows/teen_diary_wan21_i2v.json
ATLAS_LOCAL_VIDEO_TIMEOUT=600
ATLAS_LOCAL_VIDEO_FRAMES=65
ATLAS_LOCAL_VIDEO_FPS=16
ATLAS_LOCAL_VIDEO_WIDTH=480
ATLAS_LOCAL_VIDEO_HEIGHT=832

# Tambem aproveita a GPU para CODIFICAR o video final (bem mais rapido que
# so por CPU). "auto" detecta sozinho se ha suporte a NVENC.
ATLAS_VIDEO_ENCODER=auto
```

Também vale a pena gerar as **imagens-chave** de cada cena pela GPU local
(mais rápido e sem depender de internet), usando o mesmo ComfyUI:

```env
ATLAS_LOCAL_SD_URL=http://127.0.0.1:7860
```

> Nota: a geração de IMAGEM usa a API estilo Automatic1111
> (`/sdapi/v1/txt2img`), diferente da API do ComfyUI usada para vídeo. Se
> quiser usar Automatic1111 (Stable Diffusion WebUI) só para as imagens,
> instale-o separadamente (porta padrão 7860) — é opcional; sem isso, o
> ATLAS continua gerando as imagens-chave pelo Pollinations (remoto,
> gratuito), só o vídeo (movimento) depende do ComfyUI.

## 8. Rodar o ATLAS e gerar um episódio de teste

1. Reinicie o ATLAS (feche a janela e abra `ATLAS.bat` de novo).
2. Abra `/stories` no painel → aba **"Diário da Bela"**.
3. Clique em **"Gerar próxima parte"**.
4. Acompanhe o log — quando chegar na parte de vídeo, deve aparecer:
   `[VIDEO LOCAL] ComfyUI detectado em http://127.0.0.1:8188 (GPU local).`
5. Cada cena vai demorar mais que o modo antigo (é normal, está gerando
   vídeo de verdade). Acompanhe o progresso pelo log da própria página.

Se algo falhar no meio (ComfyUI travou, faltou memória etc.), o ATLAS cai
sozinho no modo de imagem parada + zoom/pan **só para aquela cena** — o
episódio inteiro não é perdido.

## 9. O que fazer depois de assistir ao resultado

Depois de ver a qualidade, volte para o outro computador (onde está esta
conversa) e me diga:
- Se o movimento ficou bom, exagerado, ou pouco perceptível.
- Se o rosto/aparência da Bela/Maria ficou consistente com o estilo
  travado no código.
- Quanto tempo levou para gerar (para eu calibrar frames/resolução).

A partir disso, ajusto os parâmetros (frames, resolução, prompts de
movimento) e você testa de novo — sem precisar reinstalar nada, só puxar
a atualização do GitHub.

---

## Solução de problemas comuns

| Sintoma | Causa provável | Solução |
|---|---|---|
| `CUDA out of memory` | Modelo 14B não cabe em 6GB | Use versão GGUF quantizada (passo 4) |
| `[VIDEO LOCAL] ComfyUI não respondeu` | ComfyUI fechado ou porta errada | Confirme que o ComfyUI está aberto e a URL no `.env` bate com a porta mostrada por ele |
| `Missing Node Type` ao abrir o workflow | Faltou instalar o VideoHelperSuite | Repita o passo 3 |
| Vídeo gerado mas sem áudio depois | Normal — o ComfyUI só gera o VÍDEO da cena; o ATLAS adiciona a narração por cima depois, na montagem final | Nenhuma ação necessária |
| Demorou muito (10+ min por cena) | Normal na 1ª vez (carrega modelo) ou resolução/frames altos demais | Reduza `ATLAS_LOCAL_VIDEO_FRAMES` e `_WIDTH`/`_HEIGHT` no `.env` |
