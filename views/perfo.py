import streamlit as st
from streamlit import session_state as ss

import pandas as pd

import plotly.express as px
from waterfall_graphs import generate_contrats_waterfall, generate_allocations_waterfall
import plotly.graph_objects as go


df_allocations = ss['df_allocations']
df_contrats = ss['df_contrats']
df_contrat_selected = ss['df_contrat_selected']
contrat = ss['contrat']
df_contrat_agg = ss['df_contrat_agg']

st.title("Analyse de la performance")

# --- START: KPI Calculations ---
if not df_contrat_selected.empty:
    # Extract data
    valorisation = df_contrat_selected['Valorisation'].iloc[0]
    date_ouverture_raw = df_contrat_selected['Ouverture'].iloc[0] if 'Ouverture' in df_contrat_selected.columns else None
    date_valorisation_raw = df_contrat_selected['Date de valorisation'].iloc[0] if 'Date de valorisation' in df_contrat_selected.columns else None
    montant_versements_bruts = df_contrat_selected['Montant total des versements bruts'].iloc[0] if 'Montant total des versements bruts' in df_contrat_selected.columns else 0.0
    montant_versements_nets = df_contrat_selected['Montant total des versements nets'].iloc[0] if 'Montant total des versements nets' in df_contrat_selected.columns else 0.0

    # Calculate TRA
    tra_str = "N/A"
    if pd.notna(date_ouverture_raw) and pd.notna(date_valorisation_raw) and valorisation > 0:
        date_ouverture_dt = pd.to_datetime(date_ouverture_raw)
        date_valorisation_dt = pd.to_datetime(date_valorisation_raw)
        
        if date_valorisation_dt > date_ouverture_dt:
            years = (date_valorisation_dt - date_ouverture_dt).days / 365.25
            if montant_versements_nets > 0:
                # Simplified TRA calculation
                tra = ((valorisation / montant_versements_nets) ** (1 / years) - 1) * 100
                tra_str = f"{tra:.2f}%"
            else:
                tra_str = "N/A (V.N. nuls)"
        else:
             tra_str = "N/A (Durée <= 0)"
    
    # Calculate Performance vs Payments
    var_vs_brut_pct_str = "N/A"
    if montant_versements_bruts > 0:
        var_vs_brut_pct = ((valorisation - montant_versements_bruts) / montant_versements_bruts) * 100
        var_vs_brut_pct_str = f"{var_vs_brut_pct:.2f}%"

    var_vs_net_pct_str = "N/A"
    if montant_versements_nets > 0:
        var_vs_net_pct = ((valorisation - montant_versements_nets) / montant_versements_nets) * 100
        var_vs_net_pct_str = f"{var_vs_net_pct:.2f}%"

    # Display KPIs
    st.subheader("Indicateurs Clés de Performance")
    
    col1, col2 = st.columns(2)
    col1.metric("Valorisation", f"{valorisation:,.0f} €".replace(",", " "))
    col2.metric("TRA (estimé)", tra_str)

    col3, col4 = st.columns(2)
    col3.metric("Versements Bruts", f"{montant_versements_bruts:,.0f} €".replace(",", " "))
    col4.metric("Performance / VB (%)", var_vs_brut_pct_str)

    col5, col6 = st.columns(2)
    col5.metric("Versements Nets", f"{montant_versements_nets:,.0f} €".replace(",", " "))
    col6.metric("Performance / VN (%)", var_vs_net_pct_str)
    
    st.divider()
# --- END: KPI Calculations ---

if (df_contrat_selected.Enveloppe.values[0] == "PER"):
    add_reduction_IR = st.checkbox("Ajouter avantage fiscal")
    if add_reduction_IR:
        IR = st.selectbox(
            "Tranche marginale d'imposition",
            ("0%", "11%", "30%", "41%", "45%"), index=2)
        IR_num = float(IR.replace("%", "")) / 100
    else:
        IR_num = 0.
else:
    add_reduction_IR = False
    IR_num = 0.


