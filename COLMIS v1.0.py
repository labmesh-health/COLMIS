import streamlit as st
import pandas as pd
import pdfplumber
import re
from datetime import datetime
from io import BytesIO
import altair as alt

# Extract date from text
def extract_date_from_text(text):
    for line in text.split('\n')[:6]:
        match = re.search(r'(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})', line)
        if match:
            date_part, time_part = match.groups()
            try:
                return datetime.strptime(f"{date_part} {time_part}", "%d/%m/%Y %H:%M")
            except:
                continue
    return None

# Generic PDF table parser
def parse_table(pdf_bytes, headers, pattern):
    rows = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue
            lines = text.split('\n')
            current_unit = None
            date = extract_date_from_text(text)
            for i, line in enumerate(lines):
                line_strip = line.strip()
                # Detect unit for certain counters
                if 'Unit:' in line_strip:
                    match = re.match(r'Unit:\s*(\S+)', line_strip, re.IGNORECASE)
                    if match:
                        current_unit = match.group(1)
                # Find headers
                if re.search(pattern, line_strip, re.IGNORECASE):
                    for data_line in lines[i+1:]:
                        data_line_strip = data_line.strip()
                        # Break conditions
                        if not data_line_strip or data_line_strip.lower().startswith(('total', 'unit:', 'system:')):
                            break
                        row = re.split(r'\s+', data_line_strip)
                        if len(row) >= len(headers):
                            row = row[:len(headers)]
                            row_dict = dict(zip(headers, row))
                            if 'Unit' in row_dict:
                                current_unit = row_dict['Unit']
                            row_dict['Unit'] = current_unit
                            row_dict['Page'] = page_num + 1
                            row_dict['Date'] = date
                            rows.append(row_dict)
    df = pd.DataFrame(rows)
    if not df.empty:
        for col in df.columns:
            if col not in ['Unit', 'Date']:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
    return df

# Parsers for counters
def parse_test_counter(pdf_bytes):
    headers = ['Test', 'ACN', 'Routine', 'Rerun', 'STAT', 'Calibrator', 'QC', 'Total Count']
    pattern = r'Test\s+ACN\s+Routine\s+Rerun\s+STAT\s+Calibrator\s+QC\s+Total\s+Count'
    return parse_table(pdf_bytes, headers, pattern)

def parse_sample_counter(pdf_bytes):
    headers = ['Unit', 'Routine', 'Rerun', 'STAT', 'Total Count']
    pattern = r'Unit[:]*\s*Routine\s+Rerun\s+STAT\s+Total\s+Count'
    return parse_table(pdf_bytes, headers, pattern)

def parse_mc_counter(pdf_bytes):
    headers = ['Unit', 'MC Serial No.', 'Last Reset', 'Count after Reset', 'Total Count']
    pattern = r'Unit[:]*\s*MC Serial No\.\s+Last Reset\s+Count after Reset\s+Total Count'
    return parse_table(pdf_bytes, headers, pattern)

# Dashboard
st.title("LAB MIS Instrument Counters Dashboard")

uploaded_file = st.sidebar.file_uploader("Upload PDF", type=["pdf"])

# Initialize dataframes
test_df = sample_df = mc_df = pd.DataFrame()

if uploaded_file:
    pdf_bytes = uploaded_file.read()
    with st.spinner("Extracting Test Counter data..."):
        test_df = parse_test_counter(pdf_bytes)
    with st.spinner("Extracting Sample Counter data..."):
        sample_df = parse_sample_counter(pdf_bytes)
    with st.spinner("Extracting MC Counter data..."):
        mc_df = parse_mc_counter(pdf_bytes)

# Sidebar filters setup
def setup_filters(df, name):
    if df.empty or 'Date' not in df.columns or df['Date'].isnull().all():
        st.sidebar.warning(f"No valid date data in {name}")
        return None, []
    df['Date'] = pd.to_datetime(df['Date']).dt.date
    min_date = df['Date'].min()
    max_date = df['Date'].max()
    date_range = st.sidebar.date_input(f"{name} Date Range", value=(min_date, max_date), min_value=min_date, max_value=max_date)
    if not isinstance(date_range, tuple) or len(date_range) != 2:
        date_range = (min_date, max_date)
    all_units = sorted(df['Unit'].dropna().unique())
    unit = None
    if all_units:
        unit = st.sidebar.selectbox(f"{name} Unit", options=all_units)
    return date_range, unit

test_date_range, test_unit = setup_filters(test_df, "Test Counter") if not test_df.empty else (None, None)
sample_date_range, sample_unit = setup_filters(sample_df, "Sample Counter") if not sample_df.empty else (None, None)
mc_date_range, mc_unit = setup_filters(mc_df, "MC Counter") if not mc_df.empty else (None, None)

# Filter data
def filter_df(df, date_range, unit):
    if df.empty:
        return df
    start, end = date_range if date_range else (None, None)
    filt = df
    if start and end:
        filt = filt[(filt['Date'] >= start) & (filt['Date'] <= end)]
    if unit:
        filt = filt[filt['Unit'] == unit]
    return filt

filtered_test_df = filter_df(test_df, test_date_range, test_unit)
filtered_sample_df = filter_df(sample_df, sample_date_range, sample_unit)
filtered_mc_df = filter_df(mc_df, mc_date_range, mc_unit)

# Tabs for data display
tabs = st.tabs(["Test Counter", "Sample Counter", "MC Counter", "Download"])

# Test Counter Tab
with tabs[0]:
    st.header("Test Counter Data")
    if not filtered_test_df.empty:
        st.dataframe(filtered_test_df)
        chart = alt.Chart(filtered_test_df).mark_line(point=True).encode(
            x='Date:T',
            y='Total Count:Q',
            color='Unit:N',
            tooltip=['Unit', 'Date', 'Total Count']
        ).interactive()
        st.altair_chart(chart, use_container_width=True)
    else:
        st.info("No data available.")

# Sample Counter Tab
with tabs[1]:
    st.header("Sample Counter Data")
    if not filtered_sample_df.empty:
        st.dataframe(filtered_sample_df)
        if 'Routine' in filtered_sample_df.columns:
            chart_sample = alt.Chart(filtered_sample_df).mark_bar().encode(
                x='Unit:N',
                y='Routine:Q'
            )
            st.altair_chart(chart_sample, use_container_width=True)

# MC Counter Tab
with tabs[2]:
    st.header("MC Counter Data")
    if not filtered_mc_df.empty:
        st.dataframe(filtered_mc_df)
        chart_mc = alt.Chart(filtered_mc_df).mark_line().encode(
            x='Date:T',
            y='Total Count:Q',
            color='Unit:N'
        ).interactive()
        st.altair_chart(chart_mc, use_container_width=True)

# Download tab
with tabs[3]:
    st.header("Download Data")
    if not test_df.empty:
        st.download_button("Download Test CSV", test_df.to_csv(index=False), "test_counter.csv")
    if not sample_df.empty:
        st.download_button("Download Sample CSV", sample_df.to_csv(index=False), "sample_counter.csv")
    if not mc_df.empty:
        st.download_button("Download MC CSV", mc_df.to_csv(index=False), "mc_counter.csv")
