from pathlib import Path
import datetime
import io
import os
import sys

import pandas as pd
import streamlit as st
from streamlit import session_state as ss

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from projection_helpers import (
    calculate_contract_projection,
    detect_contract_fee_rate,
    detect_default_monthly_contribution,
    detect_initial_contribution,
    filter_early_valuation_anomalies,
    build_projection_trajectory_figure,
    build_projection_breakdown_figure,
    build_projection_stacked_area_figure,
    build_projection_fee_comparison_figure,
    generate_projection_pptx,
)
from tri_integration import load_tri_analyses, match_tri_analyses_to_contracts, pdf_dir_signature


@st.cache_resource(show_spinner=False)
def _get_tri_analyses(pdf_signature: tuple = ()):
    return load_tri_analyses()


st.title("Projection / Plan à long terme")
st.caption(
    "Resituez l'évolution de la valorisation du contrat dans le temps et projetez son capital à long terme "
    "selon plusieurs scénarios de rendement en intégrant les frais et les versements programmés."
)

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
    if st.button("Ouvrir Données", key="proj_open_data_ingestion"):
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
        key="proj_client_select",
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
        key="proj_contrat_select",
    )

if not selected_contrat:
    st.warning("Aucun contrat disponible pour ce client.")
    st.stop()

df_contrat_selected = df_contrats_client[df_contrats_client["N° de contrat"].astype(str) == str(selected_contrat)].copy()
df_allocations_client = df_allocations[df_allocations["Numéro contrat"].astype(str) == str(selected_contrat)].copy()

if df_contrat_selected.empty:
    st.warning("Données introuvables pour le contrat sélectionné.")
    st.stop()

# Met à jour le session state global pour la navigation
ss["client"] = selected_client
ss["contrat"] = selected_contrat
ss["df_contrat_selected"] = df_contrat_selected
ss["df_allocations_client"] = df_allocations_client

# Appariement TRI pour récupérer les versements programmés éventuels
_, tri_contracts_map = match_tri_analyses_to_contracts(
    _get_tri_analyses(pdf_dir_signature()),
    df_contrats[["N° de contrat", "Titulaire(s)", "Enveloppe", "Partenaire"]].drop_duplicates().copy(),
)
tri_analysis = tri_contracts_map.get(str(selected_contrat))

# Informations clés du contrat
enveloppe = str(df_contrat_selected["Enveloppe"].iloc[0]) if "Enveloppe" in df_contrat_selected.columns else "N/A"
partenaire = str(df_contrat_selected["Partenaire"].iloc[0]) if "Partenaire" in df_contrat_selected.columns else "N/A"
valorisation_actuelle = float(df_contrat_selected["Valorisation"].iloc[0]) if "Valorisation" in df_contrat_selected.columns else 0.0
is_per = "PER" in enveloppe.upper()

date_val_raw = df_contrat_selected["Date de valorisation"].iloc[0] if "Date de valorisation" in df_contrat_selected.columns else None
current_val_date = pd.to_datetime(date_val_raw).date() if pd.notna(date_val_raw) else datetime.date.today()

# Extraction de l'historique réel pour la continuité visuelle
df_hist_ctr = pd.DataFrame()
if df_contrat_agg is not None and not df_contrat_agg.empty and "N° de contrat" in df_contrat_agg.columns:
    df_hist_ctr = df_contrat_agg[df_contrat_agg["N° de contrat"].astype(str) == str(selected_contrat)].copy()

# Détection automatique du premier versement, des frais et des versements programmés
init_contrib_info = detect_initial_contribution(df_contrat_selected, tri_analysis, df_hist_ctr)
frais_contrat_def, frais_supports_def, frais_versement_def = detect_contract_fee_rate(df_contrat_selected, df_allocations_client)
vp_auto_amt = detect_default_monthly_contribution(tri_analysis, df_contrat_selected)

# Bannière récapitulative contrat
c_m1, c_m2, c_m3, c_m4 = st.columns(4)
c_m1.metric("Enveloppe fiscale", enveloppe)
c_m2.metric("Assureur / Partenaire", partenaire)
c_m3.metric("Valorisation actuelle", f"{valorisation_actuelle:,.0f} €".replace(",", " "), help=f"Situation arrêtée au {current_val_date.strftime('%d/%m/%Y')}")
c_m4.metric("Type de contrat", "PER (Plan d'Épargne Retraite)" if is_per else "Assurance-vie")

