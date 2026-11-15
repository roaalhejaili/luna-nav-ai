"""Check the Gemini key and model before a demo.  Usage: python scripts/check_gemini.py"""
import asyncio, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from orchestration import gemini

async def timed(label, coro):
    t = time.perf_counter()
    try:
        out = await coro
        print(f'{label}: {out or "rejected (ungrounded or empty)"}  [{time.perf_counter() - t:.1f} s, answered by {gemini.last_model}]')
        return True
    except Exception as e:
        detail = getattr(getattr(e, 'response', None), 'text', '') or str(e)
        print(f'{label}: FAILED after {time.perf_counter() - t:.1f} s: {type(e).__name__} {detail[:400]}')
        return False

async def main():
    if gemini.key_problem(): sys.exit(gemini.key_problem())
    import httpx
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get('https://generativelanguage.googleapis.com/v1beta/models',
                        headers={'x-goog-api-key': os.environ['GEMINI_API_KEY']}, params={'pageSize': 200})
    if r.status_code != 200: sys.exit(f'Key rejected ({r.status_code}): {r.text[:300]}')
    names = [m['name'].split('/', 1)[1] for m in r.json().get('models', [])
             if 'generateContent' in m.get('supportedGenerationMethods', [])]
    if gemini.model() not in names:
        sys.exit(f'Model {gemini.model()} not available. Options: {", ".join(n for n in names if "flash" in n)}')
    print(f'Key OK. Model {gemini.model()}, timeout {os.getenv("GEMINI_TIMEOUT", "30")} s, thinking {os.getenv("GEMINI_THINKING", "off")}')
    ok = await timed('Interpret test', gemini.interpret('we want to put a rover near the lunar south pole'))
    ev = {'data_status': 'UNVERIFIED', 'site': 'Test site', 'slope_deg': 0.7, 'sunlight_hours': 96.0, 'score': 0.922}
    ok &= await timed('Summary test', gemini.summarize(ev, os.getenv('LUNA_GEMINI_LANG', 'en')))
    print('OK: Gemini is ready.' if ok else 'Not ready. Send the FAILED lines above (without the key).')

asyncio.run(main())
