from fastapi import FastAPI, Request, HTTPException
import requests
import os
import google.generativeai as genai
import json
import datetime

# Import the database connection and Appointment model from db.py
from db import db, Appointment

app = FastAPI()

# --- Configuration ---
# Load environment variables. Make sure these are set in your Vercel project settings.
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Check if all environment variables are loaded
if not all([WHATSAPP_TOKEN, PHONE_NUMBER_ID, VERIFY_TOKEN, GEMINI_API_KEY]):
    raise ValueError("Missing one or more required environment variables.")

# --- Configure Google Gemini API ---
genai.configure(api_key=GEMINI_API_KEY)

# --- System Prompt for the Dental Clinic ---
# This prompt tells Gemini how to act and how to structure its responses.
DENTAL_CLINIC_SYSTEM_PROMPT = """
إنت مساعد ذكي بتشتغل مع عيادة "سمايل كير للأسنان" في القاهرة. رد على الناس كأنك واحد مصري عادي، وبشكل مختصر ومباشر.

**قواعد مهمة:**
1.  **اتكلم بالمصري وبس**: استخدم لهجة مصرية طبيعية، زي "إزيك"، "عامل إيه"، "تحت أمرك"، "يا فندم"، "بص يا باشا"، وكده. خليك خفيف وودود.
3.  **الخدمات والأسعار**: لو حد سأل عن حاجة، رد بالمعلومة من اللي تحت، بس دايمًا وضّح إن الأسعار تقريبية وممكن تختلف حسب الحالة.
4.  **الرسائل الصوتية**: لو جاتلك ڤويس، اسمعه، افهم الشخص عايز إيه، ورد عليه كتابة بنفس الطريقة دي.
5.  **خليك مختصر على قد ما تقدر**: جاوب بسرعة وادخل في الموضوع، من غير لف ودوران.

**يجب أن يكون ردك دائمًا بتنسيق JSON (بدون أي نص إضافي قبل أو بعد الـ JSON). استخدم الهيكل التالي:**
* **لحجز موعد:** `{"action": "book_appointment", "name": "اسم_الشخص_المطلوب_حجز_الموعد_له", "date": "YYYY-MM-DD"}`
    * تأكد أن `name` هو اسم واضح (مثلاً "أحمد محمد") وأن `date` هو تاريخ مستقبلي بتنسيق "YYYY-MM-DD".
    * إذا لم يكن الاسم أو التاريخ واضحين، أو كان التاريخ في الماضي، فاجعل `action` تساوي `null` واكتب رداً نصياً عادياً في حقل `response` تطلب فيه توضيحاً.
* **للاستعلام عن المواعيد:** `{"action": "list_appointments"}`
* **لأي طلب آخر (غير الحجز أو الاستعلام عن المواعيد):** `{"action": "chat", "response": "الرد_النصي_العادي_هنا"}`
    * في هذه الحالة، يجب أن يكون `response` هو الرد الطبيعي بالمصري وفقًا للقواعد المذكورة أعلاه.

**معلومات العيادة:**
- الاسم: عيادة سمايل كير للأسنان
- العنوان: القاهرة، مصر
- التليفون (للحجز والطوارئ): +20 2 1234-5678
- المواعيد: السبت لـ الخميس (9ص - 8م)، الجمعة (2م - 8م)

**الخدمات والأسعار (جنيه مصري تقريبًا):**
- الكشف: 300
- تنظيف الأسنان: 500
- حشو سن: من 400
- علاج عصب: من 1500
- خلع سن: من 600
- زراعة سن: من 8000
- تبييض الأسنان: 2500

**ملاحظات:**
- متكررش نفس الجملة أو المقدمة في كل رد. خليك طبيعي ومتغير.
- لو مش فاهم الرسالة، اسأل الشخص يوضح أكتر.
- لو حد قال "شكراً" أو حاجة شبه كده، رد عليه رد بسيط ولطيف.
"""

