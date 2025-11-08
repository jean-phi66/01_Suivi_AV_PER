import streamlit as st
from streamlit import session_state as ss

import locale
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

df_contrats = ss['df_contrats']
df_allocations = ss['df_allocations']

locale.setlocale(locale.LC_ALL, '')
# st.dataframe(df_contrats)

col_metric, col_ventilation_enveloppe = st.columns(2)
st.dataframe(
    df_contrats,
    column_config={
        "Valorisation": st.column_config.NumberColumn(format="%.0f €"),
        "Montant total des versements bruts": st.column_config.NumberColumn(format="%.0f €"),
        "Montant total des versements nets": st.column_config.NumberColumn(format="%.0f €"),
        "Performance financière en euros (perf du contrat)": st.column_config.NumberColumn(format="%.0f €"),
        "Montant total des rachats bruts": st.column_config.NumberColumn(format="%.0f €"),
    }
)

total_encours = df_contrats['Valorisation'].sum()
#        total_encours_str = str(total_encours).format(1234567890) + '€'
total_encours = np.round(total_encours, 0)
total_encours_str = '{:,}'.format(
    total_encours).replace(',', ' ') + '€'

ventilation_encours = df_contrats.groupby(['Enveloppe'], as_index=False).agg({
    "Valorisation": ['sum']})  # .reset_index()
ventilation_encours = df_contrats[['Enveloppe',
                                   'Montant total des versements bruts',
                                   'Montant total des versements nets', 'Valorisation']].groupby(['Enveloppe'], as_index=False).agg('sum')
ventilation_encours = ventilation_encours.rename(columns={'Montant total des versements bruts': 'Versements bruts',
                                                          'Montant total des versements nets': 'Versements nets'})

# --- DÉBUT BLOC EXCLUSION CONTRATS SANS PERF FINANCIERE POUR WATERFALL ---
st.subheader("🔍 Filtrage pour Waterfall Contrat Global")
contrats_perf_nan = df_contrats[df_contrats['Performance financière en euros (perf du contrat)'].isnull()]
if not contrats_perf_nan.empty:
    st.warning(
        f"{len(contrats_perf_nan)} contrat(s) ont une performance financière non renseignée et seront exclus du waterfall global :"
    )
    st.dataframe(contrats_perf_nan[[
        'Titulaire(s)', 'N° de contrat', 'Enveloppe', 'Partenaire',
        'Montant total des versements nets', 'Performance financière en euros (perf du contrat)', 'Valorisation'
    ]])
else:
    st.info("Tous les contrats ont une performance financière renseignée pour le waterfall global.")

df_contrats_pour_waterfall = df_contrats.dropna(subset=['Performance financière en euros (perf du contrat)'])
# --- FIN BLOC EXCLUSION CONTRATS SANS PERF FINANCIERE POUR WATERFALL ---

# Calculs pour le Waterfall Contrat Global (déplacés ici pour être utilisés avant l'expander de débogage si besoin)
sum_versements_bruts = df_contrats_pour_waterfall['Montant total des versements bruts'].sum()
sum_versements_nets = df_contrats_pour_waterfall['Montant total des versements nets'].sum()
sum_valorisation = df_contrats_pour_waterfall['Valorisation'].sum()
sum_perf_financiere = df_contrats_pour_waterfall['Performance financière en euros (perf du contrat)'].sum()
sum_rachats_bruts = df_contrats_pour_waterfall['Montant total des rachats bruts'].sum()

