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

def extract_date_from_text(text):
    for line in text.split('\n')[:6]:
        match = re.search(r'(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})', line)
        if match:
            date_str, time_str = match.groups()
            try:
                return datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M")
            except:
                continue
    return None

def parse_table(pdf_bytes, headers, pattern, is_test_counter=False):
    rows = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue
            lines = text.split("\n")
            current_unit = None
            date = extract_date_from_text(text)
            for i, line in enumerate(lines):
                if re.search(pattern, line, re.IGNORECASE):
                    for data_line in lines[i+1:]:
                        data_line = data_line.strip()
                        if not data_line or data_line.lower().startswith(("total", "unit:", "system:")):
                            break
                        if is_test_counter:
                            match = re.match(r'^(.*?)\s+(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)$', data_line)
                            if match:
                                row_vals = list(match.groups())
                            else:
                                continue
                        else:
                            row_vals = re.split(r"\s+", data_line)
                        if len(row_vals) == len(headers):
                            row_dict = dict(zip(headers, row_vals))
                            if "Unit" in row_dict:
                                current_unit = row_dict["Unit"]
                            row_dict["Unit"] = current_unit
                            row_dict["Date"] = date
                            rows.append(row_dict)
    df = pd.DataFrame(rows)
    if not df.empty:
        for col in df.columns:
            if col not in ["Unit", "Date", "Test"]:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    return df

def parse_test_counter(pdf_bytes):
    headers = ["Test", "ACN", "Routine", "Rerun", "STAT", "Calibrator", "QC", "Total Count"]
    pattern = r"Test\s+ACN\s+Routine\s+Rerun\s+STAT\s+Calibrator\s+QC\s+Total\s+Count"
    return parse_table(pdf_bytes, headers, pattern, is_test_counter=True)

def parse_sample_counter(pdf_bytes):
    headers = ["Unit", "Routine", "Rerun", "STAT", "Total Count"]
    pattern = r"Unit[:]*\s*Routine\s+Rerun\s+STAT\s+Total\s+Count"
    return parse_table(pdf_bytes, headers, pattern)

def parse_mc_counter(pdf_bytes):
    headers = ["Unit", "MC Serial No.", "Last Reset", "Count after Reset", "Total Count"]
    pattern = r"Unit[:]*\s*MC Serial No\.\s+Last Reset\s+Count after Reset\s+Total Count"
    return parse_table(pdf_bytes, headers, pattern)

st.title("LAB MIS Instrument Counters")

uploaded_file = st.sidebar.file_uploader("Upload your PDF report", type=["pdf"])
test_df = sample_df = mc_df = pd.DataFrame()

if uploaded_file:
    pdf_bytes = uploaded_file.read()
    with st.spinner("Extracting Test Counter..."):
        test_df = parse_test_counter(pdf_bytes)
    with st.spinner("Extracting Sample Counter..."):
        sample_df = parse_sample_counter(pdf_bytes)
    with st.spinner("Extracting MC Counter..."):
        mc_df = parse_mc_counter(pdf_bytes)

def setup_filters(df, name):
    if df.empty or "Date" not in df.columns or df["Date"].isnull().all():
        st.sidebar.warning(f"No Date data in {name}")
        return None, "All"
    df["Date"] = pd.to_datetime(df["Date"]).dt.date
    min_date = df["Date"].min()
    max_date = df["Date"].max()
    date_range = st.sidebar.date_input(f"{name} Date Range", value=(min_date, max_date), min_value=min_date, max_value=max_date)
    all_units = sorted(df["Unit"].dropna().unique())
    options = ["All"] + all_units
    selected_unit = st.sidebar.selectbox(f"{name} Unit", options=options, index=0, key=f"{name.replace(' ', '_')}_unit")
    return date_range, selected_unit

test_date_range, test_unit = setup_filters(test_df, "Test Counter") if not test_df.empty else (None, "All")
sample_date_range, sample_unit = setup_filters(sample_df, "Sample Counter") if not sample_df.empty else (None, "All")
mc_date_range, mc_unit = setup_filters(mc_df, "Measuring Cells") if not mc_df.empty else (None, "All")

