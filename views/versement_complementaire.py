import streamlit as st
from streamlit import session_state as ss

import pandas as pd
import plotly.express as px

import os

st.title("Arbitrage")

df_allocations_client = ss['df_allocations_client']
df_contrat_selected = ss['df_contrat_selected']
df_portfolio = ss['df_portfolio']

if "df_allocation_desinvest" not in st.session_state:
    ss.df_allocation_desinvest = pd.DataFrame()


st.write(df_contrat_selected['Titulaire(s)'].iloc[0], '-',
         df_contrat_selected['Enveloppe'].iloc[0], '-',
         df_contrat_selected['Partenaire'].iloc[0], '-',
         df_contrat_selected['N° de contrat'].iloc[0])

Total_VC = st.number_input("Montant du versement complémentaire")

expander_invest = st.expander("Choix des supports")
expander_new_alloc = st.expander("Ré-investissement")

df_allocation_desinvest_mod = df_allocations_client.copy()
df_allocation_desinvest_mod['Ratio désinvestissement'] = 0.
ss['df_allocation_desinvest_mod'] = df_allocation_desinvest_mod

nom_supports = expander_invest.selectbox("Nom du support", df_portfolio['Nom du fonds'].unique(),
                                         index=None)
code_ISIN = expander_invest.selectbox("Code ISIN", df_portfolio['Code ISIN'].unique(),
                                      index=None)

df_portfolio_filtered = df_portfolio[df_portfolio['Nom du fonds'].isin([nom_supports]) |
                                     df_portfolio['Code ISIN'].isin([code_ISIN])]

expander_invest.dataframe(df_portfolio_filtered, hide_index=True)

add_to_invest_button = expander_invest.button(
    "Ajouter", type="primary")

if (add_to_invest_button):
    if 'df_for_invest' not in st.session_state:
        st.session_state['df_for_invest'] = df_portfolio_filtered
    else:
        st.session_state['df_for_invest'] = pd.concat([st.session_state['df_for_invest'],
                                                       df_portfolio_filtered])
# save into session_state
if 'df_for_invest' in st.session_state:
    expander_invest.dataframe(
        st.session_state['df_for_invest'], hide_index=True)

if 'df_for_invest' in st.session_state:
    st.session_state['df_new_alloc'] = st.session_state['df_for_invest'].copy()
    st.session_state['df_new_alloc']['Ratio investissement'] = 0
    st.session_state['df_new_alloc'] = st.session_state['df_new_alloc'][['Nom du fonds',
                                                                         'Code ISIN',
                                                                         'Ratio investissement',
                                                                         'Société de gestion',
                                                                         'SRI',
                                                                         'Catégorie Quantalys',
                                                                         'VL',
                                                                         'Perf 6 mois',
                                                                         'Perf YTD',
                                                                         'Perf cumulée glissante 1 an']]

if ('df_new_alloc' not in st.session_state):
    st.session_state['df_new_alloc'] = pd.DataFrame()

# Nouvelle allocation
st.session_state['df_allocation_invest_mod'] = expander_new_alloc.data_editor(st.session_state["df_new_alloc"],
                                                                              hide_index=True,
                                                                              disabled=['Nom du fonds',
                                                                                        'Code ISIN',
                                                                                        'Société de gestion',
                                                                                        'SRI',
                                                                                        'Catégorie Quantalys',
                                                                                        'VL',
                                                                                        'Perf 6 mois',
                                                                                        'Perf YTD',
                                                                                        'Perf cumulée glissante 1 an'],
                                                                              column_config={
    "Ratio investissement": st.column_config.NumberColumn(
        "Ratio investissement",
        help="Ratio du capital désinvesti à affecter",
        min_value=0,
        max_value=100,
        step=1,
        format="%d %%",
    ),
},
    num_rows="dynamic"
)
expander_new_alloc.write(st.session_state['df_allocation_invest_mod']['Ratio investissement'].sum())
button_MAJ_new_alloc = expander_new_alloc.button("Mise à jour")

