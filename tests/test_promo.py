import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import promo_bot

promo_bot.DB_PATH = os.path.join(tempfile.gettempdir(), "teste_promo.db")
if os.path.exists(promo_bot.DB_PATH):
    os.remove(promo_bot.DB_PATH)

captured = []
real_enviar = promo_bot.enviar_telegram


async def fake_enviar(mensagem):
    captured.append(mensagem)
    return None


class FakeResp:
    def __init__(self, code, desc=None):
        self.status_code = code
        self._desc = desc

    def json(self):
        if self._desc is None:
            raise ValueError("no json")
        return {"description": self._desc}


def test_estatisticas():
    assert promo_bot.percentil([1, 2, 3, 4], 0.25) == 1.75
    assert promo_bot.percentil([1, 2, 3, 4], 0.5) == 2.5
    assert promo_bot.percentil([1, 2, 3, 4], 1.0) == 4
    assert promo_bot.percentil([], 0.5) is None
    print("OK 1: funcao percentil")


def test_regra_b_outlier_categoria():
    precos_categoria = [2000, 2100, 2200, 2300, 2400, 1500]
    eh, motivo = promo_bot.avaliar_preco_dinamico("site_outlier", 1500, precos_categoria)
    assert eh and "Outlier" in motivo, f"esperado outlier, veio: {motivo}"
    eh, _ = promo_bot.avaliar_preco_dinamico("site_outlier", 2300, precos_categoria)
    assert not eh
    eh, _ = promo_bot.avaliar_preco_dinamico("site_outlier", 1900, precos_categoria)
    assert not eh, "preco abaixo do q25 mas nao do fator estrito nao deveria alertar"
    print("OK 2: regra B estrita (outlier so quando >=25% abaixo da mediana)")


def test_titulo_filtros():
    config_5060 = {"termos_obrigatorios": ["rtx5060"]}
    config_rx = {"termos_obrigatorios": ["rx6600", "rx7600"]}
    assert not promo_bot.titulo_aceitavel("Cabo de extensão PCIe X16 RTX 5060", config_5060)
    assert not promo_bot.titulo_aceitavel("Placa gráfica de ventilador VGA RTX 3060", config_5060)
    assert not promo_bot.titulo_aceitavel("Geforce 6600LE PCI Express VGA 256MB", config_rx)
    assert promo_bot.titulo_aceitavel("Placa de Vídeo MSI RTX 5060 Ventus 2X OC", config_5060)
    assert promo_bot.titulo_aceitavel("Placa de Vídeo ASRock RX 6600 CLD 8G", config_rx)
    assert not promo_bot.titulo_aceitavel("PC Gamer RTX 5060 Completo", config_5060)
    print("OK 3: filtros de titulo (acessorios e modelo exato)")


def test_regra_a_historico():
    id_u = "site_hist"
    for p in [2000, 1800, 2100]:
        promo_bot.registrar_preco(id_u, "produto", p)
    eh, motivo = promo_bot.avaliar_preco_dinamico(id_u, 1650, None)
    assert eh and "menor preço" in motivo, f"esperado novo menor preço, veio: {motivo}"
    eh, motivo = promo_bot.avaliar_preco_dinamico(id_u, 1850, None)
    assert eh and "percentil" in motivo, f"esperado percentil 25, veio: {motivo}"
    eh, _ = promo_bot.avaliar_preco_dinamico(id_u, 2050, None)
    assert not eh
    print("OK 4: regra A (historico: novo minimo / % da media / p25)")


def test_fallback_piso():
    eh, motivo = promo_bot.verificar_preco_baixo(
        "site_frio", 1500.0, None, {"piso_bug": 2400.0}
    )
    assert eh and "piso" in motivo
    eh, _ = promo_bot.verificar_preco_baixo(
        "site_frio", 2500.0, None, {"piso_bug": 2400.0}
    )
    assert not eh
    print("OK 5: fallback piso manual como trava")


