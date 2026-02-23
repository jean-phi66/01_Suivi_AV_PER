from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit import session_state as ss

from typage_fonds_utils import load_typage_config, map_simplified_type

st.title("📊 Fonds du portefeuille")

BASE_DIR = Path(__file__).resolve().parents[1]
MAPPING_PATH = BASE_DIR / "defaults" / "typage_fonds_portefeuille.json"

SIMPLIFIED_TYPE_COLORS = {
    "Fonds euros": "#F28E2B",
    "Obligataire": "#4E79A7",
    "Actions": "#E377C2",
    "Allocation flexible": "#9467BD",
    "Immobilier": "#8C564B",
    "Long-Short": "#7F7F7F",
    "Private Equity": "#D62728",
    "Produit structuré": "#2CA02C",
    "Non classé": "#BCBD22",
    "Support non renseigné": "#17BECF",
}


def _build_treemap_simplified(df_source: pd.DataFrame, title: str, height: int = 520):
    if df_source.empty:
        st.info("Aucune donnée disponible pour ce périmètre.")
        return

    treemap_df = (
        df_source.groupby(["Type simplifié", "Support"], dropna=False)["Encours en €"]
        .sum()
        .reset_index()
    )
    treemap_df["Type simplifié"] = treemap_df["Type simplifié"].fillna("Non classé")
    treemap_df["Support"] = treemap_df["Support"].fillna("Support non renseigné")

    fig = px.treemap(
        treemap_df,
        path=["Type simplifié", "Support"],
        values="Encours en €",
        color="Type simplifié",
        color_discrete_map=SIMPLIFIED_TYPE_COLORS,
        title=title,
        hover_data={"Encours en €": ":,.2f"},
    )
    fig.update_traces(
        texttemplate="<b>%{label}</b><br>%{percentParent:.1%}",
        hovertemplate="<b>%{label}</b><br>Encours: %{value:,.2f} €<extra></extra>",
    )
    fig.update_layout(height=height)
    st.plotly_chart(fig, use_container_width=True)


def _build_summary_by_type(df_source: pd.DataFrame, label_col: str):
    if df_source.empty:
        return pd.DataFrame(columns=["Type simplifié", label_col])

    summary = (
        df_source.groupby("Type simplifié", dropna=False)["Encours en €"]
        .sum()
        .reset_index()
        .rename(columns={"Encours en €": label_col})
    )
    return summary


df_allocations = ss["df_allocations"]
df_contrats = ss["df_contrats"]

st.header("🔍 Filtres")
col_filtre1, col_filtre2 = st.columns(2)

with col_filtre1:
    enveloppes_disponibles = sorted(df_contrats["Enveloppe"].dropna().unique())
    enveloppes_selectionnees = st.multiselect(
        "Enveloppe(s)",
        options=enveloppes_disponibles,
        default=enveloppes_disponibles,
        help="Sélectionnez les enveloppes à inclure dans l'analyse",
    )

with col_filtre2:
    partenaires_disponibles = sorted(df_contrats["Partenaire"].dropna().unique())
    partenaires_selectionnes = st.multiselect(
        "Partenaire(s)",
        options=partenaires_disponibles,
        default=partenaires_disponibles,
        help="Sélectionnez les partenaires à inclure dans l'analyse",
    )

if enveloppes_selectionnees and partenaires_selectionnes:
    contrats_filtres = df_contrats[
        (df_contrats["Enveloppe"].isin(enveloppes_selectionnees))
        & (df_contrats["Partenaire"].isin(partenaires_selectionnes))
    ]

    numeros_contrats_filtres = contrats_filtres["N° de contrat"].unique()
    df_allocations = df_allocations[
        df_allocations["Numéro contrat"].isin(numeros_contrats_filtres)
    ].copy()

    if df_allocations.empty:
        st.warning("⚠️ Aucun contrat ne correspond aux filtres sélectionnés")
        st.stop()
else:
    st.warning("⚠️ Veuillez sélectionner au moins une enveloppe et un partenaire")
    st.stop()

mapping_simplifie, support_rules = load_typage_config(MAPPING_PATH)
df_allocations["Type simplifié"] = df_allocations.apply(
    lambda row: map_simplified_type(
        row.get("Type"),
        row.get("Support"),
        mapping_simplifie,
        support_rules,
    ),
    axis=1,
)