st.markdown("---")

# --- Paramètres de la Projection ---
st.subheader("Paramètres de la projection")

col_p1, col_p2, col_p3, col_p4 = st.columns(4)

with col_p1:
    st.markdown("##### 🚀 1er versement (Origine)")
    init_date_input = st.date_input(
        "Date du 1er versement",
        value=init_contrib_info["initial_date"],
        key=f"proj_init_date_{selected_contrat}",
        help="Date de versement initial / souscription du contrat.",
    )
    init_net_input = st.number_input(
        "Versement initial net (€)",
        min_value=1.0,
        max_value=10_000_000.0,
        value=float(init_contrib_info["initial_amount_net"]),
        step=1000.0,
        format="%.0f",
        key=f"proj_init_net_{selected_contrat}",
        help="Montant net investi à l'origine dans les supports (point de départ de la projection).",
    )
    init_gross_input = st.number_input(
        "Versement initial brut (€)",
        min_value=float(init_net_input),
        max_value=10_000_000.0,
        value=float(max(init_net_input, init_contrib_info["initial_amount_gross"])),
        step=1000.0,
        format="%.0f",
        key=f"proj_init_gross_{selected_contrat}",
        help="Montant brut versé par le client (matérialisé par la ligne repère horizontale).",
    )
    st.caption(f"💡 Détecté depuis : **{init_contrib_info['source']}**")
    elapsed_years = max(0.0, (current_val_date - init_date_input).days / 365.25)
    st.caption(f"⏱️ Ancienneté : **{elapsed_years:.1f} ans** d'historique réel")

    filter_early_anom = st.checkbox(
        "Filtrer anomalies de valorisation (ouverture & arbitrages)",
        value=True,
        key=f"proj_filter_anom_{selected_contrat}",
        help=(
            "Ignore les premières valorisations post-ouverture incomplètes (< 95% du net investi) ainsi que "
            "les creux transitoires en cours de vie liés aux délais de valorisation lors des arbitrages."
        ),
    )
    if filter_early_anom:
        with st.expander("⚙️ Réglage des filtres de valorisation", expanded=False):
            anom_ratio_pct = st.slider(
                "Tolérance ouverture (% versement net)",
                min_value=50,
                max_value=99,
                value=95,
                step=1,
                key=f"proj_anom_ratio_{selected_contrat}",
                help="Seuil en-deçà duquel une valorisation initiale est considérée incomplète (défaut : 95%).",
            )
            anom_window_days = st.slider(
                "Fenêtre post-ouverture (jours)",
                min_value=15,
                max_value=180,
                value=90,
                step=15,
                key=f"proj_anom_window_{selected_contrat}",
                help="Délai maximal après le premier versement durant lequel le filtre d'ouverture s'applique (défaut : 90 jours).",
            )
            filter_transient_dips = st.checkbox(
                "Filtrer les creux temporaires d'arbitrage (< 25 jours)",
                value=True,
                key=f"proj_filter_dips_{selected_contrat}",
                help="Ignore les chutes temporaires résorbées en moins de 25 jours dues aux délais de valorisation lors d'un arbitrage.",
            )
    else:
        anom_ratio_pct = 95
        anom_window_days = 90
        filter_transient_dips = False

with col_p2:
    st.markdown("##### ⏳ Horizon & Versements")
    years = st.slider(
        "Durée de projection future (années)",
        min_value=1,
        max_value=35,
        value=8,
        step=1,
        key=f"proj_years_{selected_contrat}",
        help="Nombre d'années à projeter à partir de la valorisation actuelle.",
    )
    target_year = current_val_date.year + years
    total_span_years = elapsed_years + years
    st.caption(f"📅 Atterrissage en **{target_year}** (durée totale : **{total_span_years:.1f} ans**)")

    default_vp_val = float(vp_auto_amt) if vp_auto_amt > 0 else 0.0
    monthly_contrib = st.number_input(
        "Versement programmé mensuel (€)",
        min_value=0.0,
        max_value=100000.0,
        value=default_vp_val,
        step=50.0,
        key=f"proj_monthly_{selected_contrat}",
        help="Montant épargné chaque mois. Pré-rempli automatiquement si un versement programmé a été détecté dans le contrat.",
    )
    if vp_auto_amt > 0:
        st.caption(f"💡 Versement programmé de {vp_auto_amt:,.0f} €/mois détecté dans le contrat.")

    annual_contrib = st.number_input(
        "Versement annuel complémentaire (€)",
        min_value=0.0,
        max_value=500000.0,
        value=0.0,
        step=500.0,
        key=f"proj_annual_{selected_contrat}",
        help="Versement ponctuel récurrent chaque fin d'année (ex: prime, épargne de fin d'année).",
    )

