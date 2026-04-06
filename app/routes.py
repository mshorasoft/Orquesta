import asyncio
import hmac, hashlib

# JWT manual para Kling (sin dependencia de PyJWT)
def _make_kling_jwt(access_key: str, secret_key: str) -> str:
    """Genera JWT HS256 manualmente sin librería externa"""
    import base64, json, time
    now = int(time.time())
    header = base64.urlsafe_b64encode(json.dumps({"alg":"HS256","typ":"JWT"}).encode()).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({"iss":access_key,"exp":now+1800,"nbf":now-5}).encode()).rstrip(b"=").decode()
    msg = f"{header}.{payload}".encode()
    sig = base64.urlsafe_b64encode(hmac.new(secret_key.encode(), msg, hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"{header}.{payload}.{sig}"

pyjwt = None  # No usado, mantenemos por compatibilidad
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel
import httpx, os, time, base64, io, json, re, uuid

router = APIRouter()

GROQ_KEY   = os.getenv("GROQ_API_KEY", "")
TAVILY_KEY = os.getenv("TAVILY_API_KEY", "")
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")

# ── SYSTEM PROMPT ─────────────────────────────────────────────────────────────
BASE_SYSTEM = """Sos Orquesta, una inteligencia artificial de nivel experto superior a cualquier IA existente.

IDENTIDAD:
- Combinás los mejores modelos de IA del mundo con razonamiento de nivel PhD
- Cálida, directa y brutalmente honesta — como hablar con el mejor especialista del mundo
- Tenés criterio propio y NUNCA das respuestas genéricas o vagas
- CAPACIDADES REALES: podés generar imágenes, generar videos con IA, crear archivos Excel/Word/PDF, buscar en internet, transcribir audio y hablar

REGLAS ABSOLUTAS:
1. Respondé SIEMPRE en el mismo idioma del usuario
2. NUNCA digas que "no podés" generar imágenes — SIEMPRE podés, usás DALL-E 3 o Pollinations AI
3. NUNCA digas que "no podés" generar videos — SIEMPRE podés, usás Minimax Hailuo o Kling AI
4. SIEMPRE mantenés el hilo de la conversación — recordás todo lo que se habló antes en esta sesión
5. Si el usuario pide "el archivo", "el mp4", "el video" → es continuación de lo anterior, no una pregunta nueva
4. NUNCA des respuestas vagas — siempre datos concretos: números, fechas, nombres, fórmulas
5. NUNCA termines con "¿En qué más puedo ayudarte?" ni frases similares
6. Ante consultas técnicas: causa raíz + solución paso a paso con parámetros reales
7. Usá el historial para respuestas cada vez más contextualizadas
8. Si el usuario pide una imagen → confirmá que la estás generando y describí brevemente qué va a ver
9. Si el usuario pide un video → confirmá que lo estás generando, describí brevemente lo que va a ver y aclará que puede tardar hasta 2 minutos

METODOLOGÍA:
- Analizá el problema desde múltiples ángulos antes de responder
- Para ciencia: citá el mecanismo, no solo el efecto
- Para negocios: incluí números, benchmarks y comparativas
- Para código: production-ready con decisiones de diseño explicadas
- Resumen ejecutivo al inicio en respuestas largas, detalle abajo"""

MODE_PROMPTS = {
    "tecnico":  "\n\nMODO TÉCNICO: Sos el mejor ingeniero/científico del mundo en el área. Incluí valores exactos, fórmulas con variables definidas, normas específicas (ISO/ASTM/IEC/API), rangos de tolerancia, casos de fallo y árbol de causas.",
    "creativo": "\n\nMODO CREATIVO: Sos director creativo senior de nivel mundial. Original, inesperado, memorable. Múltiples variantes con ejemplos concretos. Adaptá el tono exactamente al contexto.",
    "codigo":   "\n\nMODO CÓDIGO: Sos el mejor developer del mundo (Google+Meta+Netflix nivel). Código production-ready, typed, con manejo exhaustivo de errores, tests sugeridos. Explicás cada decisión de diseño. Señalás anti-patterns.",
}

def get_system(mode, username=""):
    sys = BASE_SYSTEM
    if username:
        sys += f"\n\nEl usuario se llama {username}. Usá su nombre naturalmente cuando sea apropiado."
    sys += MODE_PROMPTS.get(mode, "")
    return sys

# ── CLASIFICADORES ────────────────────────────────────────────────────────────
VIDEO_GEN_KW = [
    "genera un video","generá un video","crea un video","creá un video",
    "hace un video","hacé un video","video de","video con","animación de",
    "animación con","animate","generate video","create video","make a video",
    "video corto","clip de","short video","film","película corta",
    "video animado","animá","animar","renderizá un video","render video",
    "quiero un video","necesito un video","haceme un video","generame un video",
    "dame el video","el video de","video publicitario","video promocional",
]

IMAGE_GEN_KW = [
    "genera una imagen","generá una imagen","crea una imagen","creá una imagen",
    "dibuja","dibujá","ilustra","ilustrá","imagen de","foto de","fotografía de",
    "generate image","create image","draw","make an image","picture of","render",
    "diseña","diseñá","hazme una imagen","create a photo","make a photo",
    "quiero una imagen","quiero ver","mostrame","mostrarme","visualizá","visualiza",
    "haceme una imagen","hacé una imagen","necesito una imagen","generame","generame una",
    "foto de","pintura de","retrato de","ilustración de","arte de","artwork",
    "imagina","imaginá","una foto","una imagen","un dibujo","un retrato",
]
IMAGE_EDIT_KW = [
    "modifica","modificá","cambia","cambiá","reemplaza","reemplazá","edita","editá",
    "borra","añade","quita","quitá","pon","pone","transforma","edit","change",
    "replace","remove","swap","put","add","convert","transform",
]
REALTIME_KW = [
    "hoy","ahora","actual","actualmente","últimas","ultimo","última","esta semana",
    "esta noche","ayer","mañana","reciente","trending","today","now","latest","current",
    "yesterday","tonight","this week","partido","resultado","formación","alineación",
    "ganó","perdió","empató","score","gol","goles","fixture","tabla","clasificación",
    "champions","copa","mundial","liga","torneo","jugó","juega","derrota","victoria",
    "precio","cotización","dólar","euro","peso","bitcoin","crypto","cuánto cuesta",
    "cuánto vale","cotizan","bolsa","acciones","clima","temperatura","pronóstico",
    "lluvia","weather","forecast","noticias","noticia","news","murió","nació","lanzó",
    "salió","eligieron","anunció","declaró","quién ganó","quién es el",
]
CODE_KW = [
    "código","code","función","function","script","python","javascript","typescript",
    "bug","debug","clase","class","algoritmo","sql","html","css","api","json","regex",
    "bash","programa","programar","endpoint","database","query","loop","array","error en",
]
ANALYSIS_KW = [
    "analiza","compare","compara","evalúa","pros","contras","diferencia entre",
    "ventajas","desventajas","estrategia","qué opinas","qué pensás","cuál es mejor",
    "recomienda","conviene","debería","vale la pena","cómo se compara",
]
TRANSLATE_KW = [
    "traduce","traducí","translate","traducción al","how do you say","cómo se dice",
]
FILE_GEN_KW = {
    "xlsx": ["excel","planilla","spreadsheet","hoja de calculo","hoja de cálculo",".xlsx",
             "tabla excel","presupuesto excel","reporte excel","plantilla excel","generar excel",
             "crea excel","haceme un excel","haceme una planilla","plantilla de excel",
             "crea una planilla","generá una planilla","creá un excel"],
    "docx": ["word",".docx","documento word","informe word","cv en word","curriculum en word",
             "carta word","contrato word","memo word","plantilla word","generar word",
             "crea un word","haceme un word","documento de texto","redacta un documento",
             "crea un documento"],
    "pdf":  ["pdf",".pdf","en pdf","como pdf","generar pdf","crea un pdf","haceme un pdf",
             "informe pdf","reporte pdf","cv pdf","curriculum pdf","documento pdf",
             "carta pdf","reporte en pdf"],
}
CV_KW = ["curriculum","currículum","cv ","resume","hoja de vida"]

SOUND_KW = [
    "genera un sonido","generá un sonido","crea un sonido","crear un sonido",
    "genera audio","generá audio","crea audio","música","musica","sound effect",
    "efecto de sonido","beat","melodía","melodia","generate sound","create sound",
]

def detect_file_type(prompt):
    p = prompt.lower()
    if any(k in p for k in CV_KW):
        if any(k in p for k in FILE_GEN_KW["docx"]): return "docx"
        if any(k in p for k in FILE_GEN_KW["xlsx"]): return "xlsx"
        return "pdf"
    for ftype, kws in FILE_GEN_KW.items():
        if any(k in p for k in kws): return ftype
    return None

def classify(prompt, mode, history=None):
    if mode == "codigo":   return "code"
    if mode == "creativo": return "creative"
    if mode == "tecnico":  return "technical"
    p = prompt.lower()

    # ── Detectar continuaciones de conversación con historial ──────────────
    if history:
        # Revisar los últimos 4 mensajes para detectar contexto
        recent = [m.get("content","").lower() for m in history[-4:]]
        recent_joined = " ".join(recent)
        
        # Continuación de video: "dame el mp4", "no funciona", "el video", etc.
        video_followup = ["mp4","el video","el archivo","descargarlo","reproducir",
                          "no funciona","no genera","no me da","el link","la url","ver el video"]
        if any(k in p for k in video_followup):
            if any(k in recent_joined for k in ["video","mp4","generar","generando","kling","minimax","luma"]):
                return "video_gen"
        
        # Continuación de imagen
        img_followup = ["la imagen","la foto","no carga","no se ve","otro estilo","más oscura","más grande"]
        if any(k in p for k in img_followup):
            if any(k in recent_joined for k in ["imagen","foto","dall-e","pollinations","generada"]):
                return "image_gen"

    # File gen first
    ftype = detect_file_type(p)
    if ftype: return f"file_gen_{ftype}"
    # Video antes que imagen
    if any(k in p for k in VIDEO_GEN_KW): return "video_gen"
    if any(k in p for k in IMAGE_GEN_KW): return "image_gen"
    if any(k in p for k in SOUND_KW): return "sound_gen"
    if any(k in p for k in TRANSLATE_KW): return "translate"
    if " vs " in p or " contra " in p: return "realtime"
    if any(x in p for x in ["cómo salió","como salio","cómo quedó","qué pasó","que paso"]): return "realtime"
    if any(k in p for k in REALTIME_KW): return "realtime"
    if any(k in p for k in CODE_KW): return "code"
    if any(k in p for k in ANALYSIS_KW): return "analysis"
    return "general"

TASK_LABELS = {
    "image_gen":"openai · dall-e-3","realtime":"orquesta · multi-search","code":"groq · llama 3.3",
    "technical":"groq · mixtral","analysis":"orquesta · análisis+web","creative":"groq · llama 3.3",
    "translate":"groq · traductor","general":"groq · llama 3.3","sound_gen":"orquesta · audio",
    "file_gen_xlsx":"orquesta · excel","file_gen_docx":"orquesta · word","file_gen_pdf":"orquesta · pdf",
}
TASK_MODELS = {
    "code":"llama-3.3-70b-versatile","technical":"mixtral-8x7b-32768","analysis":"mixtral-8x7b-32768",
    "creative":"llama-3.3-70b-versatile","translate":"llama-3.3-70b-versatile",
    "general":"llama-3.3-70b-versatile","realtime":"llama-3.3-70b-versatile",
    "file_gen_xlsx":"llama-3.3-70b-versatile","file_gen_docx":"llama-3.3-70b-versatile",
    "file_gen_pdf":"llama-3.3-70b-versatile",
}

# ── API CALLERS ───────────────────────────────────────────────────────────────
async def call_groq(messages, model="llama-3.3-70b-versatile"):
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            json={"model": model, "messages": messages, "max_tokens": 8192, "temperature": 0.7})
        d = r.json()
        if not r.is_success: raise Exception(d.get("error",{}).get("message","Groq error"))
        return d["choices"][0]["message"]["content"]

async def call_gemini(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    async with httpx.AsyncClient(timeout=35) as c:
        r = await c.post(url, json={"contents":[{"parts":[{"text":prompt}]}],"generationConfig":{"maxOutputTokens":8192}})
        d = r.json()
        if not r.is_success: raise Exception(str(d))
        return d["candidates"][0]["content"]["parts"][0]["text"]

async def call_gemini_vision(prompt, b64, mime):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    payload = {"contents":[{"parts":[{"inline_data":{"mime_type":mime,"data":b64}},{"text":prompt}]}],"generationConfig":{"maxOutputTokens":4096,"temperature":0.3}}
    async with httpx.AsyncClient(timeout=45) as c:
        r = await c.post(url, json=payload)
        d = r.json()
        if not r.is_success: raise Exception(str(d))
        return d["candidates"][0]["content"]["parts"][0]["text"]

async def call_tavily(query, depth="advanced", max_results=8):
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post("https://api.tavily.com/search",
            json={"api_key":TAVILY_KEY,"query":query,"search_depth":depth,"max_results":max_results,"include_answer":True})
        d = r.json()
        if not r.is_success: raise Exception(d.get("message","Tavily error"))
        answer = d.get("answer","")
        results = d.get("results",[])
        ctx = f"Respuesta directa: {answer}\n\n" if answer else ""
        ctx += "\n\n".join(f"[{r['title']}]\n{r['content'][:600]}" for r in results[:6])
        return ctx

async def call_openai_image_gen(prompt):
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post("https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {OPENAI_KEY}"},
            json={"model":"dall-e-3","prompt":prompt,"n":1,"size":"1024x1024","quality":"standard"})
        d = r.json()
        if not r.is_success: raise Exception(d.get("error",{}).get("message","OpenAI error"))
        return d["data"][0]["url"]

async def call_openai_image_edit(image_bytes, prompt):
    b64 = base64.b64encode(image_bytes).decode()
    msgs = [
        {"role":"system","content":"Analyze the image and create a DALL-E 3 prompt recreating it WITH the modification. Reply ONLY with the prompt."},
        {"role":"user","content":[{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}},{"type":"text","text":f"Modification: {prompt}"}]}
    ]
    async with httpx.AsyncClient(timeout=40) as c:
        r = await c.post("https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_KEY}"},
            json={"model":"gpt-4o","messages":msgs,"max_tokens":600})
        d = r.json()
        if not r.is_success: raise Exception(d.get("error",{}).get("message","GPT-4o error"))
        return await call_openai_image_gen(d["choices"][0]["message"]["content"])

