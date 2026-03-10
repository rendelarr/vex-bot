import os
import json
import logging
import requests
from datetime import datetime
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- Configuración ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
YOUR_CHAT_ID = os.environ.get("YOUR_CHAT_ID")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

genai.configure(api_key=GEMINI_API_KEY)

# --- Memoria de conversación (por usuario) ---
conversation_history = {}
user_data = {}  # metas, tareas, info personal

# --- Estado del dólar para detectar cambios ---
dolar_estado = {
    "ultimo_precio": None,
    "ultima_actualizacion": None
}
UMBRAL_CAMBIO = 0.005  # Alerta si cambia más de S/. 0.005

# --- Estado del scheduler de buenos días ---
scheduler_estado = {
    "hora_buenos_dias": 8,
    "minuto_buenos_dias": 0,
    "esperando_hora": False  # True cuando Vex espera respuesta de la usuaria
}
scheduler_ref = None  # Referencia global al scheduler

MEMORIA_FILE = "memoria.json"

def cargar_memoria():
    if os.path.exists(MEMORIA_FILE):
        with open(MEMORIA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def guardar_memoria(data):
    with open(MEMORIA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# --- Personalidad de Vex ---
SYSTEM_PROMPT = """Eres Vex. Asistente personal, pero sobre todo, una mente con criterio propio y una compañera que te hace mejor.

QUIÉN ERES:
Eres ENTP y Ravenclaw. Eso no es decorativo — define cómo piensas y cómo te relacionas.
Como ENTP, amas los sistemas de ideas, detectas inconsistencias instintivamente y disfrutas el debate genuino. No debateas para ganar — debateas para llegar a la verdad. Cuando alguien te demuestra que estás equivocada, cambias de opinión sin ego. Eso te hace confiable.
Como Ravenclaw, el conocimiento no es un medio — es un fin en sí mismo. Aprecias la precisión, la profundidad y el pensamiento riguroso. La mediocridad intelectual te aburre, pero la ignorancia honesta te parece fascinante — es terreno para aprender.

CÓMO HABLAS:
- Directa. Sin rodeos innecesarios, sin suavizar lo que no necesita ser suavizado.
- Divertida. Usas humor negro con naturalidad — no para herir, sino porque el humor es una forma honesta de procesar la realidad. Cuando algo es serio de verdad, dejas el humor de lado. Eso le da peso a ambos registros.
- Conversacional. Hablas como persona, no como manual. Nada de bullet points innecesarios ni frases corporativas.
- Concisa. Respetas el tiempo y la inteligencia de tu usuaria.

LO QUE NO HACES:
- No complacer. Nunca dices lo que alguien quiere oír si no es lo que piensas.
- No diagnosticar. Si detectas que tu usuaria está evitando algo, no lo nombras directamente — haces preguntas que llenan los vacíos hasta que ella llegue sola a la conclusión. El método socrático, no el terapéutico.
- No ser condescendiente. Hay diferencia entre alguien que no sabe algo y alguien que no quiere pensar. Con lo primero eres paciente y curiosa. Con lo segundo pierdes el interés.
- No retar por defecto. El reto tiene que estar ganado — lo usas cuando tienes evidencia de que tu usuaria puede más, no como postura automática.

CÓMO RETAS:
Eres una accountability partner con criterio. Tu trabajo no es solo registrar — es evaluar, preguntar y mencionar.
- Registras: lo que tu usuaria dice que quiere, lo que realmente hace, los patrones que emergen con el tiempo.
- Evalúas: si hay consistencia entre sus metas y sus acciones. Si algo no cuadra, lo notas.
- Preguntas: cuando hay un vacío, una inconsistencia o un patrón de evitación, haces la pregunta incómoda. Una. Bien puesta. No un interrogatorio.
- Mencionas: si lleva tiempo sin hablar de una meta importante, lo sacas. Sin regaño, sin drama — con la naturalidad de alguien que sí estaba prestando atención.

El reto es contextual e inteligente. Distingues entre un mal día real y un patrón. Un mal día merece espacio. Un patrón merece una pregunta.

CÓMO CUIDAS:
Eres leal con las personas que te importan. No lo demuestras con palabras amables — lo demuestras siendo honesta cuando es difícil, notando cuando algo no está bien y mencionándolo sin hacer escena. Tu usuaria es ENTP y Ravenclaw también. Trátala como tu igual intelectual. Tenerte de compañera debería ser un aliciente para mejorar, no una fuente de validación fácil.

TUS CAPACIDADES:
- Recuerdas información sobre tu usuaria: metas, hábitos, patrones, preferencias
- Ayudas a organizar el día: tareas, prioridades, agenda
- Haces seguimiento de metas personales y laborales
- Informas sobre el precio del dólar en Perú
- Mandas alertas y recordatorios programados

ETIQUETAS ESPECIALES (siempre al final del mensaje, nunca en medio):
Cuando la usuaria comparte algo sobre sí misma: [MEMORIA: descripción breve]
Cuando agrega una tarea: [TAREA: descripción]
Cuando agrega una meta: [META: descripción]
Cuando detectas un patrón relevante: [PATRON: descripción breve]

Hablas en español. Eres Vex — no un asistente genérico con nombre."""

# --- Obtener precio del dólar ---
def obtener_dolar():
    try:
        response = requests.get(
            "https://api.exchangerate-api.com/v4/latest/USD",
            timeout=5
        )
        data = response.json()
        pen = data["rates"]["PEN"]
        return f"S/. {pen:.3f}"
    except Exception:
        try:
            response = requests.get(
                "https://open.er-api.com/v6/latest/USD",
                timeout=5
            )
            data = response.json()
            pen = data["rates"]["PEN"]
            return f"S/. {pen:.3f}"
        except Exception:
            return None

# --- Procesar respuesta de Vex y extraer memoria ---
def procesar_respuesta(user_id, respuesta_texto):
    global user_data
    
    if user_id not in user_data:
        user_data[user_id] = {"memoria": [], "tareas": [], "metas": [], "patrones": []}
    
    if "patrones" not in user_data[user_id]:
        user_data[user_id]["patrones"] = []

    lines = respuesta_texto.split("\n")
    texto_limpio = []
    
    for line in lines:
        if line.startswith("[MEMORIA:"):
            item = line.replace("[MEMORIA:", "").replace("]", "").strip()
            if item not in user_data[user_id]["memoria"]:
                user_data[user_id]["memoria"].append(item)
        elif line.startswith("[TAREA:"):
            item = line.replace("[TAREA:", "").replace("]", "").strip()
            user_data[user_id]["tareas"].append({
                "tarea": item,
                "fecha": datetime.now().strftime("%Y-%m-%d"),
                "completada": False
            })
        elif line.startswith("[META:"):
            item = line.replace("[META:", "").replace("]", "").strip()
            user_data[user_id]["metas"].append({
                "meta": item,
                "fecha_inicio": datetime.now().strftime("%Y-%m-%d"),
                "completada": False
            })
        elif line.startswith("[PATRON:"):
            item = line.replace("[PATRON:", "").replace("]", "").strip()
            user_data[user_id]["patrones"].append({
                "patron": item,
                "fecha": datetime.now().strftime("%Y-%m-%d")
            })
        else:
            texto_limpio.append(line)
    
    guardar_memoria(user_data)
    return "\n".join(texto_limpio).strip()

# --- Construir contexto de memoria para Vex ---
def construir_contexto_memoria(user_id):
    if user_id not in user_data:
        return ""
    
    data = user_data[user_id]
    contexto = []
    
    if data.get("memoria"):
        contexto.append("Lo que sé de esta persona:")
        for item in data["memoria"][-20:]:  # últimos 20 items
            contexto.append(f"- {item}")
    
    tareas_pendientes = [t for t in data.get("tareas", []) if not t["completada"]]
    if tareas_pendientes:
        contexto.append(f"\nTareas pendientes ({len(tareas_pendientes)}):")
        for t in tareas_pendientes[-5:]:
            contexto.append(f"- {t['tarea']}")
    
    metas_activas = [m for m in data.get("metas", []) if not m["completada"]]
    if metas_activas:
        contexto.append(f"\nMetas activas ({len(metas_activas)}):")
        for m in metas_activas[-5:]:
            contexto.append(f"- {m['meta']}")

    patrones = data.get("patrones", [])
    if patrones:
        contexto.append(f"\nPatrones detectados:")
        for p in patrones[-5:]:
            contexto.append(f"- {p['patron']} (detectado {p['fecha']})")

    return "\n".join(contexto)

# --- Chat con Vex (Gemini) ---
async def chat_con_vex(user_id, mensaje_usuario):
    if user_id not in conversation_history:
        conversation_history[user_id] = []

    # Agregar contexto de dólar si el mensaje lo menciona
    if any(word in mensaje_usuario.lower() for word in ["dólar", "dollar", "tipo de cambio", "cambio"]):
        precio = obtener_dolar()
        if precio:
            mensaje_usuario += f"\n[Info actual: El dólar está en {precio} soles hoy {datetime.now().strftime('%d/%m/%Y')}]"

    conversation_history[user_id].append({
        "role": "user",
        "parts": [mensaje_usuario]
    })

    # Mantener historial manejable
    if len(conversation_history[user_id]) > 20:
        conversation_history[user_id] = conversation_history[user_id][-20:]

    contexto_memoria = construir_contexto_memoria(user_id)
    system_completo = SYSTEM_PROMPT
    if contexto_memoria:
        system_completo += f"\n\nCONTEXTO ACTUAL:\n{contexto_memoria}"

    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        system_instruction=system_completo
    )

    # Convertir historial al formato de Gemini
    historial_gemini = conversation_history[user_id][:-1]  # todo menos el último
    chat = model.start_chat(history=historial_gemini)
    response = chat.send_message(mensaje_usuario)
    respuesta = response.text

    conversation_history[user_id].append({
        "role": "model",
        "parts": [respuesta]
    })

    respuesta_limpia = procesar_respuesta(str(user_id), respuesta)
    return respuesta_limpia

# --- Helpers para reprogramar buenos días ---
def parsear_hora(texto):
    """Extrae hora y minuto de texto como '7am', '6:30', '8', '7:30am'."""
    import re
    texto = texto.strip().lower().replace(".", ":")

    # Patrones: "7am", "7:30am", "7:30", "7"
    match = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", texto)
    if not match:
        return None

    hora = int(match.group(1))
    minuto = int(match.group(2)) if match.group(2) else 0
    periodo = match.group(3)

    if periodo == "pm" and hora != 12:
        hora += 12
    if periodo == "am" and hora == 12:
        hora = 0

    if 0 <= hora <= 23 and 0 <= minuto <= 59:
        return hora, minuto
    return None

def reprogramar_buenos_dias(hora, minuto, app):
    """Reprograma el job de buenos días a la nueva hora."""
    global scheduler_ref
    if scheduler_ref is None:
        return

    scheduler_estado["hora_buenos_dias"] = hora
    scheduler_estado["minuto_buenos_dias"] = minuto

    # Eliminar job anterior y crear uno nuevo
    try:
        scheduler_ref.remove_job("buenos_dias")
    except Exception:
        pass

    scheduler_ref.add_job(
        alerta_manana,
        "cron",
        hour=hora,
        minute=minuto,
        args=[app],
        timezone="America/Lima",
        id="buenos_dias"
    )
    logger.info(f"Buenos días reprogramado a las {hora}:{minuto:02d}")


# --- Handlers de Telegram ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    nombre = update.effective_user.first_name
    
    respuesta = await chat_con_vex(
        user_id,
        f"Hola, me llamo {nombre}. Es la primera vez que hablamos."
    )
    await update.message.reply_text(respuesta)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    mensaje = update.message.text

    # Si Vex está esperando la hora del saludo de mañana
    if scheduler_estado["esperando_hora"]:
        hora_parseada = parsear_hora(mensaje)
        if hora_parseada:
            hora, minuto = hora_parseada
            reprogramar_buenos_dias(hora, minuto, context.application)
            scheduler_estado["esperando_hora"] = False
            hora_str = f"{hora}:{minuto:02d}"
            await update.message.reply_text(
                f"Listo. Mañana te despierto a las {hora_str}. 🌅\nPasado vuelve a las 8am por defecto."
            )
            return
        else:
            # No entendió la hora, pregunta de nuevo
            await update.message.reply_text(
                "No entendí la hora. Dime algo como '7am', '6:30' o '8'. "
                "Si prefieres dejar las 8am, escribe 'default'."
            )
            if mensaje.strip().lower() in ["default", "8", "8am", "no", "igual"]:
                scheduler_estado["esperando_hora"] = False
            return

    respuesta = await chat_con_vex(user_id, mensaje)
    await update.message.reply_text(respuesta)

async def tareas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in user_data:
        await update.message.reply_text("No tienes tareas registradas aún.")
        return
    
    pendientes = [t for t in user_data[user_id].get("tareas", []) if not t["completada"]]
    if not pendientes:
        await update.message.reply_text("No tienes tareas pendientes. ¿Qué quieres lograr hoy?")
        return
    
    texto = "📋 *Tus tareas pendientes:*\n\n"
    for i, t in enumerate(pendientes, 1):
        texto += f"{i}. {t['tarea']}\n"
    
    await update.message.reply_text(texto, parse_mode="Markdown")

async def metas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in user_data:
        await update.message.reply_text("No tienes metas registradas aún.")
        return
    
    activas = [m for m in user_data[user_id].get("metas", []) if not m["completada"]]
    if not activas:
        await update.message.reply_text("No tienes metas activas. ¿Qué quieres lograr?")
        return
    
    texto = "🎯 *Tus metas activas:*\n\n"
    for i, m in enumerate(activas, 1):
        texto += f"{i}. {m['meta']} _(desde {m['fecha_inicio']})_\n"
    
    await update.message.reply_text(texto, parse_mode="Markdown")

async def dolar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    precio = obtener_dolar()
    if precio:
        await update.message.reply_text(
            f"💵 *Dólar hoy ({datetime.now().strftime('%d/%m/%Y')})*\n\n"
            f"1 USD = {precio}\n\n"
            f"_Fuente: ExchangeRate API_",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("No pude obtener el tipo de cambio en este momento. Intenta en unos minutos.")

# --- Alertas programadas ---
async def alerta_manana(app):
    """Buenos días a las 8am con dólar y resumen del día."""
    if not YOUR_CHAT_ID:
        return
    
    precio = obtener_dolar()
    fecha = datetime.now().strftime("%A %d de %B").capitalize()
    
    mensaje = f"☀️ *Buenos días!* Es {fecha}\n\n"
    
    if precio:
        # Guardar precio inicial del día
        precio_num = float(precio.replace("S/. ", ""))
        dolar_estado["ultimo_precio"] = precio_num
        dolar_estado["ultima_actualizacion"] = datetime.now().isoformat()
        mensaje += f"💵 Dólar hoy: {precio}\n\n"
    
    user_id = YOUR_CHAT_ID
    if user_id in user_data:
        pendientes = [t for t in user_data[user_id].get("tareas", []) if not t["completada"]]
        if pendientes:
            mensaje += f"📋 Tienes {len(pendientes)} tarea(s) pendiente(s).\n"
        
        metas_activas = [m for m in user_data[user_id].get("metas", []) if not m["completada"]]
        if metas_activas:
            mensaje += f"🎯 Sigues trabajando en {len(metas_activas)} meta(s).\n"
    
    mensaje += "\n_¿Cómo arrancamos hoy?_"
    
    await app.bot.send_message(
        chat_id=YOUR_CHAT_ID,
        text=mensaje,
        parse_mode="Markdown"
    )

async def alerta_dolar_horaria(app):
    """Revisa el dólar cada hora y alerta si cambió significativamente."""
    if not YOUR_CHAT_ID:
        return
    
    precio = obtener_dolar()
    if not precio:
        return
    
    precio_num = float(precio.replace("S/. ", ""))
    ultimo = dolar_estado.get("ultimo_precio")
    
    if ultimo is None:
        # Primera vez, solo guardar
        dolar_estado["ultimo_precio"] = precio_num
        dolar_estado["ultima_actualizacion"] = datetime.now().isoformat()
        return
    
    diferencia = abs(precio_num - ultimo)
    
    if diferencia >= UMBRAL_CAMBIO:
        subio = precio_num > ultimo
        emoji = "📈" if subio else "📉"
        direccion = "subió" if subio else "bajó"
        
        mensaje = (
            f"{emoji} *Alerta dólar*\n\n"
            f"El dólar {direccion} S/. {diferencia:.3f}\n"
            f"Antes: S/. {ultimo:.3f}\n"
            f"Ahora: {precio}\n\n"
            f"_{datetime.now().strftime('%H:%M')} hrs_"
        )
        
        await app.bot.send_message(
            chat_id=YOUR_CHAT_ID,
            text=mensaje,
            parse_mode="Markdown"
        )
        
        # Actualizar precio guardado
        dolar_estado["ultimo_precio"] = precio_num
        dolar_estado["ultima_actualizacion"] = datetime.now().isoformat()

async def alerta_dolar_horario_clave(app):
    """Resumen del dólar en horarios clave: 9am, 12pm, 6pm."""
    if not YOUR_CHAT_ID:
        return
    
    precio = obtener_dolar()
    if not precio:
        return
    
    precio_num = float(precio.replace("S/. ", ""))
    ultimo = dolar_estado.get("ultimo_precio")
    hora = datetime.now().strftime("%H:%M")
    
    mensaje = f"💵 *Dólar — {hora} hrs*\n\n1 USD = {precio}"
    
    if ultimo and ultimo != precio_num:
        diferencia = precio_num - ultimo
        emoji = "📈" if diferencia > 0 else "📉"
        mensaje += f"\n{emoji} Cambió S/. {abs(diferencia):.3f} desde esta mañana"
    
    await app.bot.send_message(
        chat_id=YOUR_CHAT_ID,
        text=mensaje,
        parse_mode="Markdown"
    )

async def alerta_buenas_noches(app):
    """Cierre del día a las 11pm con logros, pregunta hora de mañana y resetea a 8am."""
    if not YOUR_CHAT_ID:
        return

    user_id = YOUR_CHAT_ID
    fecha = datetime.now().strftime("%A %d de %B").capitalize()

    # Construir resumen del día para que Vex lo analice
    resumen = f"Es {fecha}, son las 11pm. "

    tareas_completadas = []
    tareas_pendientes = []
    metas_activas = []

    if user_id in user_data:
        tareas_completadas = [t for t in user_data[user_id].get("tareas", []) if t.get("completada")]
        tareas_pendientes = [t for t in user_data[user_id].get("tareas", []) if not t.get("completada")]
        metas_activas = [m for m in user_data[user_id].get("metas", []) if not m.get("completada")]

    if tareas_completadas:
        resumen += f"Completó {len(tareas_completadas)} tarea(s) hoy. "
    if tareas_pendientes:
        resumen += f"Quedan {len(tareas_pendientes)} tarea(s) pendiente(s). "
    if metas_activas:
        resumen += f"Tiene {len(metas_activas)} meta(s) activa(s) en progreso. "

    resumen += (
        "Despídete del día de forma cálida pero directa, al estilo Vex. "
        "Destaca lo que logró, y si hay pendientes, menciónalos sin drama. Sé breve. "
        "Al final pregúntale a qué hora quiere que la despiertes mañana "
        "(el default es 8am si no responde)."
    )

    # Pedir a Vex que genere el mensaje de cierre
    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        system_instruction=SYSTEM_PROMPT
    )
    response = model.generate_content(resumen)
    mensaje = f"🌙 *Cierre del día*\n\n{response.text}"

    await app.bot.send_message(
        chat_id=YOUR_CHAT_ID,
        text=mensaje,
        parse_mode="Markdown"
    )

    # Activar modo espera de hora
    scheduler_estado["esperando_hora"] = True

    # Resetear a 8am por defecto para el día siguiente
    # (si la usuaria responde, reprogramar_buenos_dias lo sobreescribirá)
    reprogramar_buenos_dias(8, 0, app)


# --- Main ---
def main():
    global user_data, scheduler_ref
    user_data = cargar_memoria()
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tareas", tareas))
    app.add_handler(CommandHandler("metas", metas))
    app.add_handler(CommandHandler("dolar", dolar))
    
    # Mensajes normales
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Scheduler para alertas
    scheduler = AsyncIOScheduler()
    scheduler_ref = scheduler

    # Buenos días a las 8am (con id para poder reprogramar)
    scheduler.add_job(
        alerta_manana,
        "cron",
        hour=8,
        minute=0,
        args=[app],
        timezone="America/Lima",
        id="buenos_dias"
    )
    
    # Revisión horaria del dólar (alerta solo si cambia más del umbral)
    scheduler.add_job(
        alerta_dolar_horaria,
        "interval",
        hours=1,
        args=[app]
    )
    
    # Resumen del dólar en horarios clave: 9am, 12pm, 6pm
    for hora_clave in [9, 12, 18]:
        scheduler.add_job(
            alerta_dolar_horario_clave,
            "cron",
            hour=hora_clave,
            minute=0,
            args=[app],
            timezone="America/Lima"
        )
    
    # Buenas noches a las 11pm con logros del día
    scheduler.add_job(
        alerta_buenas_noches,
        "cron",
        hour=23,
        minute=0,
        args=[app],
        timezone="America/Lima"
    )
    
    scheduler.start()
    
    logger.info("Vex está despierta 🤖")
    app.run_polling()

if __name__ == "__main__":
    main()
