# testemail.py
from config import EMAIL_SENDER, EMAIL_PASSWORD, SMTP_SERVER, SMTP_PORT
import smtplib
from email.message import EmailMessage

msg = EmailMessage()
msg["Subject"] = "Test e-challan email"
msg["From"] = EMAIL_SENDER
msg["To"] = EMAIL_SENDER  # send to self for testing
msg.set_content("This is a test email from Smart Traffic Detection system.")

with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
    smtp.ehlo()
    smtp.starttls()
    smtp.login(EMAIL_SENDER, EMAIL_PASSWORD)
    smtp.send_message(msg)
print("Test email sent (check inbox).")
