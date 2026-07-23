"""
tasks/task_manager.py
Gestión completa de tareas y recordatorios para O.R.I.O.N..

CRUD de tareas con parseo de lenguaje natural en español.
Cada usuario tiene sus propias tareas aisladas (por user_id).
"""

import sqlite3
import datetime
import re
from pathlib import Path
from typing import Optional


# ── Base de datos global de tareas ─────────────────────────────────
TASKS_DB = Path(__file__).parent / "tasks.db"


def _get_conn() -> sqlite3.Connection:
    """Retorna conexión a la base de datos de tareas."""
    conn = sqlite3.connect(str(TASKS_DB))
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    """Crea la tabla de tareas si no existe."""
    conn = _get_conn()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            channel TEXT DEFAULT 'telegram',
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            due_date TEXT,
            remind_at TEXT,
            recurrence TEXT DEFAULT NULL,
            status TEXT DEFAULT 'pending',
            priority TEXT DEFAULT 'normal',
            notified INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT DEFAULT NULL
        )
    ''')
    conn.commit()
    conn.close()


# Inicializar al importar
_init_db()


# ── Parseo de fechas naturales ─────────────────────────────────────

def _parse_natural_date(text: str) -> Optional[datetime.datetime]:
    """
    Parsea expresiones de fecha/hora en español usando dateparser.
    Fallback a regex si dateparser no está instalado.
    """
    try:
        import dateparser
        settings = {
            'PREFER_DATES_FROM': 'future',
            'PREFER_DAY_OF_MONTH': 'first',
            'RETURN_AS_TIMEZONE_AWARE': False,
            'RELATIVE_BASE': datetime.datetime.now(),
        }
        parsed = dateparser.parse(text, languages=['es'], settings=settings)
        if parsed:
            # Si la fecha parseada es pasada, ajustar al futuro
            now = datetime.datetime.now()
            if parsed < now:
                # Si solo falta la hora (mismo día), mover al día siguiente
                if parsed.date() == now.date():
                    parsed += datetime.timedelta(days=1)
            return parsed
    except ImportError:
        pass

    # Fallback: regex simple para patrones comunes
    return _fallback_date_parse(text)


def _fallback_date_parse(text: str) -> Optional[datetime.datetime]:
    """Parseo básico con regex para cuando dateparser no está disponible."""
    now = datetime.datetime.now()
    text_lower = text.lower().strip()

    # "mañana" / "mañana a las X"
    if "mañana" in text_lower:
        base = now + datetime.timedelta(days=1)
        hour = _extract_hour(text_lower)
        if hour is not None:
            return base.replace(hour=hour, minute=0, second=0, microsecond=0)
        return base.replace(hour=9, minute=0, second=0, microsecond=0)

    # "pasado mañana"
    if "pasado mañana" in text_lower:
        base = now + datetime.timedelta(days=2)
        hour = _extract_hour(text_lower)
        if hour is not None:
            return base.replace(hour=hour, minute=0, second=0, microsecond=0)
        return base.replace(hour=9, minute=0, second=0, microsecond=0)

    # "en X horas"
    match = re.search(r'en\s+(\d+)\s+hora', text_lower)
    if match:
        hours = int(match.group(1))
        return now + datetime.timedelta(hours=hours)

    # "en X minutos"
    match = re.search(r'en\s+(\d+)\s+minuto', text_lower)
    if match:
        minutes = int(match.group(1))
        return now + datetime.timedelta(minutes=minutes)

    # "hoy a las X"
    if "hoy" in text_lower:
        hour = _extract_hour(text_lower)
        if hour is not None:
            target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            if target <= now:
                target += datetime.timedelta(days=1)
            return target

    # Días de la semana
    dias = {
        "lunes": 0, "martes": 1, "miércoles": 2, "miercoles": 2,
        "jueves": 3, "viernes": 4, "sábado": 5, "sabado": 5, "domingo": 6
    }
    for dia_nombre, dia_num in dias.items():
        if dia_nombre in text_lower:
            days_ahead = dia_num - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            base = now + datetime.timedelta(days=days_ahead)
            hour = _extract_hour(text_lower)
            if hour is not None:
                return base.replace(hour=hour, minute=0, second=0, microsecond=0)
            return base.replace(hour=9, minute=0, second=0, microsecond=0)

    # Solo hora: "a las 3pm", "a las 15:00"
    hour = _extract_hour(text_lower)
    if hour is not None:
        target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)
        return target

    return None


def _extract_hour(text: str) -> Optional[int]:
    """Extrae la hora de un texto como 'a las 3pm', 'a las 15:00', 'a las 9 de la mañana'."""
    # "a las 15:00" o "a las 3:30"
    match = re.search(r'a\s+las?\s+(\d{1,2})[:\s](\d{2})', text)
    if match:
        h = int(match.group(1))
        return h if 0 <= h <= 23 else None

    # "a las 3pm" / "a las 3 pm" / "a las 3 de la tarde"
    match = re.search(r'a\s+las?\s+(\d{1,2})\s*(pm|am|de la tarde|de la mañana|de la noche)?', text)
    if match:
        h = int(match.group(1))
        modifier = match.group(2) or ""
        if "pm" in modifier or "tarde" in modifier:
            if h < 12:
                h += 12
        elif "noche" in modifier:
            if h < 12:
                h += 12
        elif "am" in modifier or "mañana" in modifier:
            pass  # ya está bien
        else:
            # Sin modificador: si es < 7 asumir PM
            if h < 7:
                h += 12
        return h if 0 <= h <= 23 else None

    return None


# ── Parseo de recurrencia ──────────────────────────────────────────

def _parse_recurrence(text: str) -> Optional[str]:
    """Detecta si el texto indica una tarea recurrente."""
    text_lower = text.lower()

    # "todos los días" / "cada día" / "diariamente"
    if any(p in text_lower for p in ["todos los días", "todos los dias", "cada día", "cada dia", "diariamente"]):
        return "daily"

    # "todos los lunes" / "cada lunes"
    dias = {
        "lunes": "mon", "martes": "tue", "miércoles": "wed", "miercoles": "wed",
        "jueves": "thu", "viernes": "fri", "sábado": "sat", "sabado": "sat", "domingo": "sun"
    }
    for dia_es, dia_en in dias.items():
        if f"todos los {dia_es}" in text_lower or f"cada {dia_es}" in text_lower:
            return f"weekly:{dia_en}"

    # "cada semana"
    if "cada semana" in text_lower or "semanalmente" in text_lower:
        return "weekly:mon"

    # "cada mes" / "mensualmente" / "todos los meses"
    if any(p in text_lower for p in ["cada mes", "mensualmente", "todos los meses"]):
        return "monthly"

    return None


# ── Parseo completo de tarea natural ───────────────────────────────

def parse_natural_task(text: str, user_id: str, channel: str = "telegram") -> Optional[dict]:
    """
    Parsea un texto natural y extrae la información de la tarea.
    
    Retorna dict con los campos de la tarea, o None si no parece una tarea.
    """
    text_lower = text.lower().strip()

    # Detectar intención de tarea/recordatorio
    task_triggers = [
        "recuérdame", "recuerdame", "recordarme", "recordatorio",
        "agrega tarea", "agregar tarea", "nueva tarea", "crear tarea",
        "tengo que", "debo", "no olvidar", "no olvides",
        "pendiente", "tarea:"
    ]

    is_task = any(trigger in text_lower for trigger in task_triggers)
    if not is_task:
        return None

    # Extraer el título (quitar la parte de fecha/hora y triggers)
    title = text
    # Quitar triggers del inicio
    for trigger in task_triggers:
        if text_lower.startswith(trigger):
            title = text[len(trigger):].strip()
            break

    # Quitar expresiones de fecha del título
    date_patterns = [
        r'\b(?:mañana|pasado mañana|hoy)\b',
        r'\ba\s+las?\s+\d{1,2}(?::\d{2})?\s*(?:pm|am|de la (?:tarde|mañana|noche))?\b',
        r'\ben\s+\d+\s+(?:hora|minuto|día)s?\b',
        r'\bel\s+(?:lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo)\b',
        r'\btodos\s+los\s+(?:días|dias|lunes|martes|miércoles|miercoles|jueves|viernes|sábados|sabados|domingos)\b',
        r'\bcada\s+(?:día|dia|semana|lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo)\b',
    ]
    for pattern in date_patterns:
        title = re.sub(pattern, '', title, flags=re.IGNORECASE)

    # Limpiar el título
    title = re.sub(r'\s+', ' ', title).strip()
    title = title.strip('., ')

    if not title or len(title) < 3:
        title = text.strip()

    # Capitalizar primera letra
    title = title[0].upper() + title[1:] if title else title

    # Parsear fecha
    remind_at = _parse_natural_date(text)
    if remind_at is None:
        # Si no se especificó fecha, recordar en 1 hora por defecto
        remind_at = datetime.datetime.now() + datetime.timedelta(hours=1)

    # Parsear recurrencia
    recurrence = _parse_recurrence(text)

    # Detectar prioridad
    priority = "normal"
    if any(w in text_lower for w in ["urgente", "importante", "crítico", "critico"]):
        priority = "urgent"
    elif any(w in text_lower for w in ["alta prioridad", "prioridad alta"]):
        priority = "high"

    return {
        "user_id": user_id,
        "channel": channel,
        "title": title,
        "description": "",
        "due_date": remind_at.isoformat(),
        "remind_at": remind_at.isoformat(),
        "recurrence": recurrence,
        "priority": priority,
    }


# ── CRUD de tareas ─────────────────────────────────────────────────

class TaskManager:
    """Gestor central de tareas. Thread-safe gracias a SQLite."""

    def create_task(
        self,
        user_id: str,
        title: str,
        channel: str = "telegram",
        description: str = "",
        due_date: Optional[str] = None,
        remind_at: Optional[str] = None,
        recurrence: Optional[str] = None,
        priority: str = "normal"
    ) -> int:
        """Crea una tarea y retorna su ID."""
        now = datetime.datetime.now()

        if not due_date:
            due_date = (now + datetime.timedelta(hours=1)).isoformat()
        if not remind_at:
            remind_at = due_date

        conn = _get_conn()
        cursor = conn.execute(
            """INSERT INTO tasks 
               (user_id, channel, title, description, due_date, remind_at, recurrence, status, priority)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (user_id, channel, title, description, due_date, remind_at, recurrence, priority)
        )
        task_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return task_id

    def create_from_natural(self, text: str, user_id: str, channel: str = "telegram") -> Optional[dict]:
        """
        Crea una tarea a partir de texto natural.
        Retorna dict con info de la tarea creada, o None si no se pudo parsear.
        """
        parsed = parse_natural_task(text, user_id, channel)
        if not parsed:
            return None

        task_id = self.create_task(
            user_id=parsed["user_id"],
            title=parsed["title"],
            channel=parsed["channel"],
            description=parsed.get("description", ""),
            due_date=parsed.get("due_date"),
            remind_at=parsed.get("remind_at"),
            recurrence=parsed.get("recurrence"),
            priority=parsed.get("priority", "normal")
        )

        parsed["id"] = task_id
        return parsed

    def list_tasks(
        self,
        user_id: str,
        status: str = "pending",
        limit: int = 20
    ) -> list[dict]:
        """Lista tareas de un usuario, filtradas por estado."""
        conn = _get_conn()
        cursor = conn.execute(
            """SELECT * FROM tasks 
               WHERE user_id = ? AND status = ? 
               ORDER BY due_date ASC LIMIT ?""",
            (user_id, status, limit)
        )
        tasks = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return tasks

    def list_all_tasks(self, user_id: str, limit: int = 15) -> list[dict]:
        """Lista todas las tareas de un usuario, pendientes primero, ordenadas cronológicamente."""
        conn = _get_conn()
        cursor = conn.execute(
            """SELECT * FROM tasks 
               WHERE user_id = ? 
               ORDER BY CASE WHEN status = 'pending' THEN 0 ELSE 1 END, due_date ASC 
               LIMIT ?""",
            (user_id, limit)
        )
        tasks = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return tasks

    def list_today_tasks(self, user_id: str) -> list[dict]:
        """Lista tareas de hoy para un usuario."""
        today = datetime.date.today().isoformat()
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()

        conn = _get_conn()
        cursor = conn.execute(
            """SELECT * FROM tasks 
               WHERE user_id = ? AND status = 'pending'
               AND due_date >= ? AND due_date < ?
               ORDER BY due_date ASC""",
            (user_id, today, tomorrow)
        )
        tasks = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return tasks

    def complete_task(self, task_id: int, user_id: str) -> bool:
        """Marca una tarea como completada."""
        conn = _get_conn()
        cursor = conn.execute(
            """UPDATE tasks SET status = 'completed', completed_at = ? 
               WHERE id = ? AND user_id = ?""",
            (datetime.datetime.now().isoformat(), task_id, user_id)
        )
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return success

    def delete_task(self, task_id: int, user_id: str) -> bool:
        """Elimina una tarea."""
        conn = _get_conn()
        cursor = conn.execute(
            "DELETE FROM tasks WHERE id = ? AND user_id = ?",
            (task_id, user_id)
        )
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return success

    def get_due_reminders(self) -> list[dict]:
        """
        Retorna tareas cuyo remind_at ya pasó y no han sido notificadas.
        Usado por el scheduler para enviar recordatorios.
        """
        now = datetime.datetime.now().isoformat()
        conn = _get_conn()
        cursor = conn.execute(
            """SELECT * FROM tasks 
               WHERE status = 'pending' AND notified = 0 AND remind_at <= ?
               ORDER BY remind_at ASC""",
            (now,)
        )
        tasks = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return tasks

    def mark_notified(self, task_id: int):
        """Marca una tarea como notificada."""
        conn = _get_conn()
        conn.execute(
            "UPDATE tasks SET notified = 1 WHERE id = ?",
            (task_id,)
        )
        conn.commit()
        conn.close()

    def handle_recurrence(self, task: dict):
        """
        Si una tarea es recurrente, crea la siguiente ocurrencia
        después de ser notificada.
        """
        recurrence = task.get("recurrence")
        if not recurrence:
            return

        remind_at = datetime.datetime.fromisoformat(task["remind_at"])

        if recurrence == "daily":
            next_remind = remind_at + datetime.timedelta(days=1)
        elif recurrence.startswith("weekly:"):
            next_remind = remind_at + datetime.timedelta(weeks=1)
        elif recurrence == "monthly":
            month = remind_at.month + 1
            year = remind_at.year + (month - 1) // 12
            month = ((month - 1) % 12) + 1
            try:
                next_remind = remind_at.replace(year=year, month=month)
            except ValueError:
                import calendar
                last_day = calendar.monthrange(year, month)[1]
                next_remind = remind_at.replace(year=year, month=month, day=last_day)
        else:
            return

        self.create_task(
            user_id=task["user_id"],
            title=task["title"],
            channel=task.get("channel", "telegram"),
            description=task.get("description", ""),
            due_date=next_remind.isoformat(),
            remind_at=next_remind.isoformat(),
            recurrence=recurrence,
            priority=task.get("priority", "normal")
        )

    def get_task_summary(self, user_id: str) -> str:
        """Genera un resumen legible de todas las tareas del usuario (pendientes y completadas)."""
        tasks = self.list_all_tasks(user_id, limit=20)
        if not tasks:
            return "No tiene ninguna tarea registrada, Señor. Todo está en orden."

        priority_icons = {
            "urgent": "🔴",
            "high": "🟠",
            "normal": "🔵",
            "low": "⚪"
        }

        # Contar pendientes
        pendientes = sum(1 for t in tasks if t["status"] == "pending")

        lines = [f"*Listado de tareas (Últimas {len(tasks)} - Pendientes: {pendientes}):*\n"]
        for t in tasks:
            icon = priority_icons.get(t["priority"], "🔵")
            due = ""
            if t["due_date"]:
                try:
                    dt = datetime.datetime.fromisoformat(t["due_date"])
                    due = f" — {dt.strftime('%d/%m %H:%M')}"
                except (ValueError, TypeError):
                    pass

            recurrence_tag = ""
            if t.get("recurrence"):
                if t["recurrence"] == "daily":
                    recurrence_tag = " 🔁 Diaria"
                elif t["recurrence"].startswith("weekly:"):
                    recurrence_tag = " 🔁 Semanal"
                elif t["recurrence"] == "monthly":
                    recurrence_tag = " 🔁 Mensual"

            status_mark = "☑️" if t["status"] == "completed" else "☐"
            tachado_ini = "~" if t["status"] == "completed" else ""
            tachado_fin = "~" if t["status"] == "completed" else ""
            
            lines.append(f"{status_mark} {icon} *#{t['id']}* {tachado_ini}{t['title']}{tachado_fin}{due}{recurrence_tag}")

        return "\n".join(lines)

    def format_task_created(self, task_info: dict) -> str:
        """Formatea un mensaje de confirmación de tarea creada."""
        title = task_info.get("title", "Sin título")
        task_id = task_info.get("id", "?")

        remind_str = ""
        if task_info.get("remind_at"):
            try:
                dt = datetime.datetime.fromisoformat(task_info["remind_at"])
                remind_str = dt.strftime("%d/%m/%Y a las %H:%M")
            except (ValueError, TypeError):
                remind_str = task_info["remind_at"]

        recurrence_str = ""
        rec = task_info.get("recurrence")
        if rec == "daily":
            recurrence_str = "\n🔁 Recurrencia: Diaria"
        elif rec == "monthly":
            recurrence_str = "\n🔁 Recurrencia: Mensual"
        elif rec and rec.startswith("weekly:"):
            day_map = {"mon": "Lunes", "tue": "Martes", "wed": "Miércoles",
                       "thu": "Jueves", "fri": "Viernes", "sat": "Sábado", "sun": "Domingo"}
            day = rec.split(":")[1] if ":" in rec else ""
            recurrence_str = f"\n🔁 Recurrencia: Cada {day_map.get(day, day)}"

        priority_str = ""
        if task_info.get("priority") in ("urgent", "high"):
            priority_str = f"\n⚠️ Prioridad: {task_info['priority'].capitalize()}"

        return (
            f"✅ *Tarea registrada, Señor.*\n\n"
            f"📋 *{title}*\n"
            f"🆔 #{task_id}\n"
            f"⏰ Recordatorio: {remind_str}"
            f"{recurrence_str}"
            f"{priority_str}\n\n"
            f"Le notificaré en el momento indicado."
        )


# ── Instancia global ──────────────────────────────────────────────
task_manager = TaskManager()
