from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
import httpx
import os
import time
import base64
import json
import io

router = APIRouter()

GROQ_API_KEY    = os.getenv("GROQ_API_KEY", "")
TAVILY_API_KEY  = os.getenv("TAVILY_API_KEY", "")
GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_IMAGE_MODEL = "gemini-2.0-flash-exp-image-generation"

SYSTEM_PROMPTS = {
    "general": """Eres Orquesta, un asistente de IA de nivel experto. Tu objetivo es dar respuestas de la más alta calidad posible, como lo haría un especialista senior en el tema consultado.

REGLAS:
1. Respondé SIEMPRE en el mismo idioma que usa el usuario.
2. Sé directo y específico. Nunca des respuestas vagas o genéricas.
3. Ante problemas técnicos: diagnosticá con precisión, explicá el mecanismo y dá soluciones concretas con valores y parámetros reales.
4. Estructurá la respuesta con jerarquía clara cuando haya múltiples puntos.
5. NUNCA termines con frases como ¿Necesitás más ayuda? o Espero haberte ayudado.
6. Si el tema es técnico, respondé con profundidad real — no des respuestas de manual básico.
7. Usá el contexto previo de la conversación para dar respuestas más precisas.
8. Priorizá utilidad práctica sobre longitud.""",

    "tecnico": """Eres Orquesta en modo TÉCNICO EXPERTO. Respondé como un ingeniero senior o científico especializado en el área consultada.
- Usá terminología técnica precisa
- Incluí valores, fórmulas, parámetros y especificaciones reales
- Diagnosticá causas raíz, no síntomas superficiales
- Dá soluciones paso a paso con datos concretos
- Citá normas, estándares o referencias técnicas cuando sea relevante
- NUNCA des respuestas genéricas o de manual básico
- Respondé en el idioma del usuario.""",

    "creativo": """Eres Orquesta en modo CREATIVO. Ayudás con escritura, ideas, diseño, marketing, contenido y arte.
- Sé original, fresco e imaginativo
- Proponé múltiples opciones o variaciones cuando corresponda
- Pensá fuera de lo convencional
- Adaptá el tono al contexto (formal, casual, humorístico, poético)
- Respondé en el idioma del usuario.""",

    "codigo": """Eres Orquesta en modo CÓDIGO. Sos un desarrollador senior full-stack.
- Escribí código limpio, eficiente y bien comentado
- Explicá brevemente qué hace cada bloque importante
- Seguí best practices del lenguaje
- Incluí manejo de errores cuando corresponda
- Si hay un bug, explicá la causa raíz y cómo corregirlo
- Respondé en el idioma del usuario.""",
}

REALTIME_KW = [
    "hoy","ahora","actual","actualmente","últimas","ultimo","última",
    "esta semana","esta noche","ayer","mañana","reciente",
    "today","now","latest","current","yesterday","tonight","this week",
    "partido","resultado","formación","alineación","ganó","perdió",
    "empató","score","gol","goles","fixture","tabla","clasificación",
    "champions","copa","mundial","liga","torneo","eliminatorias",
    "jugó","juega","jugarán","derrota","victoria",
    "argentina","brasil","españa","francia","alemania","inglaterra",
    "uruguay","colombia","chile","peru","mexico","zambia","nigeria",
    "real madrid","barcelona","boca","river","messi","ronaldo",
    "precio","cotización","dólar","euro","peso","bitcoin","crypto",
    "cuánto cuesta","cuánto vale","cotizan","bolsa","acciones",
    "clima","temperatura","pronóstico","lluvia","weather","forecast",
    "noticias","noticia","news","murió","nació","lanzó","salió",
    "eligieron","ganaron","perdieron","anunció","declaró","trending",
]
CODE_KW = [
    "código","code","función","function","script","python","javascript",
    "typescript","bug","debug","clase","class","algoritmo","sql",
    "html","css","api","json","regex","bash","programa","programar",
]
ANALYSIS_KW = [
    "analiza","compare","compara","evalúa","pros","contras",
    "explica en detalle","razona","diferencia entre","ventajas","desventajas",
    "estrategia","qué opinas","qué pensás",
]
IMAGE_KW = [
    "genera una imagen","generá una imagen","crea una imagen","creá una imagen",
    "dibuja","dibujá","ilustra","ilustrá","imagen de","foto de",
    "generate image","create image","draw","make an image","picture of",
    "diseña","diseñá","render",
]