with col_p3:
    st.markdown("##### 💳 Frais & Prélèvements")
    frais_contrat = st.number_input(
        "Frais de gestion contrat (% / an)",
        min_value=0.0,
        max_value=3.0,
        value=1.00,
        step=0.05,
        format="%.2f",
        key=f"proj_fee_ctr_{selected_contrat}",
        help="Frais de gestion prélevés annuellement par la compagnie d'assurance sur l'encours (défaut : 1.00%).",
    )
    frais_supports = 0.0
    frais_versement = st.number_input(
        "Frais sur versements futurs (%)",
        min_value=0.0,
        max_value=5.0,
        value=float(frais_versement_def),
        step=0.1,
        format="%.2f",
        key=f"proj_fee_contrib_{selected_contrat}",
        help="Frais prélevés à l'entrée lors de chaque nouveau versement (généralement 0% à 1% en gestion conseillée).",
    )
    st.info(f"Frais de gestion contrat : **{frais_contrat:.2f} % / an** sur l'encours.")

with col_p4:
    st.markdown("##### 📊 Scénarios & Ancrage")
    rate_prudent = st.number_input(
        "Scénario Prudent (% brut)",
        min_value=-5.0,
        max_value=15.0,
        value=2.5,
        step=0.1,
        format="%.1f",
        key=f"proj_rate_prud_{selected_contrat}",
        help="Rendement annuel brut avant frais (profil sécuritaire).",
    )
    rate_equilibre = st.number_input(
        "Scénario Équilibré (% brut)",
        min_value=-5.0,
        max_value=20.0,
        value=5.0,
        step=0.1,
        format="%.1f",
        key=f"proj_rate_equi_{selected_contrat}",
        help="Rendement annuel brut avant frais (profil équilibré).",
    )
    rate_dynamique = st.number_input(
        "Scénario Dynamique (% brut)",
        min_value=-5.0,
        max_value=25.0,
        value=6.0,
        step=0.1,
        format="%.1f",
        key=f"proj_rate_dyna_{selected_contrat}",
        help="Rendement annuel brut avant frais (profil dynamique, défaut : 6.0%).",
    )

    tmi_val = 30.0
    if is_per:
        tmi_val = st.selectbox(
            "Tranche Marginale d'IR (TMI)",
            options=[0.0, 11.0, 30.0, 41.0, 45.0],
            index=2,  # 30% par défaut
            format_func=lambda x: f"{x:.0f} %",
            key=f"proj_tmi_{selected_contrat}",
            help="Taux marginal d'imposition utilisé pour calculer l'économie d'IR sur les versements PER.",
        )

    anchor_choice = st.radio(
        "Trajectoire des scénarios",
        options=["Depuis le 1er versement", "Recalé sur encours actuel"],
        index=0,
        key=f"proj_anchor_{selected_contrat}",
        help="Depuis le 1er versement : vision globale du plan depuis l'origine. Recalé sur encours actuel : projection future démarrant depuis la valorisation d'aujourd'hui.",
    )
    selected_anchor_mode = "origin" if "1er versement" in anchor_choice else "reanchored_today"

# Construction du dictionnaire de scénarios
scenarios = {
    "Prudent": rate_prudent / 100.0,
    "Équilibré": rate_equilibre / 100.0,
    "Dynamique": rate_dynamique / 100.0,
}