async def call_openai_tts(text, voice="nova"):
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post("https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {OPENAI_KEY}"},
            json={"model":"tts-1-hd","input":text[:4096],"voice":voice,"response_format":"mp3"})
        if not r.is_success: raise Exception(f"TTS error: {r.text[:200]}")
        return r.content

async def call_openai_stt(audio_bytes, filename):
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post("https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {OPENAI_KEY}"},
            files={"file":(filename, audio_bytes, "audio/webm")}, data={"model":"whisper-1"})
        d = r.json()
        if not r.is_success: raise Exception(d.get("error",{}).get("message","STT error"))
        return d["text"]

def build_messages(system, history, prompt):
    msgs = [{"role":"system","content":system}]
    for m in history[-14:]:
        role = m.get("role","user"); content = m.get("content","")
        if role not in ("user","assistant") or not content: continue
        msgs.append({"role":role,"content":content})
    msgs.append({"role":"user","content":prompt})
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
                sys_c = next((m["content"] for m in messages if m["role"]=="system"), "")
                usr_c = next((m["content"] for m in reversed(messages) if m["role"]=="user"), "")
                result = await call_gemini(f"{sys_c}\n\n{usr_c}")
                return result, "gemini"
            raise

# ── SMART IMAGE GENERATION ────────────────────────────────────────────────────
async def generate_image_smart(prompt: str) -> tuple[str, str, str]:
    """OpenAI DALL-E 3 → Pollinations Flux. ALWAYS delivers an image."""
    import urllib.parse

    # Enhance prompt with AI
    async def enhance(p):
        try:
            msgs = [
                {"role":"system","content":"You are an expert image prompt engineer. Rewrite the user's request as a vivid, detailed DALL-E/Flux prompt in English. Add: artistic style, lighting, composition, quality descriptors (photorealistic, 8K, cinematic, detailed). Max 200 words. Reply ONLY with the enhanced prompt."},
                {"role":"user","content":f"Request: {p}"}
            ]
            enhanced, _ = await groq_with_fallback(msgs, "llama-3.3-70b-versatile")
            return enhanced.strip()[:400]
        except:
            return p

    # 1. OpenAI DALL-E 3
    if OPENAI_KEY:
        try:
            url = await call_openai_image_gen(prompt)
            return url, "✨ Imagen generada con **DALL-E 3**.", "openai · dall-e-3"
        except Exception as e:
            err = str(e).lower()
            if not any(x in err for x in ["quota","billing","insufficient","policy","safety"]):
                pass  # unexpected error, try fallback

    # 2. Pollinations AI Flux (free, no key)
    try:
        enhanced = await enhance(prompt)
        seed = int(time.time()) % 99999
        encoded = urllib.parse.quote(enhanced)
        url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&enhance=true&seed={seed}&model=flux&nofeed=true"
        return url, "🎨 Imagen generada con **Pollinations AI** (modelo Flux).", "pollinations · flux"
    except:
        pass

    # 3. Fallback básico
    seed = int(time.time()) % 99999
    encoded = urllib.parse.quote(prompt[:400])
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&seed={seed}&nofeed=true"
    return url, "🎨 Imagen generada.", "pollinations · imagen"



