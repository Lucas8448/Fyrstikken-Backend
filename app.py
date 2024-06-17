from flask import Flask, request, jsonify
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
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
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
    conn.execute("""
    CREATE TABLE IF NOT EXISTS tokens (
        token TEXT PRIMARY KEY,
        email TEXT NOT NULL
    )
    """)

    allowed_emails = os.getenv("ALLOWED_MAILS", "").split(',')
    for email in allowed_emails:
        conn.execute("INSERT OR IGNORE INTO users (email) VALUES (?)", (email,))
    
    conn.commit()
    conn.close()

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
    except FileNotFoundError as e:
        return {'message': 'Error reading email template: ' + str(e)}, 500
    except Exception as e:
        return {'message': 'Error processing email template: ' + str(e)}, 500

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
        return {'message': 'Failed to send email: ' + str(e)}, 500
    except Exception as e:
        return {'message': 'Unexpected error sending email: ' + str(e)}, 500

def generate_token(email):
    token = hashlib.sha256(os.urandom(64)).hexdigest()
    try:
        conn = get_db_connection()
        conn.execute("INSERT INTO tokens (token, email) VALUES (?,?)", (token, email))
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        return {'message': 'Database error generating token: ' + str(e)}, 500
    except Exception as e:
        return {'message': 'Unexpected error generating token: ' + str(e)}, 500
    return token

def verify_token(token):
    try:
        conn = get_db_connection()
        user = conn.execute("SELECT * FROM tokens WHERE token =?", (token,)).fetchone()
        conn.close()
    except sqlite3.Error as e:
        return False, {'message': 'Database error verifying token: ' + str(e)}
    except Exception as e:
        return False, {'message': 'Unexpected error verifying token: ' + str(e)}
    
    if user:
        return True, user['email']
    else:
        return False, {'message': 'Invalid token'}

def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.json.get('token')
        if not token:
            return jsonify({'message': 'Token is missing'}), 401
        is_valid, email_or_error = verify_token(token)
        if not is_valid:
            return jsonify(email_or_error), 401
        # Add the email to the request context for use in the view function
        request.email = email_or_error
        return f(*args, **kwargs)
    return decorated_function

@app.route('/access', methods=['POST'])
def user_access():
    email = request.json.get('email')
    code = request.json.get('code', None)

    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE email =?", (email,)).fetchone()

    if not user:
        conn.close()
        return jsonify({'error': 'Email not allowed'}), 403

    if code:
        if user['verification_code'] == code and int(time.time()) < user['code_expiry']:
            token = generate_token(email)
            conn.close()
            return jsonify({'token': token}), 200
        conn.close()
        return jsonify({'error': 'Invalid or expired code'}), 401
    else:
        code = generate_verification_code()
        expiry = int(time.time()) + 600
        conn.execute("UPDATE users SET verification_code =?, code_expiry =? WHERE email =?",
                     (code, expiry, email))
        conn.commit()
        send_verification_email(email, code)
        conn.close()
        return jsonify({'message': 'Verification code re-sent'}), 200

@app.route('/vote', methods=['POST'])
@token_required
def vote():
    email = request.email  # Retrieve the email from the request context
    contestant_id = request.json.get('contestant_id')

    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE email =?", (email,)).fetchone()

    if not user:
        conn.close()
        return jsonify({'error': 'User not found'}), 404

    if user['contestant_voted'] is not None:
        conn.close()
        return jsonify({'error': 'User has already voted'}), 400

    conn.execute("UPDATE users SET contestant_voted =? WHERE email =?", (contestant_id, email))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Vote recorded'}), 200

@app.route('/results', methods=['GET'])
def vote_results():
    conn = get_db_connection()
    results = conn.execute("SELECT contestant_voted, COUNT(*) as vote_count FROM users WHERE contestant_voted IS NOT NULL GROUP BY contestant_voted").fetchall()
    conn.close()

    vote_counts = {result['contestant_voted']: result['vote_count'] for result in results}

    return jsonify(vote_counts), 200

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', 'https://your-vercel-domain.vercel.app')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response

if __name__ == '__main__':
    init_db()
    context = ('cert.pem', 'key.pem')
    app.run(host='0.0.0.0', port=5000, ssl_context=context)
