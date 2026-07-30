import re
import json
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests

SITES_TESTE = {
    "terabyte": {
        "nome": "Terabyte - RTX 5060",
        "url": "https://www.terabyteshop.com.br/busca?str=rtx+5060",
        "referer": "https://www.terabyteshop.com.br/"
    },
    "pichau": {
        "nome": "Pichau - RTX 5060",
        "url": "https://www.pichau.com.br/search?q=rtx%205060",
        "referer": "https://www.pichau.com.br/"
    },
    "amazon": {
        "nome": "Amazon - RTX 5060",
        "url": "https://www.amazon.com.br/s?k=rtx+5060",
        "referer": "https://www.amazon.com.br/"
    }
}

IMPERSONATES = ["chrome120", "chrome124", "safari17_0", "edge101"]

def testar_parser_terabyte(html):
    soup = BeautifulSoup(html, 'html.parser')
    cards = soup.select('.pbox')
    print(f"      [Terabyte Parser] Encontrados {len(cards)} cards")
    for card in cards[:3]:
        link_elem = card.select_one('a.pbox-title')
        preco_elem = card.select_one('.prod-pnew span') or card.select_one('.val-avista')
        if link_elem and preco_elem:
            print(f"         👉 {link_elem.text.strip()[:50]}... | {preco_elem.text.strip()}")

def testar_parser_pichau(html):
    soup = BeautifulSoup(html, 'html.parser')
    script_next = soup.find('script', id='__NEXT_DATA__')
    if script_next:
        try:
            data = json.loads(script_next.string)
            # Busca do NextJS da Pichau varia, tentando vários caminhos
            page_props = data.get('props', {}).get('pageProps', {})
            prods = page_props.get('initialState', {}).get('search', {}).get('products', [])
            if not prods:
                prods = page_props.get('data', {}).get('products', [])
            
            print(f"      [Pichau Parser] Encontrados {len(prods)} produtos no JSON")
            for p in prods[:3]:
                preco = p.get('price_final') or p.get('price', 0)
                print(f"         👉 {p.get('name', '')[:50]}... | R$ {preco}")
            if prods:
                return
        except Exception:
            pass
            
    cards = soup.select('div[class*="product-card"], a[href*="/p/"]')
    print(f"      [Pichau Parser] Fallback HTML encontrou {len(cards)} elementos")

def testar_parser_amazon(html):
    soup = BeautifulSoup(html, 'html.parser')
    items = soup.select('div[data-component-type="s-search-result"]')
    print(f"      [Amazon Parser] Encontrados {len(items)} cards")
    for item in items[:5]:
        titulo_elem = item.select_one('h2 a span') or item.select_one('h2 span')
        preco_whole = item.select_one('.a-price-whole')
        preco_frac = item.select_one('.a-price-fraction')
        if titulo_elem and preco_whole:
            # FIX: Corrigindo a vírgula dupla da Amazon
            whole_str = preco_whole.text.replace('.', '').replace(',', '').strip()
            frac_str = preco_frac.text.strip() if preco_frac else "00"
            print(f"         👉 {titulo_elem.text.strip()[:50]}... | R$ {whole_str},{frac_str}")

async def rodar_diagnostico_completo():
    print("🔬 INICIANDO TESTE DE IMPERSONATE MULTI-LOJA...\n" + "="*60)
    
    headers_base = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "accept-language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "upgrade-insecure-requests": "1"
    }

    for chave, config in SITES_TESTE.items():
        print(f"\n📡 TESTANDO: {config['nome'].upper()}")
        sucesso = False
        
        for browser in IMPERSONATES:
            print(f"   ⏳ Tentando com perfil: {browser} ...")
            session = cffi_requests.Session(impersonate=browser)
            headers = headers_base.copy()
            headers["referer"] = config["referer"]
            
            try:
                # Na Terabyte, tenta acessar a home rápido para ganhar o cookie
                if chave == "terabyte":
                    try:
                        session.get("https://www.terabyteshop.com.br/", headers=headers, timeout=10)
                    except:
                        pass

                res = session.get(config["url"], headers=headers, timeout=15)
                
                # Cloudflare costuma retornar 403, ou 200 com um HTML dizendo "Just a moment"
                if res.status_code == 200 and "cloudflare" not in res.text.lower() and "just a moment" not in res.text.lower():
                    print(f"   ✅ PASSOU! (Status: 200 | Tamanho: {len(res.text)} bytes)")
                    
                    if chave == "terabyte":
                        testar_parser_terabyte(res.text)
                    elif chave == "pichau":
                        testar_parser_pichau(res.text)
                    elif chave == "amazon":
                        testar_parser_amazon(res.text)
                    
                    sucesso = True
                    break  # Se deu certo, vai pra próxima loja!
                else:
                    print(f"   ❌ Falhou. Status: {res.status_code} (Pode ser CAPTCHA)")
            except Exception as e:
                print(f"   💥 Erro de conexão: {e}")
        
        if not sucesso:
            print(f"\n   ⚠️ {config['nome'].upper()} bloqueou TODOS os perfis testados.")
            
    print("\n" + "="*60 + "\n✅ Diagnóstico concluído!")

if __name__ == "__main__":
    import asyncio
    asyncio.run(rodar_diagnostico_completo())
