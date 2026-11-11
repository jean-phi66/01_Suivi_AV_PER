import os
import re
import sys

import pandas as pd
import streamlit as st
from streamlit import session_state as ss

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pptx_report_generator import build_contract_pptx_context, generate_contract_pptx
from reporting_helpers import load_latest_fund_perf_file
from tri_integration import load_tri_analyses, match_tri_analyses_to_contracts, pdf_dir_signature


@st.cache_resource(show_spinner=False)
def _get_tri_analyses(pdf_signature: tuple = ()):
    return load_tri_analyses()


def _sanitize_filename(value: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", str(value or "")).strip()
    return cleaned or "contrat"


st.title("Bilan de contrat PowerPoint")
st.caption("Exportez une présentation PowerPoint complète d'un contrat (composition, waterfalls, évolution des fonds et de la VL).")

df_contrats = ss.get("df_contrats", pd.DataFrame())
df_allocations = ss.get("df_allocations", pd.DataFrame())
df_contrat_agg = ss.get("df_contrat_agg_filtered", ss.get("df_contrat_agg", pd.DataFrame()))

required_contrats_cols = {"Titulaire(s)", "N° de contrat", "Enveloppe", "Partenaire", "Valorisation"}
required_alloc_cols = {"Numéro contrat"}

if (
    df_contrats.empty
    or df_allocations.empty
    or not required_contrats_cols.issubset(df_contrats.columns)
    or not required_alloc_cols.issubset(df_allocations.columns)
):
    st.warning("Aucune donnée contrats/allocations disponible.")
    st.info("Cliquez sur le bouton ci-dessous pour ouvrir l'onglet Données et charger automatiquement les exports.")
    if st.button("Ouvrir Données", key="pptx_open_data_ingestion"):
        st.switch_page("views/data_ingestion.py")
    st.stop()

# --- Sélection Client & Contrat ---
clients_options = sorted(df_contrats["Titulaire(s)"].dropna().astype(str).unique().tolist())
default_client = ss.get("client") if ss.get("client") in clients_options else (clients_options[0] if clients_options else None)
client_idx = clients_options.index(default_client) if default_client in clients_options else 0

col_cli, col_ctr = st.columns(2)
with col_cli:
    selected_client = st.selectbox(
        "Titulaire",
        options=clients_options,
        index=client_idx,
        key="pptx_client_select",
    )

df_contrats_client = df_contrats[df_contrats["Titulaire(s)"].astype(str) == str(selected_client)].copy()
contrats_options = df_contrats_client["N° de contrat"].dropna().astype(str).unique().tolist()
default_contrat = (
    str(ss.get("contrat"))
    if ss.get("contrat") is not None and str(ss.get("contrat")) in contrats_options
    else (contrats_options[0] if contrats_options else None)
)
contrat_idx = contrats_options.index(default_contrat) if default_contrat in contrats_options else 0

with col_ctr:
    selected_contrat = st.selectbox(
        "Contrat",
        options=contrats_options,
        index=contrat_idx,
        key="pptx_contrat_select",
    )

if not selected_contrat:
    st.warning("Aucun contrat disponible pour ce client.")
    st.stop()

df_contrat_selected = df_contrats_client[df_contrats_client["N° de contrat"].astype(str) == str(selected_contrat)].copy()
df_allocations_client = df_allocations[df_allocations["Numéro contrat"].astype(str) == str(selected_contrat)].copy()

if df_contrat_selected.empty:
    st.warning("Données introuvables pour le contrat sélectionné.")
    st.stop()

enveloppe = str(df_contrat_selected["Enveloppe"].iloc[0]) if "Enveloppe" in df_contrat_selected.columns else "N/A"
partenaire = str(df_contrat_selected["Partenaire"].iloc[0]) if "Partenaire" in df_contrat_selected.columns else "N/A"
valorisation = float(df_contrat_selected["Valorisation"].iloc[0]) if "Valorisation" in df_contrat_selected.columns else 0.0
is_per = "PER" in enveloppe.upper()

m1, m2, m3, m4 = st.columns(4)
m1.metric("Enveloppe", enveloppe)
m2.metric("Partenaire", partenaire)
m3.metric("Valorisation", f"{valorisation:,.0f} €".replace(",", " "))
m4.metric("Avantage fiscal PER", "IR 30 % inclus" if is_per else "Non applicable")

# --- Appariement TRI & Paramètres ---
_, tri_contracts_map = match_tri_analyses_to_contracts(
    _get_tri_analyses(pdf_dir_signature()),
    df_contrats[["N° de contrat", "Titulaire(s)", "Enveloppe", "Partenaire"]].drop_duplicates().copy(),
)
tri_analysis = tri_contracts_map.get(str(selected_contrat))

st.subheader("Paramètres du bilan PowerPoint")

default_source_idx = 1 if tri_analysis is not None else 0
preferred_source = st.radio(
    "Source des versements",
    options=["CSV contrats", "Releve d'operations TRI"],
    index=default_source_idx,
    horizontal=True,
    key=f"pptx_source_{selected_contrat}",
    help="Si aucun relevé d'opérations TRI n'est apparié à ce contrat, le calcul utilise automatiquement les données CSV.",
)

if tri_analysis is not None:
    st.caption("Relevé d'opérations TRI apparié : les versements et arbitrages seront affichés sur les graphiques.")
else:
    st.caption("Aucun relevé d'opérations TRI apparié à ce contrat (les versements/arbitrages détaillés ne seront pas superposés).")

df_perfs, latest_funds_file = load_latest_fund_perf_file()
date_debut = None
date_fin = None
if not df_perfs.empty:
    min_date = df_perfs["Date"].min().date()
    max_date = df_perfs["Date"].max().date()
    default_start = (df_perfs["Date"].max() - pd.DateOffset(years=1)).date()
    if default_start < min_date:
        default_start = min_date
    d1, d2 = st.columns(2)
    with d1:
        date_debut = st.date_input(
            "Date de début (évolution des fonds base 100)",
            value=default_start,
            min_value=min_date,
            max_value=max_date,
            key=f"pptx_funds_start_{selected_contrat}",
        )
    with d2:
        date_fin = st.date_input(
            "Date de fin (évolution des fonds base 100)",
            value=max_date,
            min_value=min_date,
            max_value=max_date,
            key=f"pptx_funds_end_{selected_contrat}",
        )
    if date_debut >= date_fin:
        st.error("La date de début doit être antérieure à la date de fin.")
        st.stop()
else:
    st.info("Aucun fichier de performance quotidienne des fonds (*Top*.csv) trouvé dans 00_Exports/3_Fonds.")

e1, e2 = st.columns(2)
with e1:
    show_versements = st.checkbox("Afficher les versements", value=True, key=f"pptx_show_versements_{selected_contrat}")
with e2:
    show_arbitrages = st.checkbox("Afficher les arbitrages", value=True, key=f"pptx_show_arbitrages_{selected_contrat}")

# Construction du contexte des figures (rapide, sans export Kaleido tant qu'on n'exporte pas le PPTX)
ctx = build_contract_pptx_context(
    client_name=selected_client,
    contrat_num=selected_contrat,
    df_contrats_all=df_contrats,
    df_allocations_all=df_allocations,
    df_contrat_selected=df_contrat_selected,
    df_allocations_client=df_allocations_client,
    df_contrat_agg=df_contrat_agg,
    tri_analysis=tri_analysis,
    preferred_source=preferred_source,
    date_debut=date_debut,
    date_fin=date_fin,
    show_versements=show_versements,
    show_arbitrages=show_arbitrages,
)

if ctx["missing_funds_labels"]:
    labels_preview = ", ".join(ctx["missing_funds_labels"][:5])
    suffix = "…" if len(ctx["missing_funds_labels"]) > 5 else ""
    st.warning(f"{len(ctx['missing_funds_labels'])} support(s) sans historique dans le fichier fonds : {labels_preview}{suffix}")

classes_count = len(ctx["figures_by_class"])
total_slides = 7 + classes_count
ops_slide_num = 6 + classes_count
st.info(
    f"Le document contiendra **{total_slides} slides** : "
    f"1) Page de garde ({'PER' if ctx['is_per'] else 'Assurance-vie'}), "
    f"2) Composition (classes simplifiées & supports), "
    f"3) Waterfall contrat{' (avec IR 30 %)' if ctx['is_per'] else ''}, "
    f"4) Waterfall allocation, "
    f"5) Évolution des fonds (base 100), "
    f"{f'6-{5 + classes_count}) Évolution par classe d’actifs ({classes_count} classe(s)), ' if classes_count else ''}"
    f"{ops_slide_num}) Détail des versements et des arbitrages, "
    f"{total_slides}) Évolution temporelle de la VL avec versements et arbitrages."
)

# --- Génération et téléchargement ---
state_signature = (
    str(selected_client),
    str(selected_contrat),
    preferred_source,
    str(date_debut),
    str(date_fin),
    show_versements,
    show_arbitrages,
)

if st.button("Générer le bilan PowerPoint (.pptx)", type="primary", key="btn_generate_pptx"):
    with st.spinner("Génération des graphiques et assemblage du PowerPoint en cours..."):
        pptx_bytes = generate_contract_pptx(
            client_name=selected_client,
            contrat_num=selected_contrat,
            df_contrat_sel=df_contrat_selected,
            fig_typologie_simplifiee=ctx["fig_typologie_simplifiee"],
            fig_supports=ctx["fig_supports"],
            fig_waterfall_contract=ctx["fig_waterfall_contract"],
            fig_waterfall_allocation=ctx["fig_waterfall_allocation"],
            fig_all_funds=ctx["fig_all_funds"],
            figures_by_class=ctx["figures_by_class"],
            fig_evol=ctx["fig_evol"],
            kpis=ctx["kpis"],
            is_per=ctx["is_per"],
            tri_analysis=ctx["tri_analysis"],
        )
        ss["pptx_generated_bytes"] = pptx_bytes
        ss["pptx_generated_signature"] = state_signature
    st.success("Bilan PowerPoint généré avec succès !")

if ss.get("pptx_generated_signature") == state_signature and ss.get("pptx_generated_bytes"):
    file_name = f"{_sanitize_filename(selected_client)} - {_sanitize_filename(selected_contrat)} - Bilan.pptx"
    st.download_button(
        label="Télécharger le bilan PowerPoint (.pptx)",
        data=ss["pptx_generated_bytes"],
        file_name=file_name,
        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        key="download_bilan_pptx",
    )

# --- Aperçu interactif des graphiques inclus ---
with st.expander("Aperçu des graphiques et tableaux du bilan", expanded=False):
    tab_names = [
        "1. Composition",
        "2. Waterfall Contrat",
        "3. Waterfall Allocation",
        "4. Fonds (global & classes)",
        "5. Versements & Arbitrages",
        "6. Évolution VL",
    ]
    t1, t2, t3, t4, t5, t6 = st.tabs(tab_names)
    with t1:
        c_left, c_right = st.columns(2)
        with c_left:
            if ctx["fig_typologie_simplifiee"] is not None:
                st.plotly_chart(ctx["fig_typologie_simplifiee"], use_container_width=True)
        with c_right:
            if ctx["fig_supports"] is not None:
                st.plotly_chart(ctx["fig_supports"], use_container_width=True)
    with t2:
        if ctx["fig_waterfall_contract"] is not None:
            st.plotly_chart(ctx["fig_waterfall_contract"], use_container_width=True)
    with t3:
        if ctx["fig_waterfall_allocation"] is not None:
            st.plotly_chart(ctx["fig_waterfall_allocation"], use_container_width=True)
    with t4:
        if ctx["fig_all_funds"] is not None:
            st.plotly_chart(ctx["fig_all_funds"], use_container_width=True)
        else:
            st.info("Aucun historique de performance disponible pour les fonds du contrat.")
        for asset_class, fig_cls in ctx["figures_by_class"]:
            st.plotly_chart(fig_cls, use_container_width=True)
    with t5:
        ops_meta = ctx.get("ops_meta") or {}
        c_v, c_a = st.columns(2)
        with c_v:
            st.markdown(f"**Versements ({ops_meta.get('v_count', 0)})**")
            df_v = ctx.get("df_versements")
            if df_v is not None and not df_v.empty:
                st.dataframe(df_v, use_container_width=True, hide_index=True)
            else:
                st.info("Aucun versement extrait du relevé TRI.")
        with c_a:
            st.markdown(f"**Arbitrages ({ops_meta.get('a_count', 0)})**")
            df_a = ctx.get("df_arbitrages")
            if df_a is not None and not df_a.empty:
                st.dataframe(df_a, use_container_width=True, hide_index=True)
            else:
                st.info("Aucun arbitrage extrait du relevé TRI.")
        if ops_meta.get("assumption_note"):
            st.caption(ops_meta["assumption_note"])
    with t6:
        if ctx["fig_evol"] is not None:
            st.plotly_chart(ctx["fig_evol"], use_container_width=True)
        else:
            st.info("Historique de valorisation indisponible pour ce contrat.")