expander_new_alloc.write("Nouvelle allocation")
if (button_MAJ_new_alloc):
    df_new_alloc = df_allocation_desinvest_mod
    df_fonds_desinvestis = df_new_alloc[df_new_alloc['Ratio désinvestissement'].astype(float) != 0]
    df_fonds_desinvestis['Ratio désinvestissement'] = df_new_alloc['Ratio désinvestissement'].astype(float)
    
    txt_fonds_desinvestis_to_export = df_fonds_desinvestis[['Support',
                                                            'Code ISIN',
                                                            'Ratio désinvestissement']].to_string(
        header=False,
        index=False,
        formatters={'Ratio désinvestissement': '{:1.0f}%'.format})
    df_new_alloc = df_new_alloc[df_new_alloc['Ratio désinvestissement'].astype(
        float) != 100]
    df_new_alloc['Encours en €'] = df_new_alloc['Encours en €'] * \
        (1. -df_new_alloc['Ratio désinvestissement'].astype(float)/100)
    df_new_alloc = df_new_alloc[[
        'Support', 'Code ISIN', 'Type', 'SRI', 'Encours en €']]
    df_remaining_alloc = df_new_alloc.copy()

    df_new_fonds = st.session_state["df_allocation_invest_mod"][[
        'Nom du fonds', 'Code ISIN', 'Catégorie Quantalys', 'SRI', 'Ratio investissement']]
    df_new_fonds['Montant investi'] = df_new_fonds['Ratio investissement'] * \
        Total_VC / 100
    rename_cols = {'Nom du fonds': 'Support',
                   'Catégorie Quantalys': 'Type', 'Montant investi': 'Encours en €'}
    df_new_fonds.rename(columns=rename_cols, inplace=True)
    txt_new_fonds_to_export = df_new_fonds[['Support',
                                            'Code ISIN',
                                            'Ratio investissement']].to_string(
        header=False,
        index=False,
        formatters={'Ratio investissement': '{:1.0f}%'.format})

    df_new_fonds.drop('Ratio investissement', axis=1, inplace=True)

    # Tech Debt : Merge lines with Same ISIN
    df_new_alloc = pd.concat([df_new_alloc, df_new_fonds])
    df_new_alloc['Type'] = df_new_alloc['Type'].str.replace(
        'Oblig. Euro a echeance', 'Obligations à Echéance', regex=False)
    df_new_alloc['Type'] = df_new_alloc['Type'].str.replace(
        'Fonds à Horizon', 'Obligations à Echéance', regex=False)
    df_new_alloc['Type'] = df_new_alloc['Type'].str.replace(
        'Autres structures', 'Fonds Structurés', regex=False)
    df_new_alloc['Type'][df_new_alloc['Support'] ==
                         'NextStage Croissance A'] = "Capital Risque"
    expander_new_alloc.dataframe(df_new_alloc)

    expander_new_alloc.divider()
    expander_new_alloc.write("Informations pour fiche conseil")
    # Informations pour copier/coller dans fiche conseil
    # [df_contrat_selected['N° de contrat'] == contrat]
    infos_contrat = df_contrat_selected.copy()
    infos_contrat = infos_contrat[[
        'Titulaire(s)', 'Enveloppe', 'Contrat', 'Partenaire', 'N° de contrat']]
    expander_new_alloc.dataframe(infos_contrat, hide_index=True)
    
    
    col_desinvest, col_invest = expander_new_alloc.columns(2)
    with col_desinvest:
        st.write("Supports à désinvestir")
        st.code(txt_fonds_desinvestis_to_export.replace('%', '%' + os.linesep))
    with col_invest:
        st.write("Supports à investir")
        st.code(txt_new_fonds_to_export.replace('%', '%' + os.linesep))
    
    expander_new_alloc.divider()
    expander_new_alloc.write("Comparaison Avant / Après")
    # comparaison avant/aprés
    col_before, col_after = expander_new_alloc.columns(2)
    types_list = df_new_alloc['Type'].unique().tolist()
    c = dict(zip(types_list, px.colors.qualitative.G10))
    supports_list = df_new_alloc['Support'].unique().tolist()
    c_support = dict(zip(supports_list, px.colors.qualitative.G10))

    fig_before = px.pie(df_allocations_client,
                        values='Encours en €', names='Type', color='Type', hole=.5, color_discrete_map=c)
    fig_before.update_layout(
        title="Allocation actuelle")
    fig_after = px.pie(df_new_alloc,
                       values='Encours en €', names='Type', color='Type', hole=.5, color_discrete_map=c)
    fig_after.update_layout(
        title="Nouvelle allocation")

    fig_before_supports = px.pie(df_allocations_client,
                                 values='Encours en €', names='Support', color='Support', hole=.5, color_discrete_map=c_support)
    fig_before_supports.update_layout(
        title="Allocation actuelle")

    fig_after_supports = px.pie(df_new_alloc,
                                values='Encours en €', names='Support', color='Support', hole=.5, color_discrete_map=c_support)
    fig_after_supports.update_layout(
        title="Nouvelle allocation")

    with col_before:
        st.plotly_chart(fig_before, use_container_width=True)
        st.plotly_chart(fig_before_supports, use_container_width=True)
    with col_after:
        st.plotly_chart(fig_after, use_container_width=True)
        st.plotly_chart(fig_after_supports, use_container_width=True)
