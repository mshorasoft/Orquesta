from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx, os, time, base64, io, json, re

router = APIRouter()

GROQ_KEY      = os.getenv("GROQ_API_KEY", "")
TAVILY_KEY    = os.getenv("TAVILY_API_KEY", "")
GEMINI_KEY    = os.getenv("GEMINI_API_KEY", "")
OPENAI_KEY    = os.getenv("OPENAI_API_KEY", "")

# ── SYSTEM PROMPTS ────────────────────────────────────────────────────────────
BASE_SYSTEM = """Sos Orquesta, una inteligencia artificial de nivel experto creada para dar las mejores respuestas posibles.

PERSONALIDAD:
- Cálida, directa y profesional — como hablar con un especialista de confianza
- Si sabés el nombre del usuario, usalo naturalmente en la conversación (no en cada mensaje, solo cuando sea natural)
- Nunca sos robótico ni genérico. Tenés criterio propio.

REGLAS DE RESPUESTA:
1. Respondé SIEMPRE en el mismo idioma del usuario — si habla en español, respondé en español
2. Sé específico y profundo — nunca vago ni superficial
3. Ante problemas técnicos: diagnosticá la causa raíz con precisión, dá soluciones concretas con valores y parámetros reales
4. Estructurá bien: usá listas y pasos cuando mejoran la claridad
5. NUNCA termines con "¿En qué más puedo ayudarte?" ni frases similares
6. Si el tema es técnico, respondé con profundidad real de especialista senior
7. Usá el historial de conversación para dar respuestas más precisas y contextualizadas
8. Si el usuario da información incompleta, hacé suposiciones razonables y aclaralas brevemente
9. Para temas de actualidad que no conozcas: indicá claramente tu fecha de corte de conocimiento"""

MODE_PROMPTS = {
    "tecnico": "\n\nMODO TÉCNICO ACTIVO: Actuás como ingeniero o científico senior especializado en el área consultada. Incluí valores numéricos, fórmulas, parámetros reales, normas técnicas (ISO, ASTM, DIN, etc.). Ordená causas por probabilidad. Sin respuestas genéricas de manual básico. Diagnóstico de causa raíz siempre.",
    "creativo": "\n\nMODO CREATIVO ACTIVO: Actuás como director creativo senior. Sé original, inesperado, memorable. Proponé múltiples variantes cuando sea útil. Adaptá el tono exactamente al contexto pedido. Mostrá con ejemplos concretos.",
    "codigo": "\n\nMODO CÓDIGO ACTIVO: Actuás como desarrollador full-stack senior con 15+ años de experiencia. Código limpio, eficiente, con manejo de errores. Explicá bugs por su causa raíz exacta. Seguí best practices del lenguaje. Preferí soluciones simples sobre complejas.",
}

def get_system(mode: str, username: str = "") -> str:
    sys = BASE_SYSTEM
    if username:
        sys += f"\n\nNOMBRE DEL USUARIO: {username}. Usalo de forma natural cuando sea apropiado — no en cada mensaje."
    sys += MODE_PROMPTS.get(mode, "")
    return sys

# ── CLASSIFICATION ────────────────────────────────────────────────────────────
IMAGE_GEN_KW = [
    "genera una imagen","generá una imagen","crea una imagen","creá una imagen",
    "dibuja","dibujá","ilustra","ilustrá","imagen de","foto de","fotografía de",
    "generate image","create image","draw","make an image","picture of","render",
    "diseña un logo","diseñá","hazme una imagen","create a photo","make a photo",
]
IMAGE_EDIT_KW = [
    "modifica","modificá","cambia","cambiá","reemplaza","reemplazá",
    "edita","editá","borra","añade","quita","quitá","pon","pone","transforma",
    "edit","change","replace","remove","swap","put","add","convert","transform",
]
REALTIME_KW = [
    "hoy","ahora","actual","actualmente","últimas","ultimo","última",
    "esta semana","esta noche","ayer","mañana","reciente","trending",
    "today","now","latest","current","yesterday","tonight","this week",
    "partido","resultado","formación","alineación","ganó","perdió","empató",
    "score","gol","goles","fixture","tabla","clasificación","champions",
    "copa","mundial","liga","torneo","jugó","juega","derrota","victoria",
    "precio","cotización","dólar","euro","peso","bitcoin","crypto",
    "cuánto cuesta","cuánto vale","cotizan","bolsa","acciones",
    "clima","temperatura","pronóstico","lluvia","weather","forecast",
    "noticias","noticia","news","murió","nació","lanzó","salió",
    "eligieron","anunció","declaró","trending","quién ganó","quién es el",
    "argentina","brasil","españa","francia","alemania","inglaterra",
    "uruguay","colombia","chile","peru","mexico","zambia","nigeria",
    "real madrid","barcelona","boca","river","messi","ronaldo","mbappé",
]
CODE_KW = [
    "código","code","función","function","script","python","javascript",
    "typescript","bug","debug","clase","class","algoritmo","sql",
    "html","css","api","json","regex","bash","programa","programar",
    "endpoint","database","query","loop","array","objeto","object","error en",
]
ANALYSIS_KW = [
    "analiza","compare","compara","evalúa","pros","contras",
    "diferencia entre","ventajas","desventajas","estrategia",
    "qué opinas","qué pensás","cuál es mejor","recomienda","conviene",
    "debería","vale la pena","qué tan bueno","cómo se compara",
]
TRANSLATE_KW = [
    "traduce","traducí","translate","traducción al","how do you say",
    "cómo se dice","¿cómo se dice",
]

