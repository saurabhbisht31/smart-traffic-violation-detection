# config.py — application configuration (place next to adminapp.py)
# Update values here if needed.

# MySQL Database Settings (XAMPP)
DB_HOST = "localhost"
DB_USER = "root"
DB_PASSWORD = ""  # XAMPP default empty
DB_NAME = "helmet_detection"

# Folders
EVIDENCE_DIR = "static/evidence_images"
CHALLAN_DIR = "static/challans"
os_mkdirs = True

# Email (Gmail SMTP) — you supplied these
EMAIL_SENDER = "jonnytiwari61@gmail.com"
EMAIL_PASSWORD = "lyjdurilksuybwzr"   # stripped surrounding quotes if any
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# e-challan defaults
FINE_AMOUNT = 500.00
ISSUER_NAME = "Smart Traffic Detection System"
