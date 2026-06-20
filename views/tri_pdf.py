from pathlib import Path
import sys
import importlib

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import pdf_tri_analysis as _pdf_tri_analysis

_pdf_tri_analysis = importlib.reload(_pdf_tri_analysis)
DEFAULT_PDF_DIR = _pdf_tri_analysis.DEFAULT_PDF_DIR
analyze_directory = _pdf_tri_analysis.analyze_directory

_CIVILITES = {"madame", "monsieur", "mademoiselle", "mme", "m.", "mlle"}
_NOM_PARTICULES = {"de", "du", "des", "le", "la", "van", "von", "d"}


def subscriber_sort_key(full_name: str) -> tuple[str, str, str]:
    value = str(full_name or "").strip()
    if not value:
        return ("~~~~", "~~~~", "")
    if "inconnu" in value.lower():
        return ("~~~~", "~~~~", value.lower())

    tokens = value.split()
    if tokens and tokens[0].lower().strip(".") in _CIVILITES:
        tokens = tokens[1:]

    if not tokens:
        return ("~~~~", "~~~~", value.lower())
    if len(tokens) == 1:
        return (tokens[0].lower(), "", value.lower())

    family_tokens = [tokens[-1]]
    if len(tokens) >= 2 and tokens[-2].lower() in _NOM_PARTICULES:
        family_tokens = [tokens[-2], tokens[-1]]
        first_tokens = tokens[:-2]
    else:
        first_tokens = tokens[:-1]

    family_name = " ".join(family_tokens).lower()
    first_name = " ".join(first_tokens).lower()
    return (family_name, first_name, value.lower())


