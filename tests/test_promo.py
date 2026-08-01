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
    print("OK 2: regra B (outlier instantaneo da categoria)")


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
    print("OK 3: regra A (historico: novo minimo / % da media / p25)")


def test_fallback_piso():
    eh, motivo = promo_bot.verificar_preco_baixo(
        "site_frio", 1500.0, None, {"piso_bug": 2400.0}
    )
    assert eh and "piso" in motivo
    eh, _ = promo_bot.verificar_preco_baixo(
        "site_frio", 2500.0, None, {"piso_bug": 2400.0}
    )
    assert not eh
    print("OK 4: fallback piso manual como trava")


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
    print("OK 5: mensagem com escape, ancora e motivo")

    await promo_bot.processar_produto("rea", titulo, 1900.0, link, config)
    assert len(captured) == 2, "esperado re-alerta por queda de 5%"
    assert "PREÇO CAIU" in captured[-1], "mensagem de queda esperada"
    assert "antes R$ 2000.00" in captured[-1]

    await promo_bot.processar_produto("rea", titulo, 1900.0, link, config)
    assert len(captured) == 2, "nao deveria re-alertar sem queda relevante"
    print("OK 6: re-alerta apenas em queda >= 5%")


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
    print("OK 7: fallback de parse no enviar_telegram")


async def main():
    promo_bot.init_db()
    test_estatisticas()
    test_regra_b_outlier_categoria()
    test_regra_a_historico()
    test_fallback_piso()
    await test_mensagem_e_realerta()
    await test_fallback_parse()


asyncio.run(main())
print("ALL TESTS PASSED")
