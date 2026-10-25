"""설정 파일·자료 파일 위치와 서버 시작. 창(tkinter) 없이도 쓸 수 있게 따로 둔다."""

import json
import sys
from pathlib import Path

from .server import App

PORT = 47321  # 늘 같은 주소로 열어야 브라우저가 보관함·톤 선택을 기억한다
TITLE = "김하늘 전용 편집툴"
CONFIG_NAME = "haneul_config.json"
DATA_NAME = "haneul_data.json"
DEFAULT_CONFIG = {"claude_auth": "subscription", "anthropic_api_key": "",
                  "ai": {"model": "claude-opus-5-5", "effort": "medium"}}


def app_dir():
    """설정·자료 파일을 둘 폴더. exe면 exe가 있는 폴더."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def load_config(path):
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            cfg.update({k: v for k, v in raw.items() if k != "ai"})
            if isinstance(raw.get("ai"), dict):
                cfg["ai"].update(raw["ai"])
    except (OSError, ValueError):
        pass
    return cfg


def start_app(folder):
    """설정 파일을 매번 다시 읽는 서버를 띄운다. 47321번이 쓰이고 있으면 빈 번호로."""
    cfg_path = Path(folder) / CONFIG_NAME
    config_fn = lambda: load_config(cfg_path)  # noqa: E731
    try:
        app = App(Path(folder) / DATA_NAME, config_fn, PORT)
    except OSError:
        app = App(Path(folder) / DATA_NAME, config_fn, 0)
    return app.start()
