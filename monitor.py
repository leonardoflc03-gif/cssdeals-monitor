"""
Monitor do CSSDeals — avisa no Telegram quando um item novo aparece.

Como funciona:
  - O site carrega os produtos de uma API pública:
        https://cssdeals.com/api/product?fields=1&page=N&pageSize=100
  - Cada item tem um "id" único. O script guarda todos os IDs já vistos em
    seen_ids.json e, a cada execução, compara: ID que não estava lá = item novo.
  - Como a ordem das páginas muda sem aviso, não confiamos na posição:
      * varredura rápida (as primeiras páginas, onde ficam os mais novos) toda vez;
      * varredura completa (todas as páginas) a cada FULL_SCAN_MINUTES.
  - Na primeira execução ele só "aprende" o catálogo atual, sem notificar tudo.

Uso:
  python monitor.py            # roda uma vez (GitHub Actions)
  python monitor.py --loop     # fica rodando no seu PC, checando a cada LOOP_MINUTES
  python monitor.py --test     # manda uma mensagem de teste no Telegram
"""

import html
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

# ---------------------------------------------------------------- configuração
API = "https://cssdeals.com/api/product"
PRODUCT_URL = "https://cssdeals.com/product-detail.html?itemid={id}"
PAGE_SIZE = 100                     # máximo que a API aceita
QUICK_PAGES = int(os.getenv("QUICK_PAGES", "3"))
FULL_SCAN_MINUTES = int(os.getenv("FULL_SCAN_MINUTES", "60"))
LOOP_MINUTES = float(os.getenv("LOOP_MINUTES", "3"))
STATE_FILE = os.getenv("STATE_FILE", "seen_ids.json")
MAX_INDIVIDUAL = int(os.getenv("MAX_INDIVIDUAL", "15"))  # acima disso, manda resumo

TG_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")

# Filtros opcionais (deixe vazio para receber tudo)
#   KEYWORDS="nike,jordan,stussy"   -> só itens cujo título contém alguma palavra
#   SIZES="42,43,M,L"               -> só esses tamanhos
#   MAX_PRICE="150"                 -> preço máximo em ¥ (yuan)
#   CATEGORIES="11,15,32"           -> IDs de categoria (lista abaixo)
KEYWORDS = [k.strip().lower() for k in os.getenv("KEYWORDS", "").split(",") if k.strip()]
SIZES = [s.strip().lower() for s in os.getenv("SIZES", "").split(",") if s.strip()]
MAX_PRICE = float(os.getenv("MAX_PRICE") or 0)
CATEGORIES = [c.strip() for c in os.getenv("CATEGORIES", "").split(",") if c.strip()]

CATEGORY_NAMES = {
    "18": "Moda", "32": "Moletom", "40": "Meias", "45": "Mala", "11": "Calçados",
    "33": "Jaqueta de plumas", "12": "Casaco", "14": "Camisetas", "15": "Calças",
    "26": "Chapéus e bolsas", "34": "Terno", "35": "Manga longa", "39": "Acessórios",
    "27": "Cinto e óculos", "30": "Luvas e cachecol", "31": "Roupa íntima e pijama",
    "44": "Perfume", "41": "Acessórios", "37": "Brinquedo", "16": "Acessórios",
    "43": "Esportes", "36": "Esportes", "19": "Eletrônicos", "38": "Capinha de celular",
    "20": "Relógios", "21": "Celular", "22": "Fone de ouvido",
    "23": "Acessórios de PC", "24": "Áudio e vídeo",
}
PLATFORMS = {1: "1688", 2: "Taobao", 3: "Weidian", 99: "CSSDeals"}

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://cssdeals.com/",
})


