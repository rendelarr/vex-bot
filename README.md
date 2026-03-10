# Vex — Tu asistente personal ENTP 🤖

## ¿Qué puede hacer Vex?
- Conversar contigo y recordar cosas sobre ti
- Hacer seguimiento de tus metas y tareas
- Decirte el precio del dólar en Perú
- Mandarte un buenos días automático a las 8am con el dólar del día

---

## Comandos disponibles
| Comando | Función |
|---|---|
| `/start` | Iniciar conversación |
| `/tareas` | Ver tareas pendientes |
| `/metas` | Ver metas activas |
| `/dolar` | Ver tipo de cambio actual |

---

## Cómo subir a Render

### Paso 1 — Subir el código a GitHub
1. Crea una cuenta en github.com
2. Crea un repositorio nuevo (ej: `vex-bot`)
3. Sube estos archivos: `bot.py`, `requirements.txt`, `render.yaml`

### Paso 2 — Conectar con Render
1. Ve a render.com e inicia sesión
2. Clic en **"New +"** → **"Web Service"**
3. Conecta tu cuenta de GitHub
4. Selecciona el repositorio `vex-bot`
5. Render detectará el `render.yaml` automáticamente

### Paso 3 — Variables de entorno (aquí van tus claves)
En Render, ve a **"Environment"** y agrega:

| Variable | Valor |
|---|---|
| `TELEGRAM_TOKEN` | El token de @BotFather |
| `ANTHROPIC_API_KEY` | Tu API key de Anthropic |
| `YOUR_CHAT_ID` | Tu chat ID (ver abajo) |

### Paso 4 — Obtener tu Chat ID
1. Escríbele a tu bot en Telegram
2. Ve a: `https://api.telegram.org/bot<TU_TOKEN>/getUpdates`
3. Busca el campo `"id"` dentro de `"chat"` — ese es tu Chat ID

### Paso 5 — Deploy
Clic en **"Deploy"** — Render instalará todo y Vex estará viva.

---

## Costos estimados
- Render (plan free): $0
- Anthropic API: ~$1-3/mes con uso normal
- Telegram: $0