MODELS = {
    "realtime": "llama-3.3-70b-versatile",
    "code":     "llama-3.3-70b-versatile",
    "analysis": "mixtral-8x7b-32768",
    "text":     "llama-3.3-70b-versatile",
    "image":    "pollinations",
    "file":     "gemini",
}
LABELS = {
    "realtime": "tavily · web + groq",
    "code":     "groq · llama 3.3",
    "analysis": "groq · mixtral",
    "text":     "groq · llama 3.3",
    "image":    "pollinations · imagen",
    "file":     "gemini · visión",
}


def classify(prompt: str) -> str:
    p = prompt.lower()
    if any(k in p for k in IMAGE_KW):
        return "image"
    if " vs " in p or " contra " in p:
        return "realtime"
    if any(x in p for x in ["cómo salió","como salio","cómo le fue","qué pasó","que paso","cómo quedó","como quedo"]):
        return "realtime"
    if any(k in p for k in REALTIME_KW):
        return "realtime"
    if any(k in p for k in CODE_KW):
        return "code"
    if any(k in p for k in ANALYSIS_KW):
        return "analysis"
    return "text"


async def call_groq_with_history(prompt: str, model: str, history: list, mode: str = "general") -> str:
    system = SYSTEM_PROMPTS.get(mode, SYSTEM_PROMPTS["general"])
    messages = [{"role": "system", "content": system}]
    for m in history[-10:]:
        role = "assistant" if m.get("role") == "assistant" else "user"
        messages.append({"role": role, "content": m.get("content", "")})
    messages.append({"role": "user", "content": prompt})

    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={"model": model, "messages": messages, "max_tokens": 2048, "temperature": 0.7},
        )
        data = res.json()
        if not res.is_success:
            raise HTTPException(502, detail=data.get("error", {}).get("message", "Error Groq"))
        return data["choices"][0]["message"]["content"]


async def call_tavily(query: str) -> str:
    async with httpx.AsyncClient(timeout=20) as client:
        res = await client.post(
            "https://api.tavily.com/search",
            json={"api_key": TAVILY_API_KEY, "query": query, "search_depth": "basic", "max_results": 5, "include_answer": True},
        )
        data = res.json()
        if not res.is_success:
            raise Exception(data.get("message", "Error Tavily"))
        answer = data.get("answer", "")
        results = data.get("results", [])
        context = f"Respuesta directa: {answer}\n\n" if answer else ""
        context += "\n\n".join(f"{r['title']}\n{r['content']}" for r in results[:4])
        return context


def generate_image_url(prompt: str) -> str:
    """Generate image URL via Pollinations AI (no key needed)"""
    import urllib.parse
    encoded = urllib.parse.quote(prompt)
    return f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&enhance=true"


async def call_gemini_vision(prompt: str, image_data: str, mime_type: str) -> str:
    """Analyze image or document with Gemini"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{
            "parts": [
                {"inline_data": {"mime_type": mime_type, "data": image_data}},
                {"text": prompt or "Analizá este archivo en detalle y describí su contenido."}
            ]
        }],
        "generationConfig": {"maxOutputTokens": 2048, "temperature": 0.4}
    }
    async with httpx.AsyncClient(timeout=60) as client:
        res = await client.post(url, json=payload)
        data = res.json()
        if not res.is_success:
            raise HTTPException(502, detail=str(data))
        return data["candidates"][0]["content"]["parts"][0]["text"]


async def call_gemini_text(prompt: str, context: str) -> str:
    """Process text documents with Gemini"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    full_prompt = f"{SYSTEM_PROMPTS['general']}\n\nContenido del archivo:\n{context}\n\nConsulta del usuario: {prompt}"
    payload = {
        "contents": [{"parts": [{"text": full_prompt}]}],
        "generationConfig": {"maxOutputTokens": 2048, "temperature": 0.4}
    }
    async with httpx.AsyncClient(timeout=45) as client:
        res = await client.post(url, json=payload)
        data = res.json()
        if not res.is_success:
            raise HTTPException(502, detail=str(data))
        return data["candidates"][0]["content"]["parts"][0]["text"]


