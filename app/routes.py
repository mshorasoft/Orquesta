from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
import httpx, os, time, base64, io

router = APIRouter()

GROQ_KEY      = os.getenv("GROQ_API_KEY", "")
TAVILY_KEY    = os.getenv("TAVILY_API_KEY", "")
GEMINI_KEY    = os.getenv("GEMINI_API_KEY", "")
STABILITY_KEY = os.getenv("STABILITY_API_KEY", "")

# ─────────────────────────────────────────────
# SYSTEM PROMPTS  (inspired by ChatGPT/Claude/Gemini best practices)
# Dynamic prompts per mode — not one-size-fits-all
# ─────────────────────────────────────────────
def build_system_prompt(mode: str, task: str) -> str:
    base = """Eres Orquesta, un asistente de inteligencia artificial de nivel experto.

PRINCIPIOS FUNDAMENTALES:
- Respondé SIEMPRE en el mismo idioma que usa el usuario.
- Pensá antes de responder. Si el tema es complejo, razoná paso a paso internamente antes de dar tu respuesta final.
- Sé directo, específico y útil. Nunca genérico ni vago.
- Jamás termines con "¿En qué más puedo ayudarte?" o frases similares.
- Si el usuario tiene un problema, diagnosticá la causa raíz, no el síntoma.
- Usá datos, valores, fórmulas y especificaciones reales cuando corresponda.
- Estructurá bien: usa listas, pasos o secciones cuando haga la respuesta más clara.
- Memorizá el contexto de la conversación y usalo para dar respuestas más precisas.
"""
    modes = {
        "tecnico": """
ROL: Ingeniero senior / científico especialista en el área consultada.
- Diagnosticá con precisión técnica real. Causas raíz, no síntomas superficiales.
- Incluí valores numéricos, parámetros, fórmulas, rangos aceptables.
- Citá normas o estándares relevantes cuando corresponda (ISO, ASTM, DIN, etc.).
- Si hay múltiples causas posibles, ordenalas por probabilidad descendente.
- Dá soluciones accionables con pasos concretos.
""",
        "creativo": """
ROL: Director creativo senior con experiencia en escritura, marketing y diseño.
- Sé original, inesperado y memorable. Evitá lo genérico.
- Proponé múltiples variantes o ángulos cuando sea útil.
- Adaptá el tono exactamente al contexto (formal, casual, poético, humorístico).
- Mostrá, no solo describas — usá ejemplos concretos.
""",
        "codigo": """
ROL: Desarrollador full-stack senior con 15+ años de experiencia.
- Escribí código limpio, eficiente, bien estructurado y comentado donde sea necesario.
- Seguí las best practices del lenguaje (PEP8, ESLint, etc.).
- Incluí manejo de errores y casos edge cuando sea relevante.
- Si hay un bug, explicá la causa raíz exacta antes de dar la solución.
- Preferí soluciones simples sobre complejas (principio KISS).
- Para snippets cortos: código directo. Para sistemas: explicá la arquitectura primero.
""",
        "realtime": """
ROL: Analista de información con acceso a datos actualizados de internet.
- Presentá la información más reciente disponible de forma clara y estructurada.
- Separás hechos confirmados de información que puede cambiar.
- Si hay incertidumbre en los datos, aclaralo brevemente.
""",
        "archivo": """
ROL: Analista experto en procesamiento y comprensión de documentos.
- Analizá el contenido del archivo con profundidad real.
- Extraé los puntos clave, estructuras, datos importantes y conclusiones.
- Si el archivo tiene tablas o datos numéricos, analizalos e interpretalos.
- Respondé exactamente lo que el usuario pregunta sobre el archivo.
- Si el archivo tiene errores o inconsistencias, señalalos.
""",
    }
    tasks = {
        "image": "\nTu tarea actual: generar una descripción optimizada para creación de imagen.",
    }
    prompt = base
    if mode in modes:
        prompt += modes[mode]
    elif task in modes:
        prompt += modes[task]
    if task in tasks:
        prompt += tasks[task]
    return prompt


