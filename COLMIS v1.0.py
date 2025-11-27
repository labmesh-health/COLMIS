import streamlit as st
import pandas as pd
import pdfplumber
import re
from datetime import datetime
from io import BytesIO
import altair as alt

STYLE = """
<style>
.rounded-box {
    padding: 15px;
    margin-bottom: 20px;
    box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
    border-radius: 12px;
    background-color: #fbfbfb;
}
</style>
"""
st.set_page_config(page_title="LAB MIS Dashboard", layout="wide")
st.markdown(STYLE, unsafe_allow_html=True)

def extract_date_from_text(text: str):
    for line in text.split("\n")[:6]:
        match = re.search(r"(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})", line)
        if match:
            date_str, time_str = match.groups()
            try:
                return datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M")
            except Exception:
                continue
    return None

def parse_test_counter(pdf_bytes: bytes) -> pd.DataFrame:
    headers = ["Test", "ACN", "Routine", "Rerun", "STAT", "Calibrator", "QC", "Total Count"]
    # Looser header pattern: anything between ACN and Total Count is allowed
    header_pattern = r"Test\s+ACN.*Total\s*Count"
    rows = []

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue

            date = extract_date_from_text(text)
            lines = text.split("\n")

            for i, line in enumerate(lines):
                if re.search(header_pattern, line, re.IGNORECASE):
                    for data_line in lines[i + 1 :]:
                        data_line = data_line.strip()
                        if not data_line or data_line.lower().startswith(("total", "unit:", "system:")):
                            break

                        parts = re.split(r"\s+", data_line)
                        # Need at least 8 columns: Test, ACN + 6 numeric
                        if len(parts) < 8:
                            continue

                        # Last 6 values are the numeric counters
                        nums = parts[-6:]
                        # The ACN is the second-last non-numeric piece, Test is everything before that
                        acn = parts[-7]
                        test_name = " ".join(parts[:-7]).strip()
                        if not test_name:
                            continue

                        row = {
                            "Test": test_name,
                            "ACN": acn,
                            "Routine": nums[0],
                            "Rerun": nums[1],
                            "STAT": nums[2],
                            "Calibrator": nums[3],
                            "QC": nums[4],
                            "Total Count": nums[5],
                            "Date": date,
                        }
                        rows.append(row)

    df = pd.DataFrame(rows)
    if not df.empty:
        for col in ["Routine", "Rerun", "STAT", "Calibrator", "QC", "Total Count"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
        df["Date"] = pd.to_datetime(df["Date"])
    return df

st.title("LAB MIS Instrument Test Counter Difference Calculator")

uploaded_file_1 = st.sidebar.file_uploader("Upload first PDF report", type=["pdf"], key="file1")
uploaded_file_2 = st.sidebar.file_uploader("Upload second PDF report", type=["pdf"], key="file2")

if uploaded_file_1 and uploaded_file_2:
    pdf_bytes1 = uploaded_file_1.read()
    pdf_bytes2 = uploaded_file_2.read()

    with st.spinner("Extracting Test Counter from first PDF..."):
        df1 = parse_test_counter(pdf_bytes1)
    with st.spinner("Extracting Test Counter from second PDF..."):
        df2 = parse_test_counter(pdf_bytes2)

    if df1.empty or df2.empty:
        st.error("Test Counter data could not be found in one or both PDFs.")
    else:
        agg_cols = ["Routine", "Rerun", "STAT", "Calibrator", "QC", "Total Count"]
        df1_grouped = df1.groupby("Test")[agg_cols].sum().reset_index()
        df2_grouped = df2.groupby("Test")[agg_cols].sum().reset_index()

        date1 = df1["Date"].min()
        date2 = df2["Date"].min()

        if date1 is not None and date2 is not None:
            if date1 > date2:
                df_newer, df_older = df1_grouped, df2_grouped
                new_date, old_date = date1, date2
            else:
                df_newer, df_older = df2_grouped, df1_grouped
                new_date, old_date = date2, date1

            merged_df = pd.merge(
                df_newer, df_older, on="Test", how="outer", suffixes=("_newer", "_older")
            ).fillna(0)

            for col in agg_cols:
                merged_df[f"{col}_newer"] = merged_df[f"{col}_newer"].astype(int)
                merged_df[f"{col}_older"] = merged_df[f"{col}_older"].astype(int)
                merged_df[f"{col}_diff"] = merged_df[f"{col}_newer"] - merged_df[f"{col}_older"]

            diff_display_cols = ["Test"] + [f"{col}_diff" for col in agg_cols]
            st.header(f"Test Counter Differences: {new_date.date()} minus {old_date.date()}")
            st.dataframe(merged_df[diff_display_cols])

            base = alt.Chart(merged_df).mark_bar().encode(
                x="Test:N",
                y="Total Count_diff:Q",
                color=alt.condition(
                    alt.datum["Total Count_diff"] > 0,
                    alt.value("green"),
                    alt.value("red"),
                ),
                tooltip=["Test", "Total Count_diff"],
            )
            st.altair_chart(base, use_container_width=True)
        else:
            st.error("Unable to extract dates from the PDFs for comparison.")
else:
    st.info("Please upload two PDF files in the sidebar to compare their test counters.")
