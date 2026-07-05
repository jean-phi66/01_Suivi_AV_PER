import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from streamlit import session_state as ss

from tri_integration import (
    build_portfolio_tri_history,
    load_tri_analyses,
    match_tri_analyses_to_contracts,
    summarize_portfolio_tri_history,
)


def format_pct(value):
    if value is None or pd.isna(value):
        return "N/A"
    return f"{value * 100:.2f}%"


def format_eur(value):
    if value is None or pd.isna(value):
        return "N/A"
    return f"{value:,.0f} €".replace(",", " ")


@st.cache_resource(show_spinner=False)
def get_tri_analyses_resource():
    return load_tri_analyses()


st.title("TRI du portefeuille")
st.caption("Vue d'ensemble des TRI apparies avec recalcul sur l'historique de valorisation des contrats.")

df_contrats = ss.get("df_contrats", pd.DataFrame())
df_contrat_agg = ss.get("df_contrat_agg_filtered", ss.get("df_contrat_agg", pd.DataFrame()))

if df_contrats.empty:
    st.warning("Aucune donnee contrat disponible. Importez les donnees depuis la page Donnees.")
    st.stop()

tri_matches_df, tri_matches_map = match_tri_analyses_to_contracts(
    get_tri_analyses_resource(),
    df_contrats[["N° de contrat", "Titulaire(s)", "Enveloppe", "Partenaire"]].drop_duplicates().copy(),
)

if tri_matches_df.empty:
    st.warning("Aucune analyse TRI PDF exploitable n'a ete trouvee.")
    st.stop()

history_columns = ["N° de contrat", "Date de valorisation", "Valorisation"]
current_history = df_contrats[history_columns].copy()
current_history["Date export"] = pd.NaT

agg_columns = history_columns + (["Date export"] if "Date export" in df_contrat_agg.columns else [])
historical_history = df_contrat_agg[agg_columns].copy() if not df_contrat_agg.empty else pd.DataFrame(columns=history_columns + ["Date export"])
if "Date export" not in historical_history.columns:
    historical_history["Date export"] = pd.NaT

portfolio_source = pd.concat([historical_history, current_history], ignore_index=True)
portfolio_source = portfolio_source.drop_duplicates(
    subset=["N° de contrat", "Date de valorisation"],
    keep="last",
)

portfolio_tri_history = build_portfolio_tri_history(tri_matches_map, portfolio_source)
portfolio_tri_summary = summarize_portfolio_tri_history(portfolio_tri_history)

matched_current = tri_matches_df[tri_matches_df["Match trouve"]].copy()
coverage_ratio = len(matched_current) / max(len(df_contrats["N° de contrat"].dropna().unique()), 1)

weighted_current_tri = None
if matched_current["Valorisation TRI"].notna().any() and matched_current["TRI net"].notna().any():
    weights = matched_current["Valorisation TRI"].fillna(0).clip(lower=0)
    if weights.sum() > 0:
        weighted_current_tri = float((matched_current["TRI net"].fillna(0) * weights).sum() / weights.sum())

c1, c2, c3, c4 = st.columns(4)
c1.metric("Contrats apparies", f"{len(matched_current)}")
c2.metric("Couverture contrats", f"{coverage_ratio * 100:.1f}%")
c3.metric(
    "TRI net median actuel",
    format_pct(matched_current["TRI net"].median() if matched_current["TRI net"].notna().any() else None),
)
c4.metric("TRI net pondere actuel", format_pct(weighted_current_tri))

c5, c6 = st.columns(2)
c5.metric("Valorisation appariee", format_eur(matched_current["Valorisation TRI"].sum()))
c6.metric("Versements nets appariees", format_eur(matched_current["Versements nets"].sum()))

#st.subheader("TRI actuels par contrat")

display_current = matched_current.copy()
display_current = display_current.sort_values("TRI net", ascending=False)

st.subheader("TRI brut et net selon l'anciennete du contrat")

age_source = matched_current.copy()
if "Ouverture" in df_contrats.columns:
    age_source = age_source.merge(
        df_contrats[["N° de contrat", "Ouverture"]].drop_duplicates(),
        on="N° de contrat",
        how="left",
    )
else:
    age_source["Ouverture"] = pd.NaT