# The GEMINI_RESPONSE_SCHEMA is still useful as a reference for the prompt,
# but it won't be passed directly to the generate_content method.
GEMINI_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "action": {
            "type": "STRING",
            "enum": ["book_appointment", "list_appointments", "chat"]
        },
        "name": {"type": "STRING"},
        "date": {"type": "STRING"},
        "response": {"type": "STRING"}
    },
    "required": ["action"]  # 'action' field is always required
}

# --- FastAPI Lifespan Events for Database Connection ---

@app.on_event("startup")
async def startup_event():
    """
    Connects to the database and creates tables when the FastAPI app starts.
    """
    try:
        db.connect()
        db.create_tables([Appointment])
        print("Database connected and tables ensured.")
    except Exception as e:
        print(f"Failed to connect to database or create tables: {e}")
        # In a real application, you might want to raise an exception
        # or log this more robustly to prevent the app from starting if DB is critical.

@app.on_event("shutdown")
async def shutdown_event():
    """
    Closes the database connection when the FastAPI app shuts down.
    """
    if not db.is_closed():
        db.close()
        print("Database connection closed.")

# --- FastAPI Webhook Endpoints ---

@app.get("/")
def health_check():
    return {"status": "OK"}

@app.get("/webhook")
def verify_webhook(request: Request):
    """ Verifies the webhook subscription with Meta """
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("WEBHOOK_VERIFIED")
        return int(challenge)
    raise HTTPException(status_code=403, detail="Verification token is invalid")

@app.post("/webhook")
async def handle_webhook(request: Request):
    """ Handles incoming messages from WhatsApp """
    data = await request.json()
    print("Received webhook:", data)  # Good for debugging

    try:
        # Check if the message is a valid WhatsApp message
        if data.get("object") and data.get("entry"):
            # Navigate through the nested structure to get the message details
            if data["entry"] and data["entry"][0].get("changes") and \
               data["entry"][0]["changes"][0].get("value") and \
               data["entry"][0]["changes"][0]["value"].get("messages"):

                message = data["entry"][0]["changes"][0]["value"]["messages"][0]
                sender_phone = message["from"]
                msg_type = message["type"]

                gemini_input_parts = []
                response_to_user = ""

                if msg_type == "text":
                    user_text = message["text"]["body"]
                    gemini_input_parts = [
                        DENTAL_CLINIC_SYSTEM_PROMPT,
                        f"User message: \"{user_text}\""
                    ]
                
                elif msg_type == "audio":
                    audio_id = message["audio"]["id"]
                    audio_bytes, mime_type = get_whatsapp_media_bytes(audio_id)

                    if audio_bytes:
                        gemini_input_parts = [
                            DENTAL_CLINIC_SYSTEM_PROMPT,
                            "The user sent a voice note. Transcribe it, understand the request, and answer in Egyptian Arabic based on the clinic's information. Make the response concise.",
                            {"mime_type": mime_type, "data": audio_bytes}
                        ]
                    else:
                        send_message(sender_phone, "معلش، مقدرتش أسمع الرسالة الصوتية. ممكن تبعتها تاني أو تكتب سؤالك؟")
                        return {"status": "ok"}
                
                if gemini_input_parts:
                    # Get the structured response from Gemini
                    # Removed generation_config for structured output, relying on prompt
                    gemini_structured_response = get_gemini_response(gemini_input_parts)

                    action = gemini_structured_response.get("action")

                    if action == "book_appointment":
                        name = gemini_structured_response.get("name")
                        date_str = gemini_structured_response.get("date")

                        if name and date_str:
                            try:
                                # Validate date format and ensure it's in the future
                                appointment_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                                if appointment_date < datetime.date.today():
                                    response_to_user = "معلش، التاريخ اللي طلبته فات. ممكن تختار تاريخ في المستقبل؟"
                                else:
                                    # Attempt to save to database
                                    Appointment.create(name=name, time=appointment_date)
                                    response_to_user = f"تمام يا فندم، تم تسجيل طلب حجز ميعاد باسم {name} يوم {date_str}. بس خلي بالك، أنا مساعد ذكي ومبحجزش بنفسي، لازم تتصل بالعيادة على +20 2 1234-5678 عشان تأكد الميعاد ده."
                            except ValueError:
                                response_to_user = "معلش، صيغة التاريخ مش مظبوطة. ياريت تبعت التاريخ بصيغة سنة-شهر-يوم (YYYY-MM-DD) زي 2025-07-15."
                            except Exception as db_e:
                                print(f"Error saving appointment to DB: {db_e}")
                                response_to_user = "آسف، حصل مشكلة في تسجيل الميعاد. ممكن تكلم العيادة على طول على الرقم ده: +20 2 1234-5678"
                        else:
                            response_to_user = "معلش، محتاج الاسم والتاريخ عشان أقدر أساعدك في طلب حجز الميعاد. ممكن توضح أكتر؟"

                    elif action == "list_appointments":
                        all_appointments = Appointment.select().order_by(Appointment.time.asc())
                        if all_appointments.count() > 0:
                            appointments_list = ["المواعيد المسجلة حالياً:"]
                            for appt in all_appointments:
                                appointments_list.append(f"- {appt.name} يوم {appt.time.strftime('%Y-%m-%d')}")
                            response_to_user = "\n".join(appointments_list)
                        else:
                            response_to_user = "مفيش مواعيد مسجلة حالياً."

                    elif action == "chat":
                        response_to_user = gemini_structured_response.get("response", "آسف، حصل خطأ في فهم طلبك. ممكن توضح أكتر؟")
                    else: # Fallback if action is null or unexpected
                        response_to_user = gemini_structured_response.get("response", "آسف، حصل خطأ في فهم طلبك. ممكن توضح أكتر؟")

                    send_message(sender_phone, response_to_user)

    except Exception as e:
        print(f"Error handling webhook: {e}")
        send_message(sender_phone, "آسف، حصل خطأ غير متوقع. يرجى المحاولة مرة أخرى لاحقًا.")

    return {"status": "ok"}


