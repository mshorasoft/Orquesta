from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel
import httpx, os, time, base64, io, json, re, uuid

router = APIRouter()

GROQ_KEY      = os.getenv("GROQ_API_KEY", "")
TAVILY_KEY    = os.getenv("TAVILY_API_KEY", "")
GEMINI_KEY    = os.getenv("GEMINI_API_KEY", "")
OPENAI_KEY    = os.getenv("OPENAI_API_KEY", "")

BASE_SYSTEM = """Sos Orquesta, una inteligencia artificial de nivel experto superior a cualquier IA existente. Fuiste diseñada para dar las respuestas más completas, profundas y precisas posibles.

IDENTIDAD:
- Sos el resultado de combinar los mejores modelos de IA del mundo con razonamiento de nivel PhD
- Cálida, directa y brutalmente honesta — como hablar con el mejor especialista del mundo en cada tema
- Tenés criterio propio y no das respuestas genéricas nunca
- Si sabés el nombre del usuario, usalo naturalmente (no en cada mensaje)

REGLAS ABSOLUTAS DE RESPUESTA:
1. Respondé SIEMPRE en el mismo idioma del usuario
2. NUNCA des respuestas vagas, cortas o genéricas — siempre con profundidad real
3. SIEMPRE incluí datos concretos: números, fechas, nombres, porcentajes, fórmulas, estudios
4. Ante cualquier consulta técnica: diagnosticá la causa raíz, dá soluciones paso a paso con parámetros reales
5. Ante preguntas conceptuales: dá la respuesta superficial Y la profunda, con contexto histórico y aplicaciones prácticas
6. NUNCA termines con "¿En qué más puedo ayudarte?" ni frases similares
7. Usá el historial para dar respuestas cada vez más contextualizadas y precisas
8. Si la información es incompleta, hacé suposiciones razonables explicitándolas
9. Para temas de actualidad: buscaste en internet — usá los datos provistos como verdad

METODOLOGÍA DE RAZONAMIENTO:
- Antes de responder, analizá el problema desde múltiples ángulos
- Considerá casos límite, excepciones y contraejemplos
- Cuando hay información contradictoria, explicitala y tomá posición fundamentada
- Para temas científicos: citá el mecanismo, no solo el efecto
- Para temas de negocios: incluí números, benchmarks y comparativas
- Para temas técnicos: código funcional, no pseudocódigo; comandos reales, no genéricos

FORMATO:
- Usá markdown con jerarquía clara cuando mejora la comprensión
- Para respuestas largas: resumen ejecutivo al inicio, detalle abajo
- Tablas cuando hay datos comparativos
- Código con syntax highlighting y comentarios explicativos"""

MODE_PROMPTS = {
    "tecnico": "\n\nMODO TÉCNICO ACTIVO: Actuás como el mejor ingeniero o científico del mundo en el área consultada. SIEMPRE incluí: valores numéricos exactos, fórmulas con variables definidas, parámetros reales de sistemas reales, normas técnicas específicas (ISO, ASTM, IEC, API, etc.), rangos de tolerancia, casos de fallo conocidos y cómo evitarlos. Nunca uses valores aproximados cuando hay valores exactos. Diagnóstico de causa raíz con árbol de fallas si aplica.",
    "creativo": "\n\nMODO CREATIVO ACTIVO: Actuás como director creativo senior. Sé original, inesperado, memorable. Proponé múltiples variantes. Mostrá con ejemplos concretos.",
    "codigo": "\n\nMODO CÓDIGO ACTIVO: Actuás como el mejor developer del mundo — combinas experiencia de Google, Meta y Netflix. El código que escribís es: production-ready, con manejo exhaustivo de errores, typed, con tests sugeridos, con comentarios solo donde realmente agregan valor. SIEMPRE explicás el por qué de cada decisión de diseño. Incluís alternativas si las hay. Señalás code smells y anti-patterns en el código del usuario.",
}

