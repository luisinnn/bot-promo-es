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


async def main():
    promo_bot.enviar_telegram = fake_enviar
    promo_bot.init_db()

    config = {
        "nome": "Teste - RTX 5060",
        "piso_bug": 2400.0,
        "termos_obrigatorios": ["5060"],
        "site": "teste",
    }
    titulo = 'RTX 5060 <Gigabyte> & "Windforce" com \'aspas\''
    link = "https://exemplo.com.br/dp/ABC?psc=1&pd_rd_w=x&pd_rd_r=y"

    await promo_bot.processar_produto("123", titulo, 1500.0, link, config)
    msg = captured[-1]

    assert "&lt;Gigabyte&gt;" in msg, "titulo nao escapado"
    assert "&amp;" in msg
    assert "&quot;" in msg
    assert "&#x27;" in msg
    assert "<Gigabyte>" not in msg, "tag bruta presente"
    assert f'<a href="{link}">Comprar</a>' in msg, "link nao eh ancora"
    print("OK 1: escape do titulo + ancora no link")

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
    print("OK 2: fallback removeu parse_mode no reenvio apos erro de parse")

    calls.clear()

    def fake_post2(url, json, impersonate=None):
        calls.append(dict(json))
        return FakeResp(429, "Too Many Requests: retry after 5")

    promo_bot.cffi_requests.post = fake_post2
    await promo_bot.enviar_telegram("outra msg")
    assert len(calls) == 1, "deveria reenviar somente em erro de parse"
    print("OK 3: erro nao-parse nao gera reenvio")


asyncio.run(main())
print("ALL TESTS PASSED")