def classify(prompt: str, mode: str) -> str:
    if mode == "codigo":   return "code"
    if mode == "creativo": return "creative"
    if mode == "tecnico":  return "technical"
    p = prompt.lower()
    if any(k in p for k in IMAGE_GEN_KW):  return "image_gen"
    if any(k in p for k in TRANSLATE_KW):  return "translate"
    if " vs " in p or " contra " in p:     return "realtime"
    if any(x in p for x in ["cómo salió","como salio","cómo quedó","qué pasó","que paso","cómo le fue"]): return "realtime"
    if any(k in p for k in REALTIME_KW):   return "realtime"
    if any(k in p for k in CODE_KW):       return "code"
    if any(k in p for k in ANALYSIS_KW):   return "analysis"
    return "general"

TASK_LABELS = {
    "image_gen": "openai · dall-e-3",
    "realtime":  "tavily · web + groq",
    "code":      "groq · llama 3.3",
    "technical": "groq · mixtral",
    "analysis":  "groq · mixtral",
    "creative":  "groq · llama 3.3",
    "translate": "groq · llama 3.3",
    "general":   "groq · llama 3.3",
}
TASK_MODELS = {
    "code":      "llama-3.3-70b-versatile",
    "technical": "mixtral-8x7b-32768",
    "analysis":  "mixtral-8x7b-32768",
    "creative":  "llama-3.3-70b-versatile",
    "translate": "llama-3.3-70b-versatile",
    "general":   "llama-3.3-70b-versatile",
    "realtime":  "llama-3.3-70b-versatile",
}

# ── API CALLERS ───────────────────────────────────────────────────────────────
async def call_groq(messages: list, model: str = "llama-3.3-70b-versatile") -> str:
    async with httpx.AsyncClient(timeout=40) as c:
        r = await c.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            json={"model": model, "messages": messages, "max_tokens": 2048, "temperature": 0.65},
        )
        d = r.json()
        if not r.is_success:
            raise Exception(d.get("error", {}).get("message", "Groq error"))
        return d["choices"][0]["message"]["content"]

