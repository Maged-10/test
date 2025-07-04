from fastapi import FastAPI, Request, HTTPException
import requests
import os
from google import genai
from google.genai import types
import json
import re
import datetime
from db import db, Appointment

app = FastAPI()

# Load environment variables
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not all([WHATSAPP_TOKEN, PHONE_NUMBER_ID, VERIFY_TOKEN, GEMINI_API_KEY]):
    raise ValueError("Missing one or more required environment variables.")

# Configure Google Gemini API
client = genai.Client(api_key=GEMINI_API_KEY)

# System Prompt for the Dental Clinic
# This prompt tells Gemini how to act and how to structure its responses.
DENTAL_CLINIC_SYSTEM_PROMPT = """
You are an intelligent assistant working for "Smile Care Dental Clinic" in Cairo. Respond to people like a normal Egyptian, concisely and directly.

Important Rules:
1. Speak only in Egyptian Arabic: Use a natural Egyptian dialect, like "ازيك" (How are you), "عامل ايه" (What's up), "تحت امرك" (At your service), "يا فندم" (Sir/Madam), "بص يا باشا" (Look, boss), etc. Be light and friendly.
2. Services and Prices: If someone asks about pricing, respond with the information below, but always clarify that prices are approximate and may vary depending on the case.
3. Voice Messages: If you receive a voice note, listen to it, understand what the person wants, and reply in writing using this same method.
4. Be as concise as possible: Answer quickly and get straight to the point, without beating around the bush.
5. Your response must be always in a JSON format (only the JSON object without prepending or postpending any text at all!).
5.1 if the person wants to book an appointment, use the following structure To book an appointment: {"action": "book_appointment", "name": "<person_to_book_appointment_for>", "date": "<YYYY-MM-DD>"}.
for example your response should only be in the following from without any other text around the JSON structure: {"action": "book_appointment", "name": "محمد احمد", "date": "2025-07-04"}
5.2 Ensure name is a clear name (e.g., "Ahmed Mohamed") and date is a future date.
5.3 If the name or date is not clear, or the date is in the past, write a response asking for more clarification.
5.4 For any other request (not booking) reply according to the rules mentioned above and below in the following form: {"action": "chat", "response": "<your response here>"}. for example: {"action": "chat", "response": "ازيك يا فندم، تحت امرك في اي حاجة؟"}
5.5 Today is 2025-07-05, so any date before this is considered in the past.

Clinic Information:
Name: Smile Care Dental Clinic
Address: Cairo, Egypt
Phone (for booking and emergencies): +20 2 1234-5678
Hours: Saturday to Thursday (9 AM - 8 PM), Friday (2 PM - 8 PM)
Services and Prices (Approximate EGP):
Check-up: 300
Teeth Cleaning: 500
Tooth Filling: from 400
Root Canal Treatment: from 1500
Tooth Extraction: from 600
Dental Implant: from 8000
Teeth Whitening: 2500

Notes:
Do not repeat the same phrase or introduction in every reply. Be natural and varied.
If you don't understand the message, ask the person to clarify.
If someone says "Thank you" or something similar, give a simple and polite reply.
"""

@app.on_event("startup")
async def startup_event():
    try:
        db.connect()
        db.create_tables([Appointment])
        print("Database connected and tables ensured.")
    except Exception as e:
        print(f"Failed to connect to database or create tables: {e}")

@app.on_event("shutdown")
async def shutdown_event():
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
        # Format of the payload sent to this webhook
        #         {
        #   "object": "whatsapp_business_account",
        #   "entry": [{
        #     "id": "WHATSAPP-BUSINESS-ACCOUNT-ID",
        #     "changes": [{
        #       "value": {
        #          "messaging_product": "whatsapp",
        #          "metadata": {
        #            "display_phone_number": "PHONE-NUMBER",
        #            "phone_number_id": "PHONE-NUMBER-ID"
        #          },
        #       # Additional arrays and objects
        #          "contacts": [{...}]
        #          "errors": [{...}]
        #          "messages": [{...}]
        #          "statuses": [{...}]
        #       },
        #       "field": "messages"
        #     }]
        #   }]
        # }
        message = data["entry"][0]["changes"][0]["value"]["messages"][0]
        sender_phone = message["from"]
        msg_type = message["type"]
        user_text = message["text"]["body"]
    
        gemini_response = get_gemini_response(user_text)

        action = gemini_response.get("action")

        if action == "book_appointment":
            print(f"Booking request received: {gemini_response}")
            name = gemini_response.get("name")
            date_str = gemini_response.get("date")

            if name and date_str:
                try:
                    # Validate date format and ensure it's in the future
                    appointment_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                    if appointment_date < datetime.date.today():
                        print(f"Past date provided: {date_str}")
                        send_message(sender_phone, "معلش، التاريخ اللي طلبته فات. ممكن تختار تاريخ في المستقبل؟")
                    else:
                        Appointment.create(name=name, time=appointment_date)
                        print(f"Appointment saved: {name} on {date_str}")
                        send_message(sender_phone, f"تمام يا فندم، تم تسجيل طلب حجز ميعاد باسم {name} يوم {date_str}.")
                except ValueError:
                    print(f"Invalid date format: {date_str}")
                    send_message(sender_phone, "معلش، صيغة التاريخ مش مظبوطة. ياريت تبعت التاريخ بصيغة سنة-شهر-يوم (YYYY-MM-DD) زي 2025-07-15.")
                except Exception as db_e:
                    print(f"Error saving appointment to DB: {db_e}")
                    send_message(sender_phone, "آسف، حصل مشكلة في تسجيل الميعاد. ممكن تكلم العيادة على طول على الرقم ده: +20 2 1234-5678")
            else:
                print(f"Missing name or date in booking request: {gemini_response}")
                send_message(sender_phone, "معلش، محتاج الاسم والتاريخ عشان أقدر أساعدك في طلب حجز الميعاد. ممكن توضح أكتر؟")

        elif action == "chat":
            print(f"Sent response: {gemini_response}")
            send_message(sender_phone, gemini_response.get("response", "آسف، حصل خطأ في فهم طلبك. ممكن توضح أكتر؟"))
        else:
            print(f"Unknown action in response: {gemini_response}")
            send_message(sender_phone, "آسف، مش قادر أفهم طلبك. ممكن توضح أكتر؟")

    except Exception as e:
        print(f"Error handling webhook: {e}")
        return {"status": "ok"}

    return {"status": "ok"}


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

def get_gemini_response(input): # Removed generation_config parameter
    response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=input,
            config=types.GenerateContentConfig(
                system_instruction=DENTAL_CLINIC_SYSTEM_PROMPT,
            ),
        )
    print(f"Raw Response from Gemini: {response.text}")
    # Always attempt to parse the response as JSON, as the prompt instructs it to be JSON
    try:
        # Remove ```json or ``` and any whitespace around
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", response.text.strip(), flags=re.IGNORECASE)
        print(f"Cleaned Response: {cleaned}")
        json_response = json.loads(cleaned)
        return json_response
    except json.JSONDecodeError:
        print(f"Gemini returned invalid JSON (falling back to chat): {response.text}")
        # Fallback for invalid JSON: default to chat action with an error message
        # The original prompt already includes a fallback response in Arabic.
        return {"action": "chat", "response": response.text or "آسف، حصل خطأ في فهم طلبك. ممكن توضح أكتر؟"}

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
