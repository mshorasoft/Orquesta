from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import httpx
import os
import time

router = APIRouter()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

REALTIME_KW = [
    # Tiempo
    "hoy", "ahora", "actual", "actualmente", "últimas", "ultimo", "última",
    "hoy dia", "esta semana", "esta noche", "ayer", "mañana", "reciente",
    "today", "now", "latest", "current", "yesterday", "tonight", "this week",
    # Deportes
    "partido", "resultado", "formación", "alineación", "ganó", "perdió",
    "empató", "score", "gol", "goles", "fixture", "tabla", "clasificación",
    "champions", "copa", "mundial", "liga", "torneo", "eliminatorias",
    "vs", "contra", "jugó", "juega", "jugarán", "derrota", "victoria",
    # Selecciones y equipos comunes
    "argentina", "brasil", "españa", "francia", "alemania", "inglaterra",
    "uruguay", "colombia", "chile", "perú", "mexico", "zambia", "nigeria",
    "real madrid", "barcelona", "boca", "river", "messi", "ronaldo",
    # Economía
    "precio", "cotización", "dólar", "euro", "peso", "bitcoin", "crypto",
    "cuánto cuesta", "cuánto vale", "cotizan", "bolsa", "acciones", "nasdaq",
    "price", "stock", "market", "exchange rate",
    # Clima
    "clima", "temperatura", "pronóstico", "lluvia", "weather", "forecast",
    # Noticias
    "noticias", "noticia", "news", "murió", "nació", "lanzó", "salió",
    "eligieron", "ganaron", "perdieron", "anunció", "declaró",
    # Entretenimiento actual
    "estreno", "película", "serie", "album", "canción", "trending",
]

CODE_KW = [
    "código", "code", "función", "function", "script", "python", "javascript",
    "typescript", "bug", "debug", "clase", "class", "algoritmo", "sql",
    "html", "css", "api", "json", "regex", "bash", "programa", "programar",
]

ANALYSIS_KW = [
    "analiza", "compare", "compara", "evalúa", "pros", "contras",
    "explica en detalle", "razona", "diferencia entre", "ventajas", "desventajas",
    "estrategia", "qué opinas", "qué pensás",
]


def classify(prompt: str) -> str:
    p = prompt.lower()
    # Detectar preguntas con "vs" o "contra" — casi siempre son deportes en tiempo real
    if " vs " in p or " contra " in p:
        return "realtime"
    # Detectar "cómo salió / cómo le fue / qué pasó"
    if any(x in p for x in ["cómo salió", "como salio", "cómo le fue", "qué pasó", "que paso", "cómo quedó", "como quedo"]):
        return "realtime"
    if any(k in p for k in REALTIME_KW):
        return "realtime"
    if any(k in p for k in CODE_KW):
        return "code"
    if any(k in p for k in ANALYSIS_KW):
        return "analysis"
    return "text"


MODELS = {
    "realtime": "llama-3.3-70b-versatile",
    "code":     "llama-3.3-70b-versatile",
    "analysis": "mixtral-8x7b-32768",
    "text":     "llama-3.3-70b-versatile",
}

LABELS = {
    "realtime": "tavily · web + groq",
    "code":     "groq · llama 3.3",
    "analysis": "groq · mixtral",
    "text":     "groq · llama 3.3",
}


async def call_groq(prompt: str, model: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "Eres Orquesta, un asistente de IA experto. Respondé siempre en el mismo idioma del usuario. Sé claro, directo y completo."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 2048,
                "temperature": 0.7,
            },
        )
        data = res.json()
        if not res.is_success:
            raise HTTPException(502, detail=data.get("error", {}).get("message", "Error Groq"))
        return data["choices"][0]["message"]["content"]


async def call_tavily(query: str) -> str:
    async with httpx.AsyncClient(timeout=20) as client:
        res = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_API_KEY,
                "query": query,
                "search_depth": "basic",
                "max_results": 5,
                "include_answer": True,
            },
        )
        data = res.json()
        if not res.is_success:
            raise Exception(data.get("message", "Error Tavily"))

        answer = data.get("answer", "")
        results = data.get("results", [])
        context = f"Respuesta directa: {answer}\n\n" if answer else ""
        context += "\n\n".join(
            f"{r['title']}\n{r['content']}" for r in results[:4]
        )
        return context


class PromptRequest(BaseModel):
    prompt: str


class PromptResponse(BaseModel):
    result: str
    task_type: str
    model_label: str
    latency_ms: int


@router.post("/orchestrate", response_model=PromptResponse)
async def orchestrate(req: PromptRequest):
    if not req.prompt.strip():
        raise HTTPException(400, "El prompt no puede estar vacío")

    t0 = time.time()
    task = classify(req.prompt)
    model = MODELS[task]
    label = LABELS[task]

    if task == "realtime" and TAVILY_API_KEY:
        try:
            context = await call_tavily(req.prompt)
            synth_prompt = (
                f'El usuario pregunta: "{req.prompt}"\n\n'
                f"Información actualizada de internet:\n{context}\n\n"
                f"Respondé de forma natural y completa en el mismo idioma de la pregunta. "
                f"Usá la información provista sin citar números de fuente."
            )
            result = await call_groq(synth_prompt, model)
        except Exception:
            result = await call_groq(req.prompt, model)
    else:
        result = await call_groq(req.prompt, model)

    return PromptResponse(
        result=result,
        task_type=task,
        model_label=label,
        latency_ms=int((time.time() - t0) * 1000),
    )


@router.get("/status")
async def status():
    return {
        "groq": bool(GROQ_API_KEY),
        "tavily": bool(TAVILY_API_KEY),
    }