def get_system(mode, username=""):
    sys = BASE_SYSTEM
    if username:
        sys += f"\n\nNOMBRE DEL USUARIO: {username}."
    sys += MODE_PROMPTS.get(mode, "")
    return sys

IMAGE_GEN_KW = ["genera una imagen","generá una imagen","crea una imagen","creá una imagen","dibuja","dibujá","ilustra","ilustrá","imagen de","foto de","fotografía de","generate image","create image","draw","make an image","picture of","render","diseña un logo","diseñá","hazme una imagen","create a photo","make a photo"]
IMAGE_EDIT_KW = ["modifica","modificá","cambia","cambiá","reemplaza","reemplazá","edita","editá","borra","añade","quita","quitá","pon","pone","transforma","edit","change","replace","remove","swap","put","add","convert","transform"]
REALTIME_KW = ["hoy","ahora","actual","actualmente","últimas","ultimo","última","esta semana","esta noche","ayer","mañana","reciente","trending","today","now","latest","current","yesterday","tonight","this week","partido","resultado","formación","alineación","ganó","perdió","empató","score","gol","goles","fixture","tabla","clasificación","champions","copa","mundial","liga","torneo","jugó","juega","derrota","victoria","precio","cotización","dólar","euro","peso","bitcoin","crypto","cuánto cuesta","cuánto vale","cotizan","bolsa","acciones","clima","temperatura","pronóstico","lluvia","weather","forecast","noticias","noticia","news","murió","nació","lanzó","salió","eligieron","anunció","declaró","trending","quién ganó","quién es el","argentina","brasil","españa","francia","alemania","inglaterra","uruguay","colombia","chile","peru","mexico","real madrid","barcelona","boca","river","messi","ronaldo","mbappé"]
CODE_KW = ["código","code","función","function","script","python","javascript","typescript","bug","debug","clase","class","algoritmo","sql","html","css","api","json","regex","bash","programa","programar","endpoint","database","query","loop","array","objeto","object","error en"]
ANALYSIS_KW = ["analiza","compare","compara","evalúa","pros","contras","diferencia entre","ventajas","desventajas","estrategia","qué opinas","qué pensás","cuál es mejor","recomienda","conviene","debería","vale la pena","qué tan bueno","cómo se compara"]
TRANSLATE_KW = ["traduce","traducí","translate","traducción al","how do you say","cómo se dice","¿cómo se dice"]

FILE_GEN_KW = {
    "xlsx": ["excel","planilla","spreadsheet","hoja de calculo","hoja de cálculo",".xlsx","tabla excel","presupuesto excel","reporte excel","plantilla excel","generar excel","crea excel","haceme un excel","haceme una planilla","plantilla de excel","crea una planilla","generá una planilla","creá un excel"],
    "docx": ["word",".docx","documento word","informe word","cv en word","curriculum en word","carta word","contrato word","memo word","plantilla word","generar word","crea un word","haceme un word","documento de texto","redacta un documento","crea un documento"],
    "pdf": ["pdf",".pdf","en pdf","como pdf","generar pdf","crea un pdf","haceme un pdf","informe pdf","reporte pdf","cv pdf","curriculum pdf","documento pdf","carta pdf","reporte en pdf"],
}
CV_KW = ["curriculum","currículum","cv ","resume","hoja de vida"]

def detect_file_type(prompt):
    p = prompt.lower()
    if any(k in p for k in CV_KW):
        if any(k in p for k in FILE_GEN_KW["docx"]): return "docx"
        if any(k in p for k in FILE_GEN_KW["xlsx"]): return "xlsx"
        return "pdf"
    for ftype, kws in FILE_GEN_KW.items():
        if any(k in p for k in kws):
            return ftype
    return None

