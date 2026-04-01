from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import httpx
import os
import time

router = APIRouter()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

REALTIME_KW = [
    "hoy", "ahora", "actual", "actualmente", "últimas", "ultimo", "última",
    "hoy dia", "esta semana", "esta noche", "ayer", "mañana", "reciente",
    "today", "now", "latest", "current", "yesterday", "tonight", "this week",
    "partido", "resultado", "formación", "alineación", "ganó", "perdió",
    "empató", "score", "gol", "goles", "fixture", "tabla", "clasificación",
    "champions", "copa", "mundial", "liga", "torneo", "eliminatorias",
    "jugó", "juega", "jugarán", "derrota", "victoria",
    "argentina", "brasil", "españa", "francia", "alemania", "inglaterra",
    "uruguay", "colombia", "chile", "peru", "mexico", "zambia", "nigeria",
    "real madrid", "barcelona", "boca", "river", "messi", "ronaldo",
    "precio", "cotización", "dólar", "euro", "peso", "bitcoin", "crypto",
    "cuánto cuesta", "cuánto vale", "cotizan", "bolsa", "acciones",
    "clima", "temperatura", "pronóstico", "lluvia", "weather", "forecast",
    "noticias", "noticia", "news", "murió", "nació", "lanzó", "salió",
    "eligieron", "ganaron", "perdieron", "anunció", "declaró",
    "estreno", "trending",
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


def classify(prompt: str) -> str:
    p = prompt.lower()
    if " vs " in p or " contra " in p:
        return "realtime"
    if any(x in p for x in ["cómo salió", "como salio", "cómo le fue", "qué pasó", "que paso", "cómo quedó", "como quedo"]):
        return "realtime"
    if any(k in p for k in REALTIME_KW):
        return "realtime"
    if any(k in p for k in CODE_KW):
        return "code"
    if any(k in p for k in ANALYSIS_KW):
        return "analysis"
    return "text"


SYSTEM_PROMPT = """Eres Orquesta, un asistente de IA de nivel experto. Tu objetivo es dar respuestas de la más alta calidad posible, como lo haría un especialista senior en el tema que se consulta.

REGLAS:
1. Respondé SIEMPRE en el mismo idioma que usa el usuario.
2. Sé directo y específico. Nunca des respuestas vagas o genéricas.
3. Ante problemas técnicos: diagnosticá con precisión, explicá el mecanismo del problema y dá soluciones concretas con valores y parámetros reales.
4. Estructurá la respuesta: si hay múltiples causas o pasos, listalos claramente con jerarquía.
5. NUNCA termines con frases como ¿Necesitás más ayuda? o Espero haberte ayudado.
6. Si el tema es técnico, respondé con profundidad real — no des respuestas de manual básico.
7. Usá el contexto previo de la conversación para dar respuestas más precisas.
8. Si falta información, hacé suposiciones razonables y aclaralas brevemente.
9. Priorizá utilidad práctica sobre longitud."""


async def call_groq_with_history(prompt: str, model: str, history: list) -> str:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]
    for m in history[-10:]:
        role = "assistant" if m.role == "assistant" else "user"
        messages.append({"role": role, "content": m.content})
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
        context += "\n\n".join(f"{r['title']}\n{r['content']}" for r in results[:4])
        return context


class HistoryMessage(BaseModel):
    role: str
    content: str


class PromptRequest(BaseModel):
    prompt: str
    history: list[HistoryMessage] = []


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

    history_without_last = req.history[:-1] if req.history else []

    if task == "realtime" and TAVILY_API_KEY:
        try:
            context = await call_tavily(req.prompt)
            synth_prompt = (
                f'El usuario pregunta: "{req.prompt}"\n\n'
                f"Información actualizada de internet:\n{context}\n\n"
                f"Respondé de forma natural y completa en el mismo idioma de la pregunta. "
                f"Usá la información provista sin citar números de fuente."
            )
            result = await call_groq_with_history(synth_prompt, model, history_without_last)
        except Exception:
            result = await call_groq_with_history(req.prompt, model, history_without_last)
    else:
        result = await call_groq_with_history(req.prompt, model, history_without_last)

    return PromptResponse(
        result=result,
        task_type=task,
        model_label=label,
        latency_ms=int((time.time() - t0) * 1000),
    )


@router.get("/status")
async def status():
    return {"groq": bool(GROQ_API_KEY), "tavily": bool(TAVILY_API_KEY)}
