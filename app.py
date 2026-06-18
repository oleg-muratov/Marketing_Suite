import streamlit as st
import duckdb
import numpy as np
import altair as alt  # for more advanced plotting, if we want to go beyond st.line_chart


st.title("Marketing Suite — Agency Command Center")

# metrics = duckdb.sql("""
#     SELECT client, trade, month,
#            SUM(spend)              AS total_spend,
#            SUM(leads)              AS total_leads,
#            SUM(jobs)               AS total_jobs,
#            SUM(spend) / SUM(leads) AS cost_per_lead
#     FROM 'campaign_data.csv'
#     GROUP BY client, trade, month
#     ORDER BY client, month
# """).df()

# --- global filter: lead sources (filter once, everything flows from here) ---
raw = duckdb.sql("SELECT * FROM 'campaign_data.csv'").df()
all_sources = sorted(raw["source"].unique())
chosen_sources = st.multiselect("Lead sources", all_sources, default=all_sources)

if not chosen_sources:                       # guard: nothing selected
    st.warning("Select at least one lead source.")
    st.stop()

raw_f = raw[raw["source"].isin(chosen_sources)]   # rows for the chosen sources only

metrics = duckdb.sql("""
    SELECT client, trade, month,
           SUM(spend)              AS total_spend,
           SUM(leads)              AS total_leads,
           SUM(jobs)               AS total_jobs,
           SUM(spend) / SUM(leads) AS cost_per_lead
    FROM raw_f
    GROUP BY client, trade, month
    ORDER BY client, month
""").df()

# 1. read the clients reference data
clients_ref = duckdb.sql("SELECT * FROM 'clients.csv'").df()

# 2. build the dropdown choices from it
client_list = sorted(clients_ref["client"].unique())
# # 2.5 list of trades for the dropdown
# trade_list = sorted(clients_ref["trade"].unique())

# 3. the dropdown
selected = st.selectbox("Client", client_list)
# # 3.5. show the trade for the selected client
# trade = st.selectbox("Trade",trade_list)

# 4. filter the metrics to just that client
client_data = metrics[metrics["client"] == selected]

st.dataframe(client_data)

total_spend = client_data["total_spend"].sum()
total_leads = client_data["total_leads"].sum()
total_jobs  = client_data["total_jobs"].sum()

cpl = total_spend / total_leads          # pooled, all months

trail = 3 # number of months to look back for the "recent" CPL

# trailing 3-month pooled  -> you write this
recent = client_data.sort_values("month").tail(trail)
cpl_recent =   recent["total_spend"].sum() / recent["total_leads"].sum()  # pooled CPL over just those 3 rows

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total spend",        f"${total_spend:,.0f}")
c2.metric("Total leads",        f"{total_leads:,.0f}")
c3.metric("CPL (all 6 mo)",     f"${cpl:,.2f}")
c4.metric(
    f"CPL (last {trail} mo)",
    f"${cpl_recent:,.2f}",
    delta=f"{(cpl_recent - cpl) / cpl:+.0%}",
    delta_color="inverse",
)

# the spread, quieter
lo  = client_data["cost_per_lead"].min()
mid = client_data["cost_per_lead"].median()
hi  = client_data["cost_per_lead"].max()
st.caption(f"Monthly CPL spread — min \\${lo:,.2f} · median \\${mid:,.2f} · max \\${hi:,.2f}")

# the plotting

st.subheader("Cost per lead over time")
chart_data = client_data.sort_values("month").copy()

ma_col = f"CPL {trail}mo MA"
chart_data[ma_col] = chart_data["cost_per_lead"].rolling(window=trail).mean()

x = np.arange(len(chart_data))
slope, intercept = np.polyfit(x, chart_data["cost_per_lead"], 1)
chart_data["CPL linear trend"] = slope * x + intercept

chart_data["vs_trend"] = np.where(chart_data["cost_per_lead"] > chart_data["CPL linear trend"], "Above", "Below")

# a shared base: same x-axis for every layer
base = alt.Chart(chart_data).encode(x=alt.X("month:O", title="Month"))

observed = base.mark_point(filled=True, size=80).encode(
    y=alt.Y("cost_per_lead:Q", title="Cost per lead ($)"),
    color=alt.Color(
        "vs_trend:N",
        scale=alt.Scale(domain=["Above", "Below"], range=["#d62728", "#2ca02c"]),
        legend=alt.Legend(title="vs. trend"),
    ),
)
ma = base.mark_line(strokeDash=[6, 4], color="#ff7f0e").encode(
    y=alt.Y(f"{ma_col}:Q")
)
trend_color = "#2ca02c" if slope < 0 else "#d62728"   # falling CPL = green (good), rising = red (bad)

trend = base.mark_line(color=trend_color).encode(
    y=alt.Y("CPL linear trend:Q")
)

st.altair_chart(observed + ma + trend, use_container_width=True)

st.divider()
st.header("Cross-client benchmarks")

benchmark = duckdb.sql("""
    SELECT c.trade,
           SUM(d.spend) / SUM(d.leads) AS benchmark_cpl,
           COUNT(DISTINCT d.client)    AS n_clients
    FROM raw_f         d
    JOIN 'clients.csv' c ON d.client = c.client
    GROUP BY c.trade
    ORDER BY benchmark_cpl
""").df()

# draw benchmark_cpl as a bar per trade  -> you write this
st.bar_chart(benchmark, x="trade", y="benchmark_cpl")

client_trade = client_data["trade"].iloc[0]
trade_benchmark = benchmark[benchmark["trade"] == client_trade]["benchmark_cpl"].iloc[0]
diff = (cpl - trade_benchmark) / trade_benchmark

b1, b2, b3 = st.columns(3)
b1.metric(f"{selected} CPL", f"${cpl:,.2f}")

arrow = "▼" if diff < 0 else "▲"
color = "#2ca02c" if diff < 0 else "#d62728"      # cost-aware: down = green = good
b2.markdown(
    f"<div style='text-align:center; padding-top:18px;'>"
    f"<span style='color:{color}; font-size:1.5em; font-weight:600;'>{arrow} {diff:+.0%}</span><br>"
    f"<span style='color:gray; font-size:0.85em;'>vs. benchmark</span></div>",
    unsafe_allow_html=True,
)

b3.metric(f"{client_trade} benchmark", f"${trade_benchmark:,.2f}")

# st.divider()
# st.header("⚠️ Alerts — CPL spikes")

# # z-score of each client-month's CPL, computed within that client's own history
# metrics["cpl_z"] = metrics.groupby("client")["cost_per_lead"].transform(
#     lambda s: (s - s.mean()) / s.std()
# )

# threshold = 1.5   # your decision: how many std devs above normal counts as a spike?

# # keep only the client-months above the threshold  -> you write this
# alerts = metrics[metrics["cpl_z"] > threshold].copy()
# alerts = alerts.sort_values("cpl_z", ascending=False)

# if alerts.empty:
#     st.success("No CPL spikes above the threshold.")
# else:
#     st.dataframe(alerts[["client", "month", "cost_per_lead", "cpl_z"]])

st.divider()
st.subheader(f"{selected} — by lead source")

by_source = (
    raw_f[raw_f["client"] == selected]
    .groupby("source")
    .agg(spend=("spend", "sum"), leads=("leads", "sum"), jobs=("jobs", "sum"))
    .reset_index()
)
by_source["cost_per_lead"] = by_source["spend"] / by_source["leads"]
by_source["lead_to_job"]   = by_source["jobs"]  / by_source["leads"]

st.dataframe(by_source)
st.bar_chart(by_source, x="source", y="cost_per_lead")