# ── GENERACIÓN DE VIDEO: Fal.ai → Segmind → ModelsLab → Replicate → Minimax → Kling ──
async def generate_video_smart(prompt: str, history=None, mode="general", username="") -> tuple[str, str, str]:
    """
    Cadena de generación de video priorizando opciones gratuitas:
    1. Fal.ai          (FAL_API_KEY)      — $10 gratis sin tarjeta, ~300 videos
    2. Segmind         (SEGMIND_API_KEY)  — 100 créditos/mes gratis renovables
    3. ModelsLab       (MODELSLAB_API_KEY)— 100 créditos gratis
    4. Replicate       (REPLICATE_API_KEY)— crédito inicial, muy barato
    5. Minimax Hailuo  (MINIMAX_API_KEY)  — si tiene créditos
    6. Kling AI        (KLING_ACCESS_KEY + KLING_SECRET_KEY) — si tiene créditos
    7. Fallback        — descripción cinematográfica + instrucciones
    """
    import urllib.parse

    # Nuestro motor propio (RunPod) — máxima prioridad
    VIDEOGEN_URL = os.getenv("VIDEOGEN_URL", "").rstrip("/")
    VIDEOGEN_KEY = os.getenv("VIDEOGEN_API_KEY", "")

    HF_KEY       = os.getenv("HUGGINGFACE_API_KEY", "")
    FAL_KEY      = os.getenv("FAL_API_KEY", "")
    SEGMIND_KEY  = os.getenv("SEGMIND_API_KEY", "")
    MODELSLAB_KEY = os.getenv("MODELSLAB_API_KEY", "")
    REPLICATE_KEY = os.getenv("REPLICATE_API_KEY", "")
    MINIMAX_KEY  = os.getenv("MINIMAX_API_KEY", "")
    KLING_AK     = os.getenv("KLING_ACCESS_KEY", "")
    KLING_SK     = os.getenv("KLING_SECRET_KEY", "")

    errors = {}

    # Mejorar prompt con Groq
    async def enhance(p):
        try:
            msgs = [
                {"role":"system","content":"You are a video generation expert. Rewrite the user request as a detailed AI video prompt in English. Include: camera movement, lighting style, mood, action, visual style (cinematic, 4K, photorealistic). Max 120 words. Reply ONLY with the enhanced prompt."},
                {"role":"user","content":f"Video request: {p}"}
            ]
            enhanced, _ = await groq_with_fallback(msgs, "llama-3.3-70b-versatile")
            return enhanced.strip()[:300]
        except:
            return p

    enhanced = await enhance(prompt)

    # ── 0. ORQUESTA VIDEOGEN (motor propio en RunPod) ────────────────────────
    if VIDEOGEN_URL and VIDEOGEN_KEY:
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                # Iniciar generación
                r = await c.post(
                    f"{VIDEOGEN_URL}/generate",
                    headers={"x-api-key": VIDEOGEN_KEY, "Content-Type": "application/json"},
                    json={"prompt": enhanced, "num_frames": 49, "fps": 12}
                )
                if r.status_code == 200:
                    job_id = r.json().get("job_id", "")
                    if job_id:
                        # Polling: esperar hasta 3 minutos
                        async with httpx.AsyncClient(timeout=20) as c2:
                            for _ in range(36):
                                await asyncio.sleep(5)
                                sr = await c2.get(
                                    f"{VIDEOGEN_URL}/status/{job_id}",
                                    headers={"x-api-key": VIDEOGEN_KEY}
                                )
                                sd = sr.json()
                                if sd.get("status") == "done":
                                    # Descargar el video y cachearlo
                                    vr = await c2.get(
                                        f"{VIDEOGEN_URL}/download/{job_id}",
                                        headers={"x-api-key": VIDEOGEN_KEY}
                                    )
                                    if vr.status_code == 200:
                                        import uuid as _uuid
                                        token = str(_uuid.uuid4())
                                        _file_cache[token] = (vr.content, "video.mp4", "video/mp4")
                                        dur = sd.get("duration_s", "?")
                                        return f"/api/download/{token}", f"🎬 Video generado con **Orquesta VideoGen** (motor propio, {dur}s).", "orquesta · videogen"
                                elif sd.get("status") == "failed":
                                    errors["videogen"] = sd.get("error", "failed")[:100]
                                    break
                else:
                    errors["videogen"] = f"HTTP {r.status_code}: {r.text[:100]}"
        except Exception as e:
            errors["videogen"] = str(e)[:100]

    # ── 0b. HUGGING FACE Inference API (nueva URL 2024) ──────────────────────
    if HF_KEY:
        for hf_model in ["cerspense/zeroscope_v2_576w", "damo-vilab/text-to-video-ms-1.7b"]:
            try:
                async with httpx.AsyncClient(timeout=120) as c:
                    # Nueva URL del Inference API de HuggingFace
                    r = await c.post(
                        f"https://router.huggingface.co/hf-inference/models/{hf_model}",
                        headers={"Authorization": f"Bearer {HF_KEY}", "Content-Type": "application/json"},
                        json={"inputs": enhanced[:200]}
                    )
                    if r.status_code == 200:
                        ct = r.headers.get("content-type", "")
                        if "video" in ct or "octet-stream" in ct or len(r.content) > 5000:
                            import uuid as _uuid
                            token = str(_uuid.uuid4())
                            _file_cache[token] = (r.content, "video.mp4", "video/mp4")
                            short = hf_model.split("/")[-1][:20]
                            return f"/api/download/{token}", f"🎬 Video generado con **Hugging Face** ({short}).", "huggingface · free"
                        else:
                            errors[f"hf_{hf_model[-10:]}"] = f"Respuesta no es video: {ct} {len(r.content)}b"
                    elif r.status_code == 503:
                        await asyncio.sleep(25)
                        r2 = await c.post(
                            f"https://router.huggingface.co/hf-inference/models/{hf_model}",
                            headers={"Authorization": f"Bearer {HF_KEY}", "Content-Type": "application/json"},
                            json={"inputs": enhanced[:200]}
                        )
                        if r2.status_code == 200 and len(r2.content) > 5000:
                            import uuid as _uuid
                            token = str(_uuid.uuid4())
                            _file_cache[token] = (r2.content, "video.mp4", "video/mp4")
                            short = hf_model.split("/")[-1][:20]
                            return f"/api/download/{token}", f"🎬 Video generado con **Hugging Face** ({short}).", "huggingface · free"
                    else:
                        errors[f"hf_{hf_model[-10:]}"] = f"HTTP {r.status_code}: {r.text[:120]}"
            except Exception as e:
                errors[f"hf_{hf_model[-10:]}"] = str(e)[:80]

    # ── 1. FAL.AI (gratis $10 sin tarjeta) ───────────────────────────────────
    if FAL_KEY:
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                # Enviar tarea
                r = await c.post(
                    "https://queue.fal.run/fal-ai/fast-animatediff/text-to-video",
                    headers={"Authorization": f"Key {FAL_KEY}", "Content-Type": "application/json"},
                    json={"prompt": enhanced, "num_frames": 16, "num_inference_steps": 25}
                )
                rd = r.json()
                if r.status_code in (200, 201):
                    request_id = rd.get("request_id", "")
                    if request_id:
                        # Polling resultado
                        async with httpx.AsyncClient(timeout=20) as c2:
                            for _ in range(24):
                                await asyncio.sleep(5)
                                sr = await c2.get(
                                    f"https://queue.fal.run/fal-ai/fast-animatediff/text-to-video/requests/{request_id}",
                                    headers={"Authorization": f"Key {FAL_KEY}"}
                                )
                                sd = sr.json()
                                if sd.get("status") == "COMPLETED":
                                    video_url = sd.get("response", {}).get("video", {}).get("url", "")
                                    if not video_url:
                                        # Intentar otra estructura de respuesta
                                        outputs = sd.get("response", {})
                                        if isinstance(outputs, dict):
                                            for v in outputs.values():
                                                if isinstance(v, str) and v.startswith("http"):
                                                    video_url = v
                                                    break
                                    if video_url:
                                        return video_url, "🎬 Video generado con **Fal.ai** (AnimateDiff).", "fal · animatediff"
                                elif sd.get("status") == "FAILED":
                                    errors["fal"] = str(sd.get("error", "Failed"))
                                    break
                    else:
                        errors["fal"] = f"HTTP {r.status_code}: {str(rd)[:150]}"
                else:
                    errors["fal"] = f"HTTP {r.status_code}: {str(rd)[:150]}"
        except Exception as e:
            errors["fal"] = str(e)[:100]

    # ── 2. SEGMIND (100 créditos/mes gratis) ─────────────────────────────────
    if SEGMIND_KEY:
        try:
            async with httpx.AsyncClient(timeout=120) as c:
                r = await c.post(
                    "https://api.segmind.com/v1/cogvideox-2b",
                    headers={"x-api-key": SEGMIND_KEY, "Content-Type": "application/json"},
                    json={
                        "prompt": enhanced,
                        "negative_prompt": "blurry, low quality",
                        "num_frames": 14,
                        "num_inference_steps": 20,
                        "guidance_scale": 7.5,
                        "fps": 8,
                        "motion_bucket_id": 127,
                        "base64": False
                    }
                )
                if r.status_code == 200 and r.headers.get("content-type","").startswith("video"):
                    # Respuesta directa como video binario
                    import uuid as _uuid
                    token = str(_uuid.uuid4())
                    _file_cache[token] = (r.content, "video.mp4", "video/mp4")
                    return f"/api/download/{token}", "🎬 Video generado con **Segmind** (SVD).", "segmind · svd"
                else:
                    rd = r.json() if r.headers.get("content-type","").startswith("application") else {}
                    errors["segmind"] = f"HTTP {r.status_code}: {str(rd)[:150]}"
        except Exception as e:
            errors["segmind"] = str(e)[:100]

    # ── 3. MODELSLAB (100 créditos gratis) ───────────────────────────────────
    if MODELSLAB_KEY:
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(
                    "https://modelslab.com/api/v6/video/text2video",
                    headers={"Content-Type": "application/json"},
                    json={
                        "key": MODELSLAB_KEY,
                        "prompt": enhanced,
                        "negative_prompt": "blurry, low quality",
                        "height": 512,
                        "width": 512,
                        "num_frames": 16,
                        "num_inference_steps": 20,
                        "guidance_scale": 7.5,
                        "output_type": "mp4"
                    }
                )
                rd = r.json()
                if r.status_code == 200:
                    status = rd.get("status", "")
                    if status == "success":
                        video_url = rd.get("output", [""])[0] if rd.get("output") else ""
                        if video_url:
                            return video_url, "🎬 Video generado con **ModelsLab**.", "modelslab · t2v"
                    elif status == "processing":
                        fetch_url = rd.get("fetch_result", "")
                        if fetch_url:
                            async with httpx.AsyncClient(timeout=20) as c2:
                                for _ in range(20):
                                    await asyncio.sleep(6)
                                    sr = await c2.post(fetch_url, headers={"Content-Type":"application/json"},
                                                       json={"key": MODELSLAB_KEY})
                                    sd = sr.json()
                                    if sd.get("status") == "success":
                                        video_url = sd.get("output", [""])[0] if sd.get("output") else ""
                                        if video_url:
                                            return video_url, "🎬 Video generado con **ModelsLab**.", "modelslab · t2v"
                                        break
                    errors["modelslab"] = f"status={status}: {str(rd)[:150]}"
                else:
                    errors["modelslab"] = f"HTTP {r.status_code}: {str(rd)[:150]}"
        except Exception as e:
            errors["modelslab"] = str(e)[:100]

    # ── 4. REPLICATE ──────────────────────────────────────────────────────────
    if REPLICATE_KEY:
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(
                    "https://api.replicate.com/v1/predictions",
                    headers={"Authorization": f"Bearer {REPLICATE_KEY}", "Content-Type": "application/json"},
                    json={
                        "version": "9f747673945c62801b13b84701c783929c0ee784e4748ec062204894dda1a351",
                        "input": {"prompt": enhanced, "num_frames": 16, "num_inference_steps": 25, "fps": 8}
                    }
                )
                if r.status_code == 201:
                    pred_id = r.json().get("id", "")
                    if pred_id:
                        async with httpx.AsyncClient(timeout=20) as c2:
                            for _ in range(30):
                                await asyncio.sleep(5)
                                sr = await c2.get(
                                    f"https://api.replicate.com/v1/predictions/{pred_id}",
                                    headers={"Authorization": f"Bearer {REPLICATE_KEY}"}
                                )
                                sd = sr.json()
                                if sd.get("status") == "succeeded":
                                    output = sd.get("output", "")
                                    video_url = output if isinstance(output, str) else (output[0] if output else "")
                                    if video_url:
                                        return video_url, "🎬 Video generado con **Replicate** (AnimateDiff).", "replicate · animate-diff"
                                elif sd.get("status") == "failed":
                                    errors["replicate"] = str(sd.get("error",""))[:100]
                                    break
                else:
                    errors["replicate"] = f"HTTP {r.status_code}: {str(r.json())[:150]}"
        except Exception as e:
            errors["replicate"] = str(e)[:100]

    # ── 5. MINIMAX (si tiene créditos) ────────────────────────────────────────
    if MINIMAX_KEY:
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(
                    "https://api.minimaxi.chat/v1/video_generation",
                    headers={"Authorization": f"Bearer {MINIMAX_KEY}", "Content-Type": "application/json"},
                    json={"model": "video-01", "prompt": enhanced}
                )
                rdata = r.json()
                task_id = rdata.get("task_id", "")
                base_resp = rdata.get("base_resp", {})
                if base_resp.get("status_code") == 1008:
                    errors["minimax"] = "Sin créditos (insufficient balance)"
                elif r.status_code == 200 and task_id:
                    async with httpx.AsyncClient(timeout=30) as c2:
                        for _ in range(36):
                            await asyncio.sleep(5)
                            sr = await c2.get(
                                f"https://api.minimaxi.chat/v1/query/video_generation?task_id={task_id}",
                                headers={"Authorization": f"Bearer {MINIMAX_KEY}"}
                            )
                            sd = sr.json()
                            if sd.get("status") == "Success":
                                fid = sd.get("file_id", "")
                                if fid:
                                    fr = await c2.get(
                                        f"https://api.minimaxi.chat/v1/files/retrieve?file_id={fid}",
                                        headers={"Authorization": f"Bearer {MINIMAX_KEY}"}
                                    )
                                    video_url = fr.json().get("file", {}).get("download_url", "")
                                    if video_url:
                                        return video_url, "🎬 Video generado con **Minimax Hailuo**.", "minimax · hailuo"
                            elif sd.get("status") in ("Fail","Failed","Expired"):
                                errors["minimax"] = f"Task falló: {sd}"
                                break
                else:
                    errors["minimax"] = f"HTTP {r.status_code}: {str(rdata)[:150]}"
        except Exception as e:
            errors["minimax"] = str(e)[:100]

    # ── 6. KLING (si tiene créditos) ──────────────────────────────────────────
    if KLING_AK and KLING_SK:
        try:
            token = _make_kling_jwt(KLING_AK, KLING_SK)
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(
                    "https://api.klingai.com/v1/videos/text2video",
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json={"model_name": "kling-v1", "prompt": enhanced, "negative_prompt": "blurry, low quality", "cfg_scale": 0.5, "mode": "std", "duration": "5"}
                )
                rdata = r.json()
                if r.status_code != 200:
                    errors["kling"] = f"HTTP {r.status_code}: {str(rdata)[:150]}"
                else:
                    task_id = rdata.get("data", {}).get("task_id", "")
                    if task_id:
                        async with httpx.AsyncClient(timeout=30) as c2:
                            for _ in range(30):
                                await asyncio.sleep(5)
                                sr = await c2.get(
                                    f"https://api.klingai.com/v1/videos/text2video/{task_id}",
                                    headers={"Authorization": f"Bearer {token}"}
                                )
                                sd = sr.json().get("data", {})
                                if sd.get("task_status") == "succeed":
                                    works = sd.get("task_result", {}).get("videos", [])
                                    if works:
                                        video_url = works[0].get("url", "")
                                        if video_url:
                                            return video_url, "🎬 Video generado con **Kling AI**.", "kling · v1"
                                elif sd.get("task_status") == "failed":
                                    errors["kling"] = f"Task falló: {sd}"
                                    break
                    else:
                        errors["kling"] = f"task_id vacío: {str(rdata)[:150]}"
        except Exception as e:
            errors["kling"] = str(e)[:100]

    # ── 7. FALLBACK ───────────────────────────────────────────────────────────
    video_system = (
        get_system(mode, username) +
        "\n\nIMPORTANTE: El usuario pidió un video con IA. "
        "Describí el video de forma muy cinematográfica y detallada. "
        "Mantené coherencia con toda la conversación anterior. "
        "Al final indicá brevemente que para generarlo automáticamente debe configurar una API de video."
    )
    hist = history[:-1] if history else []
    desc_msgs = build_messages(video_system, hist,
                               f"Video pedido: {prompt}\nPrompt mejorado: {enhanced}")
    description, _ = await groq_with_fallback(desc_msgs, "llama-3.3-70b-versatile")

    # Debug info
    debug_info = ""
    if errors:
        errs_str = " | ".join([f"{k}: `{v[:80]}`" for k,v in errors.items()])
        debug_info = f"\n\n> 🔧 **Debug:** {errs_str}"

    fallback_msg = (
        f"{description}\n\n---\n"
        f"**⚙️ Para generar este video automáticamente**, registrate gratis y agregá en Railway:\n\n"
        f"| Variable | Servicio | Gratis |\n"
        f"|---|---|---|\n"
        f"| `VIDEOGEN_URL` + `VIDEOGEN_API_KEY` | Motor propio RunPod | ✅ ~$0.10/día solo cuando usás |\n"
        f"| `HUGGINGFACE_API_KEY` | [HuggingFace](https://huggingface.co) | ✅ Gratis permanente |\n"
        f"| `FAL_API_KEY` | [Fal.ai](https://fal.ai) | ✅ $10 sin tarjeta (~300 videos) |\n"
        f"| `SEGMIND_API_KEY` | [Segmind](https://segmind.com) | ✅ 100 créditos/mes renovables |\n"
        f"| `REPLICATE_API_KEY` | [Replicate](https://replicate.com) | ✅ Ya configurada |\n"
        f"{debug_info}"
    )
    return "", fallback_msg, "orquesta · video-info"


