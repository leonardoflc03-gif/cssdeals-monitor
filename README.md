# 🔔 Monitor CSSDeals

Te avisa no **Telegram** (com foto, preço, tamanho e link) sempre que um item novo aparece no cssdeals.com — 24h por dia, mesmo com o PC desligado.

## Como funciona

O site carrega os produtos de uma API pública (`cssdeals.com/api/product`). Cada item tem um **ID único**, então o monitor não depende da ordem das páginas:

- **A cada 5 min** → olha as 3 primeiras páginas (300 itens mais recentes) — pega quase tudo que entra.
- **A cada 1 hora** → varre o catálogo inteiro (~90 páginas) — pega itens que entraram fora de ordem.
- Compara com a lista de IDs que já viu. ID novo = notificação.
- Na **primeira execução** ele só memoriza os ~9.000 itens atuais e manda "✅ Monitor ativo" — não te enche de mensagem.
- Se entrarem muitos de uma vez, manda os 15 primeiros com foto e o resto num resumo com links.

---



## Filtros (opcional)

Por padrão você recebe **tudo**. Para filtrar, vá em **Settings → Secrets and variables → Actions → aba Variables → New repository variable**:

| Variável | Exemplo | O que faz |
|---|---|---|
| `KEYWORDS` | `nike,jordan,stussy,carhartt` | Só itens com alguma dessas palavras no título |
| `SIZES` | `42,43,M,L` | Só esses tamanhos |
| `MAX_PRICE` | `200` | Preço máximo em ¥ (yuan) |
| `CATEGORIES` | `11,32,15` | Só essas categorias (tabela abaixo) |

Pode combinar vários. Para voltar a receber tudo, apague a variável.

**IDs das categorias:** 11 Calçados · 12 Casaco · 14 Camisetas · 15 Calças · 18 Moda · 20 Relógios · 21 Celular · 22 Fone · 23 Acessórios de PC · 24 Áudio e vídeo · 26 Chapéus e bolsas · 27 Cinto e óculos · 30 Luvas e cachecol · 31 Roupa íntima · 32 Moletom · 33 Jaqueta de plumas · 34 Terno · 35 Manga longa · 37 Brinquedo · 38 Capinha · 40 Meias · 44 Perfume · 45 Mala · 16/39/41 Acessórios · 36/43 Esportes

---

## Plano B — rodar no seu PC

Use se o site bloquear o GitHub (você vai perceber se a aba Actions mostrar erros seguidos), ou se quiser checar mais rápido que 5 min.

```bash
pip install requests
# Windows (PowerShell):
$env:TELEGRAM_TOKEN="seu_token"; $env:TELEGRAM_CHAT_ID="seu_id"
# Mac/Linux:
export TELEGRAM_TOKEN="seu_token" TELEGRAM_CHAT_ID="seu_id"

python monitor.py --test     # testa a notificação
python monitor.py --loop     # fica monitorando (a cada 3 min); só funciona com o PC ligado
```

Ajustes: `LOOP_MINUTES=1` (checar a cada 1 min), `FULL_SCAN_MINUTES=30` (varredura completa mais frequente).

## Problemas comuns

- **Não chegou nada** → Actions → clique na última execução → veja o log do passo "Procurar itens novos".
- **"Telegram sendMessage falhou: 400 chat not found"** → você não mandou mensagem pro bot antes, ou o chat ID está errado.
- **Workflow parou de rodar sozinho** → o GitHub pausa agendamentos em repositórios sem atividade por 60 dias. Basta entrar em Actions e reativar (ou fazer qualquer commit).
- **Recebi um monte de itens de uma vez** → normal quando o site sobe um lote; o resumo agrupa tudo.
