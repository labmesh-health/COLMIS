import streamlit as st
import pdfplumber
import pandas as pd
import numpy as np
import altair as alt
import re
from datetime import datetime
import os

TEST_COUNTER_CSV = "test_counter_data.csv"
SAMPLE_COUNTER_CSV = "sample_counter_data.csv"
MC_COUNTER_CSV = "mc_counter_data.csv"

def extract_date_from_page_text(text):
    """
    Extract datetime from the end of the first line: DD/MM/YYYY HH:MM with one space in between
    Handles variable spaces before date.
    """
    if not text:
        return None
    first_line = text.split('\n')[0]
    date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2})\s*$', first_line)
    if date_match:
        date_part = date_match.group(1)
        time_part = date_match.group(2)
        try:
            dt = datetime.strptime(f"{date_part} {time_part}", "%d/%m/%Y %H:%M")
            return dt
        except Exception:
            return None
    return None

def find_table_by_header(tables, possible_headers):
    for i, t in enumerate(tables):
        header = [col.strip().lower() for col in t[0]]
        for ph in possible_headers:
            if all(any(h.lower() == c for c in header) for h in ph):
                return i, t
    return None, None

def extract_tables_by_type(pdf_path):
    test_rows, sample_rows, mc_rows = [], [], []
    date_found = False
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            page_date = extract_date_from_page_text(text)
            if page_date:
                date_found = True
            tables = page.extract_tables()
            # Test Counter
            tc_headers = [['Test', 'ACN', 'Routine', 'Rerun', 'STAT', 'Calibrator', 'QC', 'Total Count']]
            i_tc, table_tc = find_table_by_header(tables, tc_headers)
            if i_tc is not None and page_date:
                df_tc = pd.DataFrame(table_tc[1:], columns=table_tc[0])
                df_tc['Date'] = page_date
                test_rows.append(df_tc)
            # Sample Counter
            sc_headers = [['Unit', 'Routine', 'Rerun', 'STAT', 'Total Count']]
            i_sc, table_sc = find_table_by_header(tables, sc_headers)
            if i_sc is not None and page_date:
                df_sc = pd.DataFrame(table_sc[1:], columns=table_sc[0])
                df_sc['Date'] = page_date
                sample_rows.append(df_sc)
            # Measuring Cells Counter
            mc_headers = [['Unit', 'MC Serial No.', 'Last Reset', 'Count after Reset', 'Total Count']]
            i_mc, table_mc = find_table_by_header(tables, mc_headers)
            if i_mc is not None and page_date:
                df_mc = pd.DataFrame(table_mc[1:], columns=table_mc[0])
                df_mc['Date'] = page_date
                mc_rows.append(df_mc)
    test_df = pd.concat(test_rows, ignore_index=True) if test_rows else pd.DataFrame()
    sample_df = pd.concat(sample_rows, ignore_index=True) if sample_rows else pd.DataFrame()
    mc_df = pd.concat(mc_rows, ignore_index=True) if mc_rows else pd.DataFrame()
    return date_found, test_df, sample_df, mc_df

def append_and_save(df, file):
    if os.path.exists(file):
        existing = pd.read_csv(file)
        combined = pd.concat([existing, df], ignore_index=True).drop_duplicates()
    else:
        combined = df
    combined.to_csv(file, index=False)
    return combined

st.set_page_config(page_title="Instrument Dashboard", layout='wide')
st.title("Instrument Counter Dashboard")

with st.sidebar:
    st.header("Controls")
    uploaded_file = st.file_uploader("Upload PDF", type=["pdf"])
    date_filter_container = st.container()
    unit_filter_container = st.container()
    st.markdown("---")
    st.write("All data and advanced visualizations are below!")

def safe_load(file):
    if os.path.exists(file):
        return pd.read_csv(file)
    else:
        return pd.DataFrame()

test_counter_df = safe_load(TEST_COUNTER_CSV)
sample_counter_df = safe_load(SAMPLE_COUNTER_CSV)
mc_counter_df = safe_load(MC_COUNTER_CSV)

error_flag = False
error_message = ""

if uploaded_file:
    with open("uploaded_now.pdf", "wb") as f:
        f.write(uploaded_file.getbuffer())
    date_found, tdf, sdf, mdf = extract_tables_by_type("uploaded_now.pdf")
    for df in [tdf, sdf, mdf]:
        for col in df.columns:
            if df[col].dtype == "object":
                try:
                    df[col] = pd.to_numeric(df[col], errors="ignore")
                except:
                    pass
    if not date_found or (tdf.empty and sdf.empty and mdf.empty):
        error_flag = True
        error_message = "You have not uploaded the system detailed test counter PDF, Kindly download again from instrument and reload in COLMIS."
    else:
        if not tdf.empty:
            test_counter_df = append_and_save(tdf, TEST_COUNTER_CSV)
        if not sdf.empty:
            sample_counter_df = append_and_save(sdf, SAMPLE_COUNTER_CSV)
        if not mdf.empty:
            mc_counter_df = append_and_save(mdf, MC_COUNTER_CSV)

all_dates = []
if "Date" in test_counter_df.columns:
    all_dates = list(pd.unique(test_counter_df['Date']))
if not all_dates:
    all_dates = []

selected_date = date_filter_container.selectbox(
    "Choose a Date for Visualization (latest by default):",
    reversed(sorted(all_dates)) if all_dates else [],
    index=0 if all_dates else None,
    key="sel_date"
)

all_units = []
if "Unit" in test_counter_df.columns:
    all_units = list(pd.unique(test_counter_df['Unit']))
