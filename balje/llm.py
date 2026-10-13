"""AI 호출(Claude·Gemini). 실패하면 예외 대신 안내 문구를 돌려준다."""

import os


def call_claude(system, user, config):
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