# Updating contracts with allocation performance
df_summary_allocations = df_allocations[~df_allocations['Type'].isin(
    ["Fonds en Euros"])]
df_summary_allocations = df_summary_allocations.groupby(
    'Numéro contrat')['+/- value (en €)'].sum().reset_index('Numéro contrat')

df_contrats_upd = pd.merge(df_contrats, df_summary_allocations,
                           how='left', left_on='N° de contrat', right_on='Numéro contrat')
df_contrats_upd['Performance embarquée'] = df_contrats_upd[
    'Performance financière en euros (perf du contrat)'] - df_contrats_upd['+/- value (en €)']
df_contrats_upd.rename(
    columns={'+/- value (en €)': 'Performance allocation'}, inplace=True)

# Waterfalls graphics for contracts & Allocation
df_client_waterfall, measure = generate_contrats_waterfall(
    df_contrats_upd, contrat, add_reduction_IR, IR_num)

fig_waterfall_contract = go.Figure(go.Waterfall(
    name="20", orientation="v",
    measure=measure,
    x=df_client_waterfall['variable'],
    textposition="auto",
    text=df_client_waterfall['value'].apply(lambda x: str(int(round(x, 0)))),
    y=df_client_waterfall['value'],
    connector={"line": {"color": "rgb(63, 63, 63)"}},
    cliponaxis=False
))
fig_waterfall_contract.update_layout(
    title="Situation contrat",
    showlegend=False
)
st.plotly_chart(fig_waterfall_contract, use_container_width=True)

df_allocations_waterfall = generate_allocations_waterfall(
    df_allocations, contrat)
fig_waterfall_allocation = go.Figure(go.Waterfall(
    name="20", orientation="v",
    measure=df_allocations_waterfall['measure'],
    x=df_allocations_waterfall['Support'],
    textposition="auto",
    text=df_allocations_waterfall['+/- value (en €)'].apply(
        lambda x: str(int(round(x, 0)))),
    y=df_allocations_waterfall['+/- value (en €)'],
    connector={"line": {"color": "rgb(63, 63, 63)"}},
    cliponaxis=False
))
fig_waterfall_allocation.update_layout(
    title="Performance allocation",
    showlegend=False,
    # plot_bgcolor="#f0f2f6"
)
st.plotly_chart(fig_waterfall_allocation, use_container_width=True)
ss['fig_waterfall_contract'] = fig_waterfall_contract
ss['fig_waterfall_allocation'] = fig_waterfall_allocation

# Historical evolution
# df_contrat_selected est le point de données actuel pour le contrat sélectionné (depuis ss)
# df_contrat_agg contient toutes les données historiques pour tous les contrats (depuis ss)

# 1. Filtrer les données historiques pour le contrat sélectionné
df_historical_for_contract = df_contrat_agg[df_contrat_agg['N° de contrat'] == contrat].copy()

# 2. Les données actuelles pour le contrat sont dans df_contrat_selected (qui vient de ss['df_contrat_selected'])
df_current_for_contract = df_contrat_selected.copy()

# 3. Colonnes nécessaires pour le graphique et la fusion
required_cols = ['N° de contrat', 'Date de valorisation', 'Valorisation', 'Titulaire(s)']

# S'assurer que les deux DataFrames ont ces colonnes
df_historical_for_plot = df_historical_for_contract[required_cols]
df_current_for_plot = df_current_for_contract[required_cols]

# 4. Combiner les données historiques et actuelles
df_combined_plot_data = pd.concat([df_historical_for_plot, df_current_for_plot], ignore_index=True)

# 5. Supprimer les doublons potentiels et trier par date
df_combined_plot_data.drop_duplicates(subset=['N° de contrat', 'Date de valorisation'], inplace=True)
df_combined_plot_data.sort_values(by='Date de valorisation', inplace=True)

# Sauvegarder le nombre de points avant filtrage
points_avant_filtrage = len(df_combined_plot_data)
df_combined_plot_data_filtered = df_combined_plot_data.copy() # Initialiser avec une copie

