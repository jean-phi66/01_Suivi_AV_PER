import streamlit as st
from streamlit import session_state as ss

import plotly.express as px

df_allocations = ss['df_allocations']

df_prod_struct = df_allocations[df_allocations['Support'].str.contains(
    'Exceltis', case=False)]
df_prod_struct['for_count'] = 1
#st.dataframe(df_prod_struct)

fig_pie_PS_nombre = px.pie(df_prod_struct,
                            values='for_count', names='Support', hole=.5)
fig_pie_PS_nombre.update_layout(
    title="Ventilation Produit structuré par nombre")
fig_pie_PS_nombre.update_traces(
    hoverinfo='label+percent', textinfo='value')

fig_pie_PS_encours = px.pie(df_prod_struct,
                            values='Encours en €', names='Support', hole=.5)
fig_pie_PS_encours.update_layout(
    title="Ventilation Produit structuré par encours")
fig_pie_PS_encours.update_traces(
    hoverinfo='label+percent', textinfo='value')

col_PS_nombre, col_PS_encours = st.columns(2)

col_PS_nombre.plotly_chart(fig_pie_PS_nombre)
col_PS_encours.plotly_chart(fig_pie_PS_encours)

df_summary_prod_struct = df_prod_struct[['Support',
                                            'Encours en €',
                                            '+/- value (en €)',
                                            '+/- value (en %))']].groupby(['Support']).agg({'Encours en €': ['count', 'sum', 'max'],
                                                                                        '+/- value (en €)': ['sum'],
                                                                                            '+/- value (en %))': ['mean']})
df_summary_prod_struct.columns = [
    ' '.join(str(i) for i in col) for col in df_summary_prod_struct.columns]
df_summary_prod_struct.reset_index(inplace=True)

# Tableau interactif avec sélection
st.subheader("Résumé des produits structurés")

# Ajouter une colonne de sélection
df_with_selection = df_summary_prod_struct.copy()
df_with_selection.insert(0, 'Sélectionner', False)

# Utiliser data_editor avec colonnes configurées
config = {
    'Sélectionner': st.column_config.CheckboxColumn(
        'Sélectionner',
        help="Cochez pour voir les contrats de ce support",
        default=False,
    )
}

edited_df = st.data_editor(
    df_with_selection,
    column_config=config,
    disabled=['Support', 'Encours en € count', 'Encours en € sum', 'Encours en € max', '+/- value (en €) sum', '+/- value (en %)) mean'],
    hide_index=True,
    use_container_width=True,
    key="prod_struct_selector"
)

# Récupérer les lignes sélectionnées
selected_supports = edited_df[edited_df['Sélectionner'] == True]['Support'].tolist()

if selected_supports:
        st.subheader("Contrats concernés")
        
        # Filtrer les données pour les supports sélectionnés
        df_contrats_concernes = df_prod_struct[df_prod_struct['Support'].isin(selected_supports)]
        
        # Afficher les colonnes pertinentes pour les contrats (avec Titulaire et Type en début)
        colonnes_contrats = ['Titulaire(s)', 'Type', 'Contrat', 'Support', 'Encours en €', '+/- value (en €)', '+/- value (en %))']
        # Vérifier que les colonnes existent dans le DataFrame
        colonnes_disponibles = [col for col in colonnes_contrats if col in df_contrats_concernes.columns]
        
        if colonnes_disponibles:
            df_contrats_affichage = df_contrats_concernes[colonnes_disponibles].copy()
            
            # Trier par encours décroissant
            if 'Encours en €' in df_contrats_affichage.columns:
                df_contrats_affichage = df_contrats_affichage.sort_values('Encours en €', ascending=False)
            
            st.dataframe(
                df_contrats_affichage,
                hide_index=True,
                use_container_width=True
            )
            
            # Afficher quelques statistiques
            nb_contrats = len(df_contrats_affichage)
            encours_total = df_contrats_affichage['Encours en €'].sum() if 'Encours en €' in df_contrats_affichage.columns else 0
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Nombre de contrats", nb_contrats)
            with col2:
                st.metric("Encours total", f"{encours_total:,.0f} €")
            with col3:
                # Compter les types de contrats
                if 'Type' in df_contrats_affichage.columns:
                    types_contrats = df_contrats_affichage['Type'].value_counts()
                    types_str = " | ".join([f"{k}: {v}" for k, v in types_contrats.items()])
                    st.metric("Répartition AV/PER", types_str)
        else:
            st.warning("Les colonnes de contrat ne sont pas disponibles dans les données")
else:
    st.info("Sélectionnez une ou plusieurs lignes dans le tableau ci-dessus pour voir les contrats concernés")
