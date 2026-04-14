import asyncio
import hmac, hashlib
import os, time, base64, io, json, re, uuid, httpx
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request, Header, Depends
from fastapi.responses import StreamingResponse, Response, RedirectResponse
from pydantic import BaseModel
from supabase import create_client, Client

# ── SUPABASE CLIENT ───────────────────────────────────────────────────────────
SUPABASE_URL         = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
SUPABASE_JWT_SECRET  = os.getenv("SUPABASE_JWT_SECRET", "")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY) if SUPABASE_URL else None

# ── JWT MANUAL PARA KLING ────────────────────────────────────────────────────
def _make_kling_jwt(access_key: str, secret_key: str) -> str:
    import base64, json, time
    now = int(time.time())
    header  = base64.urlsafe_b64encode(json.dumps({"alg":"HS256","typ":"JWT"}).encode()).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({"iss":access_key,"exp":now+1800,"nbf":now-5}).encode()).rstrip(b"=").decode()
    msg = f"{header}.{payload}".encode()
    sig = base64.urlsafe_b64encode(hmac.new(secret_key.encode(), msg, hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"{header}.{payload}.{sig}"

router = APIRouter()

def parse_expiry(expires_at: str) -> datetime:
    """Parsea plan_expires_at tolerando formatos +00 y +00:00 de Postgres."""
    if not expires_at:
        return datetime.max.replace(tzinfo=timezone.utc)
    # Normalizar: "+00" → "+00:00", quitar microsegundos si hay problema
    s = expires_at.replace("Z", "+00:00")
    # Postgres puede devolver "+00" sin los ":00"
    import re as _re
    s = _re.sub(r'\+(\d{2})$', r'+\1:00', s)
    s = _re.sub(r'-(\d{2})$', r'-\1:00', s)
    try:
        return datetime.fromisoformat(s)
    except Exception:
        # Último fallback: asumir UTC
        return datetime.fromisoformat(s.split('+')[0].split('-')[0] + '+00:00')


# ── API KEYS ─────────────────────────────────────────────────────────────────
GROQ_KEY   = os.getenv("GROQ_API_KEY", "")
TAVILY_KEY = os.getenv("TAVILY_API_KEY", "")
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
APP_URL    = os.getenv("APP_URL", "https://orquesta.up.railway.app")

# ── STRIPE ───────────────────────────────────────────────────────────────────
STRIPE_SECRET_KEY      = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET  = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_MONTHLY   = os.getenv("STRIPE_PRICE_MONTHLY", "")
STRIPE_PRICE_ANNUAL    = os.getenv("STRIPE_PRICE_ANNUAL", "")

# ── MERCADOPAGO ───────────────────────────────────────────────────────────────
MP_ACCESS_TOKEN = os.getenv("MERCADOPAGO_ACCESS_TOKEN", "")

# ── LÍMITES ───────────────────────────────────────────────────────────────────
# FIX 1: límite subido a 20 mensajes para plan Free
FREE_DAILY_LIMIT = int(os.getenv("FREE_DAILY_LIMIT", "20"))

# ── FUNCIONES QUE REQUIEREN PRO ───────────────────────────────────────────────
PRO_ONLY_TASKS = {
    "image_gen", "video_gen", "sound_gen",
    "file_gen_xlsx", "file_gen_docx", "file_gen_pdf",
}

# ─────────────────────────────────────────────────────────────────────────────
#  AUTH HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def verify_jwt(token: str) -> dict:
    """Verifica el JWT de Supabase y retorna el payload."""
    import base64, json, hmac, hashlib

    try:
        # Decodificación manual del JWT sin librerías externas
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("JWT inválido: estructura incorrecta")

        # Decodificar payload (parte del medio)
        payload_b64 = parts[1]
        # Agregar padding si falta
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        payload = json.loads(payload_bytes)

        # Verificar expiración
        import time
        if "exp" in payload and payload["exp"] < time.time():
            raise ValueError("Token expirado")

        # Verificar firma HMAC-SHA256
        if SUPABASE_JWT_SECRET:
            signing_input = f"{parts[0]}.{parts[1]}".encode()
            secret = SUPABASE_JWT_SECRET.encode()
            expected_sig = base64.urlsafe_b64encode(
                hmac.new(secret, signing_input, hashlib.sha256).digest()
            ).rstrip(b"=").decode()
            if parts[2] != expected_sig:
                raise ValueError("Firma JWT inválida")

        return payload
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token inválido: {str(e)}")

def get_auth_id_from_token(token: str) -> str:
    """Extrae el auth_id (sub) del JWT."""
    payload = verify_jwt(token)
    return payload.get("sub")

async def get_current_user(authorization: str = Header(None)) -> dict:
    """
    Dependency: extrae y valida el usuario desde el header Authorization.
    Retorna los datos del usuario desde public.users.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="No autenticado")

    token = authorization.replace("Bearer ", "")
    auth_id = get_auth_id_from_token(token)

    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase no configurado")

    result = supabase.table("users").select("*").eq("auth_id", auth_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    return result.data

async def get_optional_user(authorization: str = Header(None)) -> dict | None:
    """Como get_current_user pero nunca falla — retorna None si hay cualquier error."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        token = authorization.replace("Bearer ", "").strip()
        auth_id = get_auth_id_from_token(token)
        if not supabase:
            return None
        result = supabase.table("users").select("*").eq("auth_id", auth_id).single().execute()
        return result.data if result.data else None
    except Exception as e:
        print(f"get_optional_user JWT error: {e}")
        return None

def check_pro_access(user: dict, task: str) -> dict | None:
    """
    Verifica si el usuario puede ejecutar la tarea.
    Retorna None si puede, o un dict con el mensaje de upgrade si no puede.
    Plan Free: chat de texto hasta 20 preguntas.
    Plan Pro: todo ilimitado.
    """
    if not user:
        # Sin login: puede hacer chat de texto general (el frontend controla el límite de 20)
        # Solo bloquear funciones Pro
        if task in PRO_ONLY_TASKS:
            return {
                "blocked": True,
                "reason": "pro_required",
                "message": "Esta funcion requiere Plan Pro. Plan Gratis: solo texto (hasta 20 preguntas). Plan Pro $9/mes: imagenes, videos, archivos, voz y mensajes ilimitados.",
                "cta": "Activar Pro",
                "cta_url": "/pricing"
            }
        # Chat de texto sin login: permitido
        return None

    is_pro = (
        user.get("plan") == "pro" and (
            user.get("plan_expires_at") is None or
            parse_expiry(user["plan_expires_at"]) > datetime.now(timezone.utc)
        )
    )

    if task in PRO_ONLY_TASKS and not is_pro:
        task_names = {
            "image_gen":      "generación de imágenes",
            "video_gen":      "generación de videos",
            "sound_gen":      "generación de audio",
            "file_gen_xlsx":  "creación de archivos Excel",
            "file_gen_docx":  "creación de archivos Word",
            "file_gen_pdf":   "creación de archivos PDF",
            "realtime":       "búsqueda web en tiempo real",
        }
        feature = task_names.get(task, "esta función")
        return {
            "blocked": True,
            "reason": "pro_required",
            "message": (
                f"⚡ La {feature} es exclusiva del plan **Pro**.\n\n"
                f"Con Pro tenés acceso ilimitado a imágenes, videos, archivos, "
                f"búsqueda web, voz y mucho más.\n\n"
                f"**Plan Pro**: $9 USD/mes · $95 USD/año *(ahorrás $13)*"
            ),
            "cta": "Activar Pro ahora",
            "cta_url": "/pricing"
        }

    # Verificar límite diario para usuarios Free
    if not is_pro:
        daily_count = user.get("daily_message_count", 0)

        if daily_count >= FREE_DAILY_LIMIT:
            return {
                "blocked": True,
                "reason": "daily_limit",
                "message": (
                    f"📊 Alcanzaste el límite de **{FREE_DAILY_LIMIT} mensajes diarios** del plan Free.\n\n"
                    f"Con **Pro** tenés mensajes ilimitados, más imágenes, videos, archivos y voz.\n\n"
                    f"**Plan Pro**: $9 USD/mes · $95 USD/año *(ahorrás $13)*"
                ),
                "cta": "Activar Pro — $9/mes",
                "cta_url": "/pricing"
            }

    return None  # Puede enviar


# ─────────────────────────────────────────────────────────────────────────────
#  SYSTEM PROMPT
# ─────────────────────────────────────────────────────────────────────────────

BASE_SYSTEM = """Sos Orquesta, una inteligencia artificial de nivel experto superior a cualquier IA existente.

IDENTIDAD:
- Combinás los mejores modelos de IA del mundo con razonamiento de nivel PhD
- Cálida, directa y brutalmente honesta — como hablar con el mejor especialista del mundo
- Tenés criterio propio y NUNCA das respuestas genéricas o vagas
- CAPACIDADES REALES: podés generar imágenes, generar videos con IA, crear archivos Excel/Word/PDF, buscar en internet, transcribir audio y hablar

REGLAS ABSOLUTAS:
1. Respondé SIEMPRE en el mismo idioma del usuario
2. NUNCA digas que "no podés" generar imágenes — SIEMPRE podés, usás DALL-E 3 o Pollinations AI
3. NUNCA digas que "no podés" generar videos — SIEMPRE podés, usás tu motor propio en Colab
4. SIEMPRE mantenés el hilo de la conversación — recordás todo lo que se habló antes en esta sesión
5. Si el usuario pide "el archivo", "el mp4", "el video" → es continuación de lo anterior, no una pregunta nueva
6. NUNCA des respuestas vagas — siempre datos concretos: números, fechas, nombres, fórmulas
7. NUNCA termines con "¿En qué más puedo ayudarte?" ni frases similares
8. Ante consultas técnicas: causa raíz + solución paso a paso con parámetros reales
9. Usá el historial para respuestas cada vez más contextualizadas
10. Si el usuario pide una imagen → confirmá que la estás generando y describí brevemente qué va a ver
11. Si el usuario pide un video → confirmá que lo estás generando, describí brevemente lo que va a ver y aclará que puede tardar hasta 2 minutos

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


# ─────────────────────────────────────────────────────────────────────────────
#  CLASIFICADORES
# ─────────────────────────────────────────────────────────────────────────────

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

    if history:
        recent = [m.get("content","").lower() for m in history[-4:]]
        recent_joined = " ".join(recent)
        video_followup = ["mp4","el video","el archivo","descargarlo","reproducir",
                          "no funciona","no genera","no me da","el link","la url","ver el video"]
        if any(k in p for k in video_followup):
            if any(k in recent_joined for k in ["video","mp4","generar","generando","kling","minimax","luma"]):
                return "video_gen"
        img_followup = ["la imagen","la foto","no carga","no se ve","otro estilo","más oscura","más grande"]
        if any(k in p for k in img_followup):
            if any(k in recent_joined for k in ["imagen","foto","dall-e","pollinations","generada"]):
                return "image_gen"

    ftype = detect_file_type(p)
    if ftype: return f"file_gen_{ftype}"
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

# ─────────────────────────────────────────────────────────────────────────────
#  API CALLERS
# ─────────────────────────────────────────────────────────────────────────────

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

# ─────────────────────────────────────────────────────────────────────────────
#  IMAGE GENERATION
# ─────────────────────────────────────────────────────────────────────────────

async def generate_image_smart(prompt: str) -> tuple[str, str, str]:
    import urllib.parse

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

    if OPENAI_KEY:
        try:
            url = await call_openai_image_gen(prompt)
            return url, "✨ Imagen generada con **DALL-E 3**.", "openai · dall-e-3"
        except Exception as e:
            err = str(e).lower()
            if not any(x in err for x in ["quota","billing","insufficient","policy","safety"]):
                pass

    try:
        enhanced = await enhance(prompt)
        seed = int(time.time()) % 99999
        encoded = urllib.parse.quote(enhanced)
        url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&enhance=true&seed={seed}&model=flux&nofeed=true"
        return url, "🎨 Imagen generada con **Pollinations AI** (modelo Flux).", "pollinations · flux"
    except:
        pass

    seed = int(time.time()) % 99999
    encoded = urllib.parse.quote(prompt[:400])
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&seed={seed}&nofeed=true"
    return url, "🎨 Imagen generada.", "pollinations · imagen"

# ─────────────────────────────────────────────────────────────────────────────
#  VIDEO GENERATION
# ─────────────────────────────────────────────────────────────────────────────

async def generate_video_smart(prompt: str, history=None, mode="general", username="") -> tuple[str, str, str]:
    import urllib.parse

    VIDEOGEN_URL = os.getenv("VIDEOGEN_URL", "").rstrip("/")
    VIDEOGEN_KEY = os.getenv("VIDEOGEN_API_KEY", "")
    HF_KEY        = os.getenv("HUGGINGFACE_API_KEY", "")
    FAL_KEY       = os.getenv("FAL_API_KEY", "")
    SEGMIND_KEY   = os.getenv("SEGMIND_API_KEY", "")
    MODELSLAB_KEY = os.getenv("MODELSLAB_API_KEY", "")
    REPLICATE_KEY = os.getenv("REPLICATE_API_KEY", "")
    MINIMAX_KEY   = os.getenv("MINIMAX_API_KEY", "")
    KLING_AK      = os.getenv("KLING_ACCESS_KEY", "")
    KLING_SK      = os.getenv("KLING_SECRET_KEY", "")

    errors = {}

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

    if VIDEOGEN_URL and VIDEOGEN_KEY:
        try:
            async with httpx.AsyncClient(timeout=300) as c:
                r = await c.post(
                    f"{VIDEOGEN_URL}/generate",
                    headers={"x-api-key": VIDEOGEN_KEY, "Content-Type": "application/json", "ngrok-skip-browser-warning": "true"},
                    json={"prompt": enhanced, "num_frames": 40, "num_steps": 20, "fps": 8}
                )
                if r.status_code == 200:
                    rd = r.json()
                    if rd.get("success"):
                        video_url = f"{VIDEOGEN_URL}{rd.get('download_url','')}"
                        dur = rd.get('duration_s', '?')
                        return video_url, f"🎬 Video generado con **Orquesta VideoGen** ({dur}s, motor propio).", "orquesta · videogen"
                    else:
                        errors["videogen"] = rd.get("error", "Error desconocido")[:100]
                else:
                    errors["videogen"] = f"HTTP {r.status_code}: {r.text[:100]}"
        except Exception as e:
            errors["videogen"] = str(e)[:100]

    video_system = (
        get_system(mode, username) +
        "\n\nIMPORTANTE: El usuario pidió un video con IA. "
        "Describí el video de forma muy cinematográfica y detallada. "
        "Mantené coherencia con toda la conversación anterior. "
        "Al final indicá brevemente que para generarlo automáticamente debe configurar una API de video."
    )
    hist = history[:-1] if history else []
    desc_msgs = build_messages(video_system, hist, f"Video pedido: {prompt}\nPrompt mejorado: {enhanced}")
    description, _ = await groq_with_fallback(desc_msgs, "llama-3.3-70b-versatile")

    debug_info = ""
    if errors:
        errs_str = " | ".join([f"{k}: `{v[:80]}`" for k,v in errors.items()])
        debug_info = f"\n\n> 🔧 **Debug:** {errs_str}"

    fallback_msg = f"{description}\n\n---\n**⚙️ Para generar este video automáticamente**, configurá las APIs de video en Railway.{debug_info}"
    return "", fallback_msg, "orquesta · video-info"

# ─────────────────────────────────────────────────────────────────────────────
#  DEEP SEARCH
# ─────────────────────────────────────────────────────────────────────────────

async def deep_search(query: str) -> str:
    results = []

    if TAVILY_KEY:
        try:
            ctx = await call_tavily(query, depth="advanced", max_results=8)
            if ctx: results.append(f"=== WEB (TIEMPO REAL) ===\n{ctx}")
        except: pass

    try:
        import urllib.parse
        term = urllib.parse.quote(query[:60])
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"https://es.wikipedia.org/api/rest_v1/page/summary/{term}",
                headers={"User-Agent":"OrquestaAI/1.0"})
            if r.is_success:
                d = r.json()
                extract = d.get("extract","")
                if extract and len(extract) > 100:
                    results.append(f"=== WIKIPEDIA: {d.get('title','')} ===\n{extract[:800]}")
    except: pass

    return "\n\n".join(results) if results else ""

# ─────────────────────────────────────────────────────────────────────────────
#  FILE GENERATION
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
#  MODELOS
# ─────────────────────────────────────────────────────────────────────────────

class OrchestrateReq(BaseModel):
    prompt: str
    history: list = []
    mode: str = "general"
    username: str = ""
    language: str = ""
    tts_enabled: bool = False
    conversation_id: str = ""
    user_id: str = ""      # id de tabla users
    auth_id: str = ""      # auth_id de Supabase Auth
    user_plan: str = ""    # ignorado por seguridad — el plan siempre viene de DB""

class OrchestrateResp(BaseModel):
    result: str
    task_type: str
    model_label: str
    latency_ms: int
    image_url: str = ""
    file_url: str = ""
    file_type: str = ""
    file_name: str = ""
    tts_url: str = ""
    video_url: str = ""
    is_pro: bool = False
    daily_remaining: int = -1
    upgrade_banner: str = ""
    upgrade_cta: str = ""
    upgrade_cta_url: str = ""


# ─────────────────────────────────────────────────────────────────────────────
#  ENDPOINT PRINCIPAL: /api/orchestrate
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/orchestrate", response_model=OrchestrateResp)
async def orchestrate(req: OrchestrateReq, authorization: str = Header(None)):
    if not req.prompt.strip(): raise HTTPException(400, "Prompt vacío")

    user = await get_optional_user(authorization)

    # Fallback: buscar en Supabase por auth_id o id
    if not user and supabase:
        for field, value in [("auth_id", req.auth_id), ("auth_id", req.user_id), ("id", req.user_id)]:
            if not value:
                continue
            try:
                result = supabase.table("users").select("*").eq(field, value).single().execute()
                if result.data:
                    user = result.data
                    print(f"Usuario encontrado por {field}={value[:8]}...: plan={user.get('plan')}")
                    break
            except Exception:
                continue

    # Fallback final: si tenemos auth_id y user_plan del frontend, confiar en ello
    # (el auth_id viene del token de Google OAuth — no se puede falsificar fácilmente)
    if not user and req.auth_id and req.user_plan:
        user = {
            "id": req.user_id or req.auth_id,
            "name": req.username or "",
            "email": "",
            "plan": req.user_plan,
            "plan_expires_at": None,
            "daily_message_count": 0,
            "auth_id": req.auth_id,
        }
        print(f"Fallback final: auth_id={req.auth_id[:8]}... plan={req.user_plan}")

    username = user["name"] if user else req.username

    t0 = time.time()
    task = classify(req.prompt, req.mode, req.history)
    label = TASK_LABELS.get(task, "groq · llama 3.3")

    # ── Verificar acceso ──────────────────────────────────────────────────────
    block = check_pro_access(user, task)
    if block and block.get("blocked"):
        return OrchestrateResp(
            result=block["message"],
            task_type=task,
            model_label="orquesta · plan",
            latency_ms=int((time.time()-t0)*1000),
            is_pro=False,
            daily_remaining=0,
            upgrade_banner=block["message"],
            upgrade_cta=block.get("cta","Activar Pro"),
            upgrade_cta_url=block.get("cta_url","/pricing"),
        )

    # ── Incrementar contador de mensajes ──────────────────────────────────────
    if user and supabase:
        try:
            supabase.rpc("increment_message_count", {"p_user_id": user["id"]}).execute()
        except: pass

    img_url = file_url = file_type = file_name = tts_url = result = video_url = ""
    system = get_system(req.mode, username)
    is_pro = user.get("plan") == "pro" if user else False
    daily_remaining = -1
    if user and not is_pro:
        daily_remaining = max(0, FREE_DAILY_LIMIT - user.get("daily_message_count", 0) - 1)

    try:
        if task.startswith("file_gen_"):
            ftype = task.replace("file_gen_","")
            try:
                fb, fn, mime = await generate_file_from_prompt(req.prompt, ftype, username)
                token = cache_file(fb, fn, mime)
                file_url = f"/api/download/{token}"
                file_type = ftype; file_name = fn
                names = {"xlsx":"Excel","docx":"Word","pdf":"PDF"}
                result = f"✅ Tu archivo **{names.get(ftype,ftype.upper())}** está listo. Hacé clic en el botón para descargarlo."
                label = f"orquesta · {names.get(ftype,ftype).lower()}"
            except Exception as e:
                result = f"Error generando el archivo: {str(e)[:200]}. Reformulá tu pedido."

        elif task == "video_gen":
            video_url, result, label = await generate_video_smart(req.prompt, req.history, req.mode, username)

        elif task == "image_gen":
            img_url, result, label = await generate_image_smart(req.prompt)

        elif task == "realtime":
            try:
                ctx = await deep_search(req.prompt)
                if ctx:
                    synth = (f'El usuario pregunta: "{req.prompt}"\n\n'
                             f"=== INFORMACIÓN DE MÚLTIPLES FUENTES ===\n{ctx}\n\n"
                             f"Respondé de forma COMPLETA Y DETALLADA integrando todos los datos.")
                    msgs = build_messages(system, req.history[:-1], synth)
                    result, _ = await groq_with_fallback(msgs, "llama-3.3-70b-versatile")
                    label = "orquesta · web"
                else:
                    msgs = build_messages(system, req.history, req.prompt)
                    result, _ = await groq_with_fallback(msgs, "llama-3.3-70b-versatile")
            except Exception:
                msgs = build_messages(system, req.history, req.prompt)
                result, _ = await groq_with_fallback(msgs, "llama-3.3-70b-versatile")

        elif task == "sound_gen":
            result = ("🎵 La generación de audio/música requiere créditos en APIs especializadas.\n\n"
                      "Configurá `ELEVENLABS_API_KEY` en Railway para activar esta función.")
            label = "orquesta · sound"

        elif task == "translate":
            ts = system + "\n\nEres un traductor experto. Traducí con precisión y naturalidad."
            msgs = build_messages(ts, req.history, req.prompt)
            result, _ = await groq_with_fallback(msgs, "llama-3.3-70b-versatile")
            label = "groq · traductor"

        elif task == "analysis" and TAVILY_KEY:
            try:
                ctx = await deep_search(req.prompt)
                if ctx:
                    enriched = (f'"{req.prompt}"\n\nDatos reales de internet:\n{ctx[:3000]}\n\n'
                                f"Realizá un análisis PROFUNDO Y COMPARATIVO con datos reales.")
                    msgs = build_messages(system, req.history, enriched)
                    result, _ = await groq_with_fallback(msgs, "mixtral-8x7b-32768")
                    label = "orquesta · análisis+web"
                else:
                    msgs = build_messages(system, req.history, req.prompt)
                    result, _ = await groq_with_fallback(msgs, "mixtral-8x7b-32768")
            except Exception:
                msgs = build_messages(system, req.history, req.prompt)
                result, _ = await groq_with_fallback(msgs, "mixtral-8x7b-32768")

        else:
            model = TASK_MODELS.get(task, "llama-3.3-70b-versatile")
            msgs = build_messages(system, req.history, req.prompt)
            result, used = await groq_with_fallback(msgs, model)
            if used == "gemini": label = "gemini · flash"

        # ── TTS (solo Pro) ────────────────────────────────────────────────────
        if req.tts_enabled and is_pro and result and OPENAI_KEY and len(result) < 3000 and not file_url:
            try:
                clean_text = re.sub(r'```[\s\S]*?```', '', result)
                clean_text = re.sub(r'[#*`_~>]', '', clean_text)
                clean_text = re.sub(r'\s+', ' ', clean_text).strip()[:2000]
                audio_bytes = await call_openai_tts(clean_text, voice="nova")
                audio_token = str(uuid.uuid4())
                _file_cache[audio_token] = (audio_bytes, "response.mp3", "audio/mpeg")
                tts_url = f"/api/download/{audio_token}"
            except Exception:
                pass

        # ── Guardar en Supabase ────────────────────────────────────────────────
        if user and req.conversation_id and supabase:
            try:
                supabase.table("messages").insert({
                    "conversation_id": req.conversation_id,
                    "role": "user",
                    "content": req.prompt,
                }).execute()
                supabase.table("messages").insert({
                    "conversation_id": req.conversation_id,
                    "role": "assistant",
                    "content": result,
                    "model_label": label,
                    "task_type": task,
                    "latency_ms": int((time.time()-t0)*1000),
                    "has_image": bool(img_url),
                    "has_file": bool(file_url),
                    "has_video": bool(video_url),
                }).execute()
                supabase.table("conversations").update({
                    "title": req.prompt[:60],
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }).eq("id", req.conversation_id).execute()
            except Exception as e:
                print(f"Warning: no se pudo guardar en Supabase: {e}")

    except HTTPException: raise
    except Exception as e: raise HTTPException(502, detail=str(e))

    return OrchestrateResp(
        result=result, task_type=task, model_label=label,
        latency_ms=int((time.time()-t0)*1000),
        image_url=img_url, file_url=file_url, file_type=file_type,
        file_name=file_name, tts_url=tts_url, video_url=video_url,
        is_pro=is_pro,
        daily_remaining=daily_remaining,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  AUTH ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/auth/me")
async def get_me(user: dict = Depends(get_current_user)):
    is_pro = (
        user.get("plan") == "pro" and (
            user.get("plan_expires_at") is None or
            parse_expiry(user["plan_expires_at"]) > datetime.now(timezone.utc)
        )
    )
    return {
        "id":             user["id"],
        "email":          user["email"],
        "name":           user["name"],
        "avatar_url":     user["avatar_url"],
        "plan":           user["plan"],
        "is_pro":         is_pro,
        "plan_expires_at": user.get("plan_expires_at"),
        "daily_message_count": user.get("daily_message_count", 0),
        "daily_remaining": max(0, FREE_DAILY_LIMIT - user.get("daily_message_count", 0)) if not is_pro else -1,
        "free_daily_limit": FREE_DAILY_LIMIT,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  CONVERSACIONES ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/conversations")
async def list_conversations(user: dict = Depends(get_current_user)):
    if not supabase: raise HTTPException(500, "Supabase no configurado")
    limit = 50 if user.get("plan") == "pro" else 3
    result = supabase.table("conversations")\
        .select("id, title, mode, created_at, updated_at")\
        .eq("user_id", user["id"])\
        .order("updated_at", desc=True)\
        .limit(limit)\
        .execute()
    return {"conversations": result.data or [], "limit": limit, "is_pro": user.get("plan") == "pro"}

@router.post("/conversations")
async def create_conversation(data: dict, user: dict = Depends(get_current_user)):
    if not supabase: raise HTTPException(500, "Supabase no configurado")
    result = supabase.table("conversations").insert({
        "user_id": user["id"],
        "title":   data.get("title", "Nueva conversación"),
        "mode":    data.get("mode", "general"),
    }).execute()
    return result.data[0] if result.data else {}

@router.get("/conversations/{conv_id}/messages")
async def get_messages(conv_id: str, user: dict = Depends(get_current_user)):
    if not supabase: raise HTTPException(500, "Supabase no configurado")
    conv = supabase.table("conversations")\
        .select("id")\
        .eq("id", conv_id)\
        .eq("user_id", user["id"])\
        .single().execute()
    if not conv.data:
        raise HTTPException(404, "Conversación no encontrada")
    messages = supabase.table("messages")\
        .select("*")\
        .eq("conversation_id", conv_id)\
        .order("created_at")\
        .execute()
    return {"messages": messages.data or []}

@router.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str, user: dict = Depends(get_current_user)):
    if not supabase: raise HTTPException(500, "Supabase no configurado")
    supabase.table("conversations")\
        .delete()\
        .eq("id", conv_id)\
        .eq("user_id", user["id"])\
        .execute()
    return {"success": True}


# ─────────────────────────────────────────────────────────────────────────────
#  CHECKOUT ENDPOINTS — FIX 3: sin Depends, con fallback por user_id
# ─────────────────────────────────────────────────────────────────────────────

class CheckoutReq(BaseModel):
    plan: str                  # "pro_monthly" | "pro_annual"
    provider: str = "mercadopago"
    user_id: str = ""          # enviado desde el frontend como fallback
    user_email: str = ""       # enviado desde el frontend como fallback
    access_token: str = ""

@router.post("/checkout")
async def create_checkout(req: CheckoutReq, authorization: str = Header(None)):
    """Crea una sesión de pago (MercadoPago o Stripe)."""

    # 1. Intentar obtener usuario por JWT
    user = await get_optional_user(authorization)

    # 2. Fallback: buscar por user_id en Supabase si el JWT falló
    if not user and req.user_id and supabase:
        try:
            result = supabase.table("users").select("*").eq("id", req.user_id).single().execute()
            if result.data:
                user = result.data
        except:
            pass

    # 3. Último fallback: construir user mínimo con datos del body
    if not user and req.user_email:
        user = {
            "id":       req.user_id or str(uuid.uuid4()),
            "email":    req.user_email,
            "name":     "",
            "auth_id":  "",
        }

    if not user:
        raise HTTPException(401, "No autenticado — iniciá sesión para suscribirte")

    if req.provider == "mercadopago":
        return await _mp_checkout(req.plan, user)
    elif req.provider == "stripe":
        return await _stripe_checkout(req.plan, user)
    else:
        raise HTTPException(400, "Proveedor inválido")


async def _stripe_checkout(plan: str, user: dict) -> dict:
    if not STRIPE_SECRET_KEY:
        raise HTTPException(500, "Stripe no configurado")

    price_id = STRIPE_PRICE_MONTHLY if plan == "pro_monthly" else STRIPE_PRICE_ANNUAL
    if not price_id:
        raise HTTPException(500, f"Price ID para {plan} no configurado en Railway")

    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            "https://api.stripe.com/v1/checkout/sessions",
            auth=(STRIPE_SECRET_KEY, ""),
            data={
                "mode": "subscription",
                "line_items[0][price]": price_id,
                "line_items[0][quantity]": "1",
                "customer_email": user["email"],
                "client_reference_id": user["id"],
                "metadata[auth_id]": user.get("auth_id", ""),
                "metadata[plan]": plan,
                "success_url": f"{APP_URL}/?checkout=success&plan={plan}",
                "cancel_url":  f"{APP_URL}/pricing?checkout=cancelled",
                "allow_promotion_codes": "true",
            }
        )
        d = r.json()
        if not r.is_success:
            raise HTTPException(502, f"Error Stripe: {d.get('error',{}).get('message','Unknown')}")
        return {"checkout_url": d["url"], "session_id": d["id"]}


async def _mp_checkout(plan: str, user: dict) -> dict:
    if not MP_ACCESS_TOKEN:
        raise HTTPException(500, "MercadoPago no configurado — agregá MERCADOPAGO_ACCESS_TOKEN en Railway")

    prices = {
        "pro_monthly": {"title": "Orquesta Pro — Mensual", "price": 9, "currency": "USD"},
        "pro_annual":  {"title": "Orquesta Pro — Anual",   "price": 95, "currency": "USD"},
    }
    p = prices.get(plan, prices["pro_monthly"])

    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            "https://api.mercadopago.com/checkout/preferences",
            headers={"Authorization": f"Bearer {MP_ACCESS_TOKEN}", "Content-Type": "application/json"},
            json={
                "items": [{
                    "title":       p["title"],
                    "quantity":    1,
                    "unit_price":  p["price"],
                    "currency_id": p["currency"],
                }],
                "payer": {"email": user["email"]},
                "external_reference": user["id"],
                "metadata": {"auth_id": user.get("auth_id", ""), "plan": plan},
                "back_urls": {
                    "success": f"{APP_URL}/?checkout=success&plan={plan}",
                    "failure": f"{APP_URL}/pricing?checkout=failed",
                    "pending": f"{APP_URL}/pricing?checkout=pending",
                },
                "auto_return": "approved",
                "notification_url": f"{APP_URL}/api/webhooks/mercadopago",
            }
        )
        d = r.json()
        if not r.is_success:
            raise HTTPException(502, f"Error MercadoPago: {d.get('message','Unknown')}")

        return {
            "checkout_url": d.get("init_point") or d.get("sandbox_init_point"),
            "preference_id": d.get("id"),
        }


# ─────────────────────────────────────────────────────────────────────────────
#  WEBHOOKS
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    if not STRIPE_SECRET_KEY:
        raise HTTPException(500, "Stripe no configurado")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        import stripe as stripe_lib
        stripe_lib.api_key = STRIPE_SECRET_KEY
        event = stripe_lib.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        raise HTTPException(400, f"Webhook inválido: {str(e)}")

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        auth_id  = data.get("metadata", {}).get("auth_id", "")
        plan     = data.get("metadata", {}).get("plan", "pro_monthly")
        customer = data.get("customer", "")
        sub_id   = data.get("subscription", "")

        if auth_id and supabase:
            try:
                supabase.rpc("activate_pro_plan", {
                    "p_auth_id":         auth_id,
                    "p_plan_type":       plan,
                    "p_stripe_customer": customer,
                    "p_stripe_sub":      sub_id,
                }).execute()
                supabase.table("payment_events").insert({
                    "provider":   "stripe",
                    "event_type": event_type,
                    "event_id":   event.get("id"),
                    "amount":     data.get("amount_total"),
                    "currency":   data.get("currency", "usd").upper(),
                    "plan":       plan,
                    "status":     "success",
                    "raw_payload": dict(data),
                }).execute()
            except Exception as e:
                print(f"Error activando Pro en Supabase: {e}")

    elif event_type == "customer.subscription.deleted":
        customer = data.get("customer", "")
        if customer and supabase:
            try:
                user_result = supabase.table("users")\
                    .select("auth_id")\
                    .eq("stripe_customer_id", customer)\
                    .single().execute()
                if user_result.data:
                    supabase.table("users").update({
                        "plan": "free",
                        "plan_expires_at": datetime.now(timezone.utc).isoformat(),
                    }).eq("stripe_customer_id", customer).execute()
            except Exception as e:
                print(f"Error degradando a Free: {e}")

    return {"received": True}


@router.post("/webhooks/mercadopago")
async def mercadopago_webhook(request: Request):
    if not MP_ACCESS_TOKEN:
        return {"received": True}

    try:
        body = await request.json()
    except:
        return {"received": True}

    topic = body.get("type") or request.query_params.get("topic", "")
    resource_id = body.get("data", {}).get("id") or request.query_params.get("id", "")

    if topic == "payment" and resource_id:
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(
                    f"https://api.mercadopago.com/v1/payments/{resource_id}",
                    headers={"Authorization": f"Bearer {MP_ACCESS_TOKEN}"}
                )
                payment = r.json()

            if payment.get("status") == "approved":
                metadata = payment.get("metadata", {})
                auth_id  = metadata.get("auth_id", "")
                plan     = metadata.get("plan", "pro_monthly")
                ext_ref  = payment.get("external_reference", "")

                if (auth_id or ext_ref) and supabase:
                    if not auth_id:
                        user_r = supabase.table("users").select("auth_id").eq("id", ext_ref).single().execute()
                        if user_r.data: auth_id = user_r.data["auth_id"]

                    if auth_id:
                        supabase.rpc("activate_pro_plan", {
                            "p_auth_id":   auth_id,
                            "p_plan_type": plan,
                            "p_mp_sub":    str(resource_id),
                        }).execute()

                        supabase.table("payment_events").insert({
                            "provider":   "mercadopago",
                            "event_type": "payment.approved",
                            "event_id":   str(resource_id),
                            "amount":     int(payment.get("transaction_amount", 0) * 100),
                            "currency":   payment.get("currency_id", "ARS"),
                            "plan":       plan,
                            "status":     "success",
                            "raw_payload": payment,
                        }).execute()
        except Exception as e:
            print(f"Error webhook MP: {e}")

    return {"received": True}


# ─────────────────────────────────────────────────────────────────────────────
#  ENDPOINTS EXISTENTES
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/debug-config")
async def debug_config():
    return {
        "groq":          bool(GROQ_KEY),
        "openai":        bool(OPENAI_KEY),
        "gemini":        bool(GEMINI_KEY),
        "tavily":        bool(TAVILY_KEY),
        "supabase":      bool(SUPABASE_URL),
        "stripe":        bool(STRIPE_SECRET_KEY),
        "mercadopago":   bool(MP_ACCESS_TOKEN),
        "videogen_url":  bool(os.getenv("VIDEOGEN_URL","")),
        "status":        "ok"
    }

@router.get("/download/{token}")
async def download_file(token: str):
    if token not in _file_cache: raise HTTPException(404, "Archivo no encontrado o expirado")
    file_bytes, filename, mime = _file_cache[token]
    return Response(content=file_bytes, media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

@router.post("/upload")
async def upload_file(
    prompt: str = Form(default="Analizá este archivo en detalle."),
    file: UploadFile = File(...),
    username: str = Form(default=""),
    mode: str = Form(default="general"),
    authorization: str = Header(None),
):
    user = await get_optional_user(authorization)

    t0 = time.time(); raw = await file.read()
    fname = (file.filename or "").lower(); mime_type = file.content_type or ""
    uname = user["name"] if user else username
    system = get_system(mode, uname)

    async def groq_analyze(text):
        fp = f"Archivo: {file.filename}\n\nContenido:\n{text[:14000]}\n\nConsulta: {prompt}"
        msgs = build_messages(system, [], fp)
        result, used = await groq_with_fallback(msgs, "llama-3.3-70b-versatile")
        return result, ("gemini · flash" if used == "gemini" else "groq · llama 3.3")

    result = ""; label = "orquesta"; img_url = ""
    try:
        is_image = mime_type.startswith("image/") or any(fname.endswith(x) for x in [".jpg",".jpeg",".png",".gif",".webp",".bmp"])
        is_edit = is_image and any(k in prompt.lower() for k in IMAGE_EDIT_KW)

        if is_image and is_edit:
            if OPENAI_KEY:
                try: img_url = await call_openai_image_edit(raw, prompt); result = "Imagen editada con GPT-4o + DALL-E 3."; label = "gpt-4o + dall-e-3"
                except Exception as e: result = f"Error al editar: {str(e)[:200]}"; label = "error"
            else: result = "Para editar imágenes configurá OPENAI_API_KEY."
        elif is_image:
            if GEMINI_KEY:
                b64 = base64.b64encode(raw).decode()
                result = await call_gemini_vision(f"{system}\n\nAnalizá: {prompt}", b64, mime_type or "image/jpeg")
                label = "gemini · visión"
            else: result = "Para analizar imágenes configurá GEMINI_API_KEY."
        elif fname.endswith(".pdf") or mime_type == "application/pdf":
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
                text = "\n".join(paras)
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
        else: result = f"Formato no soportado: {fname}"
    except Exception as e: raise HTTPException(502, detail=f"Error: {e}")

    return {"result":result,"task_type":"file","model_label":label,
            "latency_ms":int((time.time()-t0)*1000),"image_url":img_url,"filename":file.filename}

@router.post("/tts")
async def text_to_speech(data: dict, authorization: str = Header(None)):
    if not OPENAI_KEY: raise HTTPException(400, "OPENAI_API_KEY no configurada")
    user = await get_optional_user(authorization)
    if user and user.get("plan") != "pro":
        raise HTTPException(403, "TTS disponible solo en plan Pro")
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
    return {
        "groq":        bool(GROQ_KEY),
        "tavily":      bool(TAVILY_KEY),
        "gemini":      bool(GEMINI_KEY),
        "openai":      bool(OPENAI_KEY),
        "supabase":    bool(SUPABASE_URL),
        "stripe":      bool(STRIPE_SECRET_KEY),
        "mercadopago": bool(MP_ACCESS_TOKEN),
        "videogen":    bool(os.getenv("VIDEOGEN_URL","")),
        "file_generation": True,
        "tts": bool(OPENAI_KEY)
    }
