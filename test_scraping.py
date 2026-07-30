import os
from curl_cffi import requests as cffi_requests

SITES = {
    "terabyte": {
        "url": "https://www.terabyteshop.com.br/busca?str=rtx+5060",
        "referer": "https://www.terabyteshop.com.br/"
    },
    "pichau": {
        "url": "https://www.pichau.com.br/search?q=rtx%205060",
        "referer": "https://www.pichau.com.br/"
    },
    "amazon": {
        "url": "https://www.amazon.com.br/s?k=rtx+5060",
        "referer": "https://www.amazon.com.br/"
    }
}

async def rodar_teste():
    print("🔬 Iniciando testes de captura e diagnóstico...\n")
    
    session = cffi_requests.Session(impersonate="chrome120")
    
    for nome_site, config in SITES.items():
        print(f"📡 Testando {nome_site.upper()}...")
        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "accept-language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "same-origin",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "referer": config["referer"]
        }
        
        try:
            res = session.get(config["url"], headers=headers, timeout=20)
            status = res.status_code
            tamanho = len(res.text)
            
            nome_arquivo = f"{nome_site}_debug.html"
            with open(nome_arquivo, "w", encoding="utf-8") as f:
                f.write(res.text)
                
            print(f"    Status Code: {status}")
            print(f"    Tamanho do HTML: {tamanho} bytes")
            print(f"   💾 Salvo em: {nome_arquivo}")
            
            # Checagem preliminar de bloqueios
            html_lower = res.text.lower()
            if "cloudflare" in html_lower or "just a moment" in html_lower:
                print("   ⚠️ DETECTADO: Bloqueio do Cloudflare / Captcha!")
            elif "datadome" in html_lower or "imperva" in html_lower:
                print("   ⚠️ DETECTADO: Firewall DataDome / Imperva!")
            elif status == 200 and tamanho > 10000:
                print("   ✅ PARECE SUCESSO! HTML completo recebido.")
            else:
                print("   ⚠️ Resposta curta ou inesperada.")
                
        except Exception as e:
            print(f"   ❌ Erro ao acessar: {e}")
            
        print("-" * 50)

if __name__ == "__main__":
    import asyncio
    asyncio.run(rodar_teste())
