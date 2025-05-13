from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime, timedelta
import logging
import re
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secure-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///tmp/site.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize extensions
db = SQLAlchemy(app)
CORS(app, resources={r"/api/*": {"origins": "http://localhost:3000"}})  # Adjust for production

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Email configuration
SMTP_HOST = os.environ.get('SMTP_HOST')
SMTP_PORT = os.environ.get('SMTP_PORT')
SMTP_USERNAME = os.environ.get('SMTP_USERNAME')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD')
FROM_EMAIL = os.environ.get('FROM_EMAIL')
TO_EMAIL = os.environ.get('TO_EMAIL')

# Database Models
class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    consultation_date = db.Column(db.DateTime, nullable=False)
    consultation_type = db.Column(db.String(100), nullable=True)
    details = db.Column(db.Text, nullable=True)
    message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Testimonial(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(100), nullable=False)
    text = db.Column(db.Text, nullable=False)
    image = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class PracticeArea(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    icon = db.Column(db.String(50), nullable=True)
    link = db.Column(db.String(200), nullable=False)

class Contact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Input Validators
def validate_email(email):
    if not email:
        return False
    pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    return re.match(pattern, email) is not None

def validate_booking(data):
    required_fields = ['name', 'email', 'phone', 'date', 'time']
    return all(field in data for field in required_fields) and validate_email(data['email'])

def validate_contact(data):
    required_fields = ['name', 'email', 'message']
    return all(field in data for field in required_fields) and validate_email(data['email'])

# Helper function to send email notification
def send_email_notification(subject, message_body):
    if not all([SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, FROM_EMAIL, TO_EMAIL]):
        logger.error("Email configuration missing")
        return False
    try:
        # Create email message
        msg = MIMEMultipart()
        msg['From'] = FROM_EMAIL
        msg['To'] = TO_EMAIL
        msg['Subject'] = subject
        msg.attach(MIMEText(message_body, 'plain'))

        # Connect to SMTP server
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()  # Enable TLS
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(FROM_EMAIL, TO_EMAIL, msg.as_string())
        logger.info(f"Email notification sent to {TO_EMAIL}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email notification: {str(e)}")
        return False

# Routes
@app.route('/api/bookings', methods=['GET'])
def get_available_slots():
    date_str = request.args.get('date')
    if not date_str:
        logger.warning("Missing date parameter")
        return jsonify({"error": "Date parameter is required"}), 400

    try:
        selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        logger.warning("Invalid date format")
        return jsonify({"error": "Invalid date format, use YYYY-MM-DD"}), 400

    # Define default available times
    default_times = [
        "9:00 AM", "10:00 AM", "11:00 AM", "1:00 PM",
        "2:00 PM", "3:00 PM", "4:00 PM"
    ]

    # Query bookings for the selected date
    start_of_day = datetime.combine(selected_date, datetime.min.time())
    end_of_day = start_of_day + timedelta(days=1)
    booked_slots = Booking.query.filter(
        Booking.consultation_date >= start_of_day,
        Booking.consultation_date < end_of_day
    ).all()

    # Extract booked times
    booked_times = [
        booking.consultation_date.strftime("%I:%M %p").lstrip("0") for booking in booked_slots
    ]

    # Filter out booked times
    available_slots = [time for time in default_times if time not in booked_times]

    logger.info(f"Available slots retrieved for {date_str}")
    return jsonify({"availableSlots": available_slots}), 200

@app.route('/api/bookings', methods=['POST'])
def create_booking():
    data = request.get_json()
    
    if not validate_booking(data):
        logger.warning("Invalid booking data")
        return jsonify({"error": "Invalid booking data"}), 400

    try:
        # Combine date and time into consultation_date
        consultation_date_str = f"{data['date']} {data['time']}"
        consultation_date = datetime.strptime(consultation_date_str, '%Y-%m-%d %I:%M %p')
    except ValueError:
        logger.warning("Invalid date or time format")
        return jsonify({"error": "Invalid date or time format"}), 400

    # Check for existing booking at the same date and time
    existing_booking = Booking.query.filter_by(consultation_date=consultation_date).first()
    if existing_booking:
        logger.warning(f"Booking conflict at {consultation_date}")
        return jsonify({"error": "This time slot is already booked"}), 409

    # Create new booking
    booking = Booking(
        name=data['name'],
        email=data['email'],
        phone=data['phone'],
        consultation_date=consultation_date,
        consultation_type=data.get('consultationType'),
        details=data.get('details'),
        message=data.get('message')
    )
    db.session.add(booking)
    db.session.commit()
    logger.info(f"Booking created: {data['email']}")

    booking_count = Booking.query.count()
        
    subject = f"New Booking Received (Booking #{booking_count})"
    message_body = (
        f"New Booking Received!\n\n"
        f"Name: {data['name']}\n"
        f"Email: {data['email']}\n"
        f"Phone: {data['phone']}\n"
        f"Date: {data['date']}\n"
        f"Time: {data['time']}\n"
        f"Consultation Type: {data.get('consultationType', 'N/A')}\n"
        f"Details: {data.get('details', 'N/A')}\n"
        f"Message: {data.get('message', 'N/A')}"
    )
    send_email_notification(subject, message_body)

    return jsonify({"message": "Booking created successfully", "id": booking.id}), 201

@app.route('/api/testimonials', methods=['GET'])
def get_testimonials():
    testimonials = Testimonial.query.all()
    result = [{
        "id": t.id,
        "name": t.name,
        "role": t.role,
        "text": t.text,
        "image": t.image
    } for t in testimonials]
    logger.info("Testimonials retrieved")
    return jsonify(result), 200

@app.route('/api/practice-areas', methods=['GET'])
def get_practice_areas():
    practice_areas = PracticeArea.query.all()
    result = [{
        "id": pa.id,
        "title": pa.title,
        "description": pa.description,
        "icon": pa.icon,
        "link": pa.link
    } for pa in practice_areas]
    logger.info("Practice areas retrieved")
    return jsonify(result), 200

@app.route('/api/contact', methods=['POST'])
def create_contact():
    data = request.get_json()
    
    if not validate_contact(data):
        logger.warning("Invalid contact data")
        return jsonify({"error": "Invalid contact data"}), 400

    contact = Contact(
        name=data['name'],
        email=data['email'],
        message=data['message']
    )
    db.session.add(contact)
    db.session.commit()
    logger.info(f"Contact message created: {data['email']}")

    # Send email notification
    subject = "New Contact Message Received"
    message_body = (
        f"New Contact Message Received!\n\n"
        f"Name: {data['name']}\n"
        f"Email: {data['email']}\n"
        f"Message: {data['message']}"
    )
    send_email_notification(subject, message_body)

    return jsonify({"message": "Contact message sent successfully", "id": contact.id}), 201

# Error Handling
@app.errorhandler(404)
def not_found(error):
    logger.error(f"404 error: {str(error)}")
    return {"error": "Not found"}, 404

@app.errorhandler(500)
def server_error(error):
    logger.error(f"Server error: {str(error)}")
    return {"error": "Internal server error"}, 500

# Initialize Database and Seed Data
with app.app_context():
    db.create_all()
    
    # Seed testimonials (if empty)
    if not Testimonial.query.first():
        testimonials = [
            {
                "name": "Priya Sharma",
                "role": "Family Law Client",
                "image": "/images/indian-client-1.jpg",
                "text": "B Sruti provided exceptional guidance during my divorce proceedings. Her expertise and compassion made a difficult time much easier to navigate. I couldn't have asked for better representation."
            },
            {
                "name": "Rajesh Patel",
                "role": "Business Client",
                "image": "/images/indian-client-2.jpg",
                "text": "As a small business owner, I needed clear legal advice. B Sruti delivered excellent service and continues to be our trusted advisor. Her strategic approach has saved us from numerous legal complications."
            },
            {
                "name": "Ananya Desai",
                "role": "Civil Law Client",
                "image": "/images/indian-client-3.jpg",
                "text": "B Sruti's attention to detail and strategic approach helped me win my case. I highly recommend her services to anyone needing legal representation. She's simply the best in the business."
            }
        ]
        for t in testimonials:
            testimonial = Testimonial(name=t['name'], role=t['role'], text=t['text'], image=t['image'])
            db.session.add(testimonial)
        db.session.commit()
        logger.info("Testimonials seeded")

    # Seed practice areas (if empty)
    if not PracticeArea.query.first():
        practice_areas = [
            {
                "title": "Civil Law",
                "description": "Resolution of disputesrule-based access control for disputes between individuals, organizations, or government entities.",
                "icon": "Scale",
                "link": "/practice-areas#civil-law"
            },
            {
                "title": "Criminal Law",
                "description": "Defending individuals charged with criminal offenses to protect their rights.",
                "icon": "Shield",
                "link": "/practice-areas#criminal-law"
            },
            {
                "title": "Family Law",
                "description": "Legal matters involving family relationships, including divorce and custody.",
                "icon": "FileText",
                "link": "/practice-areas#family-law"
            },
            {
                "title": "Legal Opinion",
                "description": "Expert legal analysis and advice on specific legal questions and situations.",
                "icon": "FileText",
                "link": "/practice-areas#legal-opinion"
            },
            {
                "title": "Mediation",
                "description": "Alternative dispute resolution to help parties reach mutually acceptable agreements.",
                "icon": "MessageSquare",
                "link": "/practice-areas#mediation"
            },
            {
                "title": "Legal Agreement",
                "description": "Drafting and reviewing contracts and agreements to protect your interests.",
                "icon": "FileText",
                "link": "/practice-areas#legal-agreement"
            }
        ]
        for pa in practice_areas:
            practice_area = PracticeArea(title=pa['title'], description=pa['description'], icon=pa['icon'], link=pa['link'])
            db.session.add(practice_area)
        db.session.commit()
        logger.info("Practice areas seeded")

if __name__ == '__main__':
    logger.info("Starting Flask application")
    app.run(debug=True)
