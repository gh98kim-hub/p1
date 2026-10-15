"""텔레그램 알림(선택). 봇 토큰과 채팅 ID를 설정에 넣으면 후보마다 한 건씩 보낸다."""

import json
import urllib.request

from .report import split_ai

LIMIT = 3900  # 텔레그램 메시지 최대 4096자


def send(token, chat_id, text):
    data = json.dumps({"chat_id": chat_id, "text": text[:LIMIT], "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp).get("ok", False)


def send_candidates(config, cands, skeletons, ai=None):
    parts = {}
    for text in (ai or {}).values():
        parts = split_ai(text)
        if parts:
            break
    sent = 0
    for c in cands:
        body = parts.get(c.id) or skeletons[c.id]
        try:
            sent += bool(send(config["telegram_bot_token"], config["telegram_chat_id"], body))
        except Exception:  # noqa: BLE001 - 알림 실패가 리포트를 막지 않게
            continue
    return sent
