from flask import Flask, request, jsonify
from flask_restful import Api, Resource
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os
import sqlite3
import dotenv
import random
import time
import hashlib
from functools import wraps

app = Flask(__name__)
api = Api(app)
dotenv.load_dotenv()

DATABASE = 'voting.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        verification_code TEXT,
        code_expiry INTEGER,
        contestant_voted INTEGER DEFAULT NULL
    )
    """)
    conn.commit()
    conn.close()

init_db()

def generate_verification_code():
    return random.randint(100000, 999999)

def send_verification_email(email, code):
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_PASSWORD")
    recipients = [email]
    subject = "Your Verification Code"

    try:
        with open("assets/email_template.html", "r") as file:
            html_content = file.read()
        html_content = html_content.replace("{code}", str(code))
    except Exception as e:
        print(f"Failed to read or process email template: {e}")
        return

    msg = MIMEMultipart()
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = ', '.join(recipients)
    msg.attach(MIMEText(html_content, 'html'))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp_server:
            smtp_server.login(sender, password)
            smtp_server.sendmail(sender, recipients, msg.as_string())
        print("Email sent successfully")
    except smtplib.SMTPException as e:
        print(f"Failed to send email: {e}")

def generate_token():
    return hashlib.sha256(os.urandom(64)).hexdigest()

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('x-access-token')
        if not token:
            return jsonify({'message': 'Token is missing'}), 401
        if not verify_token(token):
            return jsonify({'message': 'Token is invalid'}), 401
        return f(*args, **kwargs)
    return decorated

def verify_token(token):
    # Placeholder for token verification logic
    # In a real application, you would verify the token against stored tokens
    return True

class UserAccess(Resource):
    def post(self):
        email = request.json.get('email')
        code = request.json.get('code', None)

        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

        if not user:
            code = generate_verification_code()
            expiry = int(time.time()) + 600
            conn.execute("INSERT INTO users (email, verification_code, code_expiry) VALUES (?, ?, ?)",
                         (email, code, expiry))
            conn.commit()
            send_verification_email(email, code)
            conn.close()
            return {'message': 'User registered, verification code sent'}, 200

        if code:
            if user['verification_code'] == code and int(time.time()) < user['code_expiry']:
                token = generate_token()
                # Optionally, store the token in the database associated with the user
                conn.close()
                return {'token': token}, 200
            conn.close()
            return {'error': 'Invalid or expired code'}, 401
        else:
            code = generate_verification_code()
            expiry = int(time.time()) + 600
            conn.execute("UPDATE users SET verification_code = ?, code_expiry = ? WHERE email = ?",
                         (code, expiry, email))
            conn.commit()
            send_verification_email(email, code)
            conn.close()
            return {'message': 'Verification code re-sent'}, 200

class Vote(Resource):
    @token_required
    def post(self):
        email = request.json.get('email')
        contestant_id = request.json.get('contestant_id')

        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

        if not user:
            conn.close()
            return {'error': 'User not found'}, 404

        if user['contestant_voted'] is not None:
            conn.close()
            return {'error': 'User has already voted'}, 400

        conn.execute("UPDATE users SET contestant_voted = ? WHERE email = ?", (contestant_id, email))
        conn.commit()
        conn.close()
        return {'message': 'Vote recorded'}, 200

class VoteResults(Resource):
    def get(self):
        conn = get_db_connection()
        results = conn.execute("SELECT contestant_voted, COUNT(*) as vote_count FROM users WHERE contestant_voted IS NOT NULL GROUP BY contestant_voted").fetchall()
        conn.close()

        vote_counts = {result['contestant_voted']: result['vote_count'] for result in results}

        return jsonify(vote_counts), 200

api.add_resource(UserAccess, '/access')
api.add_resource(Vote, '/vote')
api.add_resource(VoteResults, '/results')

if __name__ == '__main__':
    app.run(debug=True)