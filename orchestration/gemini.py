"""Optional Google Gemini integration (REST generateContent, structured JSON output).

Gemini is used for language only, never for measurements:
  * interpret()  - supervisor: classify the free-text mission request.
  * summarize()  - explanation: write a short narrative of the chosen site from the
                   agents' own numbers. Every number in the text must appear in the
                   evidence, otherwise the text is rejected (no invented figures).

Enabled when GEMINI_API_KEY is set. Model name from GEMINI_MODEL. Any failure returns
None and the caller keeps the deterministic result.
"""
from __future__ import annotations
import asyncio, json, os, re, time

DEFAULT_MODEL = 'gemini-3.5-flash-lite'  # fast and less busy; checked live 2026-11-14
last_model = None
ENDPOINT = 'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'


def key_problem() -> str | None:
    key = os.getenv('GEMINI_API_KEY', '').strip()
    if not key: return 'GEMINI_API_KEY is not set.'
    if not key.isascii() or ' ' in key:
        return 'GEMINI_API_KEY is not a real key (it has spaces or non-English letters). Paste the key from Google AI Studio.'
    return None


def enabled() -> bool:
    return key_problem() is None


def model() -> str:
    return os.getenv('GEMINI_MODEL', DEFAULT_MODEL)


class GeminiUnavailable(RuntimeError):
    pass


async def _post(client, name: str, body: dict, headers: dict, timeout: float):
    level = os.getenv('GEMINI_THINKING', 'off')  # 'low' or 'high' to let the model think (slower)
    cfg = dict(body['generationConfig'])
    if level != 'off': cfg['thinkingConfig'] = {'thinkingLevel': level}
    r = await client.post(ENDPOINT.format(model=name), json={**body, 'generationConfig': cfg}, headers=headers, timeout=timeout)
    if r.status_code == 400 and 'thinking' in r.text.lower():  # model without thinking levels
        r = await client.post(ENDPOINT.format(model=name), json=body, headers=headers, timeout=timeout)
    return r


async def _generate(system: str, user: str, schema: dict, timeout: float) -> dict | None:
    """Ask the configured model; if it is busy (429/5xx) or gone (404), retry once and
    then try the fallback models, all within one overall time budget."""
    import httpx
    global last_model
    body = {
        'systemInstruction': {'parts': [{'text': system}]},
        'contents': [{'role': 'user', 'parts': [{'text': user}]}],
        'generationConfig': {'temperature': 0, 'responseMimeType': 'application/json',
                             'responseJsonSchema': schema},
    }
    headers = {'x-goog-api-key': os.environ['GEMINI_API_KEY']}
    fallbacks = [m.strip() for m in os.getenv('GEMINI_FALLBACK_MODELS', 'gemini-3.1-flash-lite,gemini-flash-lite-latest,gemini-3.8-flash').split(',') if m.strip()]
    per_request = float(os.getenv('GEMINI_REQUEST_TIMEOUT', '20'))
    deadline = time.monotonic() + timeout; errors = []
    async with httpx.AsyncClient() as client:
        for name in dict.fromkeys([model()] + fallbacks):
            for attempt in range(2):
                left = deadline - time.monotonic()
                if left < 2: raise GeminiUnavailable('; '.join(errors) or 'time budget used up')
                try: r = await _post(client, name, body, headers, min(left, per_request))
                except httpx.TimeoutException: errors.append(f'{name}: timeout'); break
                if r.status_code == 200:
                    data = r.json(); last_model = name
                    text = ''.join(p.get('text', '') for p in data['candidates'][0]['content']['parts'])
                    return json.loads(text)
                errors.append(f'{name}: HTTP {r.status_code}')
                if r.status_code in (429, 500, 503) and attempt == 0: await asyncio.sleep(1.5); continue
                if r.status_code in (404, 429, 500, 503): break
                r.raise_for_status()  # 400/401/403: a real request problem, stop here
    raise GeminiUnavailable('; '.join(errors))


MISSION_TYPES = ['science', 'exploration', 'cargo', 'robotic', 'crewed']


async def interpret(request: str) -> dict | None:
    schema = {'type': 'object', 'properties': {
        'mission_type': {'type': 'string', 'enum': MISSION_TYPES},
        'explanation_focus': {'type': 'string', 'enum': ['terrain', 'sunlight', 'communication']}},
        'required': ['mission_type', 'explanation_focus']}
    out = await _generate('Classify the lunar mission request. Output only the mission type and the '
                          'explanation focus. Never output measurements or requirements.',
                          request, schema, float(os.getenv('GEMINI_TIMEOUT', '30')))
    if not out or out.get('mission_type') not in MISSION_TYPES: return None
    return out


_NUM = re.compile(r'-?\d+(?:\.\d+)?')


def _numbers(text: str) -> list[float]:
    return [float(x) for x in _NUM.findall(text)]


def grounded(text: str, evidence: dict) -> bool:
    """True when every number in text matches a number in the evidence (rounding allowed)."""
    allowed = _numbers(json.dumps(evidence))
    for n in _numbers(text):
        if not any(abs(n - a) <= max(0.051, abs(a) * 0.005) or abs(abs(n) - abs(a)) <= 0.051 for a in allowed):
            return False
    return True


async def summarize(evidence: dict, language: str = 'en') -> str | None:
    schema = {'type': 'object', 'properties': {'summary': {'type': 'string'}}, 'required': ['summary']}
    lang = 'Arabic' if language == 'ar' else 'English'
    out = await _generate(
        f'You explain a lunar landing-site recommendation to competition judges in {lang}, in plain words for non-experts. '
        'Write 2 or 3 short natural sentences. Never write JSON field names, underscores or site IDs; say "the selected site". '
        'Use ONLY numbers from the evidence, copied exactly with units (degrees, hours). Do not add any other number, date, '
        'percentage or claim. Say why the site is good (sunlight, Earth contact, gentle slope) and end by stating honestly that '
        'the data status is the given data_status (UNVERIFIED means NASA data not yet independently reviewed; MOCK means demo data).',
        json.dumps(evidence, ensure_ascii=False), schema, float(os.getenv('GEMINI_TIMEOUT', '30')))
    text = (out or {}).get('summary', '').strip()
    if not text or len(text) > 900 or not grounded(text, evidence): return None
    return text