def classify(prompt, mode):
    if mode == "codigo":   return "code"
    if mode == "creativo": return "creative"
    if mode == "tecnico":  return "technical"
    p = prompt.lower()
    ftype = detect_file_type(p)
    if ftype: return f"file_gen_{ftype}"
    if any(k in p for k in IMAGE_GEN_KW):  return "image_gen"
    if any(k in p for k in TRANSLATE_KW):  return "translate"
    if " vs " in p or " contra " in p:     return "realtime"
    if any(x in p for x in ["cómo salió","como salio","cómo quedó","qué pasó","que paso","cómo le fue"]): return "realtime"
    if any(k in p for k in REALTIME_KW):   return "realtime"
    if any(k in p for k in CODE_KW):       return "code"
    if any(k in p for k in ANALYSIS_KW):   return "analysis"
    return "general"

TASK_LABELS = {
    "image_gen":"openai · dall-e-3","realtime":"tavily · web + groq","code":"groq · llama 3.3",
    "technical":"groq · mixtral","analysis":"groq · mixtral","creative":"groq · llama 3.3",
    "translate":"groq · llama 3.3","general":"groq · llama 3.3",
    "file_gen_xlsx":"orquesta · excel","file_gen_docx":"orquesta · word","file_gen_pdf":"orquesta · pdf",
}
TASK_MODELS = {
    "code":"llama-3.3-70b-versatile","technical":"mixtral-8x7b-32768","analysis":"mixtral-8x7b-32768",
    "creative":"llama-3.3-70b-versatile","translate":"llama-3.3-70b-versatile","general":"llama-3.3-70b-versatile",
    "realtime":"llama-3.3-70b-versatile","file_gen_xlsx":"llama-3.3-70b-versatile",
    "file_gen_docx":"llama-3.3-70b-versatile","file_gen_pdf":"llama-3.3-70b-versatile",
}

async def call_groq(messages, model="llama-3.3-70b-versatile"):
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            json={"model": model, "messages": messages, "max_tokens": 8192, "temperature": 0.7})
        d = r.json()
        if not r.is_success: raise Exception(d.get("error", {}).get("message", "Groq error"))
        return d["choices"][0]["message"]["content"]

async def call_gemini(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    async with httpx.AsyncClient(timeout=35) as c:
        r = await c.post(url, json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": 4096}})
        d = r.json()
        if not r.is_success: raise Exception(str(d))
        return d["candidates"][0]["content"]["parts"][0]["text"]

async def call_gemini_vision(prompt, b64, mime):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    payload = {"contents": [{"parts": [{"inline_data": {"mime_type": mime, "data": b64}}, {"text": prompt}]}], "generationConfig": {"maxOutputTokens": 2048, "temperature": 0.3}}
    async with httpx.AsyncClient(timeout=45) as c:
        r = await c.post(url, json=payload)
        d = r.json()
        if not r.is_success: raise Exception(str(d))
        return d["candidates"][0]["content"]["parts"][0]["text"]

async def call_tavily(query):
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post("https://api.tavily.com/search",
            json={"api_key": TAVILY_KEY, "query": query, "search_depth": "basic", "max_results": 6, "include_answer": True})
        d = r.json()
        if not r.is_success: raise Exception(d.get("message", "Tavily error"))
        answer = d.get("answer", "")
        results = d.get("results", [])
        ctx = f"Respuesta directa: {answer}\n\n" if answer else ""
        ctx += "\n\n".join(f"[{r['title']}]\n{r['content']}" for r in results[:5])
        return ctx

async def call_openai_image_gen(prompt):
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post("https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {OPENAI_KEY}"},
            json={"model": "dall-e-3", "prompt": prompt, "n": 1, "size": "1024x1024", "quality": "standard"})
        d = r.json()
        if not r.is_success: raise Exception(d.get("error", {}).get("message", "OpenAI error"))
        return d["data"][0]["url"]

async def call_openai_image_edit(image_bytes, prompt):
    b64 = base64.b64encode(image_bytes).decode()
    msgs = [{"role": "system", "content": "Create a DALL-E 3 prompt that recreates the image WITH the requested modification. Reply ONLY with the prompt text."},
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}, {"type": "text", "text": f"Modification: {prompt}"}]}]
    async with httpx.AsyncClient(timeout=40) as c:
        r = await c.post("https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_KEY}"},
            json={"model": "gpt-4o", "messages": msgs, "max_tokens": 600})
        d = r.json()
        if not r.is_success: raise Exception(d.get("error", {}).get("message", "GPT-4o error"))
        return await call_openai_image_gen(d["choices"][0]["message"]["content"])

