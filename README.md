# Orquesta AI

**Tu IA. Todos los modelos.**

## Deploy en Railway (5 minutos)

### Paso 1 — Subir a GitHub
1. Entrá a **github.com** y creá un repositorio nuevo llamado `orquesta`
2. Subí todos estos archivos al repositorio

### Paso 2 — Conectar Railway
1. Andá a **railway.app** y creá cuenta con GitHub
2. Cliqueá **"New Project"** → **"Deploy from GitHub repo"**
3. Seleccioná el repo `orquesta`
4. Railway detecta automáticamente el Procfile y arranca el deploy

### Paso 3 — Agregar las API Keys
En Railway, entrá a tu proyecto → **Variables** → agregá:
```
GROQ_API_KEY=gsk_...
TAVILY_API_KEY=tvly-...
```

### Paso 4 — Obtener la URL pública
Railway te da una URL tipo `orquesta-production.up.railway.app`
¡Eso es todo — Orquesta está en vivo!

## APIs usadas
- **Groq** (gratis): console.groq.com
- **Tavily** (gratis, 1000 búsquedas/mes): app.tavily.com

## Estructura
```
orquesta/
├── main.py          # Servidor FastAPI
├── Procfile         # Instrucciones para Railway
├── requirements.txt
├── app/
│   └── routes.py   # Lógica del router
└── static/
    └── index.html  # Frontend
```