# ─────────────────────────────────────────────
# CLASSIFICATION  — smart router
# ─────────────────────────────────────────────
IMAGE_KW = [
    "genera una imagen","generá una imagen","crea una imagen","creá una imagen",
    "dibuja","dibujá","ilustra","ilustrá","imagen de","foto de","fotografía de",
    "generate image","create image","draw","make an image","picture of","render",
    "diseña un logo","diseñá un logo","hazme una imagen","create a photo",
]
REALTIME_KW = [
    "hoy","ahora","actual","actualmente","últimas","ultimo","última",
    "esta semana","esta noche","ayer","mañana","reciente","trending",
    "today","now","latest","current","yesterday","tonight","this week",
    "partido","resultado","formación","alineación","ganó","perdió","empató",
    "score","gol","goles","fixture","tabla","clasificación","champions",
    "copa","mundial","liga","torneo","eliminatorias","jugó","juega",
    "derrota","victoria","precio","cotización","dólar","euro","peso",
    "bitcoin","crypto","cuánto cuesta","cuánto vale","cotizan","bolsa",
    "acciones","clima","temperatura","pronóstico","lluvia","weather",
    "noticias","noticia","news","murió","nació","lanzó","salió",
    "eligieron","anunció","declaró","quién ganó","quién es el presidente",
    "quién es el ceo","quién lidera",
    # Países/equipos comunes que sugieren evento en tiempo real
    "argentina","brasil","españa","francia","alemania","inglaterra",
    "uruguay","colombia","chile","peru","mexico","zambia","nigeria",
    "real madrid","barcelona","boca","river","messi","ronaldo","mbappé",
]
CODE_KW = [
    "código","code","función","function","script","python","javascript",
    "typescript","bug","debug","clase","class","algoritmo","sql",
    "html","css","api","json","regex","bash","programa","programar",
    "endpoint","database","query","loop","array","objeto","object",
]
ANALYSIS_KW = [
    "analiza","compare","compara","evalúa","pros","contras",
    "explica en detalle","razona","diferencia entre","ventajas","desventajas",
    "estrategia","qué opinas","qué pensás","cuál es mejor","recomienda",
    "debería","conviene","vale la pena",
]

def classify(prompt: str, mode: str) -> str:
    if mode == "codigo":
        return "code"
    if mode == "creativo":
        return "creative"
    if mode == "tecnico":
        return "technical"
    p = prompt.lower()
    if any(k in p for k in IMAGE_KW):
        return "image"
    if " vs " in p or " contra " in p:
        return "realtime"
    if any(x in p for x in ["cómo salió","como salio","cómo quedó","como quedo","qué pasó","que paso","cómo le fue"]):
        return "realtime"
    if any(k in p for k in REALTIME_KW):
        return "realtime"
    if any(k in p for k in CODE_KW):
        return "code"
    if any(k in p for k in ANALYSIS_KW):
        return "analysis"
    return "general"


TASK_LABELS = {
    "image":     "pollinations · imagen",
    "realtime":  "tavily · web + groq",
    "code":      "groq · llama 3.3",
    "technical": "groq · mixtral",
    "analysis":  "groq · mixtral",
    "creative":  "groq · llama 3.3",
    "general":   "groq · llama 3.3",
}
TASK_MODELS = {
    "code":      "llama-3.3-70b-versatile",
    "technical": "mixtral-8x7b-32768",
    "analysis":  "mixtral-8x7b-32768",
    "creative":  "llama-3.3-70b-versatile",
    "general":   "llama-3.3-70b-versatile",
    "realtime":  "llama-3.3-70b-versatile",
}


