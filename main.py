import os
import logging
import requests
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
import atexit

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

from dotenv import load_dotenv
load_dotenv()  # will read .env in current directory

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET")  # optional, recommended
MODEL_NAME = os.getenv("MODEL_NAME", "meta-llama/llama-3.2-3b-instruct:free") #deepseek/deepseek-chat-v3.1:free
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

if not TELEGRAM_BOT_TOKEN or not OPENROUTER_KEY:
    logging.warning("Missing TELEGRAM_BOT_TOKEN or OPENROUTER_KEY environment variables.")

@app.route("/", methods=["GET"])
def index():
    return "OK", 200

def call_openrouter(prompt_text):
    payload = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": prompt_text}],
        "max_tokens": 1500,
        "temperature": 0.1
    }
    headers = {"Authorization": f"Bearer {OPENROUTER_KEY}"}
    r = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=30)
    r.raise_for_status()
    j = r.json()
    # Robust extraction (OpenRouter uses choices[].message.content like OpenAI)
    try:
        return j["choices"][0]["message"]["content"].strip()
    except Exception:
        # fallbacks
        try:
            return j["choices"][0].get("text", "").strip()
        except Exception:
            return None

def send_telegram_message(chat_id, text, reply_to=None):
    print(f"{TELEGRAM_BOT_TOKEN}")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    body = {"chat_id": chat_id, "text": text}
    if reply_to:
        body["reply_to_message_id"] = reply_to
    resp = requests.post(url, json=body, timeout=10)
    resp.raise_for_status()
    return resp.json()

@app.route("/webhook", methods=["POST"])
def webhook():
    # optional secret token verification
    if WEBHOOK_SECRET:
        header_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if header_token != WEBHOOK_SECRET:
            logging.warning("Invalid webhook secret token")
            return jsonify({"ok": False, "reason": "invalid secret"}), 403

    payload = request.get_json(force=True, silent=True)
    if not payload:
        return "ok, not payload", 200

    message = payload.get("message") or payload.get("edited_message")
    if not message:
        return "ok, not message", 200

    text = message.get("text")
    chat_id = message["chat"]["id"]

    if not text:
        # ignore non-text messages (or send a small note)
        send_telegram_message(chat_id, "Please send text messages for translation.")
        return "ok, not text", 200

    try:
        prompt = f"Translate to English (do not provide any explanation): {text}"
        translated = call_openrouter(prompt)
        if not translated:
            translated = "Sorry, couldn't translate right now."
    except Exception as e:
        logging.exception("OpenRouter call failed")
        translated = "Sorry, translation service failed."

    try:
        send_telegram_message(chat_id, translated)
    except Exception:
        logging.exception("Failed to send Telegram message")

    return "ok", 200

def job():
    logging.info("Job is executing....")

##### setup scheduler ########
scheduler = BackgroundScheduler()
scheduler.add_job(func=job, trigger="interval", minutes=1)
scheduler.start()

atexit.register(lambda: scheduler.shutdown())


if __name__ == "__main__":
    # local dev
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