# Calcul de la projection
proj_res = calculate_contract_projection(
    current_valuation=valorisation_actuelle,
    current_date=current_val_date,
    initial_amount=init_net_input,
    initial_amount_gross=init_gross_input,
    initial_date=init_date_input,
    years=years,
    monthly_contribution=monthly_contrib,
    annual_contribution=annual_contrib,
    contribution_fee_pct=frais_versement,
    contract_fee_pct=frais_contrat,
    fund_fee_pct=frais_supports,
    scenarios=scenarios,
    is_per=is_per,
    tmi_pct=tmi_val,
    historical_movements=tri_analysis.get("movements") if tri_analysis else None,
    future_anchor_mode=selected_anchor_mode,
)

ss["projection_data"] = proj_res

# --- Synthèse KPI à l'horizon ---
st.markdown("---")
st.subheader(f"Résultats projetés à l'horizon {years} ans ({target_year})")

summary = proj_res["summary"]
central_summary = summary.get("Équilibré", summary[list(summary.keys())[0]])

gain_actuel = valorisation_actuelle - init_net_input
gain_actuel_pct = (gain_actuel / init_net_input * 100.0) if init_net_input > 0 else 0.0

kpi_c1, kpi_c2, kpi_c3, kpi_c4, kpi_c5 = st.columns(5)
kpi_c1.metric(
    "1er versement net (Origine)",
    f"{init_net_input:,.0f} €".replace(",", " "),
    f"Brut : {init_gross_input:,.0f} € au {init_date_input.strftime('%d/%m/%Y')}".replace(",", " "),
)
kpi_c2.metric(
    "Valorisation actuelle",
    f"{valorisation_actuelle:,.0f} €".replace(",", " "),
    f"{gain_actuel:+,.0f} € ({gain_actuel_pct:+.1f}%)".replace(",", " "),
    help=f"Situation arrêtée au {current_val_date.strftime('%d/%m/%Y')} (après {elapsed_years:.1f} ans)",
)
kpi_c3.metric(
    "Valorisation à terme (Équilibré)",
    f"{central_summary['final_valuation']:,.0f} €".replace(",", " "),
    f"{central_summary['capital_multiplier']:.2f}x le capital versé",
)
kpi_c4.metric(
    "Total capital versé brut",
    f"{central_summary['total_invested']:,.0f} €".replace(",", " "),
    f"+{(central_summary['total_invested'] - init_gross_input):,.0f} € versés".replace(",", " "),
)
kpi_c5.metric(
    "Gain financier net",
    f"{central_summary['net_gain']:,.0f} €".replace(",", " "),
    f"+{central_summary['net_gain_pct']:.1f} %",
)

# --- Visualisation unique : Graphique 1 (Trajectoire globale) ---
st.markdown("### Trajectoire globale (Historique réel & Projections)")
st.caption(
    "Ce graphique unifie le **versement initial net** (point de départ de la projection), la ligne repère horizontale du **versement initial brut**, "
    "l'**historique réel constaté** jusqu'à aujourd'hui et le **faisceau de projections futures** selon les scénarios de rendement."
)

fig_trajectory = build_projection_trajectory_figure(
    projection_data=proj_res,
    historical_df=df_hist_ctr,
    contrat_num=selected_contrat,
    client_name=selected_client,
    future_anchor_mode=selected_anchor_mode,
    filter_early_anomalies=filter_early_anom,
    anomaly_min_ratio=anom_ratio_pct / 100.0,
    anomaly_window_days=anom_window_days,
    filter_transient_dips=filter_transient_dips,
    height=620,
)

anomalies_detectees = getattr(fig_trajectory, "_filtered_anomalies", [])
if filter_early_anom and anomalies_detectees:
    anom_open = [a for a in anomalies_detectees if a.get("type") == "Ouverture incomplète"]
    anom_dips = [a for a in anomalies_detectees if a.get("type") != "Ouverture incomplète"]
    details_parts = []
    if anom_open:
        desc_o = ", ".join([f"**{a['Valorisation']:,.0f} €** au {pd.to_datetime(a['Date']).strftime('%d/%m/%Y')} ({a.get('Ratio', 0):.0%} du net)" for a in anom_open])
        details_parts.append(f"{len(anom_open)} ouverture(s) incomplète(s) ({desc_o})")
    if anom_dips:
        desc_d = ", ".join([f"**{a['Valorisation']:,.0f} €** au {pd.to_datetime(a['Date']).strftime('%d/%m/%Y')}" for a in anom_dips])
        details_parts.append(f"{len(anom_dips)} creux d'arbitrage temporaire(s) ({desc_d})")
    full_desc = " et ".join(details_parts)
    st.info(
        f"💡 **Filtre d'anomalies actif** : {len(anomalies_detectees)} point(s) masqué(s) : {full_desc}. "
        "Les encours partiels transitoires (délai de règlement multi-supports ou d'arbitrage) sont neutralisés pour refléter une trajectoire fidèle."
    )