# ─────────────────────────────────────────────
# API CALLERS  — with cascade fallback
# ─────────────────────────────────────────────
async def call_groq(messages: list, model: str = "llama-3.3-70b-versatile") -> str:
    async with httpx.AsyncClient(timeout=35) as c:
        r = await c.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            json={"model": model, "messages": messages, "max_tokens": 2048, "temperature": 0.65},
        )
        d = r.json()
        if not r.is_success:
            raise Exception(d.get("error", {}).get("message", "Groq error"))
        return d["choices"][0]["message"]["content"]


async def call_groq_fallback(messages: list) -> str:
    """Try Mixtral first, then Llama as fallback"""
    try:
        return await call_groq(messages, "mixtral-8x7b-32768")
    except Exception:
        return await call_groq(messages, "llama-3.3-70b-versatile")


async def call_gemini(prompt: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    async with httpx.AsyncClient(timeout=35) as c:
        r = await c.post(url, json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": 2048}})
        d = r.json()
        if not r.is_success:
            raise Exception(str(d))
        return d["candidates"][0]["content"]["parts"][0]["text"]


async def call_gemini_vision(prompt: str, b64: str, mime: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    payload = {"contents": [{"parts": [{"inline_data": {"mime_type": mime, "data": b64}}, {"text": prompt}]}], "generationConfig": {"maxOutputTokens": 2048, "temperature": 0.3}}
    async with httpx.AsyncClient(timeout=45) as c:
        r = await c.post(url, json=payload)
        d = r.json()
        if not r.is_success:
            raise Exception(str(d))
        return d["candidates"][0]["content"]["parts"][0]["text"]


async def call_stability_inpaint(image_b64: str, prompt: str, negative_prompt: str = "") -> str:
    """
    Stability AI SD3.5 image editing via inpainting.
    Automatically generates a face/subject mask using the prompt context.
    Returns base64 encoded result image.
    """
    import base64

    # Decode original image
    image_bytes = base64.b64decode(image_b64)

    # Use Stability AI's search-and-replace endpoint (no manual mask needed)
    # This is the most user-friendly: describe what to replace + what to put instead
    async with httpx.AsyncClient(timeout=60) as c:
        response = await c.post(
            "https://api.stability.ai/v2beta/stable-image/edit/search-and-replace",
            headers={
                "authorization": f"Bearer {STABILITY_KEY}",
                "accept": "image/*",
            },
            files={"image": ("image.jpg", image_bytes, "image/jpeg")},
            data={
                "prompt": prompt,
                "search_prompt": "",  # auto-detect what to replace based on prompt
                "negative_prompt": negative_prompt or "blurry, low quality, watermark",
                "output_format": "jpeg",
            },
        )

        if response.status_code == 200:
            result_b64 = base64.b64encode(response.content).decode()
            return result_b64
        else:
            error = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            raise Exception(f"Stability AI error {response.status_code}: {error.get('message', response.text[:200])}")


async def call_stability_generate(prompt: str) -> str:
    """Generate a new image with Stability AI SD3.5"""
    async with httpx.AsyncClient(timeout=60) as c:
        response = await c.post(
            "https://api.stability.ai/v2beta/stable-image/generate/sd3",
            headers={
                "authorization": f"Bearer {STABILITY_KEY}",
                "accept": "image/*",
            },
            files={"none": ""},
            data={
                "prompt": prompt,
                "model": "sd3.5-large-turbo",
                "output_format": "jpeg",
            },
        )
        if response.status_code == 200:
            return base64.b64encode(response.content).decode()
        else:
            raise Exception(f"Stability AI error {response.status_code}: {response.text[:200]}")


async def call_tavily(query: str) -> str:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            "https://api.tavily.com/search",
            json={"api_key": TAVILY_KEY, "query": query, "search_depth": "basic", "max_results": 6, "include_answer": True},
        )
        d = r.json()
        if not r.is_success:
            raise Exception(d.get("message", "Tavily error"))
        answer = d.get("answer", "")
        results = d.get("results", [])
        ctx = f"Respuesta directa: {answer}\n\n" if answer else ""
        ctx += "\n\n".join(f"[{r['title']}]\n{r['content']}" for r in results[:5])
        return ctx


def image_url(prompt: str) -> str:
    import urllib.parse
    return f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}?width=1024&height=1024&nologo=true&enhance=true&seed={int(time.time())}"


# ─────────────────────────────────────────────
# BUILD MESSAGES  — with conversation memory
# ─────────────────────────────────────────────
def build_messages(system: str, history: list, prompt: str) -> list:
    msgs = [{"role": "system", "content": system}]
    for m in history[-12:]:  # last 12 messages = 6 turns of context
        role = m.get("role", "user")
        content = m.get("content", "")
        if role not in ("user", "assistant") or not content:
            continue
        msgs.append({"role": role, "content": content})
    msgs.append({"role": "user", "content": prompt})
    return msgs


# ─────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────
class Msg(BaseModel):
    role: str
    content: str

class OrchestrateReq(BaseModel):
    prompt: str
    history: list = []
    mode: str = "general"

class OrchestrateResp(BaseModel):
    result: str
    task_type: str
    model_label: str
    latency_ms: int
    image_url: str = ""


# ─────────────────────────────────────────────
# MAIN ENDPOINT
# ─────────────────────────────────────────────
@router.post("/orchestrate", response_model=OrchestrateResp)
async def orchestrate(req: OrchestrateReq):
    if not req.prompt.strip():
        raise HTTPException(400, "Prompt vacío")

    t0 = time.time()
    task = classify(req.prompt, req.mode)
    label = TASK_LABELS.get(task, "groq · llama 3.3")
    img_url = ""
    result = ""

    try:
        # ── IMAGE GENERATION ──────────────────
        if task == "image":
            img_url = image_url(req.prompt)
            result = f"Generando imagen para: *{req.prompt}*"

        # ── REAL-TIME SEARCH ──────────────────
        elif task == "realtime":
            if TAVILY_KEY:
                try:
                    ctx = await call_tavily(req.prompt)
                    synth = (
                        f"El usuario pregunta: \"{req.prompt}\"\n\n"
                        f"Información actualizada obtenida de internet:\n{ctx}\n\n"
                        f"Instrucción: Respondé de forma natural y completa en el mismo idioma de la pregunta. "
                        f"Usá los datos reales provistos. No cites números de fuente como [1] o [2]. "
                        f"Si la información es parcial o incierta, aclaralo brevemente."
                    )
                    sys_prompt = build_system_prompt("realtime", task)
                    msgs = build_messages(sys_prompt, req.history[:-1], synth)
                    result = await call_groq(msgs)
                    label = "tavily · web + groq"
                except Exception:
                    # Fallback: Groq sin búsqueda
                    sys_prompt = build_system_prompt(req.mode, task)
                    msgs = build_messages(sys_prompt, req.history, req.prompt)
                    result = await call_groq(msgs)
                    label = "groq · llama 3.3"
            else:
                sys_prompt = build_system_prompt(req.mode, task)
                msgs = build_messages(sys_prompt, req.history, req.prompt)
                result = await call_groq(msgs)
                label = "groq · llama 3.3"

        # ── TEXT / CODE / ANALYSIS / TECHNICAL ─
        else:
            sys_prompt = build_system_prompt(req.mode, task)
            msgs = build_messages(sys_prompt, req.history, req.prompt)
            model = TASK_MODELS.get(task, "llama-3.3-70b-versatile")
            try:
                result = await call_groq(msgs, model)
            except Exception:
                # Cascade: try other Groq model
                try:
                    alt = "llama-3.3-70b-versatile" if model != "llama-3.3-70b-versatile" else "mixtral-8x7b-32768"
                    result = await call_groq(msgs, alt)
                    label = f"groq · fallback"
                except Exception:
                    # Last resort: Gemini
                    if GEMINI_KEY:
                        full = f"{sys_prompt}\n\n{req.prompt}"
                        result = await call_gemini(full)
                        label = "gemini · flash"
                    else:
                        raise HTTPException(502, "Todos los modelos fallaron")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=str(e))

    return OrchestrateResp(
        result=result,
        task_type=task,
        model_label=label,
        latency_ms=int((time.time() - t0) * 1000),
        image_url=img_url,
    )


