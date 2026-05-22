import base64
import re
from email.utils import parsedate_to_datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from playwright.sync_api import sync_playwright

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
OFFICE_KEYWORDS = ["SCBD"]


def decode_body(data):
    if not data:
        return None
    return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")


def extract_email_content(payload):
    html_body = None
    text_body = None

    def walk(part):
        nonlocal html_body, text_body

        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")

        if mime == "text/html" and data and not html_body:
            html_body = decode_body(data)

        elif mime == "text/plain" and data and not text_body:
            text_body = decode_body(data)

        for child in part.get("parts", []):
            walk(child)

    walk(payload)

    if html_body:
        return html_body

    if text_body:
        return f"<pre>{text_body}</pre>"

    return "<p>Email body unavailable</p>"


def get_headers(payload):
    headers = {}
    for h in payload.get("headers", []):
        headers[h["name"]] = h["value"]
    return headers


def clean_text(html):
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_receipt_metadata(email_html, headers):
    text = clean_text(email_html)

    # -------------------------
    # receipt date from Gmail header
    # -------------------------
    receipt_date = "unknown_date"

    try:
        dt = parsedate_to_datetime(headers.get("Date", ""))
        receipt_date = dt.strftime("%Y-%m-%d")
    except:
        pass

    # -------------------------
    # grab type
    # -------------------------
    if re.search(r"\bBike\b", text, re.I):
        grab_type = "bike"
    else:
        grab_type = "car"

    # -------------------------
    # amount
    # -------------------------
    amt_match = re.search(
        r"Total\s+Paid\s+(?:RP|Rp)?\s*([\d\.]+)",
        text,
        re.I
    )

    paid_amt = (
        amt_match.group(1).replace(".", "")
        if amt_match
        else "unknown"
    )

    # -------------------------
    # pickup/dropoff detection
    # -------------------------
    destination_type = "unknown"

    locations = re.findall(
        r"([A-Za-z0-9 ,.\-#/()]+?)\s+\d{1,2}:\d{2}(?:AM|PM)",
        text,
        re.I
    )

    if len(locations) >= 2:
        pickup = locations[0].upper()
        dropoff = locations[1].upper()

        if any(k in pickup for k in OFFICE_KEYWORDS):
            destination_type = "from_office"

        elif any(k in dropoff for k in OFFICE_KEYWORDS):
            destination_type = "to_office"

    return {
        "receipt_date": receipt_date,
        "grab_type": grab_type,
        "destination_type": destination_type,
        "paid_amt": paid_amt
    }


def build_filename(meta):
    return (
        f"{meta['receipt_date']}_"
        f"{meta['grab_type']}_"
        f"{meta['destination_type']}_"
        f"{meta['paid_amt']}.pdf"
    )


def build_printable_html(email_body, headers):
    subject = headers.get("Subject", "")
    sender = headers.get("From", "")
    reply_to = headers.get("Reply-To", "")
    recipient = headers.get("To", "")

    raw_date = headers.get("Date", "")
    try:
        dt = parsedate_to_datetime(raw_date)
        dt = dt.astimezone(ZoneInfo("Asia/Jakarta"))
        date = dt.strftime("%d %b %Y, %H:%M WIB")
    except:
        date = raw_date

    gmail_logo = "https://ssl.gstatic.com/ui/v1/icons/mail/rfr/logo_gmail_lockup_default_1x_r5.png"

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{
                margin: 0;
                background: #f1f3f4;
                font-family: Arial, Helvetica, sans-serif;
                color: #202124;
            }}

            .page {{
                padding: 12px;
                box-sizing: border-box;
            }}

            .topbar {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 8px 0 16px 0;
            }}

            .logo {{
                height: 36px;
            }}

            .account {{
                font-size: 14px;
                font-weight: 600;
                color: #5f6368;
            }}

            .mail-shell {{
                border-top: 2px solid #9e9e9e;
            }}

            .subject-row {{
                padding: 12px 0;
                font-size: 24px;
                font-weight: 700;
                border-bottom: 2px solid #9e9e9e;
            }}

            .meta-row {{
                display: flex;
                justify-content: space-between;
                align-items: flex-start;
                padding: 12px 0 24px 0;
                font-size: 14px;
            }}

            .meta-left {{
                line-height: 1.4;
            }}

            .sender {{
                font-weight: bold;
            }}

            .meta-right {{
                white-space: nowrap;
            }}

            .email-wrapper {{
                display: flex;
                justify-content: center;
            }}

            .email-content {{
                width: 100%;
                max-width: 820px;
                background: white;
                overflow: hidden;
            }}

            img {{
                max-width: 100%;
                height: auto;
            }}

            table {{
                max-width: 100% !important;
            }}

            td {{
                word-break: break-word;
            }}

            pre {{
                white-space: pre-wrap;
                word-wrap: break-word;
                font-family: Arial;
            }}

            @page {{
                size: A4;
                margin: 10mm;
            }}
        </style>
    </head>

    <body>
        <div class="page">
            <div class="topbar">
                <img class="logo" src="{gmail_logo}">
                <div class="account">{recipient}</div>
            </div>

            <div class="mail-shell">
                <div class="subject-row">
                    {subject}
                </div>

                <div class="meta-row">
                    <div class="meta-left">
                        <div class="sender">{sender}</div>
                        <div>Reply-To: {reply_to}</div>
                        <div>To: {recipient}</div>
                    </div>

                    <div class="meta-right">
                        {date}
                    </div>
                </div>

                <div class="email-wrapper">
                    <div class="email-content">
                        {email_body}
                    </div>
                </div>
            </div>
        </div>
    </body>
    </html>
    """


def save_email_as_pdf(message_id, path_folder):
    creds = Credentials.from_authorized_user_file(
        "token.json",
        SCOPES
    )

    service = build("gmail", "v1", credentials=creds)

    msg = service.users().messages().get(
        userId="me",
        id=message_id,
        format="full"
    ).execute()

    headers = get_headers(msg["payload"])
    email_body = extract_email_content(msg["payload"])

    meta = parse_receipt_metadata(email_body, headers)
    output_file = build_filename(meta)
    output_file = path_folder +'/'+ output_file

    final_html = build_printable_html(email_body, headers)

    with sync_playwright() as p:
        browser = p.chromium.launch()

        page = browser.new_page(
            viewport={
                "width": 1600,
                "height": 2200
            }
        )

        page.set_content(
            final_html,
            wait_until="networkidle"
        )

        page.pdf(
            path=output_file,
            format="A4",
            print_background=True
        )

        browser.close()

    print(f"Saved: {output_file}")
    return meta


# if __name__ == "__main__":
#     message_id = input("Enter Gmail Message ID: ").strip()
#     email_meta = save_email_as_pdf(message_id)