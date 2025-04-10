import os
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, session
from openai import OpenAI
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from dotenv import load_dotenv
import logging

# Настройка логирования
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
app.secret_key = os.urandom(24)
load_dotenv()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# Инициализация клиента DeepSeek
client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com/v1"
)

# Настройки Google Calendar API
SCOPES = ['https://www.googleapis.com/auth/calendar']
CREDENTIALS_FILE = 'credentials.json'

# Чтение системного промпта
with open('prompt-doctor.txt', 'r', encoding='utf-8') as file:
    SYSTEM_PROMPT = file.read().strip()


def get_calendar_service():
    """Создает сервис для работы с Google Calendar"""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('calendar', 'v3', credentials=creds)


def create_calendar_event(patient_name, specialist, appointment_time):
    """Создает событие в календаре"""
    try:
        service = get_calendar_service()
        event = {
            'summary': f'Прием: {patient_name}, {specialist}',
            'description': 'Требует подтверждения',
            'start': {
                'dateTime': appointment_time.isoformat(),
                'timeZone': 'Europe/Moscow',
            },
            'end': {
                'dateTime': (appointment_time + timedelta(hours=1)).isoformat(),
                'timeZone': 'Europe/Moscow',
            },
        }
        event = service.events().insert(calendarId='primary', body=event).execute()
        logging.debug(f"Событие создано: {event.get('htmlLink')}")
        return event
    except Exception as e:
        logging.error(f"Ошибка создания события: {str(e)}")
        raise


def get_doctor_response(user_input, conversation_history):
    """Получает ответ от модели DeepSeek"""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *conversation_history,
        {"role": "user", "content": user_input}
    ]
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages
    )
    return response.choices[0].message.content


@app.route('/')
def index():
    session.clear()
    session['conversation'] = []
    return render_template('index1.html')


@app.route('/chat', methods=['POST'])
def chat():
    user_input = request.json.get('message').strip()
    conversation_history = session.get('conversation', [])

    # Добавляем сообщение пользователя в историю
    conversation_history.append({"role": "user", "content": user_input})

    # Получаем ответ от ИИ
    try:
        ai_response = get_doctor_response(user_input, conversation_history)
    except Exception as e:
        logging.error(f"Ошибка API DeepSeek: {str(e)}")
        return jsonify({'response': 'Произошла ошибка. Попробуйте еще раз.'})

    conversation_history.append({"role": "assistant", "content": ai_response})
    session['conversation'] = conversation_history

    # Обработка предложения записи
    if "предлагаем запись" in ai_response.lower():
        try:
            # Извлекаем время из ответа ИИ
            time_str = ai_response.split("в ")[1].split(".")[0].strip()
            appointment_time = datetime.strptime(time_str, "%H:%M")

            # Формируем дату записи (сегодня + 3 часа)
            appointment_time = datetime.now().replace(
                hour=appointment_time.hour,
                minute=appointment_time.minute
            ) + timedelta(hours=3)

            # Сохраняем данные в сессии
            session['appointment'] = {
                'time': appointment_time.isoformat(),
                'patient': user_input.split()[0],
                'specialist': ai_response.split("к ")[1].split(".")[0].strip()
            }

        except Exception as e:
            logging.error(f"Ошибка обработки времени: {str(e)}")
            return jsonify({'response': 'Произошла ошибка. Попробуйте еще раз.'})

    # Обработка подтверждения записи
    if user_input.lower() == "да" and 'appointment' in session:
        try:
            appointment = session['appointment']
            create_calendar_event(
                appointment['patient'],
                appointment['specialist'],
                datetime.fromisoformat(appointment['time'])
            )
            ai_response = f"Запись к {appointment['specialist']} на {appointment['time']} оформлена."
            session.pop('appointment')
        except Exception as e:
            logging.error(f"Ошибка записи: {str(e)}")
            ai_response = "Не удалось создать запись. Попробуйте позже."

    # Обработка отказа
    elif user_input.lower() == "нет" and 'appointment' in session:
        ai_response = "В случае ухудшения состояния обратитесь в скорую помощь по телефону 103."
        session.pop('appointment')

    return jsonify({'response': ai_response})


if __name__ == '__main__':
    app.run(debug=True)