st.plotly_chart(fig_trajectory, use_container_width=True)

# Tableau prévisionnel et export CSV
with st.expander("📄 Afficher le tableau détaillé des flux et exporter en CSV", expanded=False):
    yearly_df = proj_res["yearly_df"].copy()
    display_cols = ["Annee", "Date", "Versements_cumules"]
    rename_dict = {
        "Annee": "Année",
        "Date": "Date",
        "Versements_cumules": "Capital versé brut (€)",
    }
    for s in scenarios:
        display_cols.append(f"Val_{s}")
        rename_dict[f"Val_{s}"] = f"Valorisation {s} (€)"
        display_cols.append(f"FraisGestion_{s}")
        rename_dict[f"FraisGestion_{s}"] = f"Frais cumulés {s} (€)"

    df_display = yearly_df[display_cols].rename(columns=rename_dict).copy()
    df_display["Date"] = pd.to_datetime(df_display["Date"]).dt.strftime("%d/%m/%Y")
    for col in df_display.columns:
        if "€" in col:
            df_display[col] = df_display[col].apply(lambda x: f"{x:,.0f} €".replace(",", " "))

    st.dataframe(df_display, use_container_width=True, hide_index=True)

    csv_data = yearly_df.to_csv(index=False, sep=";").encode("utf-8")
    st.download_button(
        label="Exporter les données prévisionnelles (CSV)",
        data=csv_data,
        file_name=f"Projection_{selected_client}_{selected_contrat}_{years}ans.csv",
        mime="text/csv",
        key=f"dl_proj_csv_{selected_contrat}",
    )

# --- Export de la synthèse de projection en PowerPoint ---
st.markdown("---")
st.subheader("Export de la projection")

pptx_signature = (
    str(selected_client),
    str(selected_contrat),
    str(init_date_input),
    float(init_net_input),
    float(init_gross_input),
    str(selected_anchor_mode),
    int(years),
    float(monthly_contrib),
    float(annual_contrib),
    float(frais_contrat),
    float(frais_supports),
    float(frais_versement),
    float(rate_prudent),
    float(rate_equilibre),
    float(rate_dynamique),
    float(tmi_val),
    bool(filter_early_anom),
    float(anom_ratio_pct),
    int(anom_window_days),
    bool(filter_transient_dips),
)

col_exp_pptx, col_dl_pptx = st.columns([2, 3])
with col_exp_pptx:
    if st.button("Générer la présentation du plan (.pptx)", type="primary", key=f"btn_proj_pptx_{selected_contrat}"):
        with st.spinner("Génération de la présentation PowerPoint du plan de projection en cours..."):
            pptx_bytes = generate_projection_pptx(
                projection_data=proj_res,
                client_name=selected_client,
                contrat_num=selected_contrat,
                enveloppe=enveloppe,
                partenaire=partenaire,
                fig_trajectory=fig_trajectory,
            )
            ss[f"proj_pptx_bytes_{selected_contrat}"] = pptx_bytes
            ss[f"proj_pptx_sig_{selected_contrat}"] = pptx_signature
        st.success("Présentation PowerPoint générée avec succès !")

with col_dl_pptx:
    if ss.get(f"proj_pptx_sig_{selected_contrat}") == pptx_signature and ss.get(f"proj_pptx_bytes_{selected_contrat}"):
        st.download_button(
            label="Télécharger la présentation du plan de projection (.pptx)",
            data=ss[f"proj_pptx_bytes_{selected_contrat}"],
            file_name=f"{selected_client} - {selected_contrat} - Plan de projection {years} ans.pptx",
            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            key=f"dl_proj_pptx_{selected_contrat}",
        )

# Sauvegarde des résultats dans session_state pour utilisation inter-pages
ss["projection_data"] = proj_res
ss["fig_projection_trajectory"] = fig_trajectory
