import os
import re
import json
import html
import sqlite3
import asyncio
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests
from datetime import datetime, timedelta

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
INTERVALO_CHECAGEM = int(os.environ.get("INTERVALO_CHECAGEM", 300))
DB_PATH = os.environ.get("DB_PATH", "/app/data/historico.db")

FATOR_MEDIA = float(os.environ.get("FATOR_MEDIA", 0.85))
DIAS_HISTORICO = int(os.environ.get("DIAS_HISTORICO", 30))
MIN_AMOSTRAS = int(os.environ.get("MIN_AMOSTRAS", 3))
MIN_PRODUTOS_CATEGORIA = int(os.environ.get("MIN_PRODUTOS_CATEGORIA", 5))
QUEDA_PARA_REALERTAR = float(os.environ.get("QUEDA_PARA_REALERTAR", 0.05))
FATOR_OUTLIER = float(os.environ.get("FATOR_OUTLIER", 0.75))
AMAZON_TAG = os.environ.get("AMAZON_TAG", "").strip()


CATEGORIAS_PATH = os.environ.get("CATEGORIAS_PATH", "/app/categorias.json")

CATEGORIAS_PADRAO = [
    # --- KABUM ---
    {
        "nome": "KaBuM - RTX 5060",
        "url": "https://servicespub.prod.api.aws.grupokabum.com.br/catalog/v2/products?query=rtx%205060&page_number=1&page_size=100",
        "termos_obrigatorios": ["rtx5060"],
        "piso_bug": 2400.00,
        "site": "kabum_api"
    },
    {
        "nome": "KaBuM - RTX 3060",
        "url": "https://servicespub.prod.api.aws.grupokabum.com.br/catalog/v2/products?query=rtx%203060&page_number=1&page_size=100",
        "termos_obrigatorios": ["rtx3060"],
        "piso_bug": 2200.00,
        "site": "kabum_api"
    },
    {
        "nome": "KaBuM - RX 7600 / RX 6600",
        "url": "https://servicespub.prod.api.aws.grupokabum.com.br/catalog/v2/products?query=rx%206600&page_number=1&page_size=100",
        "termos_obrigatorios": ["rx6600", "rx7600"],
        "piso_bug": 1500.00,
        "site": "kabum_api"
    },

    # --- AMAZON BRASIL ---
    {
        "nome": "Amazon - RTX 5060",
        "url": "https://www.amazon.com.br/s?k=rtx+5060",
        "termos_obrigatorios": ["rtx5060"],
        "piso_bug": 2400.00,
        "site": "amazon"
    },
    {
        "nome": "Amazon - RTX 3060",
        "url": "https://www.amazon.com.br/s?k=rtx+3060",
        "termos_obrigatorios": ["rtx3060"],
        "piso_bug": 2200.00,
        "site": "amazon"
    },
    {
        "nome": "Amazon - RX 6600 / RX 7600",
        "url": "https://www.amazon.com.br/s?k=rx+6600",
        "termos_obrigatorios": ["rx6600", "rx7600"],
        "piso_bug": 1500.00,
        "site": "amazon"
    },

    # --- PICHAU (Sujeito a bloqueio de IP de Datacenter) ---
    {
        "nome": "Pichau - RTX 5060",
        "url": "https://www.pichau.com.br/search?q=rtx%205060",
        "termos_obrigatorios": ["rtx5060"],
        "piso_bug": 2400.00,
        "site": "pichau"
    },

    # --- TERABYTE (Sujeito a bloqueio de IP de Datacenter) ---
    {
        "nome": "Terabyte - RTX 5060",
        "url": "https://www.terabyteshop.com.br/busca?str=rtx+5060",
        "termos_obrigatorios": ["rtx5060"],
        "piso_bug": 2400.00,
        "site": "terabyte"
    }
]

def carregar_categorias():
    for caminho in [CATEGORIAS_PATH, "categorias.json"]:
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                dados = json.load(f)
            if isinstance(dados, list) and dados:
                print(f"📂 Categorias carregadas de {caminho} ({len(dados)} categorias).")
                return dados
        except Exception:
            continue
    print("[⚠️] categorias.json não encontrado; usando categorias padrão.")
    return CATEGORIAS_PADRAO

