import streamlit as st
import pdfplumber
import pandas as pd
import re
from datetime import datetime
import os

# --- File Storage Names ---
TEST_COUNTER_CSV = "test_counter_data.csv"
SAMPLE_COUNTER_CSV = "sample_counter_data.csv"
MC_COUNTER_CSV = "mc_counter_data.csv"

# --- Extraction Helpers ---

def extract_date_from_page_text(text):
    date_match = re.search(r'Date[:\s]+(\d{4}-\d{2}-\d{2})', text)
    if date_match:
        return datetime.strptime(date_match.group(1), '%Y-%m-%d').date()
    else:
        # Fallback: try to find any date pattern YYYY-MM-DD
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', text)
        if date_match:
            return datetime.strptime(date_match.group(1), '%Y-%m-%d').date()
    return None

def find_table_by_header(tables, possible_headers):
    """
    Helper: Given list of pdfplumber-extracted tables, return index and table matching any of the possible_headers.
    """
    for i, t in enumerate(tables):
        header = [col.strip().lower() for col in t[0]]
        for ph in possible_headers:
            if all(h.lower() in header for h in ph):
                return i, t
    return None, None

def extract_tables_by_type(pdf_path):
    """
    Extracts Test Counter, Sample Counter, MC Counter tables into their own DataFrames
    (appends all new data with date per page)
    """
    test_rows = []
    sample_rows = []
    mc_rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            page_date = extract_date_from_page_text(text)
            tables = page.extract_tables()

            # -- Test Counter (standard test table) --
            tc_headers = [
                ['Test', 'ACN', 'Routine', 'Rerun', 'STAT', 'Calibrator', 'QC', 'Total Count']
            ]
            i_tc, table_tc = find_table_by_header(tables, tc_headers)
            if i_tc is not None:
                df_tc = pd.DataFrame(table_tc[1:], columns=table_tc[0])
                df_tc['Date'] = page_date
                test_rows.append(df_tc)

            # -- Sample Counter --
            sc_headers = [
                ['Unit:', 'Routine', 'Rerun', 'STAT', 'Total Count'],
                ['Unit', 'Routine', 'Rerun', 'STAT', 'Total Count']
            ]
            i_sc, table_sc = find_table_by_header(tables, sc_headers)
            if i_sc is not None:
                df_sc = pd.DataFrame(table_sc[1:], columns=table_sc[0])
                df_sc['Date'] = page_date
                sample_rows.append(df_sc)

            # -- Measuring Cells Counter --
            mc_headers = [
                ['Unit:', 'MC Serial No.', 'Last Reset', 'Count after Reset', 'Total Count'],
                ['Unit', 'MC Serial No.', 'Last Reset', 'Count after Reset', 'Total Count']
            ]
            i_mc, table_mc = find_table_by_header(tables, mc_headers)
            if i_mc is not None:
                df_mc = pd.DataFrame(table_mc[1:], columns=table_mc[0])
                df_mc['Date'] = page_date
                mc_rows.append(df_mc)

    # Clean up and merge all frames
    test_df = pd.concat(test_rows, ignore_index=True) if test_rows else pd.DataFrame()
    sample_df = pd.concat(sample_rows, ignore_index=True) if sample_rows else pd.DataFrame()
    mc_df = pd.concat(mc_rows, ignore_index=True) if mc_rows else pd.DataFrame()
    return test_df, sample_df, mc_df

def append_and_save(df, file):
    if os.path.exists(file):
        existing = pd.read_csv(file)
        combined = pd.concat([existing, df], ignore_index=True).drop_duplicates()
    else:
        combined = df
    combined.to_csv(file, index=False)
    return combined

# --- Streamlit UI ---
st.set_page_config(page_title="Instrument Analysis", layout='wide')
st.title("Instrument Counter Dashboard")

# === Sidebar ===
with st.sidebar:
    st.header("Controls")
    uploaded_file = st.file_uploader("Upload a PDF file", type=["pdf"])

# --- Load persistent data ---
def safe_load(file):
    if os.path.exists(file):
        return pd.read_csv(file)
    else:
        return pd.DataFrame()

