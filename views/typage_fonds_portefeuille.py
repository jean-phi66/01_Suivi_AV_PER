from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit import session_state as ss

from typage_fonds_utils import (
    SIMPLIFIED_CATEGORIES,
    default_support_rules,
    load_typage_config,
    save_typage_config,
    suggest_simplified_category,
)

BASE_DIR = Path(__file__).resolve().parents[1]
MAPPING_PATH = BASE_DIR / "defaults" / "typage_fonds_portefeuille.json"


def _extract_quantalys_categories():
    df_allocations = ss.get("df_allocations")
    if df_allocations is None or not hasattr(df_allocations, "empty") or df_allocations.empty:
        return []
    if "Type" not in df_allocations.columns:
        return []

    categories = (
        df_allocations["Type"]
        .dropna()
        .astype(str)
        .str.strip()
    )
    categories = [category for category in categories.unique().tolist() if category]
    return sorted(categories)


def _build_editor_dataframe(quantalys_categories, loaded_mapping):
    all_categories = sorted(set(quantalys_categories) | set(loaded_mapping.keys()))

    rows = []
    for q_category in all_categories:
        rows.append(
            {
                "Catégorie Quantalys": q_category,
                "Catégorie simplifiée": loaded_mapping.get(
                    q_category,
                    suggest_simplified_category(q_category)
                ),
            }
        )

    return pd.DataFrame(rows)


def _build_rules_dataframe(loaded_rules):
    if not loaded_rules:
        loaded_rules = default_support_rules()
    return pd.DataFrame(loaded_rules)


def _extract_mapping_from_df(df_mapping):
    mapping = {}
    for _, row in df_mapping.iterrows():
        q_category = str(row.get("Catégorie Quantalys", "")).strip()
        s_category = str(row.get("Catégorie simplifiée", "")).strip()

        if not q_category:
            continue
        if s_category not in SIMPLIFIED_CATEGORIES:
            continue

        mapping[q_category] = s_category
    return mapping


def _extract_rules_from_df(df_rules):
    rules = []
    for _, row in df_rules.iterrows():
        keyword = str(row.get("Mot-clé support", "")).strip()
        category = str(row.get("Catégorie simplifiée", "")).strip()
        if not keyword:
            continue
        if category not in SIMPLIFIED_CATEGORIES:
            continue
        rules.append({
            "Mot-clé support": keyword,
            "Catégorie simplifiée": category,
        })
    return rules


st.title("Typage des fonds du portefeuille")
st.write("Associez chaque catégorie Quantalys à une catégorie simplifiée.")

quantalys_categories = _extract_quantalys_categories()
loaded_mapping, loaded_rules = load_typage_config(MAPPING_PATH)

if "typage_fonds_df" not in ss:
    ss["typage_fonds_df"] = _build_editor_dataframe(quantalys_categories, loaded_mapping)
if "typage_fonds_rules_df" not in ss:
    ss["typage_fonds_rules_df"] = _build_rules_dataframe(loaded_rules)

if st.button("Réinitialiser avec proposition par défaut"):
    ss["typage_fonds_df"] = _build_editor_dataframe(quantalys_categories, {})
    ss["typage_fonds_rules_df"] = _build_rules_dataframe(default_support_rules())

editor_df = ss["typage_fonds_df"].copy()
rules_df = ss["typage_fonds_rules_df"].copy()

if editor_df.empty:
    st.warning("Aucune catégorie Quantalys détectée dans les données actuelles.")
else:
    st.caption(f"Fichier de mapping : {MAPPING_PATH.name}")
    st.subheader("Mapping des catégories Quantalys")
    updated_df = st.data_editor(
        editor_df,
        hide_index=True,
        num_rows="fixed",
        column_config={
            "Catégorie Quantalys": st.column_config.TextColumn(
                "Catégorie Quantalys",
                width="large",
                disabled=True,
            ),
            "Catégorie simplifiée": st.column_config.SelectboxColumn(
                "Catégorie simplifiée",
                options=SIMPLIFIED_CATEGORIES,
                width="medium",
                required=True,
            ),
        },
        use_container_width=True,
    )

    st.subheader("Règles de priorité sur le nom du support")
    updated_rules_df = st.data_editor(
        rules_df,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "Mot-clé support": st.column_config.TextColumn(
                "Mot-clé support",
                width="large",
                help="Si le nom du fonds contient ce mot-clé, la catégorie simplifiée est imposée.",
            ),
            "Catégorie simplifiée": st.column_config.SelectboxColumn(
                "Catégorie simplifiée",
                options=SIMPLIFIED_CATEGORIES,
                width="medium",
                required=True,
            ),
        },
        use_container_width=True,
    )

    col_save, col_load = st.columns(2)
    with col_save:
        if st.button("Enregistrer"):
            mapping_to_save = _extract_mapping_from_df(updated_df)
            rules_to_save = _extract_rules_from_df(updated_rules_df)
            saved_mapping, saved_rules = save_typage_config(MAPPING_PATH, mapping_to_save, rules_to_save)
            ss["typage_fonds_df"] = updated_df.copy()
            ss["typage_fonds_rules_df"] = updated_rules_df.copy()
            ss["typage_fonds_mapping"] = saved_mapping
            ss["typage_fonds_support_rules"] = saved_rules
            st.success("Mapping enregistré dans defaults.")

    with col_load:
        if st.button("Charger depuis JSON"):
            reloaded_mapping, reloaded_rules = load_typage_config(MAPPING_PATH)
            ss["typage_fonds_df"] = _build_editor_dataframe(quantalys_categories, reloaded_mapping)
            ss["typage_fonds_rules_df"] = _build_rules_dataframe(reloaded_rules)
            ss["typage_fonds_mapping"] = reloaded_mapping
            ss["typage_fonds_support_rules"] = reloaded_rules
            st.rerun()

    current_mapping = {
        str(row["Catégorie Quantalys"]): str(row["Catégorie simplifiée"])
        for _, row in updated_df.iterrows()
        if str(row["Catégorie Quantalys"]).strip()
    }
    ss["typage_fonds_mapping"] = current_mapping
    ss["typage_fonds_support_rules"] = _extract_rules_from_df(updated_rules_df)
