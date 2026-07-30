import os
import re
import json
import sqlite3
import asyncio
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests
from datetime import datetime, timedelta

# Configurações de Ambiente
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
INTERVALO_CHECAGEM = int(os.environ.get("INTERVALO_CHECAGEM", 300))
DB_PATH = os.environ.get("DB_PATH", "/app/data/historico.db")

# Matriz de Monitoramento Multi-Loja
CATEGORIAS = [
    # --- KABUM ---
    {
        "nome": "KaBuM - RTX 5060",
        "url": "https://servicespub.prod.api.aws.grupokabum.com.br/catalog/v2/products?query=rtx%205060&page_number=1&page_size=100",
        "termos_obrigatorios": ["5060"],
        "piso_bug": 2300.00,
        "site": "kabum_api"
    },
    {
        "nome": "KaBuM - RTX 3060",
        "url": "https://servicespub.prod.api.aws.grupokabum.com.br/catalog/v2/products?query=rtx%203060&page_number=1&page_size=100",
        "termos_obrigatorios": ["3060"],
        "piso_bug": 2200.00,
        "site": "kabum_api"
    },
    {
        "nome": "KaBuM - RX 7600 / RX 6600",
        "url": "https://servicespub.prod.api.aws.grupokabum.com.br/catalog/v2/products?query=rx%206600&page_number=1&page_size=100",
        "termos_obrigatorios": ["6600", "7600"],
        "piso_bug": 1500.00,
        "site": "kabum_api"
    },

    # --- TERABYTE ---
    {
        "nome": "Terabyte - RTX 5060",
        "url": "https://www.terabyteshop.com.br/busca?str=rtx+5060",
        "termos_obrigatorios": ["5060"],
        "piso_bug": 2300.00,
        "site": "terabyte"
    },
    {
        "nome": "Terabyte - RTX 3060",
        "url": "https://www.terabyteshop.com.br/busca?str=rtx+3060",
        "termos_obrigatorios": ["3060"],
        "piso_bug": 2200.00,
        "site": "terabyte"
    },
    {
        "nome": "Terabyte - RX 6600 / RX 7600",
        "url": "https://www.terabyteshop.com.br/busca?str=rx+6600",
        "termos_obrigatorios": ["6600", "7600"],
        "piso_bug": 1500.00,
        "site": "terabyte"
    },

    # --- PICHAU ---
    {
        "nome": "Pichau - RTX 5060",
        "url": "https://www.pichau.com.br/search?q=rtx%205060",
        "termos_obrigatorios": ["5060"],
        "piso_bug": 2300.00,
        "site": "pichau"
    },
    {
        "nome": "Pichau - RTX 3060",
        "url": "https://www.pichau.com.br/search?q=rtx%203060",
        "termos_obrigatorios": ["3060"],
        "piso_bug": 2200.00,
        "site": "pichau"
    },
    {
        "nome": "Pichau - RX 6600 / RX 7600",
        "url": "https://www.pichau.com.br/search?q=rx%206600",
        "termos_obrigatorios": ["6600", "7600"],
        "piso_bug": 1500.00,
        "site": "pichau"
    },

    # --- AMAZON BRASIL ---
    {
        "nome": "Amazon - RTX 5060",
        "url": "https://www.amazon.com.br/s?k=rtx+5060",
        "termos_obrigatorios": ["5060"],
        "piso_bug": 2300.00,
        "site": "amazon"
    },
    {
        "nome": "Amazon - RTX 3060",
        "url": "https://www.amazon.com.br/s?k=rtx+3060",
        "termos_obrigatorios": ["3060"],
        "piso_bug": 2200.00,
        "site": "amazon"
    },
    {
        "nome": "Amazon - RX 6600 / RX 7600",
        "url": "https://www.amazon.com.br/s?k=rx+6600",
        "termos_obrigatorios": ["6600", "7600"],
        "piso_bug": 1500.00,
        "site": "amazon"
    }
]