async def call_gemini(prompt: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    async with httpx.AsyncClient(timeout=35) as c:
        r = await c.post(url, json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": 2048}})
        d = r.json()
        if not r.is_success: raise Exception(str(d))
        return d["candidates"][0]["content"]["parts"][0]["text"]

async def call_gemini_vision(prompt: str, b64: str, mime: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    payload = {
        "contents": [{"parts": [{"inline_data": {"mime_type": mime, "data": b64}}, {"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 2048, "temperature": 0.3}
    }
    async with httpx.AsyncClient(timeout=45) as c:
        r = await c.post(url, json=payload)
        d = r.json()
        if not r.is_success: raise Exception(str(d))
        return d["candidates"][0]["content"]["parts"][0]["text"]

async def call_tavily(query: str) -> str:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            "https://api.tavily.com/search",
            json={"api_key": TAVILY_KEY, "query": query, "search_depth": "basic", "max_results": 6, "include_answer": True},
        )
        d = r.json()
        if not r.is_success: raise Exception(d.get("message", "Tavily error"))
        answer = d.get("answer", "")
        results = d.get("results", [])
        ctx = f"Respuesta directa: {answer}\n\n" if answer else ""
        ctx += "\n\n".join(f"[{r['title']}]\n{r['content']}" for r in results[:5])
        return ctx

async def call_openai_image_gen(prompt: str) -> str:
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {OPENAI_KEY}"},
            json={"model": "dall-e-3", "prompt": prompt, "n": 1, "size": "1024x1024", "quality": "standard"},
        )
        d = r.json()
        if not r.is_success:
            raise Exception(d.get("error", {}).get("message", "OpenAI error"))
        return d["data"][0]["url"]

async def call_openai_image_edit(image_bytes: bytes, prompt: str) -> str:
    """GPT-4o analyzes image + DALL-E 3 generates edited version."""
    b64 = base64.b64encode(image_bytes).decode()
    analysis_messages = [
        {"role": "system", "content": "You are an expert image editor. Analyze the image carefully and create a detailed DALL-E 3 prompt that recreates the image WITH the requested modification. Be very specific about: photographic style, lighting, composition, colors, background, subject pose. The goal is maximum similarity to the original with only the requested change."},
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            {"type": "text", "text": f"Create a DALL-E 3 prompt for this image WITH this modification: {prompt}. Reply with ONLY the prompt text, nothing else."}
        ]}
    ]
    async with httpx.AsyncClient(timeout=40) as c:
        r = await c.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_KEY}"},
            json={"model": "gpt-4o", "messages": analysis_messages, "max_tokens": 600},
        )
        d = r.json()
        if not r.is_success:
            raise Exception(d.get("error", {}).get("message", "GPT-4o error"))
        optimized_prompt = d["choices"][0]["message"]["content"]
    return await call_openai_image_gen(optimized_prompt)

async def call_openai_tts(text: str, voice: str = "nova") -> bytes:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {OPENAI_KEY}"},
            json={"model": "tts-1", "input": text[:4096], "voice": voice},
        )
        if not r.is_success: raise Exception(f"TTS error {r.status_code}: {r.text[:200]}")
        return r.content

async def call_openai_stt(audio_bytes: bytes, filename: str) -> str:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {OPENAI_KEY}"},
            files={"file": (filename, audio_bytes, "audio/webm")},
            data={"model": "whisper-1"},
        )
        d = r.json()
        if not r.is_success: raise Exception(d.get("error", {}).get("message", "STT error"))
        return d["text"]

def build_messages(system: str, history: list, prompt: str) -> list:
    msgs = [{"role": "system", "content": system}]
    for m in history[-14:]:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role not in ("user", "assistant") or not content: continue
        msgs.append({"role": role, "content": content})
    msgs.append({"role": "user", "content": prompt})
    return msgs

async def groq_with_fallback(messages: list, model: str) -> tuple[str, str]:
    """Try primary model, fallback to alternate Groq model, then Gemini."""
    try:
        return await call_groq(messages, model), model
    except Exception:
        try:
            alt = "llama-3.3-70b-versatile" if model != "llama-3.3-70b-versatile" else "mixtral-8x7b-32768"
            return await call_groq(messages, alt), alt
        except Exception:
            if GEMINI_KEY:
                # Extract prompt from messages for Gemini
                sys_content = next((m["content"] for m in messages if m["role"] == "system"), "")
                user_content = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
                result = await call_gemini(f"{sys_content}\n\n{user_content}")
                return result, "gemini"
            raise

# ── MODELS ───────────────────────────────────────────────────────────────────
class OrchestrateReq(BaseModel):
    prompt: str
    history: list = []
    mode: str = "general"
    username: str = ""
    language: str = ""  # auto-detect if empty

class OrchestrateResp(BaseModel):
    result: str
    task_type: str
    model_label: str
    latency_ms: int
    image_url: str = ""
    detected_language: str = ""

