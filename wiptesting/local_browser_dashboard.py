
# dashboard/app.py
import sqlite3, pandas as pd
import plotly.express as px
import streamlit as st       # pip install streamlit plotly pandas

st.set_page_config(page_title="HSB Test Dashboard", layout="wide")

@st.cache_data
def load_tables(db_path="db/results.sqlite"):
    con = sqlite3.connect(db_path)
    runs = pd.read_sql_query("SELECT * FROM runs ORDER BY timestamp DESC", con)
    tests = pd.read_sql_query("SELECT * FROM tests", con)
    metrics = pd.read_sql_query("SELECT * FROM metrics", con)
    con.close()
    return runs, tests, metrics

runs, tests, metrics = load_tables()

st.title("Orin + FPGA HSB Test Dashboard")

# KPI row
col1, col2, col3, col4 = st.columns(4)
total_runs = len(runs)
total_tests = len(tests)
passed = (tests["status"] == "pass").sum()
yield_rate = (passed / total_tests * 100) if total_tests else 0
col1.metric("Total Runs", total_runs)
col2.metric("Total Tests", total_tests)
col3.metric("Passed", passed)
col4.metric("Yield Rate", f"{yield_rate:.1f}%")

# Yield over time
if not runs.empty:
    # Derive per-run yield
    per_run = tests.groupby("run_id").agg(
        total=("status","size"),
        passed=("status", lambda s: (s=="pass").sum())
    ).reset_index()
    per_run["yield_pct"] = per_run["passed"]/per_run["total"]*100
    per_run = per_run.merge(runs[["run_id","timestamp","fpga_bitstream","orin_image"]], on="run_id", how="left")
    fig = px.line(per_run.sort_values("timestamp"),
                  x="timestamp", y="yield_pct", color="fpga_bitstream",
                  markers=True, title="Yield Rate Over Time by Bitstream")
    st.plotly_chart(fig, use_container_width=True)

# Run selector + drilldown
run_sel = st.selectbox("Select a run", options=runs["run_id"].tolist())
run_tests = tests[tests["run_id"] == run_sel]
st.subheader(f"Run {run_sel} — Tests")
st.dataframe(run_tests[["name","status","duration_ms","error_message"]])

# Compare anomalies/metrics across runs
st.subheader("Compare Metrics Across Runs")
metric_candidates = metrics["name"].dropna().unique().tolist()
metric_name = st.selectbox("Metric name", options=metric_candidates)
subset = metrics[(metrics["name"] == metric_name) & (metrics["scope"]=="run")]
if not subset.empty:
    df = subset.merge(runs[["run_id","timestamp","fpga_bitstream","orin_image"]], on="run_id", how="left")
    fig2 = px.scatter(df.sort_values("timestamp"), x="timestamp", y="value",
                      color="fpga_bitstream", hover_data=["run_id","orin_image"],
                      title=f"{metric_name} over time")
    st.plotly_chart(fig2, use_container_width=True)