test_counter_df = safe_load(TEST_COUNTER_CSV)
sample_counter_df = safe_load(SAMPLE_COUNTER_CSV)
mc_counter_df = safe_load(MC_COUNTER_CSV)

# --- Process PDF Upload ---
if uploaded_file:
    with open("temp_uploaded.pdf", "wb") as f:
        f.write(uploaded_file.getbuffer())
    st.sidebar.success('File uploaded.')
    tdf, sdf, mdf = extract_tables_by_type("temp_uploaded.pdf")

    # Try converting numeric columns
    for df in [tdf, sample_counter_df, sdf, mc_counter_df, mdf]:
        numeric_cols = {'Total Count', 'Routine', 'STAT', 'Rerun', 'Count after Reset'}
        for col in df.columns:
            if col in numeric_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce')

    # Update persistent CSV data
    if not tdf.empty:
        test_counter_df = append_and_save(tdf, TEST_COUNTER_CSV)
    if not sdf.empty:
        sample_counter_df = append_and_save(sdf, SAMPLE_COUNTER_CSV)
    if not mdf.empty:
        mc_counter_df = append_and_save(mdf, MC_COUNTER_CSV)

tabs = st.tabs(["Graphs", "Tables"])

# === Tab 1: Graphical Dashboards ===
with tabs[0]:
    st.header("Test Counter (Unit-wise Total)")
    if not test_counter_df.empty:
        st.write("Bar chart of unit-wise test total (latest date):")
        latest_date = test_counter_df['Date'].max()
        df_latest = test_counter_df[test_counter_df['Date'] == latest_date]
        if 'Unit' in df_latest.columns and 'Total Count' in df_latest.columns:
            st.bar_chart(df_latest.groupby('Unit')['Total Count'].sum())
        else:
            st.write("Unit or Total Count column missing in extracted data.")
    else:
        st.info("No Test Counter data available.")

    st.header("Sample Counter")
    if not sample_counter_df.empty:
        st.write("Sample Counter (latest date) by Unit:")
        latest_date = sample_counter_df['Date'].max()
        df_latest = sample_counter_df[sample_counter_df['Date'] == latest_date]
        st.bar_chart(df_latest.set_index('Unit')['Total Count'])
        # Optionally: Time series or more complex charts
    else:
        st.info("No Sample Counter table data found.")

    st.header("Measuring Cells Counter")
    if not mc_counter_df.empty:
        st.write("Measuring Cells Counter (latest date) by Unit:")
        latest_date = mc_counter_df['Date'].max()
        df_latest = mc_counter_df[mc_counter_df['Date'] == latest_date]
        st.bar_chart(df_latest.set_index('Unit')['Total Count'])
    else:
        st.info("No Measuring Cells Counter table data found.")

# === Tab 2: Full Tables & Analysis ===
with tabs[1]:
    st.header("Select Dates for Test Counter Comparison")
    if not test_counter_df.empty and 'Date' in test_counter_df.columns:
        dates = sorted(test_counter_df['Date'].unique())
        date1 = st.sidebar.selectbox("From date", dates, key="from_date")
        date2 = st.sidebar.selectbox("To date", dates, key="to_date")
        if date1 and date2 and date1 != date2:
            df1 = test_counter_df[test_counter_df['Date'] == date1]
            df2 = test_counter_df[test_counter_df['Date'] == date2]
            diff = (df2.groupby('Unit')['Total Count'].sum() - df1.groupby('Unit')['Total Count'].sum()).reset_index()
            diff.columns = ['Unit', f"Difference ({date2} - {date1})"]
            st.subheader("Test Counter Difference by Unit")
            st.dataframe(diff)
        else:
            st.info("Select two different dates for difference.")

    st.subheader("Test Counter Table")
    st.dataframe(test_counter_df)
    st.subheader("Sample Counter Table")
    st.dataframe(sample_counter_df)
    st.subheader("Measuring Cells Counter Table")
    st.dataframe(mc_counter_df)