async def test_mensagem_e_realerta():
    config = {
        "nome": "Teste - RTX 5060",
        "piso_bug": 99999.0,
        "termos_obrigatorios": ["5060"],
        "site": "teste",
    }
    titulo = 'RTX 5060 <Gigabyte> & "Windforce" com \'aspas\''
    link = "https://exemplo.com.br/dp/ABC?psc=1&pd_rd_w=x&pd_rd_r=y"

    promo_bot.enviar_telegram = fake_enviar
    await promo_bot.processar_produto("rea", titulo, 2000.0, link, config)
    msg = captured[-1]
    assert "&lt;Gigabyte&gt;" in msg and "&amp;" in msg and "&quot;" in msg
    assert "<Gigabyte>" not in msg
    assert f'<a href="{link}">Comprar</a>' in msg
    assert "Trava" in msg
    print("OK 6: mensagem com escape, ancora e motivo")

    await promo_bot.processar_produto("rea", titulo, 1900.0, link, config)
    assert len(captured) == 2, "esperado re-alerta por queda de 5%"
    assert "PREÇO CAIU" in captured[-1], "mensagem de queda esperada"
    assert "antes R$ 2000.00" in captured[-1]

    await promo_bot.processar_produto("rea", titulo, 1900.0, link, config)
    assert len(captured) == 2, "nao deveria re-alertar sem queda relevante"
    print("OK 7: re-alerta apenas em queda >= 5%")


async def test_fallback_parse():
    calls = []
    promo_bot.enviar_telegram = real_enviar

    def fake_post(url, json, impersonate=None):
        calls.append(dict(json))
        if len(calls) == 1:
            return FakeResp(400, "Bad Request: can't parse entities")
        return FakeResp(200)

    promo_bot.cffi_requests.post = fake_post
    await promo_bot.enviar_telegram("mensagem teste")
    assert len(calls) == 2, "fallback nao chamado"
    assert calls[0]["parse_mode"] == "HTML"
    assert "parse_mode" not in calls[1], "segundo envio ainda tem parse_mode"

    calls.clear()

    def fake_post2(url, json, impersonate=None):
        calls.append(dict(json))
        return FakeResp(429, "Too Many Requests: retry after 5")

    promo_bot.cffi_requests.post = fake_post2
    await promo_bot.enviar_telegram("outra msg")
    assert len(calls) == 1, "deveria reenviar somente em erro de parse"
    print("OK 8: fallback de parse no enviar_telegram")


async def test_analisar_terabyte():
    html = """
    <div class="product-item__box">
      <a href="/produto/39095/placa-de-video-msi-rtx-5060">
        <div class="product-item__name">Placa de Vídeo MSI NVIDIA GeForce RTX 5060 Ventus 2X OC</div>
        <div class="product-item__new-price">R$ 3.899,99\nà vista no Pix</div>
      </a>
    </div>
    <div class="product-item__box">
      <a href="/produto/42569/placa-de-video-palit-rtx-5060">
        <div class="product-item__name">Placa de Vídeo Palit NVIDIA GeForce RTX 5060</div>
        <div class="product-item__new-price">R$ 2.499,00</div>
      </a>
    </div>
    <div class="product-item__box">
      <div class="product-item__name">Sem preço novo</div>
      <div class="product-item__old-price">De: R$ 3.000,00</div>
    </div>
    """
    produtos = await promo_bot.analisar_terabyte(html, {})
    assert len(produtos) == 2, f"esperado 2, veio {len(produtos)}"
    id1, titulo1, preco1, link1 = produtos[0]
    assert id1 == "39095"
    assert preco1 == 3899.99
    assert link1 == "https://www.terabyteshop.com.br/produto/39095/placa-de-video-msi-rtx-5060"
    assert produtos[1][2] == 2499.0
    print("OK 9: parser terabyte (estrutura nova product-item)")


async def main():
    promo_bot.init_db()
    test_estatisticas()
    test_regra_b_outlier_categoria()
    test_titulo_filtros()
    test_regra_a_historico()
    test_fallback_piso()
    await test_mensagem_e_realerta()
    await test_fallback_parse()
    await test_analisar_terabyte()


asyncio.run(main())
print("ALL TESTS PASSED")