# ── MAIN ENDPOINT ─────────────────────────────────────────────────────────────
@router.post("/orchestrate", response_model=OrchestrateResp)
async def orchestrate(req: OrchestrateReq):
    if not req.prompt.strip():
        raise HTTPException(400, "Prompt vacío")

    t0 = time.time()
    task = classify(req.prompt, req.mode)
    label = TASK_LABELS.get(task, "groq · llama 3.3")
    img_url = ""
    result = ""
    system = get_system(req.mode, req.username)

    try:
        # ── IMAGE GENERATION ─────────────────────────────────────────────────
        if task == "image_gen":
            if OPENAI_KEY:
                try:
                    img_url = await call_openai_image_gen(req.prompt)
                    result = "Imagen generada con DALL-E 3."
                    label = "openai · dall-e-3"
                except Exception as e:
                    if "quota" in str(e).lower() or "billing" in str(e).lower():
                        raise HTTPException(402, "Sin créditos en OpenAI. Recargá tu cuenta en platform.openai.com/billing")
                    raise
            else:
                import urllib.parse
                img_url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(req.prompt)}?width=1024&height=1024&nologo=true&enhance=true&seed={int(time.time())}"
                result = "Imagen generada con Pollinations AI."
                label = "pollinations · imagen"

        # ── REAL-TIME SEARCH ─────────────────────────────────────────────────
        elif task == "realtime":
            if TAVILY_KEY:
                try:
                    ctx = await call_tavily(req.prompt)
                    synth = (
                        f'El usuario pregunta: "{req.prompt}"\n\n'
                        f"Información actualizada de internet:\n{ctx}\n\n"
                        f"Respondé de forma natural y completa en el mismo idioma de la pregunta. "
                        f"Usá los datos reales provistos. No cites números de fuente como [1] o [2]."
                    )
                    msgs = build_messages(system, req.history[:-1], synth)
                    result, used_model = await groq_with_fallback(msgs, "llama-3.3-70b-versatile")
                    label = "tavily · web + groq"
                except Exception:
                    msgs = build_messages(system, req.history, req.prompt)
                    result, _ = await groq_with_fallback(msgs, "llama-3.3-70b-versatile")
                    label = "groq · llama 3.3"
            else:
                msgs = build_messages(system, req.history, req.prompt)
                result, _ = await groq_with_fallback(msgs, "llama-3.3-70b-versatile")
                label = "groq · llama 3.3"

        # ── TRANSLATION ──────────────────────────────────────────────────────
        elif task == "translate":
            translate_system = system + "\n\nEres un traductor experto. Traducí con precisión y naturalidad, respetando el registro (formal/informal) del texto original."
            msgs = build_messages(translate_system, req.history, req.prompt)
            result, used = await groq_with_fallback(msgs, "llama-3.3-70b-versatile")
            label = f"groq · traductor"

        # ── TEXT / CODE / ANALYSIS / TECHNICAL ──────────────────────────────
        else:
            model = TASK_MODELS.get(task, "llama-3.3-70b-versatile")
            msgs = build_messages(system, req.history, req.prompt)
            result, used = await groq_with_fallback(msgs, model)
            if used == "gemini":
                label = "gemini · flash"

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=str(e))

    return OrchestrateResp(
        result=result, task_type=task, model_label=label,
        latency_ms=int((time.time() - t0) * 1000), image_url=img_url,
    )

