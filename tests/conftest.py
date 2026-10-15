"""테스트 공통: 실제 Claude Code(claude -p)를 절대 실행하지 않게 막는다.
구독 경로를 시험하는 테스트는 llm.find_claude를 따로 바꿔 가짜를 쓴다."""

import pytest


@pytest.fixture(autouse=True)
def _no_real_claude_code(monkeypatch):
    from balje import llm

    monkeypatch.setattr(llm, "find_claude", lambda: None)

    def blocked(*a, **k):
        raise AssertionError("테스트에서 실제 프로세스를 실행하려 했습니다")

    monkeypatch.setattr(llm.subprocess, "run", blocked)
    monkeypatch.setattr(llm.subprocess, "Popen", blocked)