aggregation_contrat = pd.DataFrame() # Initialisation
if not df_contrats_pour_waterfall.empty:
    aggregation_contrat = df_contrats_pour_waterfall[['Montant total des versements bruts',
                                       'Montant total des versements nets', 'Valorisation',
                                       'Performance financière en euros (perf du contrat)',
                                       'Montant total des rachats bruts'
                                       ]].sum().to_frame().transpose()
    aggregation_contrat['Frais'] = aggregation_contrat['Montant total des versements bruts'] - \
        aggregation_contrat['Montant total des versements nets']
    aggregation_contrat['Frais'] = - aggregation_contrat['Frais']
    aggregation_contrat['Rachats'] = -aggregation_contrat['Montant total des rachats bruts']
    aggregation_contrat['Solde Net Mouvements'] = aggregation_contrat['Montant total des versements nets'] + aggregation_contrat['Rachats']

    perfo_allocation = df_allocations[~df_allocations['Type'].isin(
        ["Fonds en Euros", "Trésorerie Régulière"])]['+/- value (en €)'].sum()
    aggregation_contrat['Performance allocation'] = perfo_allocation

    if 'Performance financière en euros (perf du contrat)' in aggregation_contrat.columns and 'Performance allocation' in aggregation_contrat.columns:
        aggregation_contrat['Performance embarquée'] = aggregation_contrat[
            'Performance financière en euros (perf du contrat)'] - aggregation_contrat['Performance allocation']
    else:
        aggregation_contrat['Performance embarquée'] = 0 # Fallback si une colonne manque

    # Sélection finale des colonnes pour le waterfall
    aggregation_contrat = aggregation_contrat.reindex(columns=['Montant total des versements bruts',
                                               'Frais',
                                               'Montant total des versements nets',
                                               'Rachats',
                                               'Solde Net Mouvements',
                                               'Performance embarquée',
                                               'Performance allocation',
                                               'Valorisation'], fill_value=0)

# --- FIN DES CALCULS PRÉPARATOIRES POUR LE WATERFALL ---

# Affichage du Waterfall Contrat Global
if not aggregation_contrat.empty:
    aggregation_contrat_melted = pd.melt(aggregation_contrat)
    aggregation_contrat_melted['variable'] = aggregation_contrat_melted['variable'].str.replace('Montant total des versements bruts',
                                                                                  'Versements bruts')
    aggregation_contrat_melted['variable'] = aggregation_contrat_melted['variable'].str.replace('Montant total des versements nets',
                                                                                  'Versements nets')
    # Pas besoin de remplacer 'Rachats' ou 'Solde Net Mouvements' si les noms de colonnes sont déjà corrects

    # Mise à jour de la liste 'measure' pour inclure les nouvelles étapes
    measure = ["relative", "relative", "total",  # VB, Frais -> VN
               "relative", "total",              # Rachats -> SNM
               "relative", "relative", "total"]  # PE, PA -> Valorisation
    fig_waterfall_aggregation_contract = go.Figure(go.Waterfall(
        name="20", orientation="v",
        measure=measure,
        x=aggregation_contrat_melted['variable'],
        textposition="auto",
        text=aggregation_contrat_melted['value'].apply(lambda x: f"{round(x, 0):,.0f} €".replace(',', ' ')),
        y=aggregation_contrat_melted['value'],
        connector={"line": {"color": "rgb(63, 63, 63)"}},
        cliponaxis=False
    ))
    fig_waterfall_aggregation_contract.update_layout(
        title="Situation contrat (basée sur les contrats avec performance financière renseignée)",
        showlegend=False
    )
    st.plotly_chart(fig_waterfall_aggregation_contract, use_container_width=True)
else:
    st.info("Le graphique Waterfall de la situation contrat ne peut pas être généré car aucun contrat ne dispose des données de performance financière nécessaires après filtrage.")


# ventilation_encours['Performance embarquée'] = ventilation_encours[
#    'Performance financière en euros (perf du contrat)'] - ventilation_encours['+/- value (en €)']


fig_pie_enveloppe = px.pie(ventilation_encours,
                           values='Valorisation', names='Enveloppe', hole=.5)
fig_pie_enveloppe.update_layout(
    title="Ventilation par Enveloppe fiscale")
fig_pie_enveloppe.update_traces(
    texttemplate='%{value:,.0f}€ (%{percent})',
    hovertemplate='<b>%{label}</b><br>Valorisation: %{value:,.0f}€<br>Pourcentage: %{percent}<extra></extra>'
)

