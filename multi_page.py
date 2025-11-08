import streamlit as st

st.set_page_config(layout="wide")

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

test_page = st.Page(
    page = 'views/time_serie.py',
    title = 'TEST',
    icon='🤓'
)

pg = st.navigation({"DONNEES":[data_ingestion_page], 
                    "CLIENT":[client_page, composition_page, perfo_page], 
                    #"OPERATION":[arbitrage_page, VC_page],
                    "PORTEFEUILLE SOUS GESTION":[sous_gestion_page, exposition_page, prod_struct_page], 
                    "Reporting":[ batch_reports_page],
                    #"TEST":[test_page]
                    })
pg.run()