if not all_units:
    all_units = []

selected_units = unit_filter_container.multiselect(
    "Filter by Unit(s):", all_units, default=all_units
) if all_units else []

tabs = st.tabs(["Graphs", "Tables", "Download Data"])

if error_flag:
    st.error(error_message)
else:
    with tabs[0]:
        st.header("Instrument Test Counter Visualizations")
        if not test_counter_df.empty and "Date" in test_counter_df.columns and "Unit" in test_counter_df.columns:
            test_counter_df['Date'] = pd.to_datetime(test_counter_df['Date'])
            ts = test_counter_df[test_counter_df["Unit"].isin(selected_units)]
            st.subheader("Time Series: Total Count Over Time")
            chart = alt.Chart(ts).mark_line(point=True).encode(
                x='Date:T',
                y='Total Count:Q',
                color='Unit:N',
                tooltip=['Unit', 'Date', 'Total Count']
            ).interactive()
            st.altair_chart(chart, use_container_width=True)
        st.subheader("Sample Counter Grouped Bar Chart (Latest Date)")
        if not sample_counter_df.empty and "Unit" in sample_counter_df.columns:
            sample_counter_df['Date'] = pd.to_datetime(sample_counter_df['Date'])
            latest_sample = sample_counter_df[sample_counter_df['Date'] == sample_counter_df['Date'].max()]
            long_form = pd.melt(
                latest_sample,
                id_vars=["Unit", "Date"],
                value_vars=[col for col in ["Routine", "Rerun", "STAT"] if col in latest_sample.columns],
                var_name="Type", value_name="Count"
            )
            chart2 = alt.Chart(long_form[long_form["Unit"].isin(selected_units)]).mark_bar().encode(
                x=alt.X('Unit:N', title="Unit"),
                y=alt.Y('Count:Q', title="Sample Count"),
                color='Type:N',
                tooltip=['Unit', 'Type', 'Count']
            )
            st.altair_chart(chart2, use_container_width=True)
        else:
            st.info("No Sample Counter data available.")
        st.subheader("Test Counter Heatmap")
        if not test_counter_df.empty and 'Unit' in test_counter_df.columns:
            heatmap_df = test_counter_df[test_counter_df["Unit"].isin(selected_units)].copy()
            heatmap_df["Date_str"] = heatmap_df['Date'].dt.strftime("%Y-%m-%d %H:%M")
            hm = alt.Chart(heatmap_df).mark_rect().encode(
                x='Unit:N',
                y=alt.Y('Date_str:O', sort='descending'),
                color=alt.Color('Total Count:Q', scale=alt.Scale(scheme='viridis')),
                tooltip=['Unit', 'Date_str', 'Total Count']
            )
            st.altair_chart(hm, use_container_width=True)
        st.subheader("Measuring Cells Counter Over Time")
        if not mc_counter_df.empty and "Unit" in mc_counter_df.columns:
            mc_counter_df['Date'] = pd.to_datetime(mc_counter_df['Date'])
            mc_chart = alt.Chart(mc_counter_df[mc_counter_df["Unit"].isin(selected_units)]).mark_line(point=True).encode(
                x='Date:T',
                y=alt.Y('Total Count:Q', title="Measuring Cells Count"),
                color='Unit:N',
                tooltip=['Unit', 'Date', 'Total Count']
            )
            st.altair_chart(mc_chart, use_container_width=True)
        else:
            st.info("No Measuring Cells Counter data available.")
        st.subheader("Distribution of Total Counts (Boxplot)")
        if not test_counter_df.empty and 'Unit' in test_counter_df.columns:
            box = alt.Chart(test_counter_df[test_counter_df["Unit"].isin(selected_units)]).mark_boxplot().encode(
                x='Unit:N', y='Total Count:Q', color='Unit:N'
            )
            st.altair_chart(box, use_container_width=True)
    with tabs[1]:
        st.header("Data Tables and Interactive Filters")
        st.markdown("*Use table filters above for custom views*")
        if not test_counter_df.empty:
            st.subheader("Test Counter Table (filtered)")
            df = test_counter_df[(test_counter_df["Unit"].isin(selected_units))]
            st.dataframe(df.style.background_gradient(subset=['Total Count'], cmap='viridis'), use_container_width=True)
        if not sample_counter_df.empty:
            st.subheader("Sample Counter Table (filtered)")
            df = sample_counter_df[(sample_counter_df["Unit"].isin(selected_units))]
            st.dataframe(df.style.background_gradient(subset=['Total Count'], cmap='plasma'), use_container_width=True)
        if not mc_counter_df.empty:
            st.subheader("Measuring Cells Counter Table (filtered)")
            df = mc_counter_df[(mc_counter_df["Unit"].isin(selected_units))]
            st.dataframe(df.style.background_gradient(subset=['Total Count'], cmap='magma'), use_container_width=True)
    with tabs[2]:
        st.header("Download All Data")
        if not test_counter_df.empty:
            st.download_button(
                "Download Test Counter CSV", test_counter_df.to_csv(index=False), "test_counter_data.csv"
            )
        if not sample_counter_df.empty:
            st.download_button(
                "Download Sample Counter CSV", sample_counter_df.to_csv(index=False), "sample_counter_data.csv"
            )
        if not mc_counter_df.empty:
            st.download_button(
                "Download Measuring Cells Counter CSV", mc_counter_df.to_csv(index=False), "mc_counter_data.csv"
            )

st.markdown("---")
st.write("Tip: Use sidebar filters and download data for offline analysis. Advanced charts update based on your selections!")