async def gemini_generate_image(prompt: str) -> str:
    """Genera una imagen desde texto usando Gemini Image Generation. Retorna base64."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_IMAGE_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}
    }
    async with httpx.AsyncClient(timeout=60) as client:
        res = await client.post(url, json=payload)
        data = res.json()
        if not res.is_success:
            raise HTTPException(502, detail=str(data))
        for part in data["candidates"][0]["content"]["parts"]:
            if "inlineData" in part:
                return part["inlineData"]["data"]
        raise HTTPException(502, detail="Gemini no devolvió imagen")


async def gemini_edit_image(prompt: str, image_data: str, mime_type: str) -> str:
    """Edita una imagen con instrucciones en lenguaje natural. Retorna base64."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_IMAGE_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{
            "parts": [
                {"inline_data": {"mime_type": mime_type, "data": image_data}},
                {"text": prompt}
            ]
        }],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}
    }
    async with httpx.AsyncClient(timeout=60) as client:
        res = await client.post(url, json=payload)
        data = res.json()
        if not res.is_success:
            raise HTTPException(502, detail=str(data))
        for part in data["candidates"][0]["content"]["parts"]:
            if "inlineData" in part:
                return part["inlineData"]["data"]
        raise HTTPException(502, detail="Gemini no devolvió imagen editada")