# --- BANCO DE DADOS (SQLite) ---
def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cursor = conn.cursor()
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS alertas (
        id TEXT PRIMARY KEY,
        titulo TEXT,
        preco REAL,
        created_at TEXT DEFAULT (datetime('now', 'localtime'))
    )''')
    
    cursor.execute("PRAGMA table_info(alertas)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'created_at' not in columns:
        print("[DB] Coluna 'created_at' não encontrada. Adicionando coluna...")
        cursor.execute("ALTER TABLE alertas ADD COLUMN created_at TEXT DEFAULT '2026-01-01 00:00:00'")
    
    conn.commit()
    conn.close()

def ja_alertou(anuncio_id):
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM alertas WHERE id = ?", (anuncio_id,))
    res = cursor.fetchone()
    conn.close()
    return res is not None

def salvar_alerta(anuncio_id, titulo, preco):
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cursor = conn.cursor()
    agora = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("INSERT INTO alertas (id, titulo, preco, created_at) VALUES (?, ?, ?, ?)", (anuncio_id, titulo, preco, agora))
    conn.commit()
    conn.close()

def limpar_alertas_antigos():
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        cursor = conn.cursor()
        limite = datetime.now() - timedelta(days=30)
        limite_str = limite.strftime('%Y-%m-%d %H:%M:%S')
        
        cursor.execute("DELETE FROM alertas WHERE created_at < ?", (limite_str,))
        removidos = cursor.rowcount
        conn.commit()
        
        if removidos > 0:
            conn.isolation_level = None
            conn.execute("VACUUM")
            
        conn.close()
        
        if removidos > 0:
            print(f"[🧹 Limpeza] {removidos} alertas antigos removidos (>{30} dias).")
    except Exception as e:
        print(f"[❌ Erro Limpeza] Falha ao limpar banco: {e}")

# --- NOTIFICAÇÃO TELEGRAM ---
async def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem, "parse_mode": "HTML"}
    try:
        response = cffi_requests.post(url, json=payload, impersonate="chrome120")
        if response.status_code == 200:
            print(f"   [✈️] ✅ Telegram confirmou: Mensagem entregue com sucesso!")
        else:
            print(f"   [✈️] ❌ Telegram REJEITOU! Código: {response.status_code}, Motivo: {response.text}")
    except Exception as e:
        print(f"   [✈️] ❌ Erro Crítico na função enviar_telegram: {e}")

async def teste_telegram():
    print("🧪 Testando conexão inicial com o Telegram...")
    await enviar_telegram("🤖 <b>Bot Multi-Loja V6.0 online!</b>\nMonitorando KaBuM, Pichau, Terabyte e Amazon!")

TERMOS_BLOQUEADOS = [
    "pcgamer", "computador", "notebook", "cpu", "workstation", "desktop",
    "zephyrus", "laptop", "tela", "g14", "g15", "g16", "nitro", "tuf",
    "strix", "legion", "ideapad", "macbook", "intelcore", "ryzen", "ssd"
]

# --- PROCESSADOR CENTRAL DE PRODUTOS ---
async def processar_produto(id_produto, titulo, preco_float, link, config):
    try:
        if not id_produto or not titulo or preco_float <= 0:
            return False

        titulo_limpo = titulo.lower().replace(" ", "").replace("·", "")
        
        # 1. Bloqueia setups completos e laptops
        if any(termo in titulo_limpo for termo in TERMOS_BLOQUEADOS):
            return False

        # 2. Garante que o modelo buscado (ex: "3060") esteja no título
        termos_obrigatorios = config.get("termos_obrigatorios", [])
        if termos_obrigatorios and not any(termo in titulo_limpo for termo in termos_obrigatorios):
            return False

        print(f"\n-> Analisando ({config['nome']}): {titulo}")
        print(f"   [✅] PASSOU NO FILTRO! Preço: R$ {preco_float:.2f}")

        # 3. Valida contra o piso bug e envia alerta
        if 100.0 < preco_float <= config["piso_bug"]:
            # ID único composto por loja + produto para evitar colisão entre sites
            id_unico = f"{config['site']}_{id_produto}"
            if not ja_alertou(id_unico):
                msg = f"🚨 <b>ALERTA DE PREÇO: {config['nome']}</b> 🚨\n\n🖥 {titulo}\n💵 <b>R$ {preco_float:.2f}</b>\n\n🛒 Link: {link}"
                await enviar_telegram(msg)
                salvar_alerta(id_unico, titulo, preco_float)
            else:
                print(f"   [💤] Já alertado anteriormente.")
        return True
    except Exception as e:
        print(f"Erro ao processar produto individual: {e}")
        return False

# --- PARSERS DE CADA LOJA ---

async def analisar_api_kabum(dados_json, config):
    produtos = dados_json.get('data', [])
    print(f"📦 Recebidos {len(produtos)} produtos via KaBuM.")
    
    produtos_avaliados = 0
    for item in produtos:
        id_produto = str(item.get("id") or item.get("code", ""))
        atributos = item.get("attributes", {})
        titulo = atributos.get("title") or item.get("name", "")
        preco_bruto = atributos.get("price_with_discount") or item.get("price", 0)
        friendly_name = atributos.get("friendly_name") or item.get("friendlyName", "produto")
        link = f"https://www.kabum.com.br/produto/{id_produto}/{friendly_name}"
        
        if await processar_produto(id_produto, titulo, float(preco_bruto), link, config):
            produtos_avaliados += 1
            
    print(f"Processamento KaBuM concluído ({produtos_avaliados} aprovados).")

async def analisar_terabyte(html_content, config):
    soup = BeautifulSoup(html_content, 'html.parser')
    cards = soup.select('.pbox')
    print(f"📦 Recebidos {len(cards)} produtos via Terabyte.")
    
    produtos_avaliados = 0
    for card in cards:
        link_elem = card.select_one('a.pbox-title')
        preco_elem = card.select_one('.prod-pnew span') or card.select_one('.val-avista')
        
        if not link_elem or not preco_elem:
            continue
            
        titulo = link_elem.text.strip()
        link = link_elem.get('href', '')
        
        id_match = re.search(r'pbox-(\d+)', str(card)) or re.search(r'/(\d+)', link)
        id_produto = id_match.group(1) if id_match else str(hash(link))
        
        preco_texto = preco_elem.text.replace('R$', '').replace('.', '').replace(',', '.').strip()
        try:
            preco_float = float(re.sub(r'[^\d.]', '', preco_texto))
        except ValueError:
            continue
            
        if await processar_produto(id_produto, titulo, preco_float, link, config):
            produtos_avaliados += 1
            
    print(f"Processamento Terabyte concluído ({produtos_avaliados} aprovados).")

async def analisar_pichau(html_content, config):
    soup = BeautifulSoup(html_content, 'html.parser')
    script_next = soup.find('script', id='__NEXT_DATA__')
    
    produtos = []
    if script_next:
        try:
            data = json.loads(script_next.string)
            page_props = data.get('props', {}).get('pageProps', {})
            search_data = page_props.get('initialState', {}).get('search', {}) or page_props.get('data', {})
            
            if isinstance(search_data, dict):
                produtos = search_data.get('products', []) or search_data.get('items', [])
        except Exception as e:
            print(f"Aviso Pichau JSON: {e}")

    # Fallback para parsing via HTML puro caso o JSON falhe
    if not produtos:
        cards = soup.select('div[class*="product-card"], a[href*="/p/"]')
        print(f"📦 Recebidos {len(cards)} produtos via HTML da Pichau.")
        produtos_avaliados = 0
        for card in cards:
            link = card.get('href', '')
            if link and not link.startswith('http'):
                link = f"https://www.pichau.com.br{link}"
            titulo_elem = card.select_one('h2, h3, [class*="title"]')
            preco_elem = card.select_one('[class*="price"]')
            if titulo_elem and preco_elem:
                titulo = titulo_elem.text.strip()
                preco_txt = preco_elem.text.replace('R$', '').replace('.', '').replace(',', '.').strip()
                try:
                    preco_float = float(re.sub(r'[^\d.]', '', preco_txt))
                    id_prod = re.search(r'-(\d+)$', link)
                    id_produto = id_prod.group(1) if id_prod else str(hash(link))
                    if await processar_produto(id_produto, titulo, preco_float, link, config):
                        produtos_avaliados += 1
                except ValueError:
                    continue
        return

    print(f"📦 Recebidos {len(produtos)} produtos via API Pichau.")
    produtos_avaliados = 0
    for item in produtos:
        id_produto = str(item.get('id', ''))
        titulo = item.get('name', '')
        preco_float = float(item.get('price_final') or item.get('price', 0))
        slug = item.get('url_key') or item.get('slug', '')
        link = f"https://www.pichau.com.br/{slug}" if slug else config['url']
        
        if await processar_produto(id_produto, titulo, preco_float, link, config):
            produtos_avaliados += 1
            
    print(f"Processamento Pichau concluído ({produtos_avaliados} aprovados).")

async def analisar_amazon(html_content, config):
    soup = BeautifulSoup(html_content, 'html.parser')
    items = soup.select('div[data-component-type="s-search-result"]')
    print(f"📦 Recebidos {len(items)} produtos via Amazon.")
    
    produtos_avaliados = 0
    for item in items:
        id_produto = item.get('data-asin', '')
        titulo_elem = item.select_one('h2 a span') or item.select_one('h2 span')
        preco_whole = item.select_one('.a-price-whole')
        preco_fraction = item.select_one('.a-price-fraction')
        link_elem = item.select_one('h2 a')
        
        if not id_produto or not titulo_elem or not preco_whole or not link_elem:
            continue
            
        titulo = titulo_elem.text.strip()
        link = f"https://www.amazon.com.br{link_elem.get('href')}"
        
        whole_str = preco_whole.text.replace('.', '').replace(',', '').strip()
        frac_str = preco_fraction.text.strip() if preco_fraction else "00"
        
        try:
            preco_float = float(f"{whole_str}.{frac_str}")
        except ValueError:
            continue
            
        if await processar_produto(id_produto, titulo, preco_float, link, config):
            produtos_avaliados += 1
            
    print(f"Processamento Amazon concluído ({produtos_avaliados} aprovados).")

# --- GERENCIADOR DE REQUISIÇÕES HTTP ---
async def raspar_vitrine(config):
    print(f"\n🔎 Analisando ({config['site'].upper()}): {config['nome']}")
    try:
        site = config["site"]
        
        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "accept-language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            "cache-control": "max-age=0",
            "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "none" if site == "terabyte" else "cross-site",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        if site == "terabyte":
            headers["referer"] = "https://www.terabyteshop.com.br/"
        elif site == "pichau":
            headers["referer"] = "https://www.pichau.com.br/"
        elif site == "amazon":
            headers["referer"] = "https://www.amazon.com.br/"

        session = cffi_requests.Session(impersonate="chrome120")
        
        # Aquecimento de sessão para Terabyte (gera cookies para passar pelo Cloudflare)
        if site == "terabyte":
            try:
                session.get("https://www.terabyteshop.com.br/", headers=headers, timeout=15)
                await asyncio.sleep(1)
            except Exception as e:
                print(f"   [⚠️ Aquecimento Terabyte]: {e}")

        response = session.get(config["url"], headers=headers, timeout=25)
        
        if response.status_code == 200:
            if site == "kabum_api":
                await analisar_api_kabum(response.json(), config)
            elif site == "terabyte":
                await analisar_terabyte(response.text, config)
            elif site == "pichau":
                await analisar_pichau(response.text, config)
            elif site == "amazon":
                await analisar_amazon(response.text, config)
        else:
            print(f"⚠️ Status {response.status_code} recebido de {config['nome']}")
    except Exception as e:
        print(f"❌ Falha de requisição em {config['nome']}: {e}")

# --- LOOP PRINCIPAL ---
async def main():
    print("🚀 Bot V6.0 (Multi-Loja: KaBuM, Pichau, Terabyte, Amazon) Iniciado...")
    
    init_db()
    await teste_telegram()
    
    while True:
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🔄 Iniciando varredura em massa em todas as lojas...")
        
        limpar_alertas_antigos()
        
        for cat in CATEGORIAS:
            await raspar_vitrine(cat)
            await asyncio.sleep(4)  # Pausa respeitosa entre requisições
            
        print(f"\n💤 Varredura concluída. Dormindo por {INTERVALO_CHECAGEM} segundos...")
        await asyncio.sleep(INTERVALO_CHECAGEM)

if __name__ == "__main__":
    asyncio.run(main())