# ---------------------------------------------------------------- API do site
def fetch_page(page: int) -> dict:
    for attempt in range(4):
        try:
            r = session.get(API, params={"fields": 1, "page": page, "pageSize": PAGE_SIZE},
                            timeout=30)
            r.raise_for_status()
            body = r.json()
            if body.get("code") != 0:
                raise RuntimeError(f"API respondeu code={body.get('code')} msg={body.get('msg')}")
            return body["data"]
        except Exception as e:  # noqa: BLE001
            wait = 2 ** attempt
            print(f"  página {page}: erro ({e}); tentando de novo em {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"Falhou ao baixar a página {page}")


def scan(pages: int | None) -> tuple[dict, int]:
    """Baixa `pages` páginas (None = todas). Retorna {id: item} e o total do site."""
    items, page, total = {}, 1, 0
    while True:
        data = fetch_page(page)
        total = int(data.get("total") or 0)
        for rec in data.get("records") or []:
            items[str(rec["id"])] = rec
        last_page = -(-total // PAGE_SIZE) if total else page
        if not data.get("records") or page >= last_page or (pages and page >= pages):
            break
        page += 1
        time.sleep(0.4)  # educado com o servidor
    return items, total


# ---------------------------------------------------------------- estado
def load_state() -> dict | None:
    if not os.path.exists(STATE_FILE):
        return None
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            s = json.load(f)
        s["seen"] = set(s.get("seen", []))
        return s
    except Exception as e:  # noqa: BLE001
        print(f"Estado corrompido ({e}); reiniciando.")
        return None


def save_state(state: dict) -> None:
    out = dict(state)
    out["seen"] = sorted(state["seen"])
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f)
    os.replace(tmp, STATE_FILE)


# ---------------------------------------------------------------- formatação
def info(item: dict) -> dict:
    sku = (item.get("skus") or [{}])[0]
    title = html.unescape(item.get("title") or "").strip()
    return {
        "id": str(item["id"]),
        "title": title[:180],
        "price": sku.get("price"),
        "size": (sku.get("size") or "").strip(),
        "variant": html.unescape(sku.get("skuNames") or "").strip(" ;")[:150],
        "image": sku.get("image") or "",
        "category": CATEGORY_NAMES.get(str(item.get("categoryId")), "—"),
        "platform": PLATFORMS.get(item.get("salePlatform"), "?"),
        "url": PRODUCT_URL.format(id=item["id"]),
    }


def passes_filters(i: dict, raw: dict) -> bool:
    if KEYWORDS and not any(k in (i["title"] + " " + i["variant"]).lower() for k in KEYWORDS):
        return False
    if SIZES and i["size"].lower() not in SIZES:
        return False
    if MAX_PRICE and (i["price"] is None or float(i["price"]) > MAX_PRICE):
        return False
    if CATEGORIES and str(raw.get("categoryId")) not in CATEGORIES:
        return False
    return True


def esc(t: str) -> str:
    return html.escape(t or "", quote=False)


def caption(i: dict) -> str:
    lines = [f"🆕 <b>{esc(i['title'])}</b>", ""]
    if i["price"] is not None:
        lines.append(f"💰 ¥{float(i['price']):.2f}")
    if i["size"]:
        lines.append(f"📏 Tamanho: {esc(i['size'])}")
    if i["variant"] and i["variant"] != i["size"]:
        lines.append(f"🎨 {esc(i['variant'])}")
    lines.append(f"🏷 {esc(i['category'])} · {i['platform']}")
    lines.append(f'\n<a href="{i["url"]}">👉 Abrir no CSSDeals</a>')
    return "\n".join(lines)[:1024]


# ---------------------------------------------------------------- Telegram
def tg(method: str, **payload) -> bool:
    if not (TG_TOKEN and TG_CHAT):
        print("  (Telegram não configurado — só imprimindo)")
        return False
    url = f"https://api.telegram.org/bot{TG_TOKEN}/{method}"
    for _ in range(3):
        r = requests.post(url, data={"chat_id": TG_CHAT, "parse_mode": "HTML", **payload},
                          timeout=30)
        if r.status_code == 429:  # limite de mensagens: espera o que o Telegram pedir
            time.sleep(r.json().get("parameters", {}).get("retry_after", 5) + 1)
            continue
        if not r.ok:
            print(f"  Telegram {method} falhou: {r.status_code} {r.text[:200]}")
        return r.ok
    return False


def notify(new_items: list[dict]) -> None:
    for n, i in enumerate(new_items[:MAX_INDIVIDUAL]):
        print(f"  NOVO: {i['title'][:70]} | ¥{i['price']} | {i['url']}")
        sent = i["image"] and tg("sendPhoto", photo=i["image"], caption=caption(i))
        if not sent:  # imagem quebrada? manda só o texto
            tg("sendMessage", text=caption(i), disable_web_page_preview="false")
        time.sleep(1.1)

    rest = new_items[MAX_INDIVIDUAL:]
    if rest:
        print(f"  + {len(rest)} itens em resumo")
        chunk, header = [], f"📦 <b>Mais {len(rest)} itens novos:</b>\n"
        for i in rest:
            price = f"¥{float(i['price']):.0f}" if i["price"] is not None else ""
            size = f" ({esc(i['size'])})" if i["size"] else ""
            chunk.append(f'• <a href="{i["url"]}">{esc(i["title"][:60])}</a>{size} {price}')
            if len("\n".join(chunk)) > 3500:
                tg("sendMessage", text=header + "\n".join(chunk), disable_web_page_preview="true")
                chunk, header = [], ""
                time.sleep(1.1)
        if chunk:
            tg("sendMessage", text=header + "\n".join(chunk), disable_web_page_preview="true")


# ---------------------------------------------------------------- execução
def run_once() -> None:
    now = time.time()
    state = load_state()
    first_run = state is None
    if first_run:
        state = {"seen": set(), "last_full": 0, "total": 0}

    full = first_run or (now - state.get("last_full", 0)) >= FULL_SCAN_MINUTES * 60
    mode = "completa" if full else f"rápida ({QUICK_PAGES} págs)"
    print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC] varredura {mode}")

    items, total = scan(None if full else QUICK_PAGES)
    new_ids = [i for i in items if i not in state["seen"]]
    # mais novos primeiro (os IDs crescem com o tempo)
    new_ids.sort(key=int, reverse=True)

    if first_run:
        print(f"  Primeira execução: {len(items)} itens memorizados, sem notificar.")
        tg("sendMessage", text=f"✅ Monitor do CSSDeals ativo!\n{len(items)} itens já no site "
                               f"foram memorizados. A partir de agora você recebe só os novos.")
    else:
        wanted = []
        for _id in new_ids:
            i = info(items[_id])
            if passes_filters(i, items[_id]):
                wanted.append(i)
        print(f"  {len(items)} itens lidos, {len(new_ids)} novos, {len(wanted)} passam nos filtros")
        if wanted:
            notify(wanted)

    state["seen"].update(items.keys())
    if full:
        state["last_full"] = now
    state["total"] = total
    save_state(state)


def main() -> None:
    if "--test" in sys.argv:
        ok = tg("sendMessage", text="🔔 Teste do monitor CSSDeals: as notificações estão funcionando!")
        print("Mensagem enviada!" if ok else "Falhou — confira TELEGRAM_TOKEN e TELEGRAM_CHAT_ID.")
        return
    if "--loop" in sys.argv:
        while True:
            try:
                run_once()
            except Exception as e:  # noqa: BLE001
                print(f"Erro nesta rodada: {e}")
            time.sleep(LOOP_MINUTES * 60)
    run_once()


if __name__ == "__main__":
    main()
