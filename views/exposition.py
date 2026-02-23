import streamlit as st
from streamlit import session_state as ss

import pandas as pd
import numpy as np
from report_generator import generate_exposition_filters_pdf

df_allocations = ss['df_allocations']
df_contrats = ss['df_contrats']

# Création des onglets
tab1, tab2 = st.tabs(["Exposition par fonds", "Contrats multi-fonds"])

# Onglet 1 : Code original - Exposition par fonds
with tab1:
    st.header("Exposition par fonds")
    
    fond_expose = st.selectbox('Sélectionner fond',
                                df_allocations.sort_values(by="Support")['Support'].unique())
    df_exposition = df_allocations[df_allocations['Support']
                                    == fond_expose]
    df_exposition = df_exposition[['Nom', 'Prénom', 'Prestation', 'Support',
                                    'Encours en €', '+/- value (en €)',  '+/- value (en %))', 'Numéro contrat']]
    df_contrat_join = df_contrats[['Valorisation', 'N° de contrat']]
    df_exposition = pd.merge(df_exposition, df_contrat_join,
                                how='left', right_on='N° de contrat', left_on='Numéro contrat')
    df_exposition = df_exposition.drop(
        ['N° de contrat', 'Numéro contrat'], axis=1)
    df_exposition['Ratio valorisation [%]'] = np.round(
        df_exposition['Encours en €'] / df_exposition['Valorisation'] * 100, 2)
    st.dataframe(df_exposition)

# Onglet 2 : Nouveau - Contrats contenant des fonds spécifiques
with tab2:
    st.header("Contrats contenant des fonds spécifiques")
    
    # Sélection multiple de fonds
    fonds_disponibles = sorted(df_allocations['Support'].unique())
    fonds_selectionnes = st.multiselect(
        "Sélectionner les fonds à rechercher dans les contrats",
        options=fonds_disponibles,
        help="Sélectionnez un ou plusieurs fonds. Seuls les contrats contenant TOUS ces fonds seront affichés."
    )
    
    if fonds_selectionnes:
        # Trouver les contrats qui contiennent TOUS les fonds sélectionnés
        contrats_avec_fonds = []
        
        for contrat in df_allocations['Numéro contrat'].unique():
            fonds_du_contrat = set(df_allocations[df_allocations['Numéro contrat'] == contrat]['Support'].tolist())
            fonds_recherches = set(fonds_selectionnes)
            
            # Vérifier si le contrat contient tous les fonds recherchés
            if fonds_recherches.issubset(fonds_du_contrat):
                contrats_avec_fonds.append(contrat)
        
        if contrats_avec_fonds:
            # Créer un DataFrame avec les informations des contrats trouvés
            df_contrats_trouves = df_allocations[df_allocations['Numéro contrat'].isin(contrats_avec_fonds)]
            
            # Agrégation par contrat pour avoir les informations de base
            contrats_resume = df_contrats_trouves.groupby('Numéro contrat').agg({
                'Nom': 'first',
                'Prénom': 'first',
                'Prestation': 'first',
                'Support': 'count',  # Nombre total de fonds dans le contrat
                'Encours en €': 'sum'  # Encours total du contrat
            }).reset_index()
            
            # Renommer pour clarté
            contrats_resume.rename(columns={'Support': 'Nombre total de fonds'}, inplace=True)
            
            # Joindre avec les données de valorisation
            df_contrat_join = df_contrats[['Valorisation', 'N° de contrat']]
            contrats_resume = pd.merge(contrats_resume, df_contrat_join,
                                     how='left', right_on='N° de contrat', left_on='Numéro contrat')
            contrats_resume = contrats_resume.drop(['N° de contrat'], axis=1)
            
            # Calculer le ratio d'encours
            contrats_resume['Ratio valorisation [%]'] = np.round(
                contrats_resume['Encours en €'] / contrats_resume['Valorisation'] * 100, 2)
            
            # Trier par encours décroissant
            contrats_resume = contrats_resume.sort_values('Encours en €', ascending=False)
            
            # Calculer l'encours total des fonds sélectionnés uniquement
            encours_fonds_selectionnes_total = df_allocations[
                (df_allocations['Numéro contrat'].isin(contrats_avec_fonds)) & 
                (df_allocations['Support'].isin(fonds_selectionnes))
            ]['Encours en €'].sum()
            
            # Affichage des statistiques
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Contrats trouvés", len(contrats_resume))
            with col2:
                st.metric("Encours fonds sélectionnés", f"{encours_fonds_selectionnes_total:,.2f} €")
            with col3:
                st.metric("Fonds recherchés", len(fonds_selectionnes))
            
            st.dataframe(contrats_resume)

            # Export PDF des résultats de filtres
            with st.container():
                pdf_bytes = generate_exposition_filters_pdf(
                    contrats_resume=contrats_resume,
                    fonds_selectionnes=fonds_selectionnes,
                    df_allocations=df_allocations
                )
                st.download_button(
                    label="Exporter les résultats en PDF",
                    data=pdf_bytes,
                    file_name="Export_Exposition_Filtres.pdf",
                    mime="application/pdf"
                )
            
            # Section pour voir le détail des fonds sélectionnés dans chaque contrat
            st.subheader("Détail des fonds sélectionnés par contrat")
            
            for contrat in contrats_avec_fonds:
                with st.expander(f"Contrat {contrat} - {contrats_resume[contrats_resume['Numéro contrat'] == contrat]['Nom'].iloc[0]} {contrats_resume[contrats_resume['Numéro contrat'] == contrat]['Prénom'].iloc[0]}"):
                    # Afficher seulement les fonds sélectionnés pour ce contrat
                    detail_fonds_selectionnes = df_allocations[
                        (df_allocations['Numéro contrat'] == contrat) & 
                        (df_allocations['Support'].isin(fonds_selectionnes))
                    ]
                    detail_fonds_selectionnes = detail_fonds_selectionnes[['Support', 'Encours en €', '+/- value (en €)', '+/- value (en %))', 'Type', 'SRRI']]
                    detail_fonds_selectionnes = detail_fonds_selectionnes.sort_values('Encours en €', ascending=False)
                    
                    # Calculer le total des encours pour les fonds sélectionnés
                    encours_fonds_selectionnes = detail_fonds_selectionnes['Encours en €'].sum()
                    encours_total_contrat = contrats_resume[contrats_resume['Numéro contrat'] == contrat]['Encours en €'].iloc[0]
                    pourcentage_fonds_selectionnes = (encours_fonds_selectionnes / encours_total_contrat * 100) if encours_total_contrat > 0 else 0
                    
                    st.write(f"**Encours des fonds sélectionnés :** {encours_fonds_selectionnes:,.2f} € ({pourcentage_fonds_selectionnes:.1f}% du contrat)")
                    st.dataframe(detail_fonds_selectionnes, use_container_width=True)
        else:
            st.warning(f"Aucun contrat ne contient tous les fonds sélectionnés : {', '.join(fonds_selectionnes)}")
    else:
        st.info("Sélectionnez un ou plusieurs fonds pour voir les contrats qui les contiennent tous.")
