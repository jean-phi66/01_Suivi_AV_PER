import json
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit import session_state as ss

BASE_DIR = Path(__file__).resolve().parents[1]
CATALOGUE_PATH = BASE_DIR / "defaults" / "fonds_catalogue.json"


def _load_catalogue():
    if not CATALOGUE_PATH.exists():
        return []
    try:
        with CATALOGUE_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return data


def _save_catalogue(items):
    payload = []
    for item in items:
        name = str(item.get("Nom", "")).strip()
        isin = str(item.get("Code ISIN", "")).strip().upper()
        if not name and not isin:
            continue
        payload.append({"Nom": name, "Code ISIN": isin})
    with CATALOGUE_PATH.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


st.title("Catalogue des fonds")

items = _load_catalogue()
if "catalogue_df" not in ss:
    ss["catalogue_df"] = pd.DataFrame(items)

catalogue_df = ss["catalogue_df"].copy()
if catalogue_df.empty:
    catalogue_df = pd.DataFrame(columns=["Nom", "Code ISIN"])

catalogue_df = catalogue_df[["Nom", "Code ISIN"]]

st.write("Ajoutez, modifiez ou supprimez des fonds disponibles pour l'arbitrage.")
updated_df = st.data_editor(
    catalogue_df,
    hide_index=True,
    num_rows="dynamic",
    column_config={
        "Nom": st.column_config.TextColumn("Nom", width="large"),
        "Code ISIN": st.column_config.TextColumn("Code ISIN", width="medium"),
    },
)

col_save, col_reload = st.columns([1, 1])
with col_save:
    if st.button("Enregistrer"):
        _save_catalogue(updated_df.to_dict(orient="records"))
        ss["catalogue_df"] = updated_df.copy()
        st.success("Catalogue mis a jour.")
with col_reload:
    if st.button("Recharger"):
        ss["catalogue_df"] = pd.DataFrame(_load_catalogue())
        st.rerun()
