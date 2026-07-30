import os
import sqlite3
import asyncio
from curl_cffi import requests as cffi_requests
from datetime import datetime, timedelta

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
INTERVALO_CHECAGEM = int(os.environ.get("INTERVALO_CHECAGEM", 300))
DB_PATH = os.environ.get("DB_PATH", "/app/data/historico.db")

CATEGORIAS = [
    {
        "nome": "Kabum - Placas de Vídeo RTX 5060",
        "url": "https://servicespub.prod.api.aws.grupokabum.com.br/catalog/v2/products?query=rtx%205060&page_number=1&page_size=100",
        "piso_bug": 3500.00,
        "site": "kabum_api"
    }
]

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cursor = conn.cursor()
    
    # 1. Cria a tabela (a sintaxe do DEFAULT é válida aqui na criação inicial)
    cursor.execute('''CREATE TABLE IF NOT EXISTS alertas (
        id TEXT PRIMARY KEY,
        titulo TEXT,
        preco REAL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # 2. Migração: Adiciona a coluna se não existir.
    # O SQLite bloqueia funções dinâmicas (como datetime('now')) no DEFAULT do ALTER TABLE.
    # O truque é usar CURRENT_TIMESTAMP, que é uma constante do SQLite.
    cursor.execute("PRAGMA table_info(alertas)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'created_at' not in columns:
        print("[DB] Coluna 'created_at' não encontrada. Adicionando via ALTER TABLE...")
        # Correção Crítica Aqui:
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
    # Apenas enviamos os dados antigos. A coluna created_at será preenchida 
    # automaticamente pelo banco graças ao 'DEFAULT CURRENT_TIMESTAMP'.
    cursor.execute("INSERT INTO alertas (id, titulo, preco) VALUES (?, ?, ?)", (anuncio_id, titulo, preco))
    conn.commit()
    conn.close()

def limpar_alertas_antigos():
    """Remove alertas com mais de 30 dias para otimizar disco."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        cursor = conn.cursor()
        
        # Como o CURRENT_TIMESTAMP do SQLite grava em UTC (GTM+0), 
        # a limpeza também precisa calcular a data em UTC.
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
        else:
            print("[🧹 Limpeza] Nenhum alerta antigo para remover.")
            
    except Exception as e:
        print(f"[❌ Erro Limpeza] Falha ao limpar banco: {e}")

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
    await enviar_telegram("🤖 <b>Bot operando!</b>\nSua EC2 está turbinada e o bot está online!")

async def analisar_api_kabum(dados_json, config):
    try:
        produtos = dados_json.get('data', [])
        print(f"📦 Recebidos {len(produtos)} produtos via API da Kabum.")
        
        produtos_processados = 0
        for item in produtos:
            try:
                id_produto = str(item.get("id") or item.get("code", ""))
                atributos = item.get("attributes", {})
                titulo = atributos.get("title") or item.get("name", "")
                
                if not id_produto or not titulo:
                    continue
                
                preco_bruto = atributos.get("price_with_discount") or item.get("price", 0)
                preco_float = float(preco_bruto)
                if preco_float == 0:
                    continue
                
                friendly_name = atributos.get("friendly_name") or item.get("friendlyName", "produto")
                link = f"https://www.kabum.com.br/produto/{id_produto}/{friendly_name}"
                
                titulo_limpo = titulo.lower().replace(" ", "")
                
                if "rtx" not in titulo_limpo or "5060" not in titulo_limpo:
                    continue
                    
                if any(x in titulo_limpo for x in ["pcgamer", "computador", "notebook", "cpu", "workstation", "desktop"]):
                     continue
                
                print(f"\n-> Analisando: {titulo}")
                print(f"   [✅] PASSOU NO FILTRO! Preço: R$ {preco_float}")
                produtos_processados += 1
                
                if 100.0 < preco_float <= config["piso_bug"]:
                    if not ja_alertou(id_produto):
                        msg = f"🚨 <b>ALERTA DE PREÇO: {config['nome']}</b> 🚨\n\n🖥 {titulo}\n💵 <b>R$ {preco_float:.2f}</b>\n\n🛒 Link: {link}"
                        await enviar_telegram(msg)
                        salvar_alerta(id_produto, titulo, preco_float)
                    else:
                        print(f"   [💤] Já alertado anteriormente.")
                        
            except Exception as item_erro:
                print(f"Erro num item específico: {item_erro}")
                continue
                
        print(f"\nProcessamento concluído. {produtos_processados} produtos avaliados com sucesso.")
        
    except Exception as e:
        print(f"Erro ao ler JSON: {e}")

async def raspar_vitrine(config):
    print(f"🔎 Analisando API: {config['nome']}")
    try:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.kabum.com.br",
            "Referer": "https://www.kabum.com.br/"
        }
        
        response = cffi_requests.get(config["url"], headers=headers, impersonate="chrome120", timeout=15)
        
        if response.status_code == 200:
            if config["site"] == "kabum_api":
                await analisar_api_kabum(response.json(), config)
        else:
            print(f"⚠️ Erro {response.status_code} na API da Kabum.")
    except Exception as e:
        print(f"❌ Falha de requisição: {e}")

async def main():
    print("🚀 Bot V5.3 (Com Auto-Limpeza de DB Corrigida) Iniciado...")
    
    await teste_telegram()
    
    # ⚠️ SE O BOT FICAR REINICIANDO EM LOOP AQUI, O ERRO É NO DB.
    # Com a correção aplicada acima, isso não deve mais acontecer.
    init_db()
    
    while True:
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Iniciando varredura em massa...")
        
        limpar_alertas_antigos()
        
        for cat in CATEGORIAS:
            await raspar_vitrine(cat)
            await asyncio.sleep(5)
            
        print(f"💤 Varredura concluída. Dormindo por {INTERVALO_CHECAGEM} segundos...")
        await asyncio.sleep(INTERVALO_CHECAGEM)

if __name__ == "__main__":
    asyncio.run(main())