with col_metric:
    st.metric(label="En cours sous gestion", value=total_encours_str)
    st.dataframe(
        ventilation_encours,
        hide_index=True,
        column_config={
            "Versements bruts": st.column_config.NumberColumn(format="%.0f €"),
            "Versements nets": st.column_config.NumberColumn(format="%.0f €"),
            "Valorisation": st.column_config.NumberColumn(format="%.0f €"),
        })
with col_ventilation_enveloppe:
    st.plotly_chart(fig_pie_enveloppe)

# Aggregation by support
df_agg_support = df_allocations.groupby(['Support'],
                                        as_index=False)
df_agg_support = df_agg_support.agg(Type=("Type", "first"),
                                    SRI=('SRI', 'first'),
                                    Prestation=('Prestation', 'first'),
                                    Nombre_de_lignes=(
                                        'Prestation', 'count'),
                                    Encours_total=(
                                        "Encours en €", "sum"),
                                    Encours_moyen=(
                                        'Encours en €', 'mean'),
                                    plus_value_totale=('+/- value (en €)', 'sum'))
df_agg_support['plus_value (en %)'] = np.round(
    df_agg_support['plus_value_totale'] / df_agg_support['Encours_total'] * 100, 2)

fig_sunb = px.sunburst(df_agg_support,
                        # path= ['Type', 'SRI', 'Support'],
                        path=['Type', 'Support'],
                        values='Encours_total')
fig_sunb.update_traces(
    insidetextorientation='radial',
    hovertemplate='<b>%{label}</b><br>Encours total: %{value:,.0f}€<extra></extra>'
)
st.plotly_chart(fig_sunb)


# Préparation des données pour le waterfall des performances par support
df_supports_perf = df_agg_support[~df_agg_support['Type'].isin(
    ["Fonds en Euros", "Trésorerie Régulière"]
)].copy()

# Trier les supports par leur performance (plus_value_totale)
df_supports_perf = df_supports_perf.sort_values(by=['plus_value_totale'])

# Calculer la ligne "Total"
total_plus_value = df_supports_perf['plus_value_totale'].sum()
total_row = pd.DataFrame({
    'Support': ['Total'],
    'plus_value_totale': [total_plus_value],
    # Autres colonnes pourraient être ajoutées ici si nécessaire pour le hovertemplate, etc.
    # Pour ce graphique, 'Type' et autres ne sont pas directement utilisés pour la ligne Total.
})

# Concaténer les supports triés avec la ligne "Total" à la fin
df_waterfall_data = pd.concat([df_supports_perf, total_row], ignore_index=True)

# Définir les mesures pour le waterfall
df_waterfall_data['measure'] = 'relative'
df_waterfall_data.loc[df_waterfall_data['Support'] == 'Total', 'measure'] = 'total'

fig_waterfall_agg_support = go.Figure(go.Waterfall(
    name="20", orientation="v",
    measure=df_waterfall_data['measure'],
    x=df_waterfall_data['Support'],
    textposition="auto",
    text=df_waterfall_data['plus_value_totale'].apply(lambda x: f"{round(x, 0):,.0f} €".replace(',', ' ')),
    y=df_waterfall_data['plus_value_totale'],
    connector={"line": {"color": "rgb(63, 63, 63)"}},
    cliponaxis=False
))
fig_waterfall_agg_support.update_layout(
    title="Performance allocation",
    showlegend=False,
    # plot_bgcolor="#f0f2f6"
)
st.plotly_chart(fig_waterfall_agg_support, use_container_width=True)


st.divider()

# --- START: Analyse Statistique des Performances des Contrats ---
st.header("Analyse Statistique des Performances des Contrats")

# Créer une copie pour les calculs afin de ne pas modifier le df original
df_kpis = df_contrats.copy()

# --- Calcul des KPIs pour tous les contrats ---

# 1. TRA (Taux de Rendement Annuel)
# S'assurer que les colonnes de date sont au format datetime
df_kpis['Ouverture_dt'] = pd.to_datetime(df_kpis['Ouverture'], errors='coerce')
df_kpis['Date_valorisation_dt'] = pd.to_datetime(df_kpis['Date de valorisation'], errors='coerce')