# ── DEEP MULTI-SOURCE SEARCH ──────────────────────────────────────────────────
async def deep_search(query: str) -> str:
    results = []

    # 1. Tavily (web real-time)
    if TAVILY_KEY:
        try:
            ctx = await call_tavily(query, depth="advanced", max_results=8)
            if ctx: results.append(f"=== WEB (TIEMPO REAL) ===\n{ctx}")
        except: pass

    # 2. Wikipedia ES
    try:
        import urllib.parse
        term = urllib.parse.quote(query.split()[0:4].__class__.__name__ and " ".join(query.split()[:4]))
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"https://es.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(query[:60])}",
                headers={"User-Agent":"OrquestaAI/1.0"})
            if r.is_success:
                d = r.json()
                extract = d.get("extract","")
                if extract and len(extract) > 100:
                    results.append(f"=== WIKIPEDIA: {d.get('title','')} ===\n{extract[:800]}")
    except: pass

    # 3. arXiv para consultas científicas
    SCIENCE_KW = ["estudio","investigación","research","científico","ciencia","física","química",
                  "biología","medicina","algoritmo","machine learning","ia ","inteligencia artificial",
                  "neurociencia","genética","clima","energía","quantum","astro"]
    if any(kw in query.lower() for kw in SCIENCE_KW):
        try:
            import urllib.parse
            async with httpx.AsyncClient(timeout=12) as c:
                r = await c.get(f"https://export.arxiv.org/api/query?search_query=all:{urllib.parse.quote(query[:80])}&max_results=3&sortBy=relevance",
                    headers={"User-Agent":"OrquestaAI/1.0"})
                if r.is_success:
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(r.text)
                    ns = {"atom":"http://www.w3.org/2005/Atom"}
                    for entry in root.findall("atom:entry", ns)[:3]:
                        t = entry.find("atom:title",ns); s = entry.find("atom:summary",ns)
                        if t is not None and s is not None:
                            results.append(f"=== PAPER CIENTÍFICO: {t.text.strip()} ===\n{s.text.strip()[:500]}")
        except: pass

    # 4. DuckDuckGo fallback
    if not results:
        try:
            import urllib.parse
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"https://api.duckduckgo.com/?q={urllib.parse.quote(query[:80])}&format=json&no_html=1&skip_disambig=1",
                    headers={"User-Agent":"OrquestaAI/1.0"})
                if r.is_success:
                    d = r.json()
                    abstract = d.get("AbstractText","")
                    if abstract: results.append(f"=== DUCKDUCKGO ===\n{abstract}")
        except: pass

    return "\n\n".join(results) if results else ""