# ── FILE UPLOAD ───────────────────────────────────────────────────────────────
@router.post("/upload")
async def upload_file(
    prompt: str = Form(default="Analizá este archivo en detalle y explicá su contenido de forma clara y profesional."),
    file: UploadFile = File(...),
    username: str = Form(default=""),
    mode: str = Form(default="general"),
):
    t0 = time.time()
    raw = await file.read()
    fname = (file.filename or "").lower()
    mime = file.content_type or ""
    system = get_system(mode, username)

    async def groq_analyze(text: str) -> tuple[str, str]:
        full_prompt = f"Archivo: {file.filename}\n\nContenido:\n{text[:14000]}\n\nConsulta del usuario: {prompt}"
        msgs = build_messages(system, [], full_prompt)
        result, used = await groq_with_fallback(msgs, "llama-3.3-70b-versatile")
        label = "gemini · flash" if used == "gemini" else "groq · llama 3.3"
        return result, label

    result = ""
    label = "orquesta"
    img_url = ""

    try:
        is_image = mime.startswith("image/") or any(fname.endswith(x) for x in [".jpg",".jpeg",".png",".gif",".webp",".bmp"])
        is_edit = is_image and any(k in prompt.lower() for k in IMAGE_EDIT_KW)

        # IMAGE EDITING — GPT-4o + DALL-E 3
        if is_image and is_edit:
            if OPENAI_KEY:
                try:
                    img_url = await call_openai_image_edit(raw, prompt)
                    result = "Imagen editada con GPT-4o + DALL-E 3."
                    label = "gpt-4o + dall-e-3"
                except Exception as e:
                    err = str(e)
                    if "quota" in err.lower() or "billing" in err.lower():
                        result = "Tu cuenta de OpenAI no tiene crédito. Cargá saldo en platform.openai.com/billing para editar imágenes."
                    else:
                        result = f"Error al editar: {err}"
                    label = "error"
            else:
                result = "Para editar imágenes necesitás configurar OPENAI_API_KEY en Railway."
                label = "orquesta"

        # IMAGE ANALYSIS — Gemini Vision
        elif is_image:
            if GEMINI_KEY:
                b64 = base64.b64encode(raw).decode()
                sys_prompt = f"{system}\n\nAnalizá la imagen respondiendo: {prompt}"
                result = await call_gemini_vision(sys_prompt, b64, mime or "image/jpeg")
                label = "gemini · visión"
            else:
                result = "Para analizar imágenes necesitás configurar GEMINI_API_KEY en Railway."
                label = "orquesta"

        # PDF — Gemini Vision
        elif fname.endswith(".pdf") or mime == "application/pdf":
            if GEMINI_KEY:
                b64 = base64.b64encode(raw).decode()
                sys_prompt = f"{system}\n\nAnalizá este PDF respondiendo: {prompt}"
                result = await call_gemini_vision(sys_prompt, b64, "application/pdf")
                label = "gemini · pdf"
            else:
                result = "Para leer PDFs necesitás configurar GEMINI_API_KEY en Railway."
                label = "orquesta"

        # DOCX
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
            except Exception as e:
                result = f"No se pudo leer el archivo Word: {e}. Asegurate de que sea un .docx válido."
                label = "error"

        # XLSX
        elif any(fname.endswith(x) for x in [".xlsx", ".xls"]):
            try:
                import openpyxl
                wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
                sheets = []
                for sname in wb.sheetnames[:6]:
                    ws = wb[sname]
                    rows = []
                    for row in ws.iter_rows(max_row=300, values_only=True):
                        cells = [str(c) for c in row if c is not None]
                        if cells: rows.append(" | ".join(cells))
                    if rows: sheets.append(f"=== Hoja: {sname} ===\n" + "\n".join(rows[:150]))
                text = "\n\n".join(sheets)
                result, label = await groq_analyze(text)
            except Exception as e:
                result = f"No se pudo leer el Excel: {e}."
                label = "error"

        # TEXT / CODE / CSV / JSON / etc
        elif any(fname.endswith(x) for x in [".txt",".md",".csv",".json",".xml",".py",".js",".ts",".html",".css",".sql",".yaml",".yml",".log",".sh"]):
            text = raw.decode("utf-8", errors="ignore")
            result, label = await groq_analyze(text)

        elif fname.endswith(".doc"):
            result = "Los archivos .doc (Word 97-2003) no son compatibles. Abrí el archivo en Word, guardalo como .docx y volvé a subirlo."
            label = "orquesta"

        else:
            result = f"Formato no soportado: {fname}\n\nFormatos compatibles: imágenes (JPG/PNG/WebP/GIF), PDF, Word (.docx), Excel (.xlsx/.xls), texto (.txt/.csv/.json/.md), código fuente."
            label = "orquesta"

    except Exception as e:
        raise HTTPException(502, detail=f"Error procesando archivo: {e}")

    return {
        "result": result, "task_type": "file", "model_label": label,
        "latency_ms": int((time.time() - t0) * 1000),
        "image_url": img_url, "filename": file.filename,
    }

# ── AUDIO ─────────────────────────────────────────────────────────────────────
@router.post("/tts")
async def text_to_speech(data: dict):
    if not OPENAI_KEY:
        raise HTTPException(400, "OPENAI_API_KEY no configurada")
    text = data.get("text", "")
    voice = data.get("voice", "nova")
    if not text: raise HTTPException(400, "Texto vacío")
    try:
        audio = await call_openai_tts(text, voice)
        return StreamingResponse(io.BytesIO(audio), media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(502, str(e))

@router.post("/stt")
async def speech_to_text(file: UploadFile = File(...)):
    if not OPENAI_KEY:
        raise HTTPException(400, "OPENAI_API_KEY no configurada")
    try:
        audio_bytes = await file.read()
        text = await call_openai_stt(audio_bytes, file.filename or "audio.webm")
        return {"text": text}
    except Exception as e:
        raise HTTPException(502, str(e))

# ── STATUS ────────────────────────────────────────────────────────────────────
@router.get("/status")
async def status():
    return {
        "groq": bool(GROQ_KEY),
        "tavily": bool(TAVILY_KEY),
        "gemini": bool(GEMINI_KEY),
        "openai": bool(OPENAI_KEY),
    }
