import streamlit as st
import pandas as pd
import re
import io
import json
from datetime import datetime
import matplotlib.pyplot as plt
import plotly.express as px
from sklearn.ensemble import IsolationForest
from scipy import stats
import requests

# ==============================
# 📌 Utility Functions
# ==============================

def extract_log_details(entry, ftype):
    """Extract fields from a single log entry."""
    timestamp = re.search(r"\[ts:(\d+)]", entry)
    event = re.search(r"EVNT:(XR-\w+)", entry)
    username = re.search(r"usr:(\w+)", entry)
    ipaddr = re.search(r"IP:([\d\.]+)", entry)
    filepath = re.search(r"=>/(.+)", entry)
    process_id = re.search(r"pid(\d+)", entry)
    
    return {
        "time": int(timestamp.group(1)) if timestamp else None,
        "event": event.group(1) if event else None,
        "user": username.group(1) if username else None,
        "ip": ipaddr.group(1) if ipaddr else None,
        "path": "/" + filepath.group(1) if filepath else None,
        "pid": int(process_id.group(1)) if process_id else None,
        "format": ftype
    }

@st.cache_data
def fetch_ip_location(ipaddress):
    """Fetch geo-location data for a given IP address."""
    try:
        response = requests.get(f"https://ipinfo.io/{ipaddress}/json", timeout=2).json()
        loc_parts = response.get("loc", "").split(",")
        return float(loc_parts[0]), float(loc_parts[1]), response.get("city"), response.get("country")
    except:
        return None, None, None, None

# ==============================
# 🎨 Streamlit Interface
# ==============================

st.set_page_config(page_title="Log Inspector", layout="wide")

# Custom CSS styling
st.markdown("""
    <style>
    .main-title { font-size: 34px; font-weight: bold; color: #2C3E50; }
    .section-title { font-size: 22px; color: #34495E; }
    .sub-text { font-size: 18px; color: #7F8C8D; }
    </style>
""", unsafe_allow_html=True)

st.title("🔍 **Log File Inspector & Analyzer**")

# File uploader widget
uploaded_files = st.file_uploader("Upload your log files (.txt / .vlog)", ["txt", "vlog"], accept_multiple_files=True)
if not uploaded_files:
    st.warning("Upload at least one log file to proceed.")
    st.stop()

# Parse uploaded logs
records = []
for file in uploaded_files:
    filetype = file.name.split('.')[-1].upper()
    content = file.read().decode().splitlines()
    for line in content:
        parsed = extract_log_details(line, filetype)
        if parsed["time"]:
            records.append(parsed)

df_logs = pd.DataFrame(records)

# ✅ Check for empty DataFrame or missing 'time' column
if not df_logs.empty and "time" in df_logs.columns:
    df_logs["time"] = pd.to_datetime(df_logs["time"], unit="s")
    st.success(f"Parsed {len(df_logs)} log entries successfully.")
else:
    st.warning("No valid log entries parsed. Please check your log file format.")
    st.stop()

# ==============================
# 🗂️ Dashboard Tabs
# ==============================

tab_summary, tab_timeline, tab_alerts, tab_geo = st.tabs(["📋 Summary", "📅 Timeline", "⚠️ Anomalies", "🌍 IP Map"])

with tab_summary:
    st.markdown("<div class='section-title'>Log Summary Overview</div>", unsafe_allow_html=True)
    st.write(f"**Total Entries:** {len(df_logs)}")
    st.write(f"**Distinct Users:** {df_logs['user'].nunique()}")
    st.write(f"**Event Types:** {df_logs['event'].nunique()}")
    st.write(f"**Unique IPs:** {df_logs['ip'].nunique()}")

with tab_timeline:
    st.markdown("<div class='section-title'>Events Timeline</div>", unsafe_allow_html=True)
    event_counts = df_logs.groupby(pd.Grouper(key="time", freq="10S")).size().reset_index(name="count")
    
    fig_line = px.line(event_counts, x="time", y="count", title="Events per 10 Seconds", labels={"time": "Timestamp", "count": "Event Count"})
    st.plotly_chart(fig_line)

    # Download timeline as PNG
    buffer = io.BytesIO()
    plt.figure(figsize=(8, 3))
    plt.plot(event_counts["time"], event_counts["count"], "-o")
    plt.title("Event Frequency Over Time")
    plt.xlabel("Time")
    plt.ylabel("Count")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(buffer, format="png")
    st.download_button("Download Timeline PNG", buffer.getvalue(), file_name="timeline.png")

with tab_alerts:
    st.markdown("<div class='section-title'>Detected Anomalies</div>", unsafe_allow_html=True)
    
    # Z-score method
    event_counts["zscore"] = stats.zscore(event_counts["count"])
    z_outliers = event_counts[abs(event_counts["zscore"]) > 2]
    st.write("🔺 **Z-Score Outliers:**")
    st.dataframe(z_outliers, use_container_width=True)

    # Isolation Forest method
    iso_model = IsolationForest(contamination=0.05, random_state=42).fit(event_counts[["count"]])
    event_counts["isoforest"] = iso_model.predict(event_counts[["count"]])
    iso_outliers = event_counts[event_counts["isoforest"] == -1]
    st.write("🔻 **Isolation Forest Outliers:**")
    st.dataframe(iso_outliers, use_container_width=True)

    # Scatter plot of anomalies
    fig_anomaly = px.scatter(event_counts, x="time", y="count", color=event_counts["isoforest"].map({1: "Normal", -1: "Outlier"}),
                             title="Anomalies Detected Over Time", labels={"time": "Timestamp", "count": "Event Count"})
    st.plotly_chart(fig_anomaly)

with tab_geo:
    st.markdown("<div class='section-title'>IP Geolocation Mapping</div>", unsafe_allow_html=True)
    ips = df_logs["ip"].dropna().unique()
    geo_data = pd.DataFrame([{
        "ip": ip,
        **dict(zip(("latitude", "longitude", "city", "country"), fetch_ip_location(ip)))
    } for ip in ips])

    merged_geo = df_logs.merge(geo_data, on="ip", how="left").dropna(subset=["latitude", "longitude"])
    if not merged_geo.empty:
        fig_map = px.scatter_mapbox(merged_geo, lat="latitude", lon="longitude", color="event",
                                    hover_data=["user", "ip", "city", "country"], zoom=2, height=400)
        fig_map.update_layout(mapbox_style="open-street-map")
        st.plotly_chart(fig_map)
    else:
        st.info("No IP geolocation data could be retrieved.")

# ==============================
# 💾 Data Export Section
# ==============================

st.subheader("📁 Export Results")
export_format = st.radio("Choose export format", ["JSON", "CSV", "TXT"], horizontal=True)

export_df = df_logs.copy()
export_df["time"] = export_df["time"].astype(str)
export_df = export_df.where(pd.notnull(export_df), None)

if export_format == "JSON":
    st.download_button("Download JSON", json.dumps(export_df.to_dict("records"), indent=2), file_name="logs.json")
elif export_format == "CSV":
    st.download_button("Download CSV", export_df.to_csv(index=False), file_name="logs.csv")
else:
    st.download_button("Download TXT", export_df.to_string(index=False), file_name="logs.txt")