# 5b. Filtrer les baisses de valorisation > 30%
est_filtre = False
if points_avant_filtrage > 1: # Le filtrage n'a de sens que s'il y a au moins 2 points
    # .pct_change() calcule (actuel - précédent) / précédent
    # Une baisse de 30% est -0.3. On veut garder ce qui est >= -0.3
    variation = df_combined_plot_data_filtered['Valorisation'].pct_change()
    # Le premier point aura NaN pour la variation, on le garde.
    # Les autres points sont gardés si leur variation est >= -0.30
    condition_filtrage = (variation >= -0.30) | variation.isnull()
    df_combined_plot_data_filtered = df_combined_plot_data_filtered[condition_filtrage]

points_apres_filtrage = len(df_combined_plot_data_filtered)

if points_avant_filtrage > points_apres_filtrage:
    est_filtre = True
    points_filtres_count = points_avant_filtrage - points_apres_filtrage
    st.info(f"{points_filtres_count} point(s) de données ont été filtrés en raison d'une baisse de valorisation supérieure à 30% par rapport au point précédent.")


# 6. Créer le graphique
# Déterminer le titulaire à partir du dataframe filtré si possible, sinon du non-filtré
titulaire_pour_titre = ""
if not df_combined_plot_data_filtered.empty and 'Titulaire(s)' in df_combined_plot_data_filtered.columns:
    titulaire_pour_titre = df_combined_plot_data_filtered['Titulaire(s)'].iloc[0]
elif not df_combined_plot_data.empty and 'Titulaire(s)' in df_combined_plot_data.columns: # Fallback au df non filtré
    titulaire_pour_titre = df_combined_plot_data['Titulaire(s)'].iloc[0]

if titulaire_pour_titre:
    fig_evol_title = f"Évolution de la valorisation pour {titulaire_pour_titre} - Contrat {contrat}"
else:
    fig_evol_title = f"Évolution de la valorisation du contrat {contrat}"

if est_filtre:
    fig_evol_title += " (filtrée)"

fig_evol = px.line(df_combined_plot_data_filtered, x='Date de valorisation', y='Valorisation',
                   title=fig_evol_title, markers=True) # Passage à un graphique en ligne avec marqueurs
fig_evol.update_xaxes(title_text='Date de valorisation')
fig_evol.update_yaxes(title_text='Valorisation (€)', tickformat=",.0f")

# Ajouter la ligne horizontale pour le montant total des versements bruts
if 'Montant total des versements bruts' in df_current_for_contract.columns:
    montant_versements_bruts = df_current_for_contract['Montant total des versements bruts'].iloc[0]
    # Ligne pour les versements bruts
    fig_evol.add_hline(y=montant_versements_bruts,
                        line_dash="dash",
                        line_color="red",
                        annotation_text=f"Versements Bruts: {montant_versements_bruts:,.0f} €",
                        annotation_position="bottom right",
                        annotation_font_size=10,
                        annotation_font_color="red")

    # Ligne pour l'effort d'épargne (Versements Nets après avantage fiscal) si c'est un PER et que l'avantage fiscal est ajouté
    if df_contrat_selected.Enveloppe.values[0] == "PER" and add_reduction_IR:
        # Effort d'épargne = Versements Bruts * (1 - TMI)
        # IR_num est déjà défini plus haut dans le script
        effort_epargne = montant_versements_bruts * (1 - IR_num)
        fig_evol.add_hline(y=effort_epargne,
                            line_dash="dash",
                            line_color="blue", # Couleur différente pour la distinction
                            annotation_text=f"Effort d'épargne (après avantage fiscal): {effort_epargne:,.0f} €",
                            annotation_position="top right", # Positionner pour éviter chevauchement
                            annotation_font_size=10,
                            annotation_font_color="blue")

ss['fig_evol'] = fig_evol
st.plotly_chart(fig_evol, use_container_width=True)
