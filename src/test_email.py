import os
import smtplib
from email.message import EmailMessage

from dotenv import load_dotenv


load_dotenv()

smtp_user = os.getenv("SMTP_USER")
smtp_password = os.getenv("SMTP_PASSWORD")
email_to = os.getenv("EMAIL_TO")

if not smtp_user:
    raise RuntimeError("SMTP_USER puuttuu .env-tiedostosta")

if not smtp_password:
    raise RuntimeError("SMTP_PASSWORD puuttuu .env-tiedostosta")

if not email_to:
    raise RuntimeError("EMAIL_TO puuttuu .env-tiedostosta")


message = EmailMessage()
message["Subject"] = "Job Agent - sähköpostitesti"
message["From"] = smtp_user
message["To"] = email_to

message.set_content(
    "Job Agentin sähköpostitoiminto toimii."
)


print(f"Lähettäjä: {smtp_user}")
print(f"Vastaanottaja: {email_to}")
print("Yhdistetään Gmailiin...")


with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
    smtp.login(
        smtp_user,
        smtp_password
    )

    smtp.send_message(
        message
    )


print("Sähköposti lähetetty onnistuneesti.")