def apply_filters(df, date_range, unit):
    if df.empty:
        return df
    start, end = date_range if date_range else (None, None)
    filtered = df
    if start and end:
        filtered = filtered[(filtered["Date"] >= start) & (filtered["Date"] <= end)]
    if unit and unit != "All":
        filtered = filtered[filtered["Unit"] == unit]
    return filtered

filtered_test = apply_filters(test_df, test_date_range, test_unit)
filtered_sample = apply_filters(sample_df, sample_date_range, sample_unit)
filtered_mc = apply_filters(mc_df, mc_date_range, mc_unit)

tabs = st.tabs(["Test Counter", "Sample Counter", "Measuring Cells Counter", "Download"])

with tabs[0]:
    st.header("Test Counter Data")
    columns_to_show = ["Unit", "Test", "Routine", "Rerun", "STAT", "Calibrator", "QC", "Total Count"]
    final_test_df = filtered_test[columns_to_show] if not filtered_test.empty else pd.DataFrame()
    if not final_test_df.empty:
        with st.container():
            st.markdown('<div class="rounded-box">', unsafe_allow_html=True)
            st.dataframe(final_test_df)
            base = alt.Chart(final_test_df).mark_line(point=True).encode(
                x="Test:N",
                y="Total Count:Q",
                color="Unit:N",
                tooltip=["Unit", "Test", "Total Count"]
            )
            text = base.mark_text(align='center', baseline='bottom', dy=-5).encode(text='Total Count:Q')
            st.altair_chart(base + text, use_container_width=True)
            st.markdown(
                '<div style="margin:8px 0 0 0;color:#757575;font-size:0.9em">_Select a unit or date range in the sidebar. Defaults to all._</div>',
                unsafe_allow_html=True
            )
            st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.info("No Test Counter data to display.")

with tabs[1]:
    st.header("Sample Counter Data")
    columns_to_show = ["Unit", "Routine", "Rerun", "STAT", "Total Count"]
    final_sample_df = filtered_sample[columns_to_show] if not filtered_sample.empty else pd.DataFrame()
    if not final_sample_df.empty:
        with st.container():
            st.markdown('<div class="rounded-box">', unsafe_allow_html=True)
            st.dataframe(final_sample_df)
            base = alt.Chart(final_sample_df).mark_bar().encode(
                x="Unit:N",
                y="Routine:Q",
                color="Unit:N",
                tooltip=["Unit", "Routine"]
            )
            text = base.mark_text(dy=-5, color='black').encode(text='Routine:Q')
            st.altair_chart(base + text, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.info("No Sample Counter data to display.")

with tabs[2]:
    st.header("Measuring Cells Counter Data")
    columns_to_show = ["Unit", "MC Serial No.", "Last Reset", "Count after Reset", "Total Count"]
    final_mc_df = filtered_mc[columns_to_show] if not filtered_mc.empty else pd.DataFrame()
    if not final_mc_df.empty:
        with st.container():
            st.markdown('<div class="rounded-box">', unsafe_allow_html=True)
            st.dataframe(final_mc_df)
            base = alt.Chart(final_mc_df).mark_line(point=True).encode(
                x="MC Serial No.:N",
                y="Total Count:Q",
                color="Unit:N",
                tooltip=["Unit", "MC Serial No.", "Total Count"]
            )
            text = base.mark_text(align='center', baseline='bottom', dy=-5).encode(text='Total Count:Q')
            st.altair_chart(base + text, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.info("No Measuring Cells counter data to display.")

with tabs[3]:
    st.header("Download Data")
    if not final_test_df.empty:
        st.download_button("Download Test CSV", final_test_df.to_csv(index=False), "test_counter.csv")
    if not final_sample_df.empty:
        st.download_button("Download Sample CSV", final_sample_df.to_csv(index=False), "sample_counter.csv")
    if not final_mc_df.empty:
        st.download_button("Download MC CSV", final_mc_df.to_csv(index=False), "mc_counter.csv")
