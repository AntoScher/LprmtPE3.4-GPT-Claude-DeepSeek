import os
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, session
from openai import OpenAI
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from dotenv import load_dotenv

app = Flask(__name__)
app.secret_key = os.urandom(24)
load_dotenv()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com/v1"
)

SCOPES = ['https://www.googleapis.com/auth/calendar']
CREDENTIALS_FILE = 'credentials.json'

with open('prompt-doctor.txt', 'r', encoding='utf-8') as file:
    SYSTEM_PROMPT = file.read().strip()


def get_calendar_service():
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
    service.events().insert(calendarId='primary', body=event).execute()


def get_doctor_response(user_input, conversation_history):
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
    user_input = request.json.get('message')
    conversation_history = session.get('conversation', [])
    conversation_history.append({"role": "user", "content": user_input})

    ai_response = get_doctor_response(user_input, conversation_history)
    conversation_history.append({"role": "assistant", "content": ai_response})
    session['conversation'] = conversation_history

    if "Предлагаем запись на сегодня в" in ai_response:
        time_str = ai_response.split("в ")[1].split(".")[0].strip()
        appointment_time = datetime.strptime(time_str, "%H:%M")
        appointment_time = datetime.now().replace(
            hour=appointment_time.hour,
            minute=appointment_time.minute
        ) + timedelta(hours=3)

        session['appointment'] = {
            'time': appointment_time.isoformat(),
            'patient': user_input.split()[0],
            'specialist': ai_response.split("к ")[1].split(".")[0]
        }

    if user_input.lower() == "да" and 'appointment' in session:
        appointment = session['appointment']
        create_calendar_event(
            appointment['patient'],
            appointment['specialist'],
            datetime.fromisoformat(appointment['time'])
        )
        ai_response = f"Запись к {appointment['specialist']} на {appointment['time']} оформлена."
        session.pop('appointment')

    if user_input.lower() == "нет" and 'appointment' in session:
        ai_response = "До свидания! В случае ухудшения состояния обратитесь в скорую помощь по телефону 103."
        session.pop('appointment')

    return jsonify({'response': ai_response})


if __name__ == '__main__':
    app.run(debug=True)