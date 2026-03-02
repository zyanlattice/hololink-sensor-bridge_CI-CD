
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
    artifacts = pd.read_sql_query("SELECT * FROM artifacts", con)
    con.close()
    return runs, tests, metrics, artifacts

runs, tests, metrics, artifacts = load_tables()

st.title("Orin + FPGA HSB Test Dashboard")

# KPI row
col1, col2, col3, col4 = st.columns(4)
total_runs = len(runs)
total_tests = len(tests)
# Issue 1: Count xfail as pass
passed = ((tests["status"] == "pass") | (tests["status"] == "xfail")).sum()
failed = (tests["status"] == "fail").sum()
yield_rate = (passed / total_tests * 100) if total_tests else 0
col1.metric("Total Runs", total_runs)
col2.metric("Total Tests", total_tests)
col3.metric("Passed (incl. xfail)", passed)
col4.metric("Yield Rate", f"{yield_rate:.1f}%")

# Yield over time
if not runs.empty:
    # Derive per-run yield (Issue 1: treat xfail as pass)
    per_run = tests.groupby("run_id").agg(
        total=("status","size"),
        passed=("status", lambda s: ((s=="pass") | (s=="xfail")).sum())
    ).reset_index()
    per_run["yield_pct"] = per_run["passed"]/per_run["total"]*100
    per_run = per_run.merge(runs[["run_id","timestamp","fpga_bitstream","orin_image"]], on="run_id", how="left")
    fig = px.line(per_run.sort_values("timestamp"),
                  x="timestamp", y="yield_pct", color="fpga_bitstream",
                  markers=True, title="Yield Rate Over Time by Bitstream")
    st.plotly_chart(fig, use_container_width=True)

# Run selector + drilldown
run_sel = st.selectbox("Select a run", options=runs["run_id"].tolist())
run_tests = tests[tests["run_id"] == run_sel].copy()

st.subheader(f"Run {run_sel} — Tests")

# Reset index to start from 1 for each run
run_tests = run_tests.reset_index(drop=True)
run_tests.index = run_tests.index + 1

# Ensure duration_ms shows properly (convert to numeric)
run_tests["duration_ms"] = pd.to_numeric(run_tests["duration_ms"], errors='coerce').fillna(0)

# Prepare display dataframe
display_df = run_tests[["name","status","duration_ms","error_message"]].copy()

# Add font color styling for status column
def color_status(val):
    if val == "pass":
        return 'color: #008000'  # Green
    elif val == "fail":
        return 'color: #CC0000'  # Red
    elif val == "xfail":
        return 'color: #FF8C00'  # Orange
    return ''

# Apply styling
styled_df = display_df.style.applymap(color_status, subset=['status'])
st.dataframe(styled_df, use_container_width=True)

# Test-level metrics detail
st.subheader("Test Metrics Detail")
if not run_tests.empty:
    test_sel = st.selectbox("Select a test", options=run_tests["name"].tolist())
    test_row = run_tests[run_tests["name"] == test_sel].iloc[0]
    test_id = test_row["test_id"]
    
    # Get all metrics for this test
    test_metrics = metrics[metrics["test_id"] == test_id]
    
    if not test_metrics.empty:
        st.write(f"**Test:** {test_sel} | **Status:** {test_row['status']} | **Duration:** {test_row['duration_ms']}ms")
        
        # Display metrics with proper handling of complex types
        import json
        metrics_display = []
        for _, metric in test_metrics.iterrows():
            name = metric["name"]
            value = metric["value"]
            meta = metric.get("meta")
            
            # If meta contains array/complex data, use that instead
            if pd.notna(meta):
                try:
                    meta_obj = json.loads(meta)
                    if "array" in meta_obj:
                        value = meta_obj["array"]
                except:
                    pass
            
            metrics_display.append({"Metric": name, "Value": str(value)})
        
        st.dataframe(pd.DataFrame(metrics_display), use_container_width=True)
    else:
        st.info("No metrics recorded for this test")
    
    # Display artifacts
    test_artifacts = artifacts[artifacts["test_id"] == test_id]
    if not test_artifacts.empty:
        st.write("**Artifacts:**")
        import os
        
        # Get the source directory for this run from the runs table
        run_info = runs[runs["run_id"] == run_sel]
        run_source_dir = None
        if not run_info.empty and "source_dir" in run_info.columns:
            run_source_dir = run_info.iloc[0]["source_dir"]
            if pd.notna(run_source_dir):
                st.caption(f"Source directory: {run_source_dir}")
            else:
                st.caption("⚠️ No source_dir stored - re-run ingestion to enable dynamic path resolution")
        
        for _, artifact in test_artifacts.iterrows():
            artifact_type = artifact["type"]
            artifact_path = artifact["path"]
            artifact_label = artifact.get("label", artifact_path)
            
            st.write(f"**{artifact_label}** ({artifact_type})")
            
            # If it's an image, display it
            if artifact_type in ["image", "screenshot", "png", "jpg", "jpeg"]:
                resolved_path = None
                
                # Strategy 1: Try original absolute path
                if os.path.exists(artifact_path):
                    resolved_path = artifact_path
                
                # Strategy 2: Try relative to source_dir (just filename)
                if not resolved_path and run_source_dir and pd.notna(run_source_dir):
                    filename = os.path.basename(artifact_path)
                    dynamic_path = os.path.join(run_source_dir, filename)
                    if os.path.exists(dynamic_path):
                        resolved_path = dynamic_path
                
                # Display image or error
                if resolved_path:
                    st.image(resolved_path, caption=artifact_label)
                else:
                    st.error(f"❌ Image file not found: {artifact_path}")
                    if run_source_dir and pd.notna(run_source_dir):
                        st.caption(f"Also tried: {os.path.join(run_source_dir, os.path.basename(artifact_path))}")
            else:
                st.text(f"Path: {artifact_path}")


# # Compare anomalies/metrics across runs
# st.subheader("Compare Metrics Across Runs")
# metric_candidates = metrics["name"].dropna().unique().tolist()
# metric_name = st.selectbox("Metric name", options=metric_candidates)
# subset = metrics[(metrics["name"] == metric_name) & (metrics["scope"]=="run")]
# if not subset.empty:
#     df = subset.merge(runs[["run_id","timestamp","fpga_bitstream","orin_image"]], on="run_id", how="left")
#     fig2 = px.scatter(df.sort_values("timestamp"), x="timestamp", y="value",
#                       color="fpga_bitstream", hover_data=["run_id","orin_image"],
#                       title=f"{metric_name} over time")
#     st.plotly_chart(fig2, use_container_width=True)