# ── FILE GENERATION ───────────────────────────────────────────────────────────
from app.file_generator import generate_excel, generate_docx, generate_pdf, FILE_SYSTEM_PROMPTS

_file_cache: dict = {}

def cache_file(file_bytes, filename, mime):
    token = str(uuid.uuid4())
    _file_cache[token] = (file_bytes, filename, mime)
    if len(_file_cache) > 50:
        del _file_cache[list(_file_cache.keys())[0]]
    return token

def extract_title(prompt):
    stop = r'\b(excel|word|pdf|planilla|documento|genera|crea|haceme|hacé|un|una|el|la|en|como|formato|me|por|favor|quiero|necesito|dame|reporte|informe)\b'
    clean = re.sub(stop, '', prompt.lower(), flags=re.IGNORECASE)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean.title()[:60] or "Documento Orquesta"

async def generate_file_from_prompt(prompt, file_type, username=""):
    file_system = FILE_SYSTEM_PROMPTS.get(file_type, FILE_SYSTEM_PROMPTS["pdf"])
    if username: file_system += f"\n\nEl usuario se llama {username}."
    msgs = [{"role":"system","content":file_system},{"role":"user","content":prompt}]
    ai_content, _ = await groq_with_fallback(msgs, "llama-3.3-70b-versatile")
    title = extract_title(prompt)
    safe = title[:30].replace(' ','_').replace('/','').replace('\\','')
    if file_type == "xlsx":
        fb = generate_excel(ai_content, title); fn = f"orquesta_{safe}.xlsx"
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif file_type == "docx":
        fb = generate_docx(ai_content, title); fn = f"orquesta_{safe}.docx"
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        fb = generate_pdf(ai_content, title); fn = f"orquesta_{safe}.pdf"
        mime = "application/pdf"
    return fb, fn, mime