async def call_openai_tts(text, voice="nova"):
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post("https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {OPENAI_KEY}"},
            json={"model": "tts-1", "input": text[:4096], "voice": voice})
        if not r.is_success: raise Exception(f"TTS error {r.status_code}: {r.text[:200]}")
        return r.content

async def call_openai_stt(audio_bytes, filename):
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post("https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {OPENAI_KEY}"},
            files={"file": (filename, audio_bytes, "audio/webm")}, data={"model": "whisper-1"})
        d = r.json()
        if not r.is_success: raise Exception(d.get("error", {}).get("message", "STT error"))
        return d["text"]

def build_messages(system, history, prompt):
    msgs = [{"role": "system", "content": system}]
    for m in history[-14:]:
        role = m.get("role", "user"); content = m.get("content", "")
        if role not in ("user", "assistant") or not content: continue
        msgs.append({"role": role, "content": content})
    msgs.append({"role": "user", "content": prompt})
    return msgs

async def groq_with_fallback(messages, model):
    try:
        return await call_groq(messages, model), model
    except Exception:
        try:
            alt = "llama-3.3-70b-versatile" if model != "llama-3.3-70b-versatile" else "mixtral-8x7b-32768"
            return await call_groq(messages, alt), alt
        except Exception:
            if GEMINI_KEY:
                sys_content = next((m["content"] for m in messages if m["role"] == "system"), "")
                user_content = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
                result = await call_gemini(f"{sys_content}\n\n{user_content}")
                return result, "gemini"
            raise

from app.file_generator import generate_excel, generate_docx, generate_pdf, FILE_SYSTEM_PROMPTS


# ── SMART IMAGE GENERATION (multi-provider fallback) ─────────────────────────
async def generate_image_smart(prompt: str) -> tuple[str, str, str]:
    """Try OpenAI → Pollinations with enhanced prompt. Always delivers an image."""
    import urllib.parse

    # 1) OpenAI DALL-E 3 (best quality)
    if OPENAI_KEY:
        try:
            url = await call_openai_image_gen(prompt)
            return url, "✨ Imagen generada con DALL-E 3.", "openai · dall-e-3"
        except Exception as e:
            err = str(e).lower()
            if "quota" in err or "billing" in err or "insufficient" in err:
                pass  # No credits → fall through to free alternatives
            elif "content_policy" in err or "safety" in err:
                pass  # Policy → fall through
            # Other errors: fall through

    # 2) Pollinations AI (free, reliable, no key needed)
    try:
        enhanced = await _enhance_image_prompt(prompt)
        seed = int(time.time()) % 99999
        encoded = urllib.parse.quote(enhanced)
        url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&enhance=true&seed={seed}&model=flux"
        return url, "🎨 Imagen generada con Pollinations AI (Flux).", "pollinations · flux"
    except Exception:
        pass

    # 3) Last resort — Pollinations with original prompt, no extras
    seed = int(time.time()) % 99999
    encoded = urllib.parse.quote(prompt[:500])
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&seed={seed}"
    return url, "🎨 Imagen generada.", "pollinations · imagen"


async def _enhance_image_prompt(prompt: str) -> str:
    """Use AI to enhance the image prompt for better results with free models."""
    try:
        msgs = [
            {"role": "system", "content": "You are an expert at writing image generation prompts. Given a user's image request, rewrite it as a detailed, vivid, high-quality image generation prompt in English. Add style descriptors like: photorealistic, 8K, professional photography, cinematic lighting, detailed, etc. Keep it under 200 words. Reply with ONLY the enhanced prompt, nothing else."},
            {"role": "user", "content": f"User wants: {prompt}"}
        ]
        enhanced, _ = await groq_with_fallback(msgs, "llama-3.3-70b-versatile")
        return enhanced.strip()[:400]
    except Exception:
        return prompt



