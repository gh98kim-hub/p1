"""AI 호출(Claude·Gemini). 실패하면 예외 대신 안내 문구를 돌려준다."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


# ---------------------------------------------------------------- 구독 로그인(Claude Code)
#
# Claude 구독(Pro·Max)은 Anthropic의 공식 프로그램 Claude Code에 로그인해서 쓴다.
# 이 프로그램은 로그인 정보를 다루지 않고, 기자 PC에 설치된 Claude Code(claude -p)에
# 글을 맡기기만 한다. 로그인은 Claude Code의 공식 절차(claude auth login)로만 한다.

def find_claude():
    """설치된 Claude Code 실행 파일 경로(없으면 None)."""
    exe = shutil.which("claude")
    if exe:
        return exe
    for cand in (Path.home() / ".local" / "bin" / "claude.exe", Path.home() / ".local" / "bin" / "claude"):
        if cand.exists():
            return str(cand)
    return None


def _child_env():
    """구독으로 쓰도록 API 키 환경변수는 넘기지 않는다(있으면 Claude Code가 키로 청구한다)."""
    env = os.environ.copy()
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX"):
        env.pop(k, None)
    return env


def _no_window():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform.startswith("win") else {}


def claude_code_status():
    """(설치 여부, 로그인 여부, 설명)."""
    exe = find_claude()
    if not exe:
        return False, False, "Claude Code가 설치돼 있지 않습니다."
    try:
        p = subprocess.run([exe, "auth", "status"], capture_output=True, timeout=30, env=_child_env(),
                           **_no_window())
        info = json.loads(p.stdout.decode("utf-8", "replace") or "{}")
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:
        return True, False, f"Claude Code 상태 확인 실패: {e}"
    method = info.get("authMethod", "none")
    if p.returncode != 0 or not info.get("loggedIn", method != "none") or method == "none":
        return True, False, "Claude Code는 설치됐지만 로그인이 안 돼 있습니다."
    label = {"claude.ai": "구독 계정(claude.ai)", "oauth_token": "구독 토큰",
             "api_key": "API 키(구독 요금제가 아님)", "api_key_helper": "API 키(구독 요금제가 아님)",
             "third_party": "외부 클라우드 계정"}.get(method, method)
    return True, True, f"로그인됨: {label}"


def open_login_window():
    """Claude Code 공식 로그인 절차를 새 창에서 연다(브라우저로 Anthropic 로그인)."""
    exe = find_claude()
    if not exe:
        return False
    if sys.platform.startswith("win"):
        subprocess.Popen(["cmd", "/c", "start", "Claude 로그인", "cmd", "/k", exe, "auth", "login"],
                         env=_child_env())
    else:
        subprocess.Popen([exe, "auth", "login"], env=_child_env())
    return True


def call_claude_code(system, user, config, timeout=900):
    exe = find_claude()
    if not exe:
        return ("> Claude 구독 실패: Claude Code가 설치돼 있지 않습니다. "
                "[설정]의 설치 안내를 따라 설치하고 로그인하세요.")
    ai = config.get("ai", {})
    with tempfile.TemporaryDirectory() as d:
        sp = Path(d) / "system.txt"
        sp.write_text(system, encoding="utf-8")
        cmd = [exe, "-p", "Follow the instructions in the piped input. Reply only with the requested output.",
               "--system-prompt-file", str(sp), "--tools", "", "--disallowedTools", "mcp__*",
               "--output-format", "json", "--no-session-persistence"]
        if ai.get("effort"):
            cmd += ["--effort", ai["effort"]]
        if ai.get("claude_code_model"):
            cmd += ["--model", ai["claude_code_model"]]
        try:
            # 작업 폴더는 빈 임시 폴더(다른 폴더의 설정 파일을 읽지 않게)
            p = subprocess.run(cmd, input=user.encode("utf-8"), capture_output=True, cwd=d,
                               env=_child_env(), timeout=timeout, **_no_window())
        except subprocess.TimeoutExpired:
            return f"> Claude 구독 실패: {timeout // 60}분 안에 끝나지 않았습니다."
        except OSError as e:
            return f"> Claude 구독 실패: Claude Code 실행 오류({e})"
    out = p.stdout.decode("utf-8", "replace").strip()
    err = p.stderr.decode("utf-8", "replace").strip()
    try:
        data = json.loads(out)
    except ValueError:
        data = None
    if isinstance(data, dict):
        text = str(data.get("result") or "").strip()
        if data.get("is_error") or p.returncode != 0:
            return "> Claude 구독 실패: " + _explain(text or err)
        return text or "> Claude 구독 실패: 빈 응답"
    return "> Claude 구독 실패: " + _explain(err or out or f"종료 코드 {p.returncode}")


def _explain(msg):
    low = msg.lower()
    if any(k in low for k in ("login", "log in", "authenticat", "not logged", "/login")):
        return "Claude Code 로그인이 필요합니다. [설정] → [Claude 로그인]을 누르세요."
    if any(k in low for k in ("usage limit", "rate limit", "limit reached")):
        return "구독 사용 한도에 걸렸습니다. 한도가 풀린 뒤 다시 실행하세요."
    return msg[:300]


def call_claude(system, user, config):
    if config.get("claude_auth") == "subscription":
        return call_claude_code(system, user, config)
    try:
        import anthropic
    except ImportError:
        return "> Claude를 쓰려면 `pip install anthropic`이 필요합니다."

    ai = config["ai"]
    # 설정 파일(GUI)에 저장한 키가 있으면 우선, 없으면 환경변수 ANTHROPIC_API_KEY
    key = config.get("anthropic_api_key") or None
    client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
    try:
        with client.beta.messages.stream(
            model=ai.get("model", "claude-opus-5-5"),
            max_tokens=32000,
            thinking={"type": "adaptive"},
            output_config={"effort": ai.get("effort", "high")},
            # 안전 분류기가 거절하면 서버가 다른 모델로 자동 재시도
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=system,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            response = stream.get_final_message()
    except anthropic.AuthenticationError:
        return "> Claude 실패: API 키가 올바르지 않습니다."
    except anthropic.RateLimitError:
        return "> Claude 실패: 호출 한도 초과. 잠시 후 다시 실행하세요."
    except anthropic.APIStatusError as e:
        return f"> Claude 실패: API 오류({e.status_code}) {e.message}"
    except anthropic.APIConnectionError:
        return "> Claude 실패: 네트워크 연결을 확인하세요."

    if response.stop_reason == "refusal":
        return "> Claude 실패: 모델이 응답을 거절했습니다. 자료 구성을 확인하세요."
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if response.stop_reason == "max_tokens":
        text += "\n\n> (출력 길이 제한으로 중간에 끊겼습니다.)"
    return text


def call_gemini(system, user, config):
    try:
        from google import genai
        from google.genai import errors, types
    except ImportError:
        return "> Gemini를 쓰려면 `pip install google-genai`가 필요합니다."

    key = config.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        return "> Gemini 실패: API 키가 없습니다. [설정]에 Gemini API 키를 넣으세요."
    model = config["ai"].get("gemini_model") or "gemini-pro-latest"
    try:
        client = genai.Client(api_key=key)
        resp = client.models.generate_content(
            model=model,
            contents=user,
            config=types.GenerateContentConfig(system_instruction=system, max_output_tokens=32000),
        )
    except errors.ClientError as e:
        if e.code in (400, 401, 403) and "key" in str(e).lower():
            return "> Gemini 실패: API 키가 올바르지 않습니다."
        if e.code == 404:
            return f"> Gemini 실패: 모델 '{model}'을 찾을 수 없습니다. [설정]에서 모델명을 확인하세요."
        if e.code == 429:
            return "> Gemini 실패: 호출 한도 초과. 잠시 후 다시 실행하세요."
        return f"> Gemini 실패: API 오류({e.code}) {e.message}"
    except errors.APIError as e:
        return f"> Gemini 실패: 서버 오류({e.code}). 잠시 후 다시 실행하세요."
    except Exception as e:  # 연결 오류는 httpx 예외로 올라온다
        return f"> Gemini 실패: 네트워크 연결을 확인하세요({type(e).__name__})."

    text = (resp.text or "").strip()
    if not text:
        reason = ""
        if resp.candidates:
            reason = str(resp.candidates[0].finish_reason or "")
        elif resp.prompt_feedback:
            reason = str(resp.prompt_feedback.block_reason or "")
        return f"> Gemini 실패: 빈 응답({reason or '사유 미상'})."
    if resp.candidates and str(resp.candidates[0].finish_reason).endswith("MAX_TOKENS"):
        text += "\n\n> (출력 길이 제한으로 중간에 끊겼습니다.)"
    return text


PROVIDERS = {"claude": ("Claude", call_claude), "gemini": ("Gemini", call_gemini)}


def parse_json(text):
    """AI 응답에서 JSON 객체를 꺼낸다(코드 블록·앞뒤 설명이 붙어도)."""
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None


def available_provider(config):
    """쓸 수 있는 AI. 창에서 고른 AI를 먼저, 없으면 준비된 쪽."""
    claude_ok = (bool(find_claude()) if config.get("claude_auth") == "subscription"
                 else bool(config.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")))
    has = {
        "claude": claude_ok,
        "gemini": bool(config.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY")
                       or os.environ.get("GOOGLE_API_KEY")),
    }
    first = config.get("ai", {}).get("provider", "claude")
    order = ["gemini", "claude"] if first == "gemini" else ["claude", "gemini"]
    return next((n for n in order if has[n]), None)


def strip_bold(text):
    """마크다운 굵게 표시(**) 제거."""
    return (text or "").replace("**", "")
