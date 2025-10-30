import streamlit as st
import pandas as pd
import pdfplumber
import re
from datetime import datetime
from io import BytesIO
import altair as alt

def extract_date_from_text(text):
    for line in text.split('\n')[:6]:
        match = re.search(r'(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})', line)
        if match:
            date_part, time_part = match.groups()
            try:
                return datetime.strptime(f"{date_part} {time_part}", "%d/%m/%Y %H:%M")
            except Exception:
                continue
    return None

def parse_testcounter(pdf_bytes):
    all_rows = []
    headers = ['Test', 'ACN', 'Routine', 'Rerun', 'STAT', 'Calibrator', 'QC', 'Total Count']
    header_pattern = r'Test\s+ACN\s+Routine\s+Rerun\s+STAT\s+Calibrator\s+QC\s+Total\s+Count'
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue
            lines = text.split('\n')
            current_unit = None
            date = extract_date_from_text(text)
            for idx, line in enumerate(lines):
                line_strip = line.strip()
                unit_match = re.match(r'Unit:\s*(\S+)', line_strip, re.IGNORECASE)
                if unit_match:
                    current_unit = unit_match.group(1)
                if re.search(header_pattern, line_strip, re.IGNORECASE):
                    for data_line in lines[idx+1:]:
                        data_line_strip = data_line.strip()
                        if (not data_line_strip or
                            data_line_strip.lower().startswith('total') or
                            data_line_strip.lower().startswith('unit:') or
                            data_line_strip.lower().startswith('system:')):
                            break
                        row = re.split(r'\s+', data_line_strip)
                        if len(row) >= 8:
                            row = row[:8]
                            row_dict = dict(zip(headers, row))
                            row_dict['Unit'] = current_unit
                            row_dict['Page'] = page_num + 1
                            row_dict['Date'] = date
                            all_rows.append(row_dict)
    if all_rows:
        df = pd.DataFrame(all_rows)
        cols = ['Unit', 'Date', 'Page'] + [c for c in df.columns if c not in ['Unit', 'Date', 'Page']]
        df = df[cols]
        df['Total Count'] = pd.to_numeric(df['Total Count'], errors='coerce').fillna(0).astype(int)
        return df
    return pd.DataFrame(columns=['Unit', 'Date', 'Page'] + headers)

st.title("LAB MIS Test Counter Dashboard")

# Left sidebar controls
uploaded_file = st.sidebar.file_uploader("Upload your PDF report", type=["pdf"])

df = pd.DataFrame()
if uploaded_file:
    with st.spinner("Extracting data..."):
        pdf_bytes = uploaded_file.read()
        df = parse_testcounter(pdf_bytes)

if not df.empty:
    df['Date'] = pd.to_datetime(df['Date']).dt.date

# Safe date picker in sidebar with validation
if not df.empty and 'Date' in df.columns and df['Date'].notnull().any():
    min_date = df['Date'].min()
    max_date = df['Date'].max()
    if isinstance(min_date, pd.Timestamp):
        min_date = min_date.date()
    if isinstance(max_date, pd.Timestamp):
        max_date = max_date.date()

    # st.date_input for date range picker returns tuple
    date_range = st.sidebar.date_input(
        "Select date range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date
    )

    if not isinstance(date_range, tuple) or len(date_range) != 2:
        # If user selects single date, convert to tuple
        date_range = (min_date, max_date)

    start_date, end_date = date_range
else:
    st.sidebar.warning("No valid dates found for filter.")
    start_date = end_date = None

all_units = sorted(df['Unit'].dropna().unique()) if not df.empty else []
selected_units = st.sidebar.multiselect("Select Unit(s)", options=all_units, default=all_units)

# Filter dataframe according to selections
if not df.empty:
    filtered_df = df
    if start_date and end_date:
        filtered_df = filtered_df[(filtered_df['Date'] >= start_date) & (filtered_df['Date'] <= end_date)]
    if selected_units:
        filtered_df = filtered_df[filtered_df['Unit'].isin(selected_units)]
else:
    filtered_df = pd.DataFrame()

# Main display area
st.subheader("Filtered Test Counter Data")

if not filtered_df.empty:
    st.dataframe(filtered_df)

    chart = alt.Chart(filtered_df).mark_line(point=True).encode(
        x='Date:T',
        y='Total Count:Q',
        color='Unit:N',
        tooltip=['Unit', 'Date', 'Total Count']
    ).interactive()

    st.altair_chart(chart, use_container_width=True)

    excel_bytes = BytesIO()
    filtered_df.to_excel(excel_bytes, index=False)
    st.download_button(
        "Download Filtered Data as Excel",
        excel_bytes.getvalue(),
        "filtered_testcounter.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
else:
    st.info("Upload a PDF and select filter criteria to view data.")