def format_eur(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{value:,.2f} €".replace(",", " ")


def format_pct(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{value * 100:.2f}%"


def build_summary_dataframe(analyses: list[dict[str, object]]) -> pd.DataFrame:
    valid_rows = [row for row in analyses if "error" not in row]
    if not valid_rows:
        return pd.DataFrame()

    df = pd.DataFrame(
        {
            "Fichier": [row["file_name"] for row in valid_rows],
            "Souscripteur": [row.get("subscriber_name", "Souscripteur inconnu") for row in valid_rows],
            "Type": [row.get("contract_type", "Inconnu") for row in valid_rows],
            "Contrat": [row["contract_number"] for row in valid_rows],
            "Libelle": [row["contract_label"] for row in valid_rows],
            "Date de valorisation": [row["valuation_date"] for row in valid_rows],
            "Valorisation": [row["valuation_amount"] for row in valid_rows],
            "Versements bruts": [row["gross_payments_total"] for row in valid_rows],
            "Versements nets": [row["net_payments_total"] for row in valid_rows],
            "TRI net": [row["tri_net"] for row in valid_rows],
            "TRI brut": [row["tri_gross"] for row in valid_rows],
            "Nb versements": [row["versements_count"] for row in valid_rows],
            "Nb arbitrages": [row["arbitrages_count"] for row in valid_rows],
        }
    )
    df["_sub_key"] = df["Souscripteur"].map(subscriber_sort_key)
    df = df.sort_values(["_sub_key", "Type", "Date de valorisation", "Contrat"], ascending=[True, True, False, True])
    return df.drop(columns=["_sub_key"]).reset_index(drop=True)


def build_timeline_figure(contract_row: dict[str, object]) -> go.Figure:
    movements = contract_row["movements"].copy()
    valuation_date = pd.Timestamp(contract_row["valuation_date"])
    valuation_amount = float(contract_row["valuation_amount"])

    contribution_mask = movements["movement_type"] == "contribution"
    redemption_mask = movements["movement_type"] == "redemption"
    arbitrage_mask = movements["movement_type"] == "arbitrage"

    invested = movements.loc[contribution_mask | redemption_mask, ["date", "label", "amount_net", "amount_gross", "movement_type"]].copy()
    if invested.empty:
        invested = pd.DataFrame(
            [{"date": valuation_date, "label": "Valorisation", "amount_net": 0.0, "amount_gross": 0.0, "movement_type": "valuation"}]
        )

    invested["signed_net"] = invested.apply(
        lambda row: row["amount_net"] if row["movement_type"] == "contribution" else -row["amount_net"],
        axis=1,
    )
    invested["signed_gross"] = invested.apply(
        lambda row: row["amount_gross"] if row["movement_type"] == "contribution" else -row["amount_gross"],
        axis=1,
    )
    invested = invested.sort_values(["date", "label"]).reset_index(drop=True)
    invested["cum_net"] = invested["signed_net"].cumsum()
    invested["cum_gross"] = invested["signed_gross"].cumsum()

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=invested["date"],
            y=invested["cum_net"],
            mode="lines+markers",
            name="Capital investi net",
            line={"color": "#1f77b4", "width": 3},
            hovertemplate="%{x|%d/%m/%Y}<br>Net cumule: %{y:,.2f} €<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=invested["date"],
            y=invested["cum_gross"],
            mode="lines+markers",
            name="Capital investi brut",
            line={"color": "#ff7f0e", "width": 3, "dash": "dot"},
            hovertemplate="%{x|%d/%m/%Y}<br>Brut cumule: %{y:,.2f} €<extra></extra>",
        )
    )

    last_gross = float(invested["cum_gross"].iloc[-1]) if not invested.empty else 0.0
    last_net = float(invested["cum_net"].iloc[-1]) if not invested.empty else 0.0
    y_reference = max([valuation_amount, last_gross, last_net, 1.0])

    versements = movements.loc[contribution_mask, ["date", "label", "amount_net"]]
    if not versements.empty:
        fig.add_trace(
            go.Scatter(
                x=versements["date"],
                y=[y_reference * 0.04] * len(versements),
                mode="markers",
                name="Versements",
                marker={"color": "#2ca02c", "size": 11, "symbol": "diamond"},
                customdata=versements[["label", "amount_net"]],
                hovertemplate="%{x|%d/%m/%Y}<br>%{customdata[0]}<br>Montant net: %{customdata[1]:,.2f} €<extra></extra>",
            )
        )

    arbitrages = movements.loc[arbitrage_mask, ["date", "label", "amount_net"]]
    if not arbitrages.empty:
        fig.add_trace(
            go.Scatter(
                x=arbitrages["date"],
                y=[y_reference * 0.96] * len(arbitrages),
                mode="markers",
                name="Arbitrages",
                marker={"color": "#d62728", "size": 10, "symbol": "x"},
                customdata=arbitrages[["label", "amount_net"]],
                hovertemplate="%{x|%d/%m/%Y}<br>%{customdata[0]}<br>Montant: %{customdata[1]:,.2f} €<extra></extra>",
            )
        )

    fig.add_trace(
        go.Scatter(
            x=[valuation_date],
            y=[valuation_amount],
            mode="markers",
            name="Valorisation a date",
            marker={"color": "#111111", "size": 14, "symbol": "star"},
            hovertemplate="%{x|%d/%m/%Y}<br>Valorisation: %{y:,.2f} €<extra></extra>",
        )
    )

    fig.update_layout(
        title=f"Flux et evenements - contrat {contract_row['contract_number']}",
        xaxis_title="Date",
        yaxis_title="Montant (€)",
        legend_title="Series",
        hovermode="x unified",
    )
    fig.update_yaxes(tickformat=",.0f")
    return fig


st.title("TRI des contrats PDF")
st.caption("Lecture des PDF du repertoire 00_Exports/04_Operations, calcul du TRI net et brut, hors frais de gestion.")

default_dir = str(DEFAULT_PDF_DIR)
pdf_dir_input = st.text_input("Repertoire des PDF", value=default_dir)
pdf_dir = Path(pdf_dir_input).expanduser()


def load_analyses(directory: str) -> list[dict[str, object]]:
    return analyze_directory(Path(directory))


if st.button("Recharger l'analyse"):
    st.rerun()


with st.spinner("Analyse des PDF en cours..."):
    analyses = load_analyses(str(pdf_dir))

if not analyses:
    st.warning("Aucun PDF trouve dans le repertoire indique.")
    st.stop()

