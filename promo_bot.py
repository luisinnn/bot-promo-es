import os
import re
import json
import sqlite3
import asyncio
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests
from datetime import datetime, timedelta

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
INTERVALO_CHECAGEM = int(os.environ.get("INTERVALO_CHECAGEM", 300))
DB_PATH = os.environ.get("DB_PATH", "/app/data/historico.db")

CATEGORIAS = [
    # --- KABUM ---
    {
        "nome": "KaBuM - RTX 5060",
        "url": "https://servicespub.prod.api.aws.grupokabum.com.br/catalog/v2/products?query=rtx%205060&page_number=1&page_size=100",
        "termos_obrigatorios": ["5060"],
        "piso_bug": 2400.00,
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

    # --- AMAZON BRASIL ---
    {
        "nome": "Amazon - RTX 5060",
        "url": "https://www.amazon.com.br/s?k=rtx+5060",
        "termos_obrigatorios": ["5060"],
        "piso_bug": 2400.00,
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
    },

    # --- PICHAU (Sujeito a bloqueio de IP de Datacenter) ---
    {
        "nome": "Pichau - RTX 5060",
        "url": "https://www.pichau.com.br/search?q=rtx%205060",
        "termos_obrigatorios": ["5060"],
        "piso_bug": 2400.00,
        "site": "pichau"
    },

    # --- TERABYTE (Sujeito a bloqueio de IP de Datacenter) ---
    {
        "nome": "Terabyte - RTX 5060",
        "url": "https://www.terabyteshop.com.br/busca?str=rtx+5060",
        "termos_obrigatorios": ["5060"],
        "piso_bug": 2400.00,
        "site": "terabyte"
    }
]

# Lista agressiva atualizada: Removemos TUF, STRIX e NITRO para não bloquear as placas!
TERMOS_BLOQUEADOS = [
    "pcgamer", "computador", "notebook", "cpu", "workstation", "desktop",
    "zephyrus", "laptop", "tela", "g14", "g15", "g16", "legion", "ideapad", 
    "macbook", "intelcore", "ryzen", "ssd"
]

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS alertas (
        id TEXT PRIMARY KEY,
        titulo TEXT,
        preco REAL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    cursor.execute("PRAGMA table_info(alertas)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'created_at' not in columns:
        cursor.execute("ALTER TABLE alertas ADD COLUMN created_at TEXT DEFAULT CURRENT_TIMESTAMP")
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
    cursor.execute("INSERT INTO alertas (id, titulo, preco) VALUES (?, ?, ?)", (anuncio_id, titulo, preco))
    conn.commit()
    conn.close()

def limpar_alertas_antigos():
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        cursor = conn.cursor()
        limite = datetime.utcnow() - timedelta(days=30)
        limite_str = limite.strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute("DELETE FROM alertas WHERE created_at < ?", (limite_str,))
        removidos = cursor.rowcount
        if removidos > 0:
            conn.execute("VACUUM")
        conn.commit()
        conn.close()
        if removidos > 0:
            print(f"[🧹 Limpeza] {removidos} alertas antigos removidos (>{30} dias).")
    except Exception as e:
        print(f"[❌ Erro Limpeza] Falha ao limpar banco: {e}")

async def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem, "parse_mode": "HTML"}
    try:
        response = cffi_requests.post(url, json=payload, impersonate="chrome120")
        if response.status_code != 200:
            print(f"   [✈️] ❌ Telegram REJEITOU! Código: {response.status_code}")
    except Exception as e:
        print(f"   [✈️] ❌ Erro Crítico na função enviar_telegram: {e}")

async def teste_telegram():
    print("🧪 Testando conexão com o Telegram...")
    await enviar_telegram("🤖 <b>Bot Multi-Loja V6.0 online!</b>\nMonitorando KaBuM e Amazon (Pichau/Terabyte ativadas em background)!")

async def processar_produto(id_produto, titulo, preco_float, link, config):
    try:
        if not id_produto or not titulo or preco_float <= 0:
            return False

        titulo_limpo = titulo.lower().replace(" ", "").replace("·", "")
        
        # 1. Filtro Anti-Lixo (PCs, Notebooks, Processadores perdidos)
        if any(termo in titulo_limpo for termo in TERMOS_BLOQUEADOS):
            return False

        # 2. Exigência do Modelo Exato no título (Impede a 3050 de aparecer na 3060)
        termos_obrigatorios = config.get("termos_obrigatorios", [])
        if termos_obrigatorios and not any(termo in titulo_limpo for termo in termos_obrigatorios):
            return False

        # 3. Validação do Bug / Desconto e Telegram
        if 100.0 < preco_float <= config["piso_bug"]:
            id_unico = f"{config['site']}_{id_produto}"
            print(f"   [✅] PASSOU NO FILTRO! -> {titulo[:45]}... | R$ {preco_float:.2f}")
            if not ja_alertou(id_unico):
                msg = f"🚨 <b>ALERTA DE PREÇO: {config['nome']}</b> 🚨\n\n🖥 {titulo}\n💵 <b>R$ {preco_float:.2f}</b>\n\n🛒 Link: {link}"
                await enviar_telegram(msg)
                salvar_alerta(id_unico, titulo, preco_float)
            else:
                print(f"   [💤] Produto já alertado anteriormente.")
        return True
    except Exception as e:
        print(f"Erro ao processar produto individual: {e}")
        return False

async def analisar_api_kabum(dados_json, config):
    produtos = dados_json.get('data', [])
    print(f"📦 Recebidos {len(produtos)} produtos via KaBuM API.")
    for item in produtos:
        id_produto = str(item.get("id") or item.get("code", ""))
        atributos = item.get("attributes", {})
        titulo = atributos.get("title") or item.get("name", "")
        preco_bruto = atributos.get("price_with_discount") or item.get("price", 0)
        friendly_name = atributos.get("friendly_name") or item.get("friendlyName", "produto")
        link = f"https://www.kabum.com.br/produto/{id_produto}/{friendly_name}"
        await processar_produto(id_produto, titulo, float(preco_bruto), link, config)

async def analisar_amazon(html_content, config):
    soup = BeautifulSoup(html_content, 'html.parser')
    items = soup.select('div[data-component-type="s-search-result"]')
    print(f"📦 Recebidos {len(items)} produtos via Amazon HTML.")
    for item in items:
        id_produto = item.get('data-asin', '')
        titulo_elem = item.select_one('h2 a span') or item.select_one('h2 span') or item.select_one('.a-text-normal')
        preco_whole = item.select_one('.a-price-whole')
        preco_fraction = item.select_one('.a-price-fraction')
        # FIX: Pega o link de qualquer lugar do card se não achar no h2
        link_elem = item.select_one('h2 a') or item.select_one('a.a-link-normal')
        
        if titulo_elem and preco_whole and link_elem and id_produto:
            titulo = titulo_elem.text.strip()
            link = f"https://www.amazon.com.br{link_elem.get('href')}"
            
            # Limpeza cirúrgica da vírgula dupla da Amazon
            whole_str = preco_whole.text.replace('.', '').replace(',', '').strip()
            frac_str = preco_fraction.text.strip() if preco_fraction else "00"
            try:
                preco_float = float(f"{whole_str}.{frac_str}")
                # Print opcional para você ver os preços que a Amazon está retornando
                # print(f"   [Amazon] {titulo[:40]}... | R$ {preco_float}")
                await processar_produto(id_produto, titulo, preco_float, link, config)
            except ValueError:
                continue

async def analisar_pichau(html_content, config):
    soup = BeautifulSoup(html_content, 'html.parser')
    script_next = soup.find('script', id='__NEXT_DATA__')
    if script_next:
        try:
            data = json.loads(script_next.string)
            page_props = data.get('props', {}).get('pageProps', {})
            produtos = page_props.get('initialState', {}).get('search', {}).get('products', [])
            if not produtos:
                produtos = page_props.get('data', {}).get('products', [])
            
            if produtos:
                print(f"📦 Recebidos {len(produtos)} produtos via Pichau JSON.")
                for item in produtos:
                    id_produto = str(item.get('id', ''))
                    titulo = item.get('name', '')
                    preco_float = float(item.get('price_final') or item.get('price', 0))
                    slug = item.get('url_key') or item.get('slug', '')
                    link = f"https://www.pichau.com.br/{slug}" if slug else config['url']
                    await processar_produto(id_produto, titulo, preco_float, link, config)
        except Exception:
            pass

async def analisar_terabyte(html_content, config):
    soup = BeautifulSoup(html_content, 'html.parser')
    cards = soup.select('.pbox')
    print(f"📦 Recebidos {len(cards)} produtos via Terabyte HTML.")
    for card in cards:
        link_elem = card.select_one('a.pbox-title')
        preco_elem = card.select_one('.prod-pnew span') or card.select_one('.val-avista')
        if link_elem and preco_elem:
            titulo = link_elem.text.strip()
            link = link_elem.get('href', '')
            id_match = re.search(r'pbox-(\d+)', str(card)) or re.search(r'/(\d+)', link)
            id_produto = id_match.group(1) if id_match else str(hash(link))
            
            preco_texto = preco_elem.text.replace('R$', '').replace('.', '').replace(',', '.').strip()
            try:
                preco_float = float(re.sub(r'[^\d.]', '', preco_texto))
                await processar_produto(id_produto, titulo, preco_float, link, config)
            except ValueError:
                continue

async def raspar_vitrine(config):
    print(f"\n🔎 Solicitando: {config['nome']}")
    try:
        site = config["site"]
        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "accept-language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            "upgrade-insecure-requests": "1",
        }

        # Cria a sessão que "engana" firewalls fingindo ser um Google Chrome real
        session = cffi_requests.Session(impersonate="chrome120")
        
        # Se for site fresco com firewall, fingimos visitar a home page antes
        if site in ["terabyte", "pichau", "amazon"]:
            base_url = "https://www." + config["url"].split("/")[2] + "/"
            headers["referer"] = base_url
            try:
                session.get(base_url, headers=headers, timeout=10)
                await asyncio.sleep(1)
            except:
                pass

        response = session.get(config["url"], headers=headers, timeout=15)
        
        if response.status_code == 200 and "just a moment" not in response.text.lower() and "cloudflare" not in response.text.lower():
            if site == "kabum_api":
                await analisar_api_kabum(response.json(), config)
            elif site == "amazon":
                await analisar_amazon(response.text, config)
            elif site == "pichau":
                await analisar_pichau(response.text, config)
            elif site == "terabyte":
                await analisar_terabyte(response.text, config)
        else:
            print(f"⚠️ Acesso bloqueado / Firewall ativado (Status: {response.status_code}). Site manteve o escudo levantado para nosso IP de Datacenter.")
            
    except Exception as e:
        print(f"❌ Falha de conexão: {e}")

async def main():
    print("🚀 Bot V6.0 Multi-Loja (Amazon Fix & Datacenter Aware) Iniciado...")
    init_db()
    await teste_telegram()
    
    while True:
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🔄 Iniciando varredura em massa...")
        limpar_alertas_antigos()
        
        for cat in CATEGORIAS:
            await raspar_vitrine(cat)
            await asyncio.sleep(4)  # Pausa respiratória entre requisições para não irritar os WAFs
            
        print(f"\n💤 Varredura concluída. Dormindo por {INTERVALO_CHECAGEM} segundos...")
        await asyncio.sleep(INTERVALO_CHECAGEM)

if __name__ == "__main__":
    asyncio.run(main())