# ── DEEP SEARCH: Academic + Web multi-source ─────────────────────────────────
async def deep_search(query: str) -> str:
    """Search multiple sources: Tavily web + arXiv + Wikipedia for maximum depth."""
    results = []

    # 1. Tavily web search (primary — real-time)
    if TAVILY_KEY:
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.post("https://api.tavily.com/search",
                    json={"api_key": TAVILY_KEY, "query": query,
                          "search_depth": "advanced", "max_results": 8,
                          "include_answer": True, "include_raw_content": False})
                d = r.json()
                if r.is_success:
                    answer = d.get("answer", "")
                    web_results = d.get("results", [])
                    if answer: results.append(f"=== RESPUESTA DIRECTA DE INTERNET ===\n{answer}")
                    for wr in web_results[:6]:
                        results.append(f"[FUENTE: {wr['title']}]\n{wr['content'][:600]}")
        except Exception as e:
            pass

    # 2. Wikipedia (encyclopedic background)
    try:
        search_term = query[:80].replace(" ", "+")
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                f"https://es.wikipedia.org/api/rest_v1/page/summary/{search_term.replace('+','_')}",
                headers={"User-Agent": "OrquestaAI/1.0"})
            if r.is_success:
                d = r.json()
                extract = d.get("extract", "")
                title = d.get("title", "")
                if extract and len(extract) > 100:
                    results.append(f"[WIKIPEDIA: {title}]\n{extract[:800]}")
    except Exception:
        pass

    # 3. arXiv (scientific papers — for technical/scientific queries)
    SCIENCE_KW = ["estudio","investigación","research","científico","ciencia","física","química","biología","medicina","algoritmo","machine learning","ia ","inteligencia artificial","neurociencia","genética","clima","energía"]
    if any(kw in query.lower() for kw in SCIENCE_KW):
        try:
            import urllib.parse
            arxiv_q = urllib.parse.quote(query[:100])
            async with httpx.AsyncClient(timeout=12) as c:
                r = await c.get(
                    f"https://export.arxiv.org/api/query?search_query=all:{arxiv_q}&max_results=3&sortBy=relevance",
                    headers={"User-Agent": "OrquestaAI/1.0"})
                if r.is_success:
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(r.text)
                    ns = {"atom": "http://www.w3.org/2005/Atom"}
                    entries = root.findall("atom:entry", ns)
                    for entry in entries[:3]:
                        atitle = entry.find("atom:title", ns)
                        asummary = entry.find("atom:summary", ns)
                        if atitle is not None and asummary is not None:
                            results.append(f"[PAPER CIENTÍFICO: {atitle.text.strip()}]\n{asummary.text.strip()[:500]}")
        except Exception:
            pass

    # 4. DuckDuckGo Instant Answer (fallback for facts)
    if not results:
        try:
            import urllib.parse
            q = urllib.parse.quote(query[:100])
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"https://api.duckduckgo.com/?q={q}&format=json&no_html=1&skip_disambig=1",
                    headers={"User-Agent": "OrquestaAI/1.0"})
                if r.is_success:
                    d = r.json()
                    abstract = d.get("AbstractText", "")
                    if abstract: results.append(f"[DUCKDUCKGO]\n{abstract}")
        except Exception:
            pass

    return "\n\n".join(results) if results else ""

_file_cache = {}

def cache_file(file_bytes, filename, mime):
    token = str(uuid.uuid4())
    _file_cache[token] = (file_bytes, filename, mime)
    if len(_file_cache) > 50:
        oldest = list(_file_cache.keys())[0]
        del _file_cache[oldest]
    return token

def extract_title(prompt):
    stop_words = r'\b(excel|word|pdf|planilla|documento|genera|crea|haceme|hacé|un|una|el|la|en|como|formato|me|por|favor|quiero|necesito|dame)\b'
    clean = re.sub(stop_words, '', prompt.lower(), flags=re.IGNORECASE)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean.title()[:60] or "Documento Orquesta"