# Calculer la durée en années
df_kpis['duree_annees'] = (df_kpis['Date_valorisation_dt'] - df_kpis['Ouverture_dt']).dt.days / 365.25

# Conditions pour un calcul valide du TRA
conditions_tra = (
    (df_kpis['duree_annees'] > 0) &
    (df_kpis['Montant total des versements nets'] > 0) &
    (df_kpis['Valorisation'] > 0) & (df_kpis['Montant total des rachats bruts'] == 0)
)

conditions_hist = (
    #(df_kpis['duree_annees'] > 0) &
    (df_kpis['Montant total des versements nets'] > 0) &
    (df_kpis['Valorisation'] > 0) & (df_kpis['Montant total des rachats bruts'] == 0)
)


# Calculer le TRA en utilisant np.where pour gérer les cas non valides
df_kpis['TRA'] = np.where(
    conditions_tra,
    ((df_kpis['Valorisation'] / df_kpis['Montant total des versements nets'])**(1 / df_kpis['duree_annees']) - 1) * 100,
    np.nan  # Utiliser NaN pour les cas où le calcul n'est pas possible
)

# 2. Performance par rapport aux versements
# Perf / VB (%)
df_kpis['Perf_vs_VB_pct'] = np.where(
    #df_kpis['Montant total des versements bruts'] > 0,
    conditions_hist,
    ((df_kpis['Valorisation'] - df_kpis['Montant total des versements bruts']) / df_kpis['Montant total des versements bruts']) * 100,
    np.nan
)

# Perf / VN (%)
df_kpis['Perf_vs_VN_pct'] = np.where(
    #df_kpis['Montant total des versements nets'] > 0,
    conditions_hist,
    ((df_kpis['Valorisation'] - df_kpis['Montant total des versements nets']) / df_kpis['Montant total des versements nets']) * 100,
    np.nan
)

# Sélectionner et renommer les colonnes pour l'affichage
df_kpis_display = df_kpis[[
    'Titulaire(s)', 'N° de contrat', 'Enveloppe', 'Valorisation', 'duree_annees',
    'TRA', 'Perf_vs_VB_pct', 'Perf_vs_VN_pct'
]].rename(columns={
    'duree_annees': 'Ancienneté (années)',
    'TRA': 'TRA (%)',
    'Perf_vs_VB_pct': 'Performance / VB (%)',
    'Perf_vs_VN_pct': 'Performance / VN (%)'
})

st.subheader("Tableau des KPIs par contrat")
st.dataframe(df_kpis_display.style.format({
    'Valorisation': "{:,.0f} €",
    'Ancienneté (années)': "{:.1f}",
    'TRA (%)': "{:.2f}%",
    'Performance / VB (%)': "{:.2f}%",
    'Performance / VN (%)': "{:.2f}%"
}, na_rep='N/A'))


st.subheader("Distributions statistiques des KPIs")
fig_hist_tra = px.histogram(df_kpis_display.dropna(subset=['TRA (%)']), x='TRA (%)', title='Distribution du TRA (Taux de Rendement Annuel) des contrats', nbins=30)
st.plotly_chart(fig_hist_tra, use_container_width=True)

fig_hist_perf_vn = px.histogram(df_kpis_display.dropna(subset=['Performance / VN (%)']), x='Performance / VN (%)', title='Distribution de la Performance vs Versements Nets (%)', nbins=30)
st.plotly_chart(fig_hist_perf_vn, use_container_width=True)

fig_box_tra_env = px.box(df_kpis_display.dropna(subset=['TRA (%)']), x='Enveloppe', y='TRA (%)', title='Distribution du TRA par type d\'enveloppe', points='all', color='Enveloppe')
st.plotly_chart(fig_box_tra_env, use_container_width=True)