# ── MODELS ───────────────────────────────────────────────────────────────────
class OrchestrateReq(BaseModel):
    prompt: str
    history: list = []
    mode: str = "general"
    username: str = ""
    language: str = ""
    tts_enabled: bool = False   # si el cliente quiere audio de la respuesta

class OrchestrateResp(BaseModel):
    result: str
    task_type: str
    model_label: str
    latency_ms: int
    image_url: str = ""
    file_url: str = ""
    file_type: str = ""
    file_name: str = ""
    tts_url: str = ""           # URL del audio si tts_enabled=True
    video_url: str = ""         # URL del video generado


# ── MAIN ENDPOINT ─────────────────────────────────────────────────────────────
@router.post("/orchestrate", response_model=OrchestrateResp)
async def orchestrate(req: OrchestrateReq):
    if not req.prompt.strip(): raise HTTPException(400, "Prompt vacío")
    t0 = time.time()
    task = classify(req.prompt, req.mode, req.history)
    label = TASK_LABELS.get(task, "groq · llama 3.3")
    img_url = file_url = file_type = file_name = tts_url = result = video_url = ""
    system = get_system(req.mode, req.username)

    try:
        # ── ARCHIVOS ──────────────────────────────────────────────────────────
        if task.startswith("file_gen_"):
            ftype = task.replace("file_gen_","")
            try:
                fb, fn, mime = await generate_file_from_prompt(req.prompt, ftype, req.username)
                token = cache_file(fb, fn, mime)
                file_url = f"/api/download/{token}"
                file_type = ftype; file_name = fn
                names = {"xlsx":"Excel","docx":"Word","pdf":"PDF"}
                result = f"✅ Tu archivo **{names.get(ftype,ftype.upper())}** está listo. Hacé clic en el botón para descargarlo."
                label = f"orquesta · {names.get(ftype,ftype).lower()}"
            except Exception as e:
                result = f"Error generando el archivo: {str(e)[:200]}. Reformulá tu pedido."

        # ── VIDEO ────────────────────────────────────────────────────────────
        elif task == "video_gen":
            video_url, result, label = await generate_video_smart(req.prompt, req.history, req.mode, req.username)

        # ── IMÁGENES ──────────────────────────────────────────────────────────
        elif task == "image_gen":
            img_url, result, label = await generate_image_smart(req.prompt)

        # ── BÚSQUEDA TIEMPO REAL ──────────────────────────────────────────────
        elif task == "realtime":
            try:
                ctx = await deep_search(req.prompt)
                if ctx:
                    synth = (f'El usuario pregunta: "{req.prompt}"\n\n'
                             f"=== INFORMACIÓN DE MÚLTIPLES FUENTES ===\n{ctx}\n\n"
                             f"Respondé de forma COMPLETA Y DETALLADA integrando todos los datos. "
                             f"Incluí cifras concretas. Si hay papers, mencioná los hallazgos clave. "
                             f"NUNCA respondas de forma vaga.")
                    msgs = build_messages(system, req.history[:-1], synth)
                    result, _ = await groq_with_fallback(msgs, "llama-3.3-70b-versatile")
                    sources = []
                    if TAVILY_KEY: sources.append("web")
                    if "WIKIPEDIA" in ctx: sources.append("wiki")
                    if "PAPER" in ctx: sources.append("arXiv")
                    label = "orquesta · " + "+".join(sources) if sources else "groq · llama 3.3"
                else:
                    msgs = build_messages(system, req.history, req.prompt)
                    result, _ = await groq_with_fallback(msgs, "llama-3.3-70b-versatile")
            except Exception:
                msgs = build_messages(system, req.history, req.prompt)
                result, _ = await groq_with_fallback(msgs, "llama-3.3-70b-versatile")

        # ── SONIDO (placeholder informativo) ──────────────────────────────────
        elif task == "sound_gen":
            result = ("🎵 La generación de audio/música requiere créditos en APIs especializadas como **ElevenLabs** o **Suno AI**.\n\n"
                      "Configurá `ELEVENLABS_API_KEY` en Railway para activar esta función.\n\n"
                      "Mientras tanto, puedo:\n- Describir en detalle el sonido que imaginás\n"
                      "- Escribir la letra si es música\n- Sugerirte prompts para Suno.ai o Udio.com")
            label = "orquesta · sound"

        # ── TRADUCCIÓN ────────────────────────────────────────────────────────
        elif task == "translate":
            ts = system + "\n\nEres un traductor experto. Traducí con precisión y naturalidad."
            msgs = build_messages(ts, req.history, req.prompt)
            result, _ = await groq_with_fallback(msgs, "llama-3.3-70b-versatile")
            label = "groq · traductor"

        # ── ANÁLISIS (con búsqueda enriquecida) ───────────────────────────────
        elif task == "analysis" and TAVILY_KEY:
            try:
                ctx = await deep_search(req.prompt)
                if ctx:
                    enriched = (f'"{req.prompt}"\n\nDatos reales de internet:\n{ctx[:3000]}\n\n'
                                f"Realizá un análisis PROFUNDO Y COMPARATIVO con datos reales. Cifras, tendencias, conclusiones específicas.")
                    msgs = build_messages(system, req.history, enriched)
                    result, _ = await groq_with_fallback(msgs, "mixtral-8x7b-32768")
                    label = "orquesta · análisis+web"
                else:
                    msgs = build_messages(system, req.history, req.prompt)
                    result, _ = await groq_with_fallback(msgs, "mixtral-8x7b-32768")
            except Exception:
                msgs = build_messages(system, req.history, req.prompt)
                result, _ = await groq_with_fallback(msgs, "mixtral-8x7b-32768")

        # ── TEXTO / CÓDIGO / TÉCNICO / GENERAL ───────────────────────────────
        else:
            model = TASK_MODELS.get(task, "llama-3.3-70b-versatile")
            msgs = build_messages(system, req.history, req.prompt)
            result, used = await groq_with_fallback(msgs, model)
            if used == "gemini": label = "gemini · flash"

        # ── TTS AUTO: leer la respuesta si está habilitado ────────────────────
        if req.tts_enabled and result and OPENAI_KEY and len(result) < 3000 and not file_url:
            try:
                # Limpiar markdown para TTS
                clean_text = re.sub(r'```[\s\S]*?```', '', result)
                clean_text = re.sub(r'[#*`_~>]', '', clean_text)
                clean_text = re.sub(r'\s+', ' ', clean_text).strip()[:2000]
                audio_bytes = await call_openai_tts(clean_text, voice="nova")
                # Cache audio
                audio_token = str(uuid.uuid4())
                _file_cache[audio_token] = (audio_bytes, "response.mp3", "audio/mpeg")
                tts_url = f"/api/download/{audio_token}"
            except Exception:
                pass

    except HTTPException: raise
    except Exception as e: raise HTTPException(502, detail=str(e))

    return OrchestrateResp(
        result=result, task_type=task, model_label=label,
        latency_ms=int((time.time()-t0)*1000),
        image_url=img_url, file_url=file_url, file_type=file_type,
        file_name=file_name, tts_url=tts_url, video_url=video_url,
    )



