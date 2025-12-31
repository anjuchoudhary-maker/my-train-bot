import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, request
import google.generativeai as genai
import requests

app = Flask(__name__)

# --- 1. LOAD SECRETS FROM SERVER ---
GEMINI_KEY = os.environ.get("GEMINI_KEY")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")
PHONE_ID = os.environ.get("PHONE_ID")
# We load the Google JSON key from a text variable
GOOGLE_CREDENTIALS = os.environ.get("GOOGLE_CREDENTIALS") 

# --- 2. SETUP GOOGLE SHEETS ---
def save_to_sheet(date, phone, origin, dest, train_class):
    try:
        # Convert the string back to a dictionary
        creds_dict = json.loads(GOOGLE_CREDENTIALS)
        scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        # Open the sheet named 'TrainBookings'
        sheet = client.open("TrainBookings").sheet1
        # Add the row
        sheet.append_row([date, phone, origin, dest, train_class, "PENDING"])
        return True
    except Exception as e:
        print(f"Sheet Error: {e}")
        return False

# --- 3. SETUP GEMINI AI ---
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# --- 4. THE WEBHOOK (WHATSAPP CONNECTS HERE) ---
@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    # VERIFICATION (Needed once)
    if request.method == 'GET':
        if request.args.get("hub.verify_token") == "blue_train_secret":
            return request.args.get("hub.challenge")
        return "Verification Failed", 403

    # MESSAGES
    if request.method == 'POST':
        data = request.json
        try:
            # Extract User Message
            msg_body = data['entry'][0]['changes'][0]['value']['messages'][0]
            user_text = msg_body['text']['body']
            user_phone = msg_body['from']
            
            # Send to AI
            process_chat(user_phone, user_text)
            
        except KeyError:
            pass # Ignore status updates (like "read" receipts)
            
        return "OK", 200

def process_chat(phone, text):
    # This instructs the AI how to behave
    prompt = f"""
    User Message: "{text}"
    
    You are a polite Train Ticket Clerk for 'EasyRail'.
    Your goal is to collect: Origin, Destination, Date, Class.
    
    Rules:
    1. If information is missing, ask for it politely (one question at a time).
    2. If ALL information is present, output ONLY this JSON format:
       {{"status": "COMPLETE", "origin": "...", "dest": "...", "date": "...", "class": "..."}}
    """
    
    response = model.generate_content(prompt)
    reply = response.text.strip()
    
    # Check if AI finished the job
    if "COMPLETE" in reply and "{" in reply:
        # Clean up the JSON
        clean_json = reply.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_json)
        
        # Save to Google Sheet
        success = save_to_sheet(data['date'], phone, data['origin'], data['dest'], data['class'])
        
        if success:
            send_whatsapp(phone, "✅ Great! I have received your request. Our agent will message you shortly for payment.")
        else:
            send_whatsapp(phone, "⚠️ Error saving data. Please try again.")
            
    else:
        # Just send the AI's question back to the user
        send_whatsapp(phone, reply)

def send_whatsapp(to, text):
    url = f"https://graph.facebook.com/v17.0/{PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }
    requests.post(url, headers=headers, json=payload)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