CATEGORIAS = carregar_categorias()

# Lista agressiva: bloqueia PCs completos, notebooks e acessórios (não blocos de hardware puro)
TERMOS_BLOQUEADOS = [
    "pcgamer", "computador", "notebook", "workstation", "desktop",
    "zephyrus", "laptop", "tela", "g14", "g15", "g16", "legion", "ideapad", 
    "macbook",
    # Acessórios que aparecem nas buscas e não são peças de hardware
    "ventilador", "cabo", "extens", "riser", "backplate", "suporte",
    "watercooler", "waterblock", "bracket", "adaptador",
    # Marcas genéricas/off-brand da Amazon (vendedores não-confiáveis)
    "generic"
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
    colunas = cursor.fetchall()
    nomes = [row[1] for row in colunas]
    if 'created_at' not in nomes:
        cursor.execute("ALTER TABLE alertas ADD COLUMN created_at TEXT DEFAULT CURRENT_TIMESTAMP")
    else:
        default_created = next((row[4] for row in colunas if row[1] == 'created_at'), None)
        if default_created is not None and str(default_created).upper() != "CURRENT_TIMESTAMP":
            cursor.execute("BEGIN")
            cursor.execute('''CREATE TABLE alertas_novo (
                id TEXT PRIMARY KEY,
                titulo TEXT,
                preco REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )''')
            cursor.execute("INSERT INTO alertas_novo (id, titulo, preco, created_at) SELECT id, titulo, preco, created_at FROM alertas")
            cursor.execute("DROP TABLE alertas")
            cursor.execute("ALTER TABLE alertas_novo RENAME TO alertas")
            cursor.execute("COMMIT")
    cursor.execute('''CREATE TABLE IF NOT EXISTS precos (
        id TEXT,
        titulo TEXT,
        preco REAL,
        coletado_em TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_precos_id_tempo ON precos(id, coletado_em)")
    conn.commit()
    conn.close()

def ultimo_preco_alertado(anuncio_id):
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute("SELECT preco FROM alertas WHERE id = ? ORDER BY rowid DESC LIMIT 1", (anuncio_id,))
    res = cursor.fetchone()
    conn.close()
    return res[0] if res else None

def salvar_alerta(anuncio_id, titulo, preco):
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute("UPDATE alertas SET titulo = ?, preco = ? WHERE id = ?", (titulo, preco, anuncio_id))
    if cursor.rowcount == 0:
        cursor.execute("INSERT INTO alertas (id, titulo, preco) VALUES (?, ?, ?)", (anuncio_id, titulo, preco))
    conn.commit()
    conn.close()

def registrar_preco(id_unico, titulo, preco):
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute("SELECT preco FROM precos WHERE id = ? ORDER BY rowid DESC LIMIT 1", (id_unico,))
    ultimo = cursor.fetchone()
    if ultimo is None or ultimo[0] != preco:
        cursor.execute("INSERT INTO precos (id, titulo, preco) VALUES (?, ?, ?)", (id_unico, titulo, preco))
        conn.commit()
    conn.close()

def historico_precos(id_unico, dias=None):
    dias = dias or DIAS_HISTORICO
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cursor = conn.cursor()
    limite = (datetime.utcnow() - timedelta(days=dias)).strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("SELECT preco FROM precos WHERE id = ? AND coletado_em >= ?", (id_unico, limite))
    precos = [row[0] for row in cursor.fetchall()]
    conn.close()
    return precos

def limpar_alertas_antigos():
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        cursor = conn.cursor()
        limite = datetime.utcnow() - timedelta(days=30)
        limite_str = limite.strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute("DELETE FROM alertas WHERE created_at < ?", (limite_str,))
        removidos = cursor.rowcount
        conn.commit()
        if removidos > 0:
            conn.execute("VACUUM")
            print(f"[🧹 Limpeza] {removidos} alertas antigos removidos (>{30} dias).")
    except Exception as e:
        print(f"[❌ Erro Limpeza] Falha ao limpar banco: {e}")
    finally:
        if conn:
            conn.close()

def limpar_precos_antigos():
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        cursor = conn.cursor()
        limite = datetime.utcnow() - timedelta(days=90)
        limite_str = limite.strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute("DELETE FROM precos WHERE coletado_em < ?", (limite_str,))
        removidos = cursor.rowcount
        conn.commit()
        if removidos > 0:
            print(f"[🧹 Limpeza] {removidos} registros de preco antigos removidos (>90 dias).")
    except Exception as e:
        print(f"[❌ Erro Limpeza] Falha ao limpar historico de precos: {e}")
    finally:
        if conn:
            conn.close()

def percentil(valores, p):
    if not valores:
        return None
    ordenados = sorted(valores)
    k = (len(ordenados) - 1) * p
    f = int(k)
    c = f + 1
    if c >= len(ordenados):
        return ordenados[-1]
    return ordenados[f] + (ordenados[c] - ordenados[f]) * (k - f)

def titulo_aceitavel(titulo, config):
    titulo_limpo = titulo.lower().replace(" ", "").replace("·", "")
    if any(termo in titulo_limpo for termo in TERMOS_BLOQUEADOS):
        return False
    termos_obrigatorios = config.get("termos_obrigatorios", [])
    if termos_obrigatorios and not any(termo in titulo_limpo for termo in termos_obrigatorios):
        return False
    return True

def avaliar_preco_dinamico(id_unico, preco, precos_categoria):
    historico = historico_precos(id_unico)
    if len(historico) >= MIN_AMOSTRAS:
        media = sum(historico) / len(historico)
        minimo = min(historico)
        p25 = percentil(historico, 0.25)
        if preco < minimo:
            return True, "🔥 Novo menor preço!"
        if preco <= media * FATOR_MEDIA:
            pct = (1 - preco / media) * 100
            return True, f"📉 {pct:.0f}% abaixo da média"
        if preco <= p25:
            return True, "📉 Preço abaixo do percentil 25 do histórico"
        return False, None
    if precos_categoria and len(precos_categoria) >= MIN_PRODUTOS_CATEGORIA:
        mediana_cat = percentil(precos_categoria, 0.5)
        if mediana_cat and preco <= mediana_cat * FATOR_OUTLIER:
            pct = (1 - preco / mediana_cat) * 100
            return True, f"⚡ Outlier barato da categoria ({pct:.0f}% abaixo da mediana)"
    return False, None

def verificar_preco_baixo(id_unico, preco, precos_categoria, config):
    eh_baixo, motivo = avaliar_preco_dinamico(id_unico, preco, precos_categoria)
    if eh_baixo:
        return True, motivo
    piso = config.get("piso_bug")
    if piso is not None and 100.0 < preco <= piso:
        return True, "🛟 Trava de segurança (piso manual)"
    return False, None

def contexto_historico(id_unico):
    historico = historico_precos(id_unico)
    if len(historico) < MIN_AMOSTRAS:
        return None
    minimo = min(historico)
    media = sum(historico) / len(historico)
    return f"📈 Menor em {DIAS_HISTORICO}d: R$ {minimo:.2f} | Média: R$ {media:.2f}"

def montar_link_afiliado(site, link):
    if site == "amazon" and AMAZON_TAG:
        sep = "&" if "?" in link else "?"
        return f"{link}{sep}tag={AMAZON_TAG}"
    return link

def montar_mensagem(config, titulo, preco, link, motivo, id_unico, preco_anterior=None):
    if preco_anterior is not None:
        cabecalho = f"🚨 <b>PREÇO CAIU AINDA MAIS: {config['nome']}</b> 🚨"
    else:
        cabecalho = f"🚨 <b>ALERTA DE PREÇO: {config['nome']}</b> 🚨"
    linhas = [cabecalho, "", motivo]
    contexto = contexto_historico(id_unico)
    if contexto:
        linhas.append(contexto)
    linhas.append("")
    linhas.append(f"🖥 {html.escape(titulo)}")
    preco_linha = f"💵 <b>R$ {preco:.2f}</b>"
    if preco_anterior is not None:
        preco_linha += f" (antes R$ {preco_anterior:.2f})"
    linhas.append(preco_linha)
    linhas.append("")
    linhas.append(f"🛒 <a href=\"{montar_link_afiliado(config['site'], link)}\">Comprar</a>")
    return "\n".join(linhas)

async def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem, "parse_mode": "HTML"}
    try:
        response = cffi_requests.post(url, json=payload, impersonate="chrome120")
        if response.status_code != 200:
            try:
                descricao = response.json().get("description", "").lower()
            except Exception:
                descricao = ""
            if "parse" in descricao:
                print("   [✈️] ⚠️ Erro de parsing! Reenviando sem formatação HTML...")
                payload.pop("parse_mode")
                response = cffi_requests.post(url, json=payload, impersonate="chrome120")
            if response.status_code != 200:
                print(f"   [✈️] ❌ Telegram REJEITOU! Código: {response.status_code}")
    except Exception as e:
        print(f"   [✈️] ❌ Erro Crítico na função enviar_telegram: {e}")

async def teste_telegram():
    print("🧪 Testando conexão com o Telegram...")
    await enviar_telegram("🤖 <b>Bot Multi-Loja V6.0 online!</b>\nMonitorando KaBuM e Amazon (Pichau/Terabyte ativadas em background)!")

async def processar_produto(id_produto, titulo, preco_float, link, config, precos_categoria=None):
    try:
        if not id_produto or not titulo or preco_float <= 0:
            return False

        # 1+2. Filtros de título (Anti-Lixo, acessórios e modelo exato)
        if not titulo_aceitavel(titulo, config):
            return False

        id_unico = f"{config['site']}_{id_produto}"
        eh_baixo, motivo = verificar_preco_baixo(id_unico, preco_float, precos_categoria, config)

        # 3. Registra o preço no histórico (apenas quando muda) para alimentar as regras
        registrar_preco(id_unico, titulo, preco_float)

        if eh_baixo:
            print(f"   [✅] PASSOU NO FILTRO! -> {titulo[:45]}... | R$ {preco_float:.2f} | {motivo}")
            ultimo_alerta = ultimo_preco_alertado(id_unico)
            if ultimo_alerta is None:
                await enviar_telegram(montar_mensagem(config, titulo, preco_float, link, motivo, id_unico))
                salvar_alerta(id_unico, titulo, preco_float)
            elif preco_float <= ultimo_alerta * (1 - QUEDA_PARA_REALERTAR):
                await enviar_telegram(montar_mensagem(config, titulo, preco_float, link, motivo, id_unico, preco_anterior=ultimo_alerta))
                salvar_alerta(id_unico, titulo, preco_float)
            else:
                print(f"   [💤] Já alertado; queda insuficiente para re-alertar.")
        return True
    except Exception as e:
        print(f"Erro ao processar produto individual: {e}")
        return False

async def analisar_api_kabum(dados_json, config):
    produtos = dados_json.get('data', [])
    print(f"📦 Recebidos {len(produtos)} produtos via KaBuM API.")
    resultado = []
    for item in produtos:
        id_produto = str(item.get("id") or item.get("code", ""))
        atributos = item.get("attributes", {})
        titulo = atributos.get("title") or item.get("name", "")
        preco_bruto = atributos.get("price_with_discount") or item.get("price", 0)
        friendly_name = atributos.get("friendly_name") or item.get("friendlyName", "produto")
        link = f"https://www.kabum.com.br/produto/{id_produto}/{friendly_name}"
        try:
            resultado.append((id_produto, titulo, float(preco_bruto), link))
        except ValueError:
            continue
    return resultado

async def analisar_amazon(html_content, config):
    soup = BeautifulSoup(html_content, 'html.parser')
    items = soup.select('div[data-component-type="s-search-result"]')
    print(f"📦 Recebidos {len(items)} produtos via Amazon HTML.")
    resultado = []
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
                resultado.append((id_produto, titulo, preco_float, link))
            except ValueError:
                continue
    return resultado

async def analisar_pichau(html_content, config):
    soup = BeautifulSoup(html_content, 'html.parser')
    resultado = []
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
                    resultado.append((id_produto, titulo, preco_float, link))
        except Exception:
            pass
    return resultado

async def analisar_terabyte(html_content, config):
    soup = BeautifulSoup(html_content, 'html.parser')
    cards = soup.select('div.product-item__box')
    print(f"📦 Recebidos {len(cards)} produtos via Terabyte (Playwright).")
    resultado = []
    for card in cards:
        link_elem = card.select_one('a[href]')
        nome_elem = card.select_one('.product-item__name')
        preco_elem = card.select_one('.product-item__new-price')
        if not (link_elem and nome_elem and preco_elem):
            continue
        titulo = nome_elem.text.strip()
        link = link_elem.get('href', '')
        if link and not link.startswith("http"):
            link = "https://www.terabyteshop.com.br" + link
        id_match = re.search(r'/produto/(\d+)', link)
        id_produto = id_match.group(1) if id_match else str(hash(link))

        preco_texto = preco_elem.get_text(" ", strip=True).replace('R$', '').replace('.', '').replace(',', '.').strip()
        try:
            preco_float = float(re.sub(r'[^\d.]', '', preco_texto))
            resultado.append((id_produto, titulo, preco_float, link))
        except ValueError:
            continue
    return resultado

async def obter_html_playwright(url, timeout=45000):
    try:
        from playwright.async_api import async_playwright
    except Exception as e:
        print(f"   [🌐] ❌ Playwright não instalado: {e}")
        return None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                channel="chromium-headless-shell",
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                locale="pt-BR",
            )
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
                try:
                    await page.wait_for_selector("div.product-item__box", timeout=30000)
                except Exception:
                    pass
                await page.wait_for_timeout(2000)
                return await page.content()
            finally:
                await context.close()
                await browser.close()
    except Exception as e:
        print(f"   [🌐] ❌ Erro no Playwright: {e}")
        return None

async def raspar_vitrine(config):
    print(f"\n🔎 Solicitando: {config['nome']}")
    try:
        site = config["site"]

        # Terabyte passa no Cloudflare apenas com navegador real (Playwright)
        if site == "terabyte":
            html = await obter_html_playwright(config["url"])
            produtos = await analisar_terabyte(html, config) if html else []
        else:
            headers = {
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "accept-language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                "upgrade-insecure-requests": "1",
            }

            # Cria a sessão que "engana" firewalls fingindo ser um Google Chrome real
            session = cffi_requests.Session(impersonate="chrome120")
            
            # Se for site fresco com firewall, fingimos visitar a home page antes
            if site in ["pichau", "amazon"]:
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
                    produtos = await analisar_api_kabum(response.json(), config)
                elif site == "amazon":
                    produtos = await analisar_amazon(response.text, config)
                elif site == "pichau":
                    produtos = await analisar_pichau(response.text, config)
                else:
                    produtos = []
            else:
                print(f"⚠️ Acesso bloqueado / Firewall ativado (Status: {response.status_code}). Site manteve o escudo levantado para nosso IP de Datacenter.")
                produtos = []

        # Regra B (fase fria) considera apenas produtos que passam nos filtros de título
        produtos_filtrados = [p for p in produtos if p[0] and p[1] and p[2] > 0 and titulo_aceitavel(p[1], config)]
        precos_categoria = [p[2] for p in produtos_filtrados]
        for id_produto, titulo, preco, link in produtos_filtrados:
            await processar_produto(id_produto, titulo, preco, link, config, precos_categoria)
            
    except Exception as e:
        print(f"❌ Falha de conexão: {e}")

async def main():
    print("🚀 Bot V6.0 Multi-Loja (Amazon Fix & Datacenter Aware) Iniciado...")
    init_db()
    await teste_telegram()
    
    while True:
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🔄 Iniciando varredura em massa...")
        limpar_alertas_antigos()
        limpar_precos_antigos()
        
        for cat in CATEGORIAS:
            await raspar_vitrine(cat)
            await asyncio.sleep(4)  # Pausa respiratória entre requisições para não irritar os WAFs
            
        print(f"\n💤 Varredura concluída. Dormindo por {INTERVALO_CHECAGEM} segundos...")
        await asyncio.sleep(INTERVALO_CHECAGEM)

if __name__ == "__main__":
    asyncio.run(main())