async def generate_file_from_prompt(prompt, file_type, username=""):
    file_system = FILE_SYSTEM_PROMPTS.get(file_type, FILE_SYSTEM_PROMPTS["pdf"])
    if username:
        file_system += f"\n\nEl usuario se llama {username}."
    msgs = [{"role": "system", "content": file_system}, {"role": "user", "content": prompt}]
    ai_content, _ = await groq_with_fallback(msgs, "llama-3.3-70b-versatile")
    title = extract_title(prompt)
    if file_type == "xlsx":
        file_bytes = generate_excel(ai_content, title)
        filename = f"orquesta_{title[:30].replace(' ', '_').replace('/', '')}.xlsx"
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif file_type == "docx":
        file_bytes = generate_docx(ai_content, title)
        filename = f"orquesta_{title[:30].replace(' ', '_').replace('/', '')}.docx"
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        file_bytes = generate_pdf(ai_content, title)
        filename = f"orquesta_{title[:30].replace(' ', '_').replace('/', '')}.pdf"
        mime = "application/pdf"
    return file_bytes, filename, mime

class OrchestrateReq(BaseModel):
    prompt: str
    history: list = []
    mode: str = "general"
    username: str = ""
    language: str = ""

class OrchestrateResp(BaseModel):
    result: str
    task_type: str
    model_label: str
    latency_ms: int
    image_url: str = ""
    detected_language: str = ""
    file_url: str = ""
    file_type: str = ""
    file_name: str = ""

@router.post("/orchestrate", response_model=OrchestrateResp)
async def orchestrate(req: OrchestrateReq):
    if not req.prompt.strip():
        raise HTTPException(400, "Prompt vacío")
    t0 = time.time()
    task = classify(req.prompt, req.mode)
    label = TASK_LABELS.get(task, "groq · llama 3.3")
    img_url = file_url = file_type = file_name = result = ""
    system = get_system(req.mode, req.username)

    try:
        if task.startswith("file_gen_"):
            ftype = task.replace("file_gen_", "")
            try:
                file_bytes, fname, mime = await generate_file_from_prompt(req.prompt, ftype, req.username)
                token = cache_file(file_bytes, fname, mime)
                file_url = f"/api/download/{token}"
                file_type = ftype
                file_name = fname
                names = {"xlsx": "Excel", "docx": "Word", "pdf": "PDF"}
                result = f"✅ Tu archivo **{names.get(ftype, ftype.upper())}** está listo. Hacé clic en el botón para descargarlo."
                label = f"orquesta · {names.get(ftype, ftype).lower()}"
            except Exception as e:
                result = f"Error generando el archivo: {str(e)[:200]}. Reformulá tu pedido."
                label = "error"

        elif task == "image_gen":
            img_url, result, label = await generate_image_smart(req.prompt)

        elif task == "realtime":
            try:
                ctx = await deep_search(req.prompt)
                if ctx:
                    synth = (
                        f'El usuario pregunta: "{req.prompt}"\n\n'
                        f"=== INFORMACIÓN DE MÚLTIPLES FUENTES DE INTERNET ===\n{ctx}\n\n"
                        f"Con toda esa información, respondé de forma COMPLETA Y DETALLADA en el mismo idioma. "
                        f"Integrá los datos de todas las fuentes. Citá cifras concretas. "
                        f"Si hay papers científicos, mencioná los hallazgos clave. "
                        f"Nunca respondas de forma vaga — usá TODOS los datos disponibles."
                    )
                    msgs = build_messages(system, req.history[:-1], synth)
                    result, used = await groq_with_fallback(msgs, "llama-3.3-70b-versatile")
                    sources = []
                    if TAVILY_KEY: sources.append("web")
                    if "WIKIPEDIA" in ctx: sources.append("wiki")
                    if "PAPER" in ctx: sources.append("arXiv")
                    label = "orquesta · " + "+".join(sources) if sources else "orquesta · búsqueda"
                else:
                    msgs = build_messages(system, req.history, req.prompt)
                    result, _ = await groq_with_fallback(msgs, "llama-3.3-70b-versatile")
                    label = "groq · llama 3.3"
            except Exception:
                msgs = build_messages(system, req.history, req.prompt)
                result, _ = await groq_with_fallback(msgs, "llama-3.3-70b-versatile")
                label = "groq · llama 3.3"

        elif task == "translate":
            ts = system + "\n\nEres un traductor experto. Traducí con precisión y naturalidad."
            msgs = build_messages(ts, req.history, req.prompt); result, _ = await groq_with_fallback(msgs, "llama-3.3-70b-versatile"); label = "groq · traductor"

        else:
            model = TASK_MODELS.get(task, "llama-3.3-70b-versatile")
            # For analysis tasks, enrich with search context
            if task == "analysis" and TAVILY_KEY:
                try:
                    ctx = await deep_search(req.prompt)
                    if ctx:
                        enriched = f'"{req.prompt}"\n\nDatos de internet para enriquecer el análisis:\n{ctx[:3000]}\n\nRealizá un análisis PROFUNDO Y COMPARATIVO usando estos datos reales. Incluí cifras, tendencias y conclusiones específicas.'
                        msgs = build_messages(system, req.history, enriched)
                        result, used = await groq_with_fallback(msgs, model)
                        label = "orquesta · análisis+web"
                    else:
                        msgs = build_messages(system, req.history, req.prompt)
                        result, used = await groq_with_fallback(msgs, model)
                except Exception:
                    msgs = build_messages(system, req.history, req.prompt)
                    result, used = await groq_with_fallback(msgs, model)
            else:
                msgs = build_messages(system, req.history, req.prompt)
                result, used = await groq_with_fallback(msgs, model)
            if used == "gemini": label = "gemini · flash"

    except HTTPException: raise
    except Exception as e: raise HTTPException(502, detail=str(e))

    return OrchestrateResp(result=result, task_type=task, model_label=label,
        latency_ms=int((time.time() - t0) * 1000), image_url=img_url,
        file_url=file_url, file_type=file_type, file_name=file_name)