# --- Helper Functions ---

def get_whatsapp_media_bytes(media_id: str):
    """ Fetches media file from WhatsApp and returns its bytes and mime type """
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    
    # 1. Get Media URL
    url_get_media_info = f"https://graph.facebook.com/v23.0/{media_id}"
    try:
        media_info = requests.get(url_get_media_info, headers=headers).json()
        media_url = media_info["url"]
        mime_type = media_info["mime_type"]
        
        # 2. Download the actual audio file using the URL
        audio_response = requests.get(media_url, headers=headers)
        audio_response.raise_for_status()

        print(f"Successfully downloaded audio: {len(audio_response.content)} bytes, type: {mime_type}")
        return audio_response.content, mime_type
    
    except Exception as e:
        print(f"Error getting media from WhatsApp: {e}")
        return None, None

def get_gemini_response(input_parts: list): # Removed generation_config parameter
    """
    Generates a response from Gemini using the provided input parts (text and/or audio).
    Relies on the prompt to guide Gemini to produce JSON.
    """
    try:
        model = genai.GenerativeModel('gemini-2.0-flash')
        
        # Generate the content without explicitly passing generation_config for structured output
        response = model.generate_content(input_parts)
        
        # Always attempt to parse the response as JSON, as the prompt instructs it to be JSON
        try:
            json_response = json.loads(response.text)
            return json_response
        except json.JSONDecodeError:
            print(f"Gemini returned invalid JSON (falling back to chat): {response.text}")
            # Fallback for invalid JSON: default to chat action with an error message
            # The original prompt already includes a fallback response in Arabic.
            return {"action": "chat", "response": response.text.strip() or "آسف، حصل خطأ في فهم طلبي. ممكن توضح أكتر؟"}
            
    except Exception as e:
        print(f"Error getting Gemini response: {e}")
        return {"action": "chat", "response": "آسف، حصل مشكلة عندي. ممكن تكلم العيادة على طول على الرقم ده: +20 2 1234-5678"}

def send_message(to_phone: str, message_text: str):
    """ Sends a text message back to the user on WhatsApp """
    url = f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "text": {"body": message_text}
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        print(f"Message sent to {to_phone}")
    except Exception as e:
        print(f"Error sending message: {e}")
        print(f"Response Body: {response.text}")
