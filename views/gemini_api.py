import streamlit as st

from gemini_secret import (
    delete_gemini_api_key,
    gemini_api_key_exists,
    load_gemini_api_key,
    save_gemini_api_key,
)


st.title("Clé Gemini")
st.caption("La clé est stockée localement dans un coffre chiffré sous votre dossier utilisateur.")

current_key = load_gemini_api_key()
if current_key:
    st.success("Une clé Gemini est déjà enregistrée.")
else:
    st.info("Aucune clé Gemini n'est enregistrée pour le moment.")

new_key = st.text_input(
    "Clé API Gemini",
    type="password",
    help="La clé est chiffrée avant d'être écrite sur disque. Elle n'est pas stockée dans le dépôt ni dans le code.",
)

col_save, col_delete = st.columns(2)
with col_save:
    save_clicked = st.button("Enregistrer / Mettre à jour", type="primary")
with col_delete:
    delete_clicked = st.button("Supprimer la clé")

if save_clicked:
    try:
        save_gemini_api_key(new_key)
        st.success("Clé Gemini enregistrée dans le coffre local chiffré.")
        st.rerun()
    except Exception as exc:
        st.error(str(exc))

if delete_clicked:
    try:
        delete_gemini_api_key()
        st.success("Clé Gemini supprimée du coffre local chiffré.")
        st.rerun()
    except Exception as exc:
        st.error(str(exc))

with st.expander("Détails techniques", expanded=False):
    st.write("Coffre présent :", "oui" if gemini_api_key_exists() else "non")
    st.write("Clé déchiffrable :", "oui" if current_key else "non")