async def gemini_fuse_images(prompt: str, images: list) -> str:
    """Fusiona múltiples imágenes con Gemini. images = lista de (mime_type, base64). Retorna base64."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_IMAGE_MODEL}:generateContent?key={GEMINI_API_KEY}"
    parts = []
    for mime_type, image_data in images:
        parts.append({"inline_data": {"mime_type": mime_type, "data": image_data}})
    parts.append({"text": prompt})
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}
    }
    async with httpx.AsyncClient(timeout=90) as client:
        res = await client.post(url, json=payload)
        data = res.json()
        if not res.is_success:
            raise HTTPException(502, detail=str(data))
        for part in data["candidates"][0]["content"]["parts"]:
            if "inlineData" in part:
                return part["inlineData"]["data"]
        raise HTTPException(502, detail="Gemini no devolvió imagen fusionada")


def pillow_edit_image(content: bytes, prompt: str) -> bytes:
    """Edición local con Pillow: redimensionar, recortar, rotar, filtros, etc."""
    try:
        from PIL import Image, ImageFilter, ImageEnhance
        import re
        img = Image.open(io.BytesIO(content))
        p = prompt.lower()

        # Redimensionar
        resize_match = re.search(r'(\d+)\s*[xX×]\s*(\d+)', prompt)
        if resize_match or any(k in p for k in ["redimensiona", "resize", "tamaño", "escala", "scale"]):
            if resize_match:
                w, h = int(resize_match.group(1)), int(resize_match.group(2))
            else:
                w, h = img.width // 2, img.height // 2
            img = img.resize((w, h), Image.LANCZOS)

        # Rotar
        elif any(k in p for k in ["rota", "rotate", "gira"]):
            angle_match = re.search(r'(\d+)\s*°?', prompt)
            angle = int(angle_match.group(1)) if angle_match else 90
            img = img.rotate(angle, expand=True)

        # Recortar al centro
        elif any(k in p for k in ["recorta", "crop", "centra"]):
            w, h = img.size
            new_w, new_h = w // 2, h // 2
            left = (w - new_w) // 2
            top = (h - new_h) // 2
            img = img.crop((left, top, left + new_w, top + new_h))

        # Blanco y negro
        elif any(k in p for k in ["blanco y negro", "grayscale", "grises", "b&n", "b/n"]):
            img = img.convert("L").convert("RGB")

        # Desenfoque
        elif any(k in p for k in ["desenfoca", "blur", "difumina"]):
            img = img.filter(ImageFilter.GaussianBlur(radius=5))

        # Nitidez
        elif any(k in p for k in ["nitidez", "sharpen", "enfoca"]):
            img = img.filter(ImageFilter.SHARPEN)

        # Brillo
        elif any(k in p for k in ["brillo", "brightness", "ilumina"]):
            img = ImageEnhance.Brightness(img).enhance(1.5)

        # Contraste
        elif any(k in p for k in ["contraste", "contrast"]):
            img = ImageEnhance.Contrast(img).enhance(1.5)

        # Voltear horizontal
        elif any(k in p for k in ["voltea", "flip", "espejo", "mirror"]):
            img = img.transpose(Image.FLIP_LEFT_RIGHT)

        output = io.BytesIO()
        img.save(output, format="PNG")
        return output.getvalue()

    except ImportError:
        raise HTTPException(500, detail="Pillow no está instalado. Agregá 'Pillow' a requirements.txt")


class HistoryMessage(BaseModel):
    role: str
    content: str


class PromptRequest(BaseModel):
    prompt: str
    history: list = []
    mode: str = "general"


class PromptResponse(BaseModel):
    result: str
    task_type: str
    model_label: str
    latency_ms: int
    image_url: str = ""


@router.post("/orchestrate", response_model=PromptResponse)
async def orchestrate(req: PromptRequest):
    if not req.prompt.strip():
        raise HTTPException(400, "El prompt no puede estar vacío")

    t0 = time.time()
    task = classify(req.prompt)

    if req.mode == "codigo":
        task = "code"

    model = MODELS[task]
    label = LABELS[task]
    image_url = ""

    if task == "image":
        image_url = generate_image_url(req.prompt)
        result = f"Imagen generada para: *{req.prompt}*"

    elif task == "realtime" and TAVILY_API_KEY:
        try:
            context = await call_tavily(req.prompt)
            synth_prompt = (
                f'El usuario pregunta: "{req.prompt}"\n\n'
                f"Información actualizada de internet:\n{context}\n\n"
                f"Respondé de forma natural y completa en el mismo idioma de la pregunta. "
                f"Usá la información provista sin citar números de fuente."
            )
            result = await call_groq_with_history(synth_prompt, MODELS["text"], req.history[:-1] if req.history else [], req.mode)
        except Exception:
            result = await call_groq_with_history(req.prompt, MODELS["text"], req.history[:-1] if req.history else [], req.mode)
    else:
        result = await call_groq_with_history(req.prompt, model, req.history[:-1] if req.history else [], req.mode)

    return PromptResponse(
        result=result,
        task_type=task,
        model_label=label,
        latency_ms=int((time.time() - t0) * 1000),
        image_url=image_url,
    )


@router.post("/upload")
async def upload_file(
    prompt: str = Form(default="Analizá este archivo en detalle."),
    file: UploadFile = File(...)
):
    t0 = time.time()
    content = await file.read()
    fname = file.filename.lower()
    mime = file.content_type or ""

    try:
        # Imágenes → detectar si es edición local, edición Gemini, o análisis
        if mime.startswith("image/") or any(fname.endswith(x) for x in [".jpg",".jpeg",".png",".gif",".webp"]):
            b64 = base64.b64encode(content).decode()
            p = prompt.lower()

            # Edición local con Pillow
            if any(k in p for k in ["redimensiona","resize","tamaño","rota","rotate","recorta","crop",
                                      "blanco y negro","grayscale","grises","desenfoca","blur",
                                      "nitidez","sharpen","brillo","brightness","contraste","contrast",
                                      "voltea","flip","espejo","mirror","gira"]):
                edited = pillow_edit_image(content, prompt)
                b64_result = base64.b64encode(edited).decode()
                return {
                    "result": f"✅ Imagen editada correctamente.",
                    "task_type": "image_edit",
                    "model_label": "pillow · edición local",
                    "latency_ms": int((time.time() - t0) * 1000),
                    "image_url": f"data:image/png;base64,{b64_result}",
                    "filename": file.filename,
                }

            # Edición creativa con Gemini
            elif any(k in p for k in ["edita","modifica","cambia","agrega","quita","elimina","añade",
                                        "edit","modify","change","add","remove","transform","convierte",
                                        "pon","ponle","hazlo","hazla","similar","similares","campaña"]):
                b64_result = await gemini_edit_image(prompt, b64, mime or "image/jpeg")
                return {
                    "result": f"✅ Imagen editada con Gemini.",
                    "task_type": "image_edit",
                    "model_label": "gemini · edición de imagen",
                    "latency_ms": int((time.time() - t0) * 1000),
                    "image_url": f"data:image/png;base64,{b64_result}",
                    "filename": file.filename,
                }

            # Análisis de imagen
            else:
                result = await call_gemini_vision(prompt, b64, mime or "image/jpeg")
                return {
                    "result": result,
                    "task_type": "file",
                    "model_label": "gemini · visión",
                    "latency_ms": int((time.time() - t0) * 1000),
                    "image_url": "",
                    "filename": file.filename,
                }

        # PDF → Gemini Vision
        elif fname.endswith(".pdf") or mime == "application/pdf":
            b64 = base64.b64encode(content).decode()
            result = await call_gemini_vision(prompt, b64, "application/pdf")
            label = "gemini · pdf"

        # Texto plano, código, CSV, JSON, XML
        elif any(fname.endswith(x) for x in [".txt",".md",".csv",".json",".xml",".py",".js",".html",".css"]):
            text = content.decode("utf-8", errors="ignore")[:12000]
            result = await call_gemini_text(prompt, text)
            label = "gemini · texto"

        # Word / Excel
        elif any(fname.endswith(x) for x in [".docx",".xlsx",".xls",".doc"]):
            try:
                text = content.decode("utf-8", errors="ignore")[:8000]
                result = await call_gemini_text(prompt, f"[Archivo Office] {text}")
            except Exception:
                result = "Para analizar archivos Word o Excel con mayor precisión, te recomiendo convertirlos a PDF o copiar el texto directamente en el chat."
            label = "gemini · documento"

        else:
            result = f"Tipo de archivo no soportado: {fname}. Soportados: imágenes, PDF, TXT, CSV, JSON, código fuente."
            label = "orquesta"

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"Error procesando archivo: {str(e)}")

    return {
        "result": result,
        "task_type": "file",
        "model_label": label,
        "latency_ms": int((time.time() - t0) * 1000),
        "image_url": "",
        "filename": file.filename,
    }


@router.post("/generate-image")
async def generate_image_gemini(prompt: str = Form(...)):
    """Genera una imagen desde texto usando Gemini."""
    t0 = time.time()
    b64 = await gemini_generate_image(prompt)
    return {
        "result": f"✅ Imagen generada con Gemini para: *{prompt}*",
        "task_type": "image_generate",
        "model_label": "gemini · generación de imagen",
        "latency_ms": int((time.time() - t0) * 1000),
        "image_url": f"data:image/png;base64,{b64}",
    }


@router.post("/fuse-images")
async def fuse_images(
    prompt: str = Form(default="Fusioná estas imágenes de forma creativa"),
    files: list[UploadFile] = File(...)
):
    """Fusiona múltiples imágenes con Gemini."""
    t0 = time.time()
    if len(files) < 2:
        raise HTTPException(400, "Se necesitan al menos 2 imágenes para fusionar")
    images = []
    for f in files[:4]:  # máximo 4 imágenes
        content = await f.read()
        b64 = base64.b64encode(content).decode()
        images.append((f.content_type or "image/jpeg", b64))
    b64_result = await gemini_fuse_images(prompt, images)
    return {
        "result": f"✅ Imágenes fusionadas con Gemini.",
        "task_type": "image_fuse",
        "model_label": "gemini · fusión de imágenes",
        "latency_ms": int((time.time() - t0) * 1000),
        "image_url": f"data:image/png;base64,{b64_result}",
    }


@router.get("/status")
async def status():
    return {
        "groq": bool(GROQ_API_KEY),
        "tavily": bool(TAVILY_API_KEY),
        "gemini": bool(GEMINI_API_KEY),
    }