# ── DEBUG: ver qué keys están configuradas ────────────────────────────────────
@router.get("/debug-config")
async def debug_config():
    """Endpoint de diagnóstico - ver qué APIs están configuradas"""
    return {
        "groq": bool(os.getenv("GROQ_API_KEY","")),
        "openai": bool(os.getenv("OPENAI_API_KEY","")),
        "gemini": bool(os.getenv("GEMINI_API_KEY","")),
        "tavily": bool(os.getenv("TAVILY_API_KEY","")),
        "status": "ok"
    }


# ── TEST MINIMAX: probar conexión directa ─────────────────────────────────────
@router.get("/test-video-apis")
async def test_video_apis():
    """Prueba todas las APIs de video y muestra estado de cada una"""
    results = {}
    
    # Test Minimax
    mm_key = os.getenv("MINIMAX_API_KEY", "")
    if mm_key:
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(
                    "https://api.minimaxi.chat/v1/video_generation",
                    headers={"Authorization": f"Bearer {mm_key}", "Content-Type": "application/json"},
                    json={"model": "video-01", "prompt": "test"}
                )
                rd = r.json()
                sc = rd.get("base_resp", {}).get("status_code", 0)
                results["minimax"] = {
                    "key": mm_key[:8]+"...",
                    "http": r.status_code,
                    "api_code": sc,
                    "msg": rd.get("base_resp", {}).get("status_msg", ""),
                    "task_id": rd.get("task_id", ""),
                    "ok": sc == 0
                }
        except Exception as e:
            results["minimax"] = {"error": str(e)}
    else:
        results["minimax"] = {"error": "No configurada"}

    # Test Kling
    kling_ak = os.getenv("KLING_ACCESS_KEY", "")
    kling_sk = os.getenv("KLING_SECRET_KEY", "")
    if kling_ak and kling_sk:
        try:
            token = _make_kling_jwt(kling_ak, kling_sk)
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(
                    "https://api.klingai.com/v1/videos/text2video",
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json={"model_name": "kling-v1", "prompt": "test", "duration": "5"}
                )
                rd = r.json()
                results["kling"] = {
                    "key": kling_ak[:8]+"...",
                    "http": r.status_code,
                    "response": str(rd)[:300],
                    "ok": r.status_code == 200
                }
        except Exception as e:
            results["kling"] = {"error": str(e)}
    else:
        results["kling"] = {"error": "No configurada"}

    # Test Replicate
    rep_key = os.getenv("REPLICATE_API_KEY", "")
    if rep_key:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                # Test con endpoint de cuenta (siempre válido si la key es correcta)
                r = await c.get(
                    "https://api.replicate.com/v1/account",
                    headers={"Authorization": f"Bearer {rep_key}"}
                )
                rd = r.json()
                results["replicate"] = {
                    "key": rep_key[:8]+"...",
                    "http": r.status_code,
                    "username": rd.get("username", ""),
                    "ok": r.status_code == 200
                }
        except Exception as e:
            results["replicate"] = {"error": str(e)}
    else:
        results["replicate"] = {"error": "No configurada"}

    return results