errors = [row for row in analyses if "error" in row]
summary_df = build_summary_dataframe(analyses)

if summary_df.empty:
    st.error("Aucun PDF n'a pu etre analyse correctement.")
else:
    valid_rows = [row for row in analyses if "error" not in row]
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("PDF analyses", len(valid_rows))
    col2.metric("TRI net median", format_pct(summary_df["TRI net"].dropna().median() if summary_df["TRI net"].notna().any() else None))
    col3.metric("TRI brut median", format_pct(summary_df["TRI brut"].dropna().median() if summary_df["TRI brut"].notna().any() else None))
    col4.metric("Valorisation totale", format_eur(summary_df["Valorisation"].sum()))

    display_df = summary_df.copy()
    display_df["Valorisation"] = display_df["Valorisation"].map(format_eur)
    display_df["Versements bruts"] = display_df["Versements bruts"].map(format_eur)
    display_df["Versements nets"] = display_df["Versements nets"].map(format_eur)
    display_df["TRI net"] = display_df["TRI net"].map(format_pct)
    display_df["TRI brut"] = display_df["TRI brut"].map(format_pct)
    st.dataframe(display_df, use_container_width=True, hide_index=True)

    st.subheader("Indexation des contrats")
    subscriber_options = sorted(
        {row.get("subscriber_name", "Souscripteur inconnu") for row in valid_rows},
        key=subscriber_sort_key,
    )
    selected_subscriber = st.selectbox("Souscripteur", options=subscriber_options)

    rows_by_subscriber = [row for row in valid_rows if row.get("subscriber_name", "Souscripteur inconnu") == selected_subscriber]
    type_options = sorted({row.get("contract_type", "Inconnu") for row in rows_by_subscriber})
    selected_type = st.selectbox("Type (PER/AV)", options=type_options)

    rows_filtered = [row for row in rows_by_subscriber if row.get("contract_type", "Inconnu") == selected_type]
    if not rows_filtered:
        st.warning("Aucun contrat pour cette combinaison souscripteur/type.")
        st.stop()

    contract_options = {f"{row['contract_number']} - {row['file_name']}": row for row in rows_filtered}
    selected_label = st.selectbox("Contrat a inspecter", options=list(contract_options.keys()))
    selected_contract = contract_options[selected_label]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Valorisation", format_eur(selected_contract["valuation_amount"]))
    c2.metric("TRI net", format_pct(selected_contract["tri_net"]))
    c3.metric("TRI brut", format_pct(selected_contract["tri_gross"]))
    c4.metric("Date de valorisation", pd.Timestamp(selected_contract["valuation_date"]).strftime("%d/%m/%Y"))

    c5, c6, c7 = st.columns(3)
    c5.metric("Versements nets", format_eur(selected_contract["net_payments_total"]))
    c6.metric("Versements bruts", format_eur(selected_contract["gross_payments_total"]))
    c7.metric("Arbitrages", str(selected_contract["arbitrages_count"]))
    st.caption(f"Souscripteur: {selected_contract.get('subscriber_name', 'Souscripteur inconnu')} | Type: {selected_contract.get('contract_type', 'Inconnu')}")

    if selected_contract.get("assumption_note"):
        st.info(selected_contract["assumption_note"])

    st.plotly_chart(build_timeline_figure(selected_contract), use_container_width=True)

    movements_df = selected_contract["movements"].copy()
    if not movements_df.empty:
        movements_df = movements_df.rename(
            columns={
                "date": "Date",
                "label": "Libelle",
                "amount_net": "Montant net",
                "amount_gross": "Montant brut reconstitue",
                "movement_type": "Type",
                "include_in_irr": "Pris dans TRI",
            }
        )
        movements_df["Date"] = pd.to_datetime(movements_df["Date"]).dt.strftime("%d/%m/%Y")
        st.subheader("Mouvements extraits")
        st.dataframe(movements_df, use_container_width=True, hide_index=True)

if errors:
    with st.expander("PDF en erreur"):
        st.dataframe(pd.DataFrame(errors), use_container_width=True, hide_index=True)
