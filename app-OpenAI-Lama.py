from flask import Flask, render_template, request, jsonify
import os
import openai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime, timedelta
import pytz
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

app = Flask(__name__)

# Настройки OpenAI (DeepSeek API)
openai.api_base = "https://api.deepseek.com/v1"
openai.api_key = os.getenv("DEEPSEEK_API_KEY")

# Настройки Google Календаря
SCOPES = ["https://www.googleapis.com/auth/calendar"]
SERVICE_ACCOUNT_FILE = os.getenv("SERVICE_ACCOUNT_JSON")
CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID")

# Авторизация в Google Calendar
creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
service = build("calendar", "v3", credentials=creds)

# Системный промпт из файла
with open("prompt-doctor.txt", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

# История сообщений для сессии (в памяти, для демо)
sessions = {}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    user_message = request.json.get("message")
    session_id = request.json.get("session_id")

    # Инициализируем новую сессию, если session_id не передан
    if not session_id:
        session_id = "session_" + str(len(sessions) + 1)
        sessions[session_id] = {
            "history": [],
            "patient_name": None,
            "symptoms": None,
            "doctor_type": None,
            "proposed_datetime": None,
        }
    session_data = sessions[session_id]

    # Сохраняем сообщение пациента в истории сессии
    session_data["history"].append({"role": "user", "content": user_message})

    # Если имя еще не получено, выводим начальное сообщение из системного промпта
    if not session_data["patient_name"]:
        response_text = "Здравствуйте. Вы обратились в систему записи к врачу. Сообщите ваше Имя и опишите симптомы."
    else:
        # Если имя уже известо, можно добавить обращение к DeepSeek API
        response_text = get_doctor_response(session_data)

    # Если имя и симптомы установлены, но еще не предложена запись
    if session_data["patient_name"] and session_data["symptoms"] and not session_data["proposed_datetime"]:
        # Эмулируем определение необходимых сведений
        session_data["doctor_type"] = determine_doctor_type(session_data["symptoms"])
        proposed_datetime = datetime.now(pytz.timezone("Europe/Moscow")) + timedelta(hours=2)
        proposed_datetime_str = proposed_datetime.strftime("%Y-%m-%d %H:%M")
        session_data["proposed_datetime"] = proposed_datetime_str

        response_text = (
            f"Отлично, {session_data['patient_name']}! По вашим симптомам рекомендую обратиться к {session_data['doctor_type']}.\n"
            f"Предлагаем запись: Прием: {session_data['patient_name']}, {session_data['doctor_type']}\n"
            f"Дата/Время: {proposed_datetime_str}\n"
            "Подтвердите согласие (Да/Нет)."
        )

    # Проверка ответа пациента на предлагаемый приём
    if "да" in user_message.lower() and session_data["proposed_datetime"]:
        response_text = "Запись к врачу оформлена. Подтверждения события в календаре отправлены. Ожидайте приема."
        create_calendar_event(session_data)
        del sessions[session_id]  # Очистка сессии после успешной записи

    elif "нет" in user_message.lower() and session_data["proposed_datetime"]:
        response_text = "В случае ухудшения состояния обратитесь в скорую помощь по телефону 103."
        del sessions[session_id]

    # Если имя еще не получено, пытаемся распарсить ввод пациента
    if not session_data["patient_name"] and user_message:
        try:
            name, symptoms = parse_name_and_symptoms(user_message)
            session_data["patient_name"] = name
            session_data["symptoms"] = symptoms
            response_text = (
                f"Спасибо, {name}! Ваши симптомы: {symptoms}.\n"
                "Сейчас я определю, к какому врачу вам стоит обратиться..."
            )
        except ValueError:
            response_text = ("Не удалось распознать имя и симптомы. "
                             "Пожалуйста, сформулируйте так: 'Меня зовут [Имя], у меня [симптомы]'.")

    session_data["history"].append({"role": "assistant", "content": response_text})

    return jsonify({
        "response": response_text,
        "session_id": session_id,
    })


def get_doctor_response(session_data):
    """Запрос к DeepSeek API с использованием системного промпта"""
    try:
        completion = openai.ChatCompletion.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                *session_data["history"],
            ],
            temperature=0.7,
        )
        return completion.choices[0].message["content"].strip()
    except Exception as e:
        app.logger.error(f"DeepSeek API Error: {e}")
        return "Извините, произошла ошибка при обработке запроса. Попробуйте позже."


def determine_doctor_type(symptoms):
    """Определяем тип врача по ключевым словам в описании симптомов"""
    symptoms = symptoms.lower()
    if "горло" in symptoms or "ангина" in symptoms:
        return "терапевт (ЛОР)"
    elif "живот" in symptoms or "боли в желудке" in symptoms:
        return "гастроэнтеролог"
    elif "сердце" in symptoms or "давление" in symptoms:
        return "кардиолог"
    else:
        return "терапевт"


def parse_name_and_symptoms(text):
    """
    Простой парсер для строки вида:
    "Меня зовут Иван, у меня болит голова"
    -> ('Иван', 'болит голова')
    """
    parts = text.split(",")
    if len(parts) < 2:
        raise ValueError("Неверный формат")

    name_part = parts[0].lower()
    symptoms_part = ",".join(parts[1:]).strip()

    name = name_part.replace("меня зовут", "").strip().capitalize()
    symptoms = symptoms_part.replace("у меня", "").strip()
    if not name or not symptoms:
        raise ValueError("Имя или симптомы пусты")
    return name, symptoms


def create_calendar_event(session_data):
    """Создание события в Google Calendar с пометкой 'Требует подтверждения'"""
    try:
        event = {
            "summary": f"Прием: {session_data['patient_name']}, {session_data['doctor_type']}",
            "description": f"Симптомы: {session_data['symptoms']} Требует подтверждения",
            "start": {
                "dateTime": datetime.strptime(session_data["proposed_datetime"], "%Y-%m-%d %H:%M")
                            .replace(tzinfo=pytz.timezone("Europe/Moscow"))
                            .isoformat(),
            },
            "end": {
                "dateTime": (datetime.strptime(session_data["proposed_datetime"], "%Y-%m-%d %H:%M") + timedelta(hours=1))
                            .replace(tzinfo=pytz.timezone("Europe/Moscow"))
                            .isoformat(),
            },
        }
        service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
        app.logger.info(f"Event created: {event['summary']}")
    except HttpError as e:
        app.logger.error(f"Google Calendar Error: {e}")


if __name__ == "__main__":
    app.run(debug=True)