@router.get("/download/{token}")
async def download_file(token: str):
    if token not in _file_cache: raise HTTPException(404, "Archivo no encontrado o expirado")
    file_bytes, filename, mime = _file_cache[token]
    return Response(content=file_bytes, media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

@router.post("/upload")
async def upload_file(
    prompt: str = Form(default="Analizá este archivo en detalle y explicá su contenido de forma clara y profesional."),
    file: UploadFile = File(...), username: str = Form(default=""), mode: str = Form(default="general"),
):
    t0 = time.time(); raw = await file.read(); fname = (file.filename or "").lower(); mime = file.content_type or ""; system = get_system(mode, username)
    async def groq_analyze(text):
        full_prompt = f"Archivo: {file.filename}\n\nContenido:\n{text[:14000]}\n\nConsulta: {prompt}"
        msgs = build_messages(system, [], full_prompt); result, used = await groq_with_fallback(msgs, "llama-3.3-70b-versatile")
        return result, ("gemini · flash" if used == "gemini" else "groq · llama 3.3")

    result = ""; label = "orquesta"; img_url = ""
    try:
        is_image = mime.startswith("image/") or any(fname.endswith(x) for x in [".jpg",".jpeg",".png",".gif",".webp",".bmp"])
        is_edit = is_image and any(k in prompt.lower() for k in IMAGE_EDIT_KW)
        if is_image and is_edit:
            if OPENAI_KEY:
                try: img_url = await call_openai_image_edit(raw, prompt); result = "Imagen editada con GPT-4o + DALL-E 3."; label = "gpt-4o + dall-e-3"
                except Exception as e:
                    err = str(e)
                    result = "Sin créditos en OpenAI." if "quota" in err.lower() or "billing" in err.lower() else f"Error: {err}"; label = "error"
            else: result = "Para editar imágenes configurá OPENAI_API_KEY."
        elif is_image:
            if GEMINI_KEY: b64 = base64.b64encode(raw).decode(); result = await call_gemini_vision(f"{system}\n\nAnalizá: {prompt}", b64, mime or "image/jpeg"); label = "gemini · visión"
            else: result = "Para analizar imágenes configurá GEMINI_API_KEY."
        elif fname.endswith(".pdf") or mime == "application/pdf":
            if GEMINI_KEY: b64 = base64.b64encode(raw).decode(); result = await call_gemini_vision(f"{system}\n\nAnalizá este PDF: {prompt}", b64, "application/pdf"); label = "gemini · pdf"
            else: result = "Para leer PDFs configurá GEMINI_API_KEY."
        elif fname.endswith(".docx"):
            try:
                from docx import Document; doc = Document(io.BytesIO(raw))
                paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
                tables = []
                for tbl in doc.tables:
                    for row in tbl.rows:
                        rt = " | ".join(c.text.strip() for c in row.cells if c.text.strip())
                        if rt: tables.append(rt)
                text = "\n".join(paras)
                if tables: text += "\n\nTablas:\n" + "\n".join(tables)
                result, label = await groq_analyze(text)
            except Exception as e: result = f"No se pudo leer el archivo Word: {e}."; label = "error"
        elif any(fname.endswith(x) for x in [".xlsx", ".xls"]):
            try:
                import openpyxl; wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
                sheets = []
                for sname in wb.sheetnames[:6]:
                    ws = wb[sname]; rows = []
                    for row in ws.iter_rows(max_row=300, values_only=True):
                        cells = [str(c) for c in row if c is not None]
                        if cells: rows.append(" | ".join(cells))
                    if rows: sheets.append(f"=== Hoja: {sname} ===\n" + "\n".join(rows[:150]))
                result, label = await groq_analyze("\n\n".join(sheets))
            except Exception as e: result = f"No se pudo leer el Excel: {e}."; label = "error"
        elif any(fname.endswith(x) for x in [".txt",".md",".csv",".json",".xml",".py",".js",".ts",".html",".css",".sql",".yaml",".yml",".log",".sh"]):
            result, label = await groq_analyze(raw.decode("utf-8", errors="ignore"))
        elif fname.endswith(".doc"): result = "Los .doc (Word 97-2003) no son compatibles. Guardalo como .docx y volvé a subirlo."
        else: result = f"Formato no soportado: {fname}. Compatibles: imágenes, PDF, Word (.docx), Excel (.xlsx), texto, código."
    except Exception as e: raise HTTPException(502, detail=f"Error procesando archivo: {e}")

    return {"result": result, "task_type": "file", "model_label": label, "latency_ms": int((time.time() - t0) * 1000), "image_url": img_url, "filename": file.filename}

@router.post("/tts")
async def text_to_speech(data: dict):
    if not OPENAI_KEY: raise HTTPException(400, "OPENAI_API_KEY no configurada")
    text = data.get("text", ""); voice = data.get("voice", "nova")
    if not text: raise HTTPException(400, "Texto vacío")
    try: audio = await call_openai_tts(text, voice); return StreamingResponse(io.BytesIO(audio), media_type="audio/mpeg")
    except Exception as e: raise HTTPException(502, str(e))

@router.post("/stt")
async def speech_to_text(file: UploadFile = File(...)):
    if not OPENAI_KEY: raise HTTPException(400, "OPENAI_API_KEY no configurada")
    try: audio_bytes = await file.read(); text = await call_openai_stt(audio_bytes, file.filename or "audio.webm"); return {"text": text}
    except Exception as e: raise HTTPException(502, str(e))

@router.get("/status")
async def status():
    return {"groq": bool(GROQ_KEY), "tavily": bool(TAVILY_KEY), "gemini": bool(GEMINI_KEY), "openai": bool(OPENAI_KEY), "file_generation": True}
