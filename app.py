import streamlit as st
from streamlit import session_state as ss
from config import DEMO_MODE

st.set_page_config(layout="wide")

# Afficher le badge du mode demo si activé
if DEMO_MODE:
    st.warning("🎯 Mode de démonstration activé - Données fictives uniquement")

data_ingestion_page = st.Page(
    page = 'views/data_ingestion.py',
    title = 'Données',
    icon='💾',
    default=True
)

client_page = st.Page(
    page = 'views/client.py',
    title = 'Sélection contrat',
    icon='🗄️'
    )

perfo_page = st.Page(
    page = 'views/perfo.py',
    title = "Performance",
    icon = '📈'
)

batch_reports_page = st.Page(
    page = 'views/batch_reports.py',
    title = "Rapport pdf",
    icon = '🧾'
)

fiche_per_page = st.Page(
    page = 'views/fiche_per.py',
    title = "Arbitrage PER",
    icon = '📝'
)

fiche_av_page = st.Page(
    page = 'views/fiche_av.py',
    title = "Arbitrage AV",
    icon = '📝'
)

composition_page = st.Page(
    page = 'views/composition.py',
    title = "Composition",
    icon = '🩻'
)

#arbitrage_page = st.Page(
#    page = 'views/arbitrage.py',
#    title = "Arbitrage",
#    icon = '✍🏼'
#)
#VC_page = st.Page(
#    page = 'views/versement_complementaire.py',
#    title = "Versement complémentaire",
#    icon = '💶'
#)
sous_gestion_page = st.Page(
    page = 'views/sous_gestion.py',
    title = "Analyse portefeuille",
    icon = '🏛️'
)
exposition_page = st.Page(
    page = 'views/exposition.py',
    title = "Exposition",
    icon = '🔎'
)
prod_struct_page = st.Page(
    page = 'views/prod_struct.py',
    title = "Produits structurés",
    icon = '🧮'
)

fonds_portefeuille_page = st.Page(
    page = 'views/fonds_portefeuille.py',
    title = "Fonds du portefeuille",
    icon = '📊'
)

performance_fonds_page = st.Page(
    page = 'views/performance_fonds.py',
    title = "Perfomance des fonds",
    icon = '📈'
)

catalogue_fonds_page = st.Page(
    page = 'views/fonds_catalogue.py',
    title = "Catalogue des fonds",
    icon = '🗂️'
)

typage_fonds_page = st.Page(
    page = 'views/typage_fonds_portefeuille.py',
    title = "Typage des fonds du portefeuille",
    icon = '🏷️'
)

test_page = st.Page(
    page = 'views/time_serie.py',
    title = 'TEST',
    icon='🤓'
)

show_arbitrage_per = False
show_arbitrage_av = False
df_contrat_selected = ss.get("df_contrat_selected")
if df_contrat_selected is not None and hasattr(df_contrat_selected, "empty") and not df_contrat_selected.empty:
    if "Enveloppe" in df_contrat_selected.columns:
        enveloppe = str(df_contrat_selected["Enveloppe"].iloc[0])
        show_arbitrage_per = enveloppe == "PER"
        upper_env = enveloppe.upper()
        show_arbitrage_av = "AV" in upper_env or "ASSURANCE" in upper_env

nav_items = {
    "DONNEES": [data_ingestion_page],
    "CLIENT": [client_page, composition_page, perfo_page],
    "OPERATIONS": [page for page in [fiche_per_page if show_arbitrage_per else None,
                                      fiche_av_page if show_arbitrage_av else None]
                    if page is not None],
    "PORTEFEUILLE SOUS GESTION": [
        sous_gestion_page,
        exposition_page,
        prod_struct_page,
        fonds_portefeuille_page,
        performance_fonds_page,
    ],
    "PARAMETRES": [catalogue_fonds_page, typage_fonds_page],
    "Reporting": [batch_reports_page],
}

pg = st.navigation(nav_items)
pg.run()