df_allocations = df_allocations.merge(
    contrats_filtres[["N° de contrat", "Enveloppe"]].drop_duplicates(),
    left_on="Numéro contrat",
    right_on="N° de contrat",
    how="left",
)
df_allocations.drop(columns=["N° de contrat"], inplace=True)

tab_typologie, tab_analyse = st.tabs([
    "Typologie simplifiée",
    "Analyse détaillée des fonds",
])

with tab_typologie:
    st.header("Répartition par types simplifiés")

    col_metric1, col_metric2, col_metric3 = st.columns(3)
    with col_metric1:
        st.metric("Encours total", f"{df_allocations['Encours en €'].sum():,.2f} €")
    with col_metric2:
        st.metric("Nombre de contrats", df_allocations["Numéro contrat"].nunique())
    with col_metric3:
        st.metric("Nombre de supports", df_allocations["Support"].nunique())

    _build_treemap_simplified(
        df_allocations,
        "Treemap global - tous contrats",
        height=600,
    )

    av_mask = df_allocations["Enveloppe"].fillna("").str.upper().str.contains("AV|ASSURANCE", regex=True)
    per_mask = df_allocations["Enveloppe"].fillna("").str.upper().str.contains("PER", regex=True)

    df_av = df_allocations[av_mask].copy()
    df_per = df_allocations[per_mask].copy()

    col_av, col_per = st.columns(2)
    with col_av:
        _build_treemap_simplified(df_av, "Treemap AV", height=520)
    with col_per:
        _build_treemap_simplified(df_per, "Treemap PER", height=520)

    st.subheader("Synthèse par type simplifié")
    summary_global = _build_summary_by_type(df_allocations, "Encours global")
    summary_av = _build_summary_by_type(df_av, "Encours AV")
    summary_per = _build_summary_by_type(df_per, "Encours PER")

    summary_df = summary_global.merge(summary_av, on="Type simplifié", how="outer")
    summary_df = summary_df.merge(summary_per, on="Type simplifié", how="outer").fillna(0)

    total_global = summary_df["Encours global"].sum()
    summary_df["Poids global (%)"] = (
        (summary_df["Encours global"] / total_global * 100) if total_global > 0 else 0
    )

    summary_df = summary_df.sort_values("Encours global", ascending=False)
    st.dataframe(
        summary_df,
        column_config={
            "Encours global": st.column_config.NumberColumn("Encours global", format="%.2f €"),
            "Encours AV": st.column_config.NumberColumn("Encours AV", format="%.2f €"),
            "Encours PER": st.column_config.NumberColumn("Encours PER", format="%.2f €"),
            "Poids global (%)": st.column_config.NumberColumn("Poids global (%)", format="%.1f %%"),
        },
        hide_index=True,
        use_container_width=True,
    )

    fig_bar = px.bar(
        summary_df,
        x="Type simplifié",
        y="Encours global",
        title="Encours global par type simplifié",
    )
    st.plotly_chart(fig_bar, use_container_width=True)