# ─────────────────────────────────────────────
# FILE UPLOAD  — smart extraction + cascade
# ─────────────────────────────────────────────
@router.post("/upload")
async def upload_file(
    prompt: str = Form(default="Analizá este archivo en detalle y explicá su contenido de forma clara y profesional."),
    file: UploadFile = File(...),
):
    t0 = time.time()
    raw = await file.read()
    fname = (file.filename or "").lower()
    mime = file.content_type or ""

    async def groq_analyze(text: str, extra_sys: str = "") -> tuple[str, str]:
        sys_p = build_system_prompt("archivo", "archivo") + extra_sys
        msgs = build_messages(sys_p, [], f"Archivo: {file.filename}\n\nContenido:\n{text[:14000]}\n\nConsulta: {prompt}")
        try:
            r = await call_groq(msgs, "llama-3.3-70b-versatile")
            return r, "groq · llama 3.3"
        except Exception:
            r = await call_groq(msgs, "mixtral-8x7b-32768")
            return r, "groq · mixtral"

    async def gemini_analyze(text: str) -> tuple[str, str]:
        sys_p = build_system_prompt("archivo", "archivo")
        full = f"{sys_p}\n\nArchivo: {file.filename}\n\nContenido:\n{text[:14000]}\n\nConsulta: {prompt}"
        r = await call_gemini(full)
        return r, "gemini · flash"

    async def with_fallback(text: str, extra_sys: str = "") -> tuple[str, str]:
        """Try Groq first, fallback to Gemini"""
        try:
            return await groq_analyze(text, extra_sys)
        except Exception:
            if GEMINI_KEY:
                return await gemini_analyze(text)
            raise

    result = ""
    label = "orquesta"

    try:
        # ── IMAGES → detect edit vs analysis ──
        if mime.startswith("image/") or any(fname.endswith(x) for x in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"]):
            edit_kw = ["modifica","modificá","cambia","cambiá","reemplaza","reemplazá",
                       "edita","editá","borra","añade","quita","quitá","pon","pone",
                       "edit","change","replace","remove","swap","put","add"]
            is_edit = any(k in prompt.lower() for k in edit_kw)
            if is_edit:
                import urllib.parse
                b64 = base64.b64encode(raw).decode()

                if STABILITY_KEY:
                    # Use Stability AI search-and-replace — real image editing
                    try:
                        result_b64 = await call_stability_inpaint(b64, prompt)
                        # Convert to data URL for frontend display
                        data_url = f"data:image/jpeg;base64,{result_b64}"
                        return {
                            "result": "Imagen editada con Stability AI. Solo se modificó la parte que pediste — el resto quedó igual.",
                            "task_type": "file",
                            "model_label": "stability ai · sd3.5",
                            "latency_ms": int((time.time() - t0) * 1000),
                            "image_url": data_url,
                            "filename": file.filename,
                        }
                    except Exception as e:
                        # Fallback to Pollinations if Stability fails
                        pass

                # Fallback: describe + generate new image with Pollinations
                try:
                    desc = await call_gemini_vision(
                        "Describe this image in detail: main subject, pose, expression, colors, photographic style, lighting, background. Be very specific.",
                        b64, mime or "image/jpeg"
                    )
                except Exception:
                    desc = "professional photograph"
                new_img_prompt = (
                    f"Professional photo: {prompt}. "
                    f"Same style as original: {desc}. "
                    f"Photorealistic, high quality, 4K."
                )
                edit_url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(new_img_prompt)}?width=1024&height=1024&nologo=true&enhance=true&seed={int(time.time())}"
                return {
                    "result": "Generé una versión nueva de la imagen aplicando el cambio pedido. Para edición directa de la imagen original, configurá la API key de Stability AI en Railway.",
                    "task_type": "file",
                    "model_label": "pollinations · imagen",
                    "latency_ms": int((time.time() - t0) * 1000),
                    "image_url": edit_url,
                    "filename": file.filename,
                }
            else:
                b64 = base64.b64encode(raw).decode()
                result = await call_gemini_vision(prompt, b64, mime or "image/jpeg")
                label = "gemini · visión" 

        # ── PDF → Gemini Vision (lee PDFs nativamente) ──
        elif fname.endswith(".pdf") or mime == "application/pdf":
            b64 = base64.b64encode(raw).decode()
            result = await call_gemini_vision(prompt, b64, "application/pdf")
            label = "gemini · pdf"

        # ── DOCX → extraer texto → Groq (fallback Gemini) ──
        elif fname.endswith(".docx"):
            try:
                from docx import Document
                doc = Document(io.BytesIO(raw))
                paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
                tables = []
                for tbl in doc.tables:
                    for row in tbl.rows:
                        row_txt = " | ".join(c.text.strip() for c in row.cells if c.text.strip())
                        if row_txt:
                            tables.append(row_txt)
                text = "\n".join(paras)
                if tables:
                    text += "\n\nTablas:\n" + "\n".join(tables)
                result, label = await with_fallback(text)
            except ImportError:
                result = "Módulo python-docx no instalado. Agregá 'python-docx==1.1.2' a requirements.txt."
                label = "error"
            except Exception as e:
                result = f"No se pudo leer el Word: {e}. Probá guardarlo de nuevo como .docx."
                label = "error"

        # ── XLSX → extraer datos → Groq (fallback Gemini) ──
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
                        if cells:
                            rows.append(" | ".join(cells))
                    if rows:
                        sheets.append(f"=== Hoja: {sname} ===\n" + "\n".join(rows[:150]))
                text = "\n\n".join(sheets)
                result, label = await with_fallback(text, "\n- Prestá especial atención a los datos numéricos, tendencias y anomalías.\n- Si hay múltiples hojas, analizalas en conjunto cuando sea relevante.")
            except ImportError:
                result = "Módulo openpyxl no instalado. Agregá 'openpyxl==3.1.5' a requirements.txt."
                label = "error"
            except Exception as e:
                result = f"No se pudo leer el Excel: {e}."
                label = "error"

        # ── TXT / CSV / JSON / código → Groq (fallback Gemini) ──
        elif any(fname.endswith(x) for x in [".txt", ".md", ".csv", ".json", ".xml", ".py", ".js", ".ts", ".html", ".css", ".sql", ".yaml", ".yml", ".log"]):
            text = raw.decode("utf-8", errors="ignore")
            result, label = await with_fallback(text)

        # ── DOC legacy ──
        elif fname.endswith(".doc"):
            result = "Los archivos .doc (Word 97-2003) no son compatibles. Abrí el archivo en Word moderno, guardalo como .docx y volvé a subirlo."
            label = "orquesta"

        else:
            result = f"Tipo de archivo no soportado: {fname}.\n\nFormatos compatibles: imágenes (JPG/PNG/WebP/GIF), PDF, Word (.docx), Excel (.xlsx), texto (.txt/.csv/.json/.md), código fuente (.py/.js/.ts/.html/.css/.sql)."
            label = "orquesta"

    except Exception as e:
        raise HTTPException(502, detail=f"Error procesando archivo: {e}")

    return {
        "result": result,
        "task_type": "file",
        "model_label": label,
        "latency_ms": int((time.time() - t0) * 1000),
        "image_url": "",
        "filename": file.filename,
    }


@router.get("/status")
async def status():
    return {
        "groq": bool(GROQ_KEY),
        "tavily": bool(TAVILY_KEY),
        "gemini": bool(GEMINI_KEY),
        "stability": bool(STABILITY_KEY),
    }