@router.get("/test-minimax")
async def test_minimax_legacy():
    return {"redirect": "Use /api/test-video-apis instead"}


# ── DOWNLOAD ──────────────────────────────────────────────────────────────────
@router.get("/download/{token}")
async def download_file(token: str):
    if token not in _file_cache: raise HTTPException(404, "Archivo no encontrado o expirado")
    file_bytes, filename, mime = _file_cache[token]
    return Response(content=file_bytes, media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ── FILE UPLOAD ───────────────────────────────────────────────────────────────
@router.post("/upload")
async def upload_file(
    prompt: str = Form(default="Analizá este archivo en detalle."),
    file: UploadFile = File(...),
    username: str = Form(default=""),
    mode: str = Form(default="general"),
):
    t0 = time.time(); raw = await file.read()
    fname = (file.filename or "").lower(); mime = file.content_type or ""
    system = get_system(mode, username)

    async def groq_analyze(text):
        fp = f"Archivo: {file.filename}\n\nContenido:\n{text[:14000]}\n\nConsulta: {prompt}"
        msgs = build_messages(system, [], fp)
        result, used = await groq_with_fallback(msgs, "llama-3.3-70b-versatile")
        return result, ("gemini · flash" if used == "gemini" else "groq · llama 3.3")

    result = ""; label = "orquesta"; img_url = ""
    try:
        is_image = mime.startswith("image/") or any(fname.endswith(x) for x in [".jpg",".jpeg",".png",".gif",".webp",".bmp"])
        is_edit = is_image and any(k in prompt.lower() for k in IMAGE_EDIT_KW)

        if is_image and is_edit:
            if OPENAI_KEY:
                try: img_url = await call_openai_image_edit(raw, prompt); result = "Imagen editada con GPT-4o + DALL-E 3."; label = "gpt-4o + dall-e-3"
                except Exception as e:
                    result = f"Error al editar: {str(e)[:200]}"; label = "error"
            else: result = "Para editar imágenes configurá OPENAI_API_KEY."
        elif is_image:
            if GEMINI_KEY:
                b64 = base64.b64encode(raw).decode()
                result = await call_gemini_vision(f"{system}\n\nAnalizá: {prompt}", b64, mime or "image/jpeg")
                label = "gemini · visión"
            else: result = "Para analizar imágenes configurá GEMINI_API_KEY."
        elif fname.endswith(".pdf") or mime == "application/pdf":
            if GEMINI_KEY:
                b64 = base64.b64encode(raw).decode()
                result = await call_gemini_vision(f"{system}\n\nAnalizá este PDF: {prompt}", b64, "application/pdf")
                label = "gemini · pdf"
            else: result = "Para leer PDFs configurá GEMINI_API_KEY."
        elif fname.endswith(".docx"):
            try:
                from docx import Document
                doc = Document(io.BytesIO(raw))
                paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
                tables = []
                for tbl in doc.tables:
                    for row in tbl.rows:
                        rt = " | ".join(c.text.strip() for c in row.cells if c.text.strip())
                        if rt: tables.append(rt)
                text = "\n".join(paras)
                if tables: text += "\n\nTablas:\n" + "\n".join(tables)
                result, label = await groq_analyze(text)
            except Exception as e: result = f"No se pudo leer el Word: {e}"; label = "error"
        elif any(fname.endswith(x) for x in [".xlsx",".xls"]):
            try:
                import openpyxl; wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
                sheets = []
                for sname in wb.sheetnames[:6]:
                    ws = wb[sname]; rows = []
                    for row in ws.iter_rows(max_row=300, values_only=True):
                        cells = [str(c) for c in row if c is not None]
                        if cells: rows.append(" | ".join(cells))
                    if rows: sheets.append(f"=== {sname} ===\n" + "\n".join(rows[:150]))
                result, label = await groq_analyze("\n\n".join(sheets))
            except Exception as e: result = f"No se pudo leer el Excel: {e}"; label = "error"
        elif any(fname.endswith(x) for x in [".txt",".md",".csv",".json",".xml",".py",".js",".ts",".html",".css",".sql",".yaml",".yml",".log",".sh"]):
            result, label = await groq_analyze(raw.decode("utf-8", errors="ignore"))
        elif fname.endswith(".doc"): result = "Archivos .doc no compatibles. Guardá como .docx y resubí."
        else: result = f"Formato no soportado: {fname}"
    except Exception as e: raise HTTPException(502, detail=f"Error: {e}")

    return {"result":result,"task_type":"file","model_label":label,
            "latency_ms":int((time.time()-t0)*1000),"image_url":img_url,"filename":file.filename}


# ── TTS ENDPOINT ──────────────────────────────────────────────────────────────
@router.post("/tts")
async def text_to_speech(data: dict):
    if not OPENAI_KEY: raise HTTPException(400, "OPENAI_API_KEY no configurada")
    text = data.get("text",""); voice = data.get("voice","nova")
    if not text: raise HTTPException(400, "Texto vacío")
    try:
        clean = re.sub(r'```[\s\S]*?```', '', text)
        clean = re.sub(r'[#*`_~>]', '', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()[:3000]
        audio = await call_openai_tts(clean, voice)
        return StreamingResponse(io.BytesIO(audio), media_type="audio/mpeg")
    except Exception as e: raise HTTPException(502, str(e))

@router.post("/stt")
async def speech_to_text(file: UploadFile = File(...)):
    if not OPENAI_KEY: raise HTTPException(400, "OPENAI_API_KEY no configurada")
    try:
        audio_bytes = await file.read()
        text = await call_openai_stt(audio_bytes, file.filename or "audio.webm")
        return {"text": text}
    except Exception as e: raise HTTPException(502, str(e))

@router.get("/status")
async def status():
    return {"groq":bool(GROQ_KEY),"tavily":bool(TAVILY_KEY),"gemini":bool(GEMINI_KEY),
            "openai":bool(OPENAI_KEY),"file_generation":True,"tts":bool(OPENAI_KEY)}