age_source["Ouverture"] = pd.to_datetime(
    age_source["Ouverture"],
    format="mixed",
    dayfirst=True,
    errors="coerce",
)
if "Date de valorisation TRI" in age_source.columns:
    age_source["Date reference TRI"] = pd.to_datetime(age_source["Date de valorisation TRI"], errors="coerce")
else:
    age_source["Date reference TRI"] = pd.Timestamp.today().normalize()
age_source["Date reference TRI"] = age_source["Date reference TRI"].fillna(pd.Timestamp.today().normalize())

age_source["Anciennete (annees)"] = (
    (age_source["Date reference TRI"] - age_source["Ouverture"]).dt.days / 365.25
)

age_scatter_df = age_source.dropna(subset=["Anciennete (annees)", "TRI net", "TRI brut"]).copy()
if not age_scatter_df.empty:
    age_scatter_df["Date d'ouverture"] = age_scatter_df["Ouverture"].dt.strftime("%d/%m/%Y")
    age_scatter_long = pd.concat(
        [
            age_scatter_df[[
                "N° de contrat", "Titulaire(s)", "Enveloppe", "Partenaire", "Date d'ouverture", "Anciennete (annees)", "TRI net"
            ]].rename(columns={"TRI net": "TRI"}).assign(Type="TRI net"),
            age_scatter_df[[
                "N° de contrat", "Titulaire(s)", "Enveloppe", "Partenaire", "Date d'ouverture", "Anciennete (annees)", "TRI brut"
            ]].rename(columns={"TRI brut": "TRI"}).assign(Type="TRI brut"),
        ],
        ignore_index=True,
    )

    fig_age_scatter = px.scatter(
        age_scatter_long,
        x="Anciennete (annees)",
        y="TRI",
        color="Type",
        symbol="Enveloppe",
        hover_data=["N° de contrat", "Titulaire(s)", "Partenaire", "Date d'ouverture"],
        title="TRI brut et TRI net en fonction de l'anciennete",
        color_discrete_map={"TRI net": "#1f77b4", "TRI brut": "#ff7f0e"},
    )
    fig_age_scatter.update_traces(marker=dict(size=9, opacity=0.8))
    fig_age_scatter.update_xaxes(title_text="Anciennete du contrat (annees)", tickformat=".1f")
    fig_age_scatter.update_yaxes(title_text="TRI", tickformat=".1%")
    fig_age_scatter.add_hline(y=0, line_dash="dash", line_color="gray")
    st.plotly_chart(fig_age_scatter, use_container_width=True)
else:
    st.info("Impossible d'afficher le scatter anciennete/TRI: donnees d'ouverture ou TRI manquantes.")

display_current["Date de valorisation TRI"] = pd.to_datetime(display_current["Date de valorisation TRI"]).dt.strftime("%d/%m/%Y")
display_current["Valorisation TRI"] = display_current["Valorisation TRI"].map(format_eur)
display_current["Versements nets"] = display_current["Versements nets"].map(format_eur)
display_current["Versements bruts"] = display_current["Versements bruts"].map(format_eur)
display_current["TRI net"] = display_current["TRI net"].map(format_pct)
display_current["TRI brut"] = display_current["TRI brut"].map(format_pct)

st.dataframe(
    display_current[
        [
            "N° de contrat",
            "Titulaire(s)",
            "Enveloppe",
            "Partenaire",
            "Date de valorisation TRI",
            "Valorisation TRI",
            "TRI net",
            "TRI brut",
            "Versements nets",
            "Versements bruts",
            "PDF",
        ]
    ],
    hide_index=True,
    use_container_width=True,
)

if not portfolio_tri_summary.empty:
    with st.expander("Voir l'historique agrege"):
        summary_display = portfolio_tri_summary.copy()
        summary_display["Date de valorisation"] = pd.to_datetime(summary_display["Date de valorisation"]).dt.strftime("%d/%m/%Y")
        summary_display["TRI net median"] = summary_display["TRI net median"].map(format_pct)
        summary_display["TRI brut median"] = summary_display["TRI brut median"].map(format_pct)
        summary_display["TRI net pondéré"] = summary_display["TRI net pondéré"].map(format_pct)
        summary_display["TRI brut pondéré"] = summary_display["TRI brut pondéré"].map(format_pct)
        summary_display["Valorisation totale"] = summary_display["Valorisation totale"].map(format_eur)
        st.dataframe(summary_display, hide_index=True, use_container_width=True)