with tab_analyse:
    st.divider()
    st.header("Configuration")
    col1, col2 = st.columns(2)

    with col1:
        critere_classement = st.radio(
            "Critère de classement des fonds",
            options=["Nombre d'utilisations", "Encours total"],
            help="Choisissez comment classer les fonds : par nombre de contrats qui les utilisent ou par l'encours total investi",
        )

    with col2:
        n_fonds = st.number_input(
            "Nombre de fonds à afficher séparément",
            min_value=1,
            max_value=50,
            value=10,
            help="Les n fonds les plus représentés selon le critère choisi seront affichés séparément, les autres seront regroupés dans 'Autres'",
        )

    if critere_classement == "Nombre d'utilisations":
        fonds_stats = df_allocations.groupby(["Support", "Code ISIN"]).agg(
            {
                "Numéro contrat": "count",
                "Encours en €": "sum",
                "Type simplifié": "first",
            }
        ).reset_index()

        fonds_stats.rename(columns={"Numéro contrat": "Nb_utilisations"}, inplace=True)
        fonds_stats = fonds_stats.sort_values("Nb_utilisations", ascending=False)

        critere_colonne = "Nb_utilisations"
        critere_label = "Nombre d'utilisations"

    else:
        fonds_stats = df_allocations.groupby(["Support", "Code ISIN"]).agg(
            {
                "Numéro contrat": "count",
                "Encours en €": "sum",
                "Type simplifié": "first",
            }
        ).reset_index()

        fonds_stats.rename(columns={"Numéro contrat": "Nb_utilisations"}, inplace=True)
        fonds_stats = fonds_stats.sort_values("Encours en €", ascending=False)

        critere_colonne = "Encours en €"
        critere_label = "Encours total"

    top_n_fonds = fonds_stats.head(n_fonds).copy()
    autres_fonds = fonds_stats.iloc[n_fonds:].copy()

    encours_total_portefeuille = fonds_stats["Encours en €"].sum()
    encours_fonds_selectionnes = top_n_fonds["Encours en €"].sum()
    ratio_encours_selectionnes = (
        encours_fonds_selectionnes / encours_total_portefeuille * 100
        if encours_total_portefeuille > 0
        else 0
    )

    st.header("Vue d'ensemble")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Nombre total de fonds", len(fonds_stats))

    with col2:
        st.metric("Encours fonds sélectionnés", f"{encours_fonds_selectionnes:,.2f} €")

    with col3:
        st.metric("Ratio vs encours total", f"{ratio_encours_selectionnes:.1f}%")

    with col4:
        st.metric("Nombre de contrats", df_allocations["Numéro contrat"].nunique())

    treemap_data = []

    if critere_classement == "Nombre d'utilisations":
        total_valeur = fonds_stats["Nb_utilisations"].sum()
    else:
        total_valeur = fonds_stats["Encours en €"].sum()

    for _, fonds in top_n_fonds.iterrows():
        valeur = fonds[critere_colonne]
        pourcentage = (valeur / total_valeur * 100) if total_valeur > 0 else 0

        type_fonds = fonds["Type simplifié"] if pd.notna(fonds["Type simplifié"]) else "Non classé"

        treemap_data.append(
            {
                "Support": fonds["Support"],
                "Code ISIN": fonds["Code ISIN"],
                "Type_fonds": type_fonds,
                "Nom_fonds": fonds["Support"],
                "Valeur": valeur,
                "Pourcentage": pourcentage,
                "Encours": fonds["Encours en €"],
                "Nb_utilisations": fonds["Nb_utilisations"],
                "Type simplifié": type_fonds,
            }
        )

    if len(autres_fonds) > 0:
        valeur_autres = autres_fonds[critere_colonne].sum()
        pourcentage_autres = (valeur_autres / total_valeur * 100) if total_valeur > 0 else 0

        treemap_data.append(
            {
                "Support": "Autres fonds",
                "Code ISIN": "N/A",
                "Type_fonds": "Non sélectionnés",
                "Nom_fonds": f"{len(autres_fonds)} autres fonds",
                "Valeur": valeur_autres,
                "Pourcentage": pourcentage_autres,
                "Encours": autres_fonds["Encours en €"].sum(),
                "Nb_utilisations": autres_fonds["Nb_utilisations"].sum(),
                "Type simplifié": "Divers",
            }
        )

    treemap_df = pd.DataFrame(treemap_data)

    st.header(f"Répartition des {n_fonds} fonds les plus représentés")

    fig_treemap = px.treemap(
        treemap_df,
        path=["Type_fonds", "Nom_fonds"],
        values="Valeur",
        title=f"Treemap des fonds par {critere_label.lower()} (regroupés par type)",
        hover_data={
            "Encours": ":,.2f",
            "Nb_utilisations": True,
            "Pourcentage": ":.1f",
            "Type simplifié": True,
        },
    )

    if critere_classement == "Nombre d'utilisations":
        fig_treemap.update_traces(
            hovertemplate="<b>%{label}</b><br>"
            + f"{critere_label}: %{{value}}<br>"
            + "Pourcentage: %{customdata[2]:.1f}%<br>"
            + "Encours: %{customdata[0]:,.2f} €<br>"
            + "Utilisations: %{customdata[1]}<br>"
            + "Type: %{customdata[3]}<extra></extra>",
            customdata=treemap_df[["Encours", "Nb_utilisations", "Pourcentage", "Type simplifié"]].values,
            texttemplate="<b>%{label}</b><br>%{customdata[2]:.1f}%",
        )
    else:
        fig_treemap.update_traces(
            hovertemplate="<b>%{label}</b><br>"
            + f"{critere_label}: %{{value:,.2f}} €<br>"
            + "Pourcentage: %{customdata[2]:.1f}%<br>"
            + "Utilisations: %{customdata[1]}<br>"
            + "Type: %{customdata[3]}<extra></extra>",
            customdata=treemap_df[["Encours", "Nb_utilisations", "Pourcentage", "Type simplifié"]].values,
            texttemplate="<b>%{label}</b><br>%{customdata[2]:.1f}%",
        )

    fig_treemap.update_layout(height=600)
    st.plotly_chart(fig_treemap, use_container_width=True)

    st.header(f"Détail des {n_fonds} fonds les plus représentés")
    st.dataframe(
        top_n_fonds,
        column_config={
            "Support": "Nom du fonds",
            "Code ISIN": "Code ISIN",
            "Encours en €": st.column_config.NumberColumn("Encours total", format="%.2f €"),
            "Nb_utilisations": st.column_config.NumberColumn("Nb d'utilisations", format="%d"),
            "Type simplifié": "Type simplifié",
        },
        hide_index=True,
        use_container_width=True,
    )

    st.header("🔽 Export des codes ISIN")
    st.subheader("Filtre par type de fonds")

    types_disponibles = sorted(
        [t if pd.notna(t) else "Non classé" for t in top_n_fonds["Type simplifié"].unique()]
    )
    types_selectionnes = st.multiselect(
        "Types de fonds à inclure dans l'export",
        options=types_disponibles,
        default=types_disponibles,
        help="Désélectionnez les types de fonds que vous souhaitez exclure de l'export des codes ISIN",
    )

    top_n_fonds_temp = top_n_fonds.copy()
    top_n_fonds_temp["Type_clean"] = top_n_fonds_temp["Type simplifié"].apply(
        lambda x: x if pd.notna(x) else "Non classé"
    )

    if types_selectionnes:
        fonds_filtres = top_n_fonds_temp[top_n_fonds_temp["Type_clean"].isin(types_selectionnes)]
    else:
        fonds_filtres = pd.DataFrame()

    codes_isin = fonds_filtres["Code ISIN"].dropna().tolist()
    codes_isin_str = "; ".join(codes_isin)

    if types_selectionnes:
        st.subheader(f"Codes ISIN des {len(codes_isin)} fonds sélectionnés")

        if len(fonds_filtres) > 0:
            st.text_area(
                "Codes ISIN (séparés par des point-virgules)",
                value=codes_isin_str,
                height=150,
                help="Sélectionnez tout le texte (Ctrl+A) puis copiez (Ctrl+C / Cmd+C)",
            )
            with st.expander("📊 Statistiques détaillées"):
                col1, col2 = st.columns(2)
                with col1:
                    st.write("**Répartition par type :**")
                    repartition_types = fonds_filtres["Type simplifié"].value_counts()
                    for type_fonds, count in repartition_types.items():
                        st.write(f"- {type_fonds}: {count} fonds")

                with col2:
                    st.write("**Statistiques :**")
                    st.write(f"- Encours total: {fonds_filtres['Encours en €'].sum():,.2f} €")
                    st.write(f"- Codes ISIN disponibles: {len(codes_isin)}")
                    codes_manquants = len(fonds_filtres) - len(codes_isin)
                    if codes_manquants > 0:
                        st.write(f"- Codes ISIN manquants: {codes_manquants}")
    else:
        st.warning(
            "⚠️ Aucun type de fonds sélectionné. Choisissez au moins un type pour générer l'export."
        )

    if len(autres_fonds) > 0:
        with st.expander(f"📋 Détail des {len(autres_fonds)} autres fonds"):
            st.dataframe(
                autres_fonds,
                column_config={
                    "Support": "Nom du fonds",
                    "Code ISIN": "Code ISIN",
                    "Encours en €": st.column_config.NumberColumn("Encours total", format="%.2f €"),
                    "Nb_utilisations": st.column_config.NumberColumn("Nb d'utilisations", format="%d"),
                    "Type simplifié": "Type simplifié",
                },
                hide_index=True,
                use_container_width=True,
            )

            st.write("**Statistiques des 'Autres' :**")
            st.write(f"- Nombre de fonds : {len(autres_fonds)}")
            st.write(f"- Encours total : {autres_fonds['Encours en €'].sum():,.2f} €")
            st.write(f"- Utilisations totales : {autres_fonds['Nb_utilisations'].sum()}")
