import streamlit as st
import pandas as pd

from datetime import date
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from email_pdf_generator import save_email_as_pdf

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


@st.cache_resource
def get_gmail_service():
    creds = Credentials.from_authorized_user_file(
        "token.json",
        SCOPES
    )
    return build("gmail", "v1", credentials=creds)


def search_grab_emails(service, start_date, end_date, office_keyword):
    query = (
        f'"Grab E-Receipt" "{office_keyword}" '
        f'after:{start_date} before:{end_date}'
    )

    results = service.users().messages().list(
        userId="me",
        q=query,
        maxResults=100
    ).execute()

    return results.get("messages", [])


def generate_summary(df):
    df = df.copy()

    df["paid_amt"] = pd.to_numeric(
        df["paid_amt"],
        errors="coerce"
    ).fillna(0)

    summary_rows = []

    # by grab type
    if "grab_type" in df.columns:
        grouped = (
            df.groupby("grab_type")["paid_amt"]
            .agg(["count", "sum"])
            .reset_index()
        )

        for _, row in grouped.iterrows():
            summary_rows.append({
                "Category": row["grab_type"].title(),
                "Trips": row["count"],
                "Amount": row["sum"]
            })

    # by destination
    if "destination_type" in df.columns:
        grouped = (
            df.groupby("destination_type")["paid_amt"]
            .agg(["count", "sum"])
            .reset_index()
        )

        for _, row in grouped.iterrows():
            summary_rows.append({
                "Category": row["destination_type"].replace("_", " ").title(),
                "Trips": row["count"],
                "Amount": row["sum"]
            })

    summary_rows.append({
        "Category": "TOTAL",
        "Trips": len(df),
        "Amount": df["paid_amt"].sum()
    })

    return pd.DataFrame(summary_rows)


def process_emails(messages, output_folder):
    results = []

    progress_bar = st.progress(0)
    status = st.empty()

    total = len(messages)

    for idx, msg in enumerate(messages):
        status.info(f"Processing {idx + 1}/{total}")

        try:
            meta = save_email_as_pdf(
                msg["id"],
                output_folder
            )
            results.append(meta)

        except Exception as e:
            results.append({
                "receipt_date": None,
                "grab_type": None,
                "destination_type": None,
                "paid_amt": None,
                "filename": None,
                "error": str(e)
            })

        progress_bar.progress((idx + 1) / total)

    status.success("Done")

    return results


# ----------------------------
# UI
# ----------------------------

st.set_page_config(
    page_title="Grab Reimbursement Extractor",
    layout="wide"
)

st.title("🚕 Grab Reimbursement Extractor")

st.markdown("Search Grab receipts, generate Gmail-style PDFs, and export reimbursement summary.")

col1, col2, col3 = st.columns(3)

with col1:
    start_date = st.date_input(
        "Start Date",
        value=date.today().replace(day=1)
    )

with col2:
    end_date = st.date_input(
        "End Date",
        value=date.today()
    )

with col3:
    office_keyword = st.text_input(
        "Office Keyword",
        value="SCBD"
    )

if st.button("Extract Receipts", type="primary"):
    service = get_gmail_service()

    folder_name = date.today().strftime("%Y%m%d")
    folder_path = Path.cwd() / folder_name
    folder_path.mkdir(parents=True, exist_ok=True)

    with st.spinner("Searching emails..."):
        messages = search_grab_emails(
            service,
            start_date.strftime("%Y/%m/%d"),
            end_date.strftime("%Y/%m/%d"),
            office_keyword
        )

    st.info(f"Found {len(messages)} matching emails")

    if not messages:
        st.warning("No emails found.")
        st.stop()

    results = process_emails(
        messages,
        str(folder_path)
    )

    detail_df = pd.DataFrame(results)

    if detail_df.empty:
        st.error("No receipts processed.")
        st.stop()

    summary_df = generate_summary(detail_df)

    # -------------------------
    # Metrics
    # -------------------------
    detail_df["paid_amt"] = pd.to_numeric(
        detail_df["paid_amt"],
        errors="coerce"
    ).fillna(0)

    total_trips = len(detail_df)
    total_amount = detail_df["paid_amt"].sum()

    c1, c2 = st.columns(2)

    with c1:
        st.metric("Total Trips", total_trips)

    with c2:
        st.metric(
            "Total Amount",
            f"Rp {total_amount:,.0f}"
        )

    # -------------------------
    # Summary
    # -------------------------
    st.subheader("Summary")
    st.dataframe(
        summary_df,
        use_container_width=True
    )

    # -------------------------
    # Detail
    # -------------------------
    st.subheader("Receipt Detail")
    st.dataframe(
        detail_df,
        use_container_width=True
    )

    fout = str(folder_path) + "/grab_receipts_detail.csv"
    detail_df.to_csv(fout, index=False)
    st.success(f"PDFs saved in: {folder_path}")

    import shutil
    zip_path = shutil.make_archive(
        str(folder_path),
        "zip",
        str(folder_path)
    )
    st.success(f"PDF ZIP created: {zip_path}")