fig_perf_anciennete = px.scatter(
    df_kpis_display.dropna(subset=["Performance / VN (%)", "Ancienneté (années)"]),
    x="Ancienneté (années)",
    y="Performance / VN (%)",
    color="Enveloppe",
    hover_data=['Titulaire(s)', 'N° de contrat', 'Valorisation'],
    title="Performance / Versements Nets en fonction de l'ancienneté du contrat"
)
fig_perf_anciennete.update_layout(xaxis_title="Ancienneté du contrat (années)", yaxis_title="Performance / Versements Nets (%)")
st.plotly_chart(fig_perf_anciennete, use_container_width=True)
# --- END: Analyse Statistique des Performances des Contrats ---

# --- DÉBUT SECTION DE DÉBOGAGE (DANS UN EXPANDER) ---
with st.expander("🔍 Section de Débogage"):
    st.subheader("Débogage Waterfall Contrat Global")

    # BLOC DE DÉBOGAGE 1 (Sommes et vérification égalité)
    st.write("**Informations Générales et Vérification de Cohérence**")
    if not df_contrats_pour_waterfall.empty:
        st.write("Sommes pour le waterfall (basées sur les contrats avec performance financière renseignée):")
        st.write(f"- Total Versements Bruts: {sum_versements_bruts:,.0f} €")
        st.write(f"- Total Versements Nets: {sum_versements_nets:,.0f} €")
        st.write(f"- Total Rachats Bruts (valeur absolue): {sum_rachats_bruts:,.0f} €")
        st.write(f"- Total Performance Financière: {sum_perf_financiere:,.0f} €")
        st.write(f"- Total Valorisation: {sum_valorisation:,.0f} €")

        attendu_valorisation = sum_versements_nets - sum_rachats_bruts + sum_perf_financiere
        difference = sum_valorisation - attendu_valorisation
        st.write(f"Vérification équation: Versements Nets ({sum_versements_nets:,.0f} €) - Rachats Bruts ({sum_rachats_bruts:,.0f} €) + Perf. Financière ({sum_perf_financiere:,.0f} €) = {attendu_valorisation:,.0f} €")
        st.write(f"Comparaison avec Valorisation réelle ({sum_valorisation:,.0f} €) : Différence = {difference:,.0f} €")
        if abs(difference) > 0.01:
            st.warning(f"L'équation (Versements Nets - Rachats Bruts + Perf. Financière = Valorisation) n'est pas parfaitement vérifiée. Écart: {difference:,.0f}€.")
    else:
        st.write("Aucun contrat avec performance financière renseignée pour calculer les sommes du waterfall.")
    st.divider()

    # BLOC DE DÉBOGAGE SPÉCIFIQUE PERFORMANCE EMBARQUÉE
    st.write("**Calcul Performance Embarquée**")
    if not aggregation_contrat.empty and not df_contrats_pour_waterfall.empty:
        # Recalcul de perfo_allocation ici pour être sûr qu'elle est à jour dans ce contexte
        current_perfo_allocation = df_allocations[~df_allocations['Type'].isin(
            ["Fonds en Euros", "Trésorerie Régulière"])]['+/- value (en €)'].sum()
        
        st.write(f"- Performance financière totale (des contrats inclus): {sum_perf_financiere:,.0f} €")
        st.write(f"- Performance allocation calculée (hors Fonds Euros/Tréso, sur tous les contrats): {current_perfo_allocation:,.0f} €")
        
        # S'assurer que les colonnes existent avant de calculer
        if 'Performance financière en euros (perf du contrat)' in aggregation_contrat.columns and \
           'Performance allocation' in aggregation_contrat.columns:
            
            # Utiliser les valeurs agrégées de aggregation_contrat pour le calcul de la perf embarquée affichée
            agg_sum_perf_financiere = aggregation_contrat['Performance financière en euros (perf du contrat)'].iloc[0]
            agg_perf_allocation = aggregation_contrat['Performance allocation'].iloc[0]
            
            calc_perf_embarquee = agg_sum_perf_financiere - agg_perf_allocation
            st.write(f"- Performance embarquée (calculée pour le waterfall) = {agg_sum_perf_financiere:,.0f} € - {agg_perf_allocation:,.0f} € = {calc_perf_embarquee:,.0f} €")
            
            if 'Performance embarquée' in aggregation_contrat.columns:
                 st.write(f"- Performance embarquée (assignée à aggregation_contrat): {aggregation_contrat['Performance embarquée'].iloc[0]:,.0f} €")
            else:
                st.write("- Colonne 'Performance embarquée' non trouvée dans aggregation_contrat.")
        else:
            st.write("- Colonnes nécessaires pour le calcul de la performance embarquée manquantes dans `aggregation_contrat`.")
    else:
        st.write("Aucune donnée pour calculer la performance embarquée (soit `aggregation_contrat` est vide, soit `df_contrats_pour_waterfall` est vide).")
    st.divider()

    # BLOC DE DÉBOGAGE 2 (aggregation_contrat avant sélection et melt)
    st.write("**`aggregation_contrat` (DataFrame agrégé avant sélection finale des colonnes pour `melt`)**")
    # Afficher une version temporaire de aggregation_contrat avant la sélection finale des colonnes
    if not df_contrats_pour_waterfall.empty:
        temp_aggregation_contrat_debug = df_contrats_pour_waterfall[['Montant total des versements bruts',
                                       'Montant total des versements nets', 'Valorisation',
                                       'Performance financière en euros (perf du contrat)',
                                       'Montant total des rachats bruts'
                                       ]].sum().to_frame().transpose()
        if not temp_aggregation_contrat_debug.empty:
            temp_aggregation_contrat_debug['Frais'] = temp_aggregation_contrat_debug['Montant total des versements bruts'] - temp_aggregation_contrat_debug['Montant total des versements nets']
            temp_aggregation_contrat_debug['Frais'] = - temp_aggregation_contrat_debug['Frais']
            temp_aggregation_contrat_debug['Rachats_calc_debug'] = -temp_aggregation_contrat_debug['Montant total des rachats bruts']
            temp_aggregation_contrat_debug['Solde Net Mouvements_calc_debug'] = temp_aggregation_contrat_debug['Montant total des versements nets'] + temp_aggregation_contrat_debug['Rachats_calc_debug']
            # Recalcul perfo_allocation et perf_embarquee pour ce point de débogage
            current_perfo_allocation_debug = df_allocations[~df_allocations['Type'].isin(["Fonds en Euros", "Trésorerie Régulière"])]['+/- value (en €)'].sum()
            temp_aggregation_contrat_debug['Performance allocation_calc_debug'] = current_perfo_allocation_debug
            temp_aggregation_contrat_debug['Performance embarquée_calc_debug'] = temp_aggregation_contrat_debug['Performance financière en euros (perf du contrat)'] - temp_aggregation_contrat_debug['Performance allocation_calc_debug']
            st.dataframe(temp_aggregation_contrat_debug.style.format("{:,.0f} €", na_rep='-'))
        else:
            st.write("`temp_aggregation_contrat_debug` est vide.")
    else:
        st.write("`df_contrats_pour_waterfall` est vide, impossible de générer `temp_aggregation_contrat_debug`.")
    st.divider()

    # BLOC DE DÉBOGAGE 3 (aggregation_contrat après sélection des colonnes)
    st.write("**`aggregation_contrat` (DataFrame final prêt pour `melt`)**")
    st.dataframe(aggregation_contrat.style.format("{:,.0f} €", na_rep='-'))
    st.divider()

    # BLOC DE DÉBOGAGE 4 (aggregation_contrat_melted)
    if not aggregation_contrat.empty:
        st.write("**`aggregation_contrat_melted` (données finales pour le graphique)**")
        # Le melt est déjà fait plus haut, on réutilise aggregation_contrat_melted
        st.dataframe(aggregation_contrat_melted.style.format({'value': "{:,.0f} €"}, na_rep='-'))
    else:
        st.write("`aggregation_contrat` est vide, donc `aggregation_contrat_melted` n'a pas été généré.")
# --- FIN SECTION DE DÉBOGAGE ---
