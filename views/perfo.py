from pathlib import Path

import streamlit as st
from streamlit import session_state as ss

import pandas as pd
import numpy as np

from waterfall_graphs import generate_contrats_waterfall, generate_allocations_waterfall
import plotly.graph_objects as go
import plotly.express as px
from tri_integration import load_tri_analyses, pdf_dir_signature, match_tri_analyses_to_contracts, build_contract_tri_history
from reporting_helpers import (
    build_contract_and_class_fund_figures,
    build_evolution_figure,
    build_kpi_overrides,
    build_tri_figure,
    build_tri_history,
    load_latest_fund_perf_file,
    resolve_payment_source,
)
from typage_fonds_utils import load_typage_config, map_simplified_type
from allocation_history import allocation_history_signature, load_allocation_history

BASE_DIR = Path(__file__).resolve().parents[1]
MAPPING_PATH = BASE_DIR / "defaults" / "typage_fonds_portefeuille.json"


def format_pct(value):
    if value is None or pd.isna(value):
        return "N/A"
    return f"{value * 100:.2f}%"


@st.cache_resource(show_spinner=False)
def get_tri_analyses_resource(pdf_signature: tuple = ()):
    # pdf_signature sert de cle de cache : toute modification des PDF invalide le cache.
    return load_tri_analyses()


@st.cache_data(show_spinner=False)
def get_allocation_history(signature: tuple = ()) -> pd.DataFrame:
    # signature = (nom, mtime, taille) des exports : le cache est invalide des qu'un export est ajoute.
    return load_allocation_history()


df_allocations = ss['df_allocations']
df_contrats = ss['df_contrats']
df_contrat_selected = ss['df_contrat_selected']
contrat = ss['contrat']
df_contrat_agg = ss['df_contrat_agg']

st.title("Analyse de la performance")

# Valeurs par defaut reutilisees dans toute la page.
source_versements = "CSV contrats"
montant_versements_bruts = None
montant_versements_nets = None
gross_total = None
net_total = None
source_context = {
    "source_effective": source_versements,
    "gross_used": None,
    "net_used": None,
    "fees_total": None,
    "fees_rate": None,
    "tri_net": None,
    "tri_brut": None,
}

tri_contracts_df, tri_contracts_map = match_tri_analyses_to_contracts(
    get_tri_analyses_resource(pdf_dir_signature()),
    df_contrats[["N° de contrat", "Titulaire(s)", "Enveloppe", "Partenaire"]].drop_duplicates().copy(),
)
tri_analysis = tri_contracts_map.get(str(contrat))

# --- START: KPI Calculations ---
if not df_contrat_selected.empty:
    # Extract data
    valorisation = df_contrat_selected['Valorisation'].iloc[0]
    montant_versements_bruts_csv = df_contrat_selected['Montant total des versements bruts'].iloc[0] if 'Montant total des versements bruts' in df_contrat_selected.columns else 0.0
    montant_versements_nets_csv = df_contrat_selected['Montant total des versements nets'].iloc[0] if 'Montant total des versements nets' in df_contrat_selected.columns else 0.0

    if tri_analysis is not None:
        gross_total = tri_analysis.get("gross_payments_total")
        net_total = tri_analysis.get("net_payments_total")
        if gross_total is not None and net_total is not None and not pd.isna(gross_total) and not pd.isna(net_total):
            gross_total = float(gross_total)
            net_total = float(net_total)

    if tri_analysis is not None and gross_total is not None and net_total is not None and gross_total > 0 and net_total >= 0:
        tolerance_euro = 1.0
        ecart_brut = gross_total - float(montant_versements_bruts_csv)
        ecart_net = net_total - float(montant_versements_nets_csv)
        ecart_detecte = abs(ecart_brut) > tolerance_euro or abs(ecart_net) > tolerance_euro

        if ecart_detecte:
            st.warning(
                (
                    "Ecart detecte entre versements CSV et releves d'operations. "
                    f"Bruts: {ecart_brut:,.0f} EUR | Nets: {ecart_net:,.0f} EUR"
                ).replace(",", " ")
            )
        else:
            st.caption("Versements CSV et releves d'operations coherents (ecart <= 1 EUR).")

        source_versements = st.radio(
            "Source des versements a considerer pour la page",
            options=["CSV contrats", "Releve d'operations TRI"],
            horizontal=True,
            key=f"source_versements_{contrat}",
        )

    source_context = resolve_payment_source(df_contrat_selected, tri_analysis, source_versements)
    montant_versements_bruts = source_context.get("gross_used")
    montant_versements_nets = source_context.get("net_used")
    kpi_data = build_kpi_overrides(df_contrat_selected, source_context)

    # Display KPIs
    st.subheader("Indicateurs Clés de Performance")
    
    col1, col2 = st.columns(2)
    col1.metric("Valorisation", f"{valorisation:,.0f} €".replace(",", " "))
    col2.metric("TRA (estimé)", kpi_data["tra_str"].replace(",", "."))

    col3, col4 = st.columns(2)
    col3.metric("Versements Bruts", kpi_data["montant_versements_bruts_str"])
    col4.metric("Performance / VB (%)", kpi_data["var_vs_brut_pct_str"].replace(",", "."))

    col5, col6 = st.columns(2)
    col5.metric("Versements Nets", kpi_data["montant_versements_nets_kpi_str"])
    col6.metric("Performance / VN (%)", kpi_data["var_vs_net_pct_str"].replace(",", "."))

    st.caption(f"Source des versements retenue pour ces KPI: {source_context['source_effective']}")

    col7, col8 = st.columns(2)
    col7.metric("Frais d'entree estimes", kpi_data["frais_entree_str"])
    col8.metric("Taux frais d'entree estime", kpi_data["taux_frais_str"].replace(",", "."))

    col9, col10 = st.columns(2)
    col9.metric("TRI net", kpi_data["tri_net_str"].replace(",", "."))
    col10.metric("TRI brut", kpi_data["tri_brut_str"].replace(",", "."))
    
    st.divider()
# --- END: KPI Calculations ---

enveloppe_label = str(df_contrat_selected['Enveloppe'].iloc[0]).upper() if (not df_contrat_selected.empty and 'Enveloppe' in df_contrat_selected.columns) else ""
is_per_contract = "PER" in enveloppe_label

if is_per_contract:
    add_reduction_IR = st.checkbox("Ajouter avantage fiscal")
    if add_reduction_IR:
        IR = st.selectbox(
            "Tranche marginale d'imposition",
            ("0%", "11%", "30%", "41%", "45%"), index=2)
        IR_num = float(IR.replace("%", "")) / 100
    else:
        IR_num = 0.
else:
    add_reduction_IR = False
    IR_num = 0.


# Updating contracts with allocation performance
df_summary_allocations = df_allocations[~df_allocations['Type'].isin(
    ["Fonds en Euros"])]
df_summary_allocations = df_summary_allocations.groupby(
    'Numéro contrat')['+/- value (en €)'].sum().reset_index('Numéro contrat')

df_contrats_upd = pd.merge(df_contrats, df_summary_allocations,
                           how='left', left_on='N° de contrat', right_on='Numéro contrat')
df_contrats_upd['Performance embarquée'] = df_contrats_upd[
    'Performance financière en euros (perf du contrat)'] - df_contrats_upd['+/- value (en €)']
df_contrats_upd.rename(
    columns={'+/- value (en €)': 'Performance allocation'}, inplace=True)

# Propager la source choisie au waterfall contrat.
if (
    source_versements == "Releve d'operations TRI"
    and gross_total is not None
    and net_total is not None
    and not pd.isna(gross_total)
    and not pd.isna(net_total)
):
    mask_contrat = df_contrats_upd['N° de contrat'].astype(str) == str(contrat)
    if mask_contrat.any():
        df_contrats_upd.loc[mask_contrat, 'Montant total des versements bruts'] = float(gross_total)
        df_contrats_upd.loc[mask_contrat, 'Montant total des versements nets'] = float(net_total)
        # Convention existante: Frais = -(Bruts - Nets) = Nets - Bruts
        df_contrats_upd.loc[mask_contrat, 'Frais'] = float(net_total) - float(gross_total)
        # Recalculer les performances en coherence avec la source de versements retenue.
        df_contrats_upd.loc[mask_contrat, 'Performance financière en euros (perf du contrat)'] = (
            df_contrats_upd.loc[mask_contrat, 'Valorisation'] - float(net_total)
        )
        df_contrats_upd.loc[mask_contrat, 'Performance embarquée'] = (
            df_contrats_upd.loc[mask_contrat, 'Performance financière en euros (perf du contrat)']
            - df_contrats_upd.loc[mask_contrat, 'Performance allocation']
        )

# Waterfalls graphics for contracts & Allocation
df_client_waterfall, measure = generate_contrats_waterfall(
    df_contrats_upd, contrat, add_reduction_IR, IR_num)

fig_waterfall_contract = go.Figure(go.Waterfall(
    name="20", orientation="v",
    measure=measure,
    x=df_client_waterfall['variable'],
    textposition="auto",
    text=df_client_waterfall['value'].apply(lambda x: str(int(round(x, 0))) if pd.notna(x) else ''),
    y=df_client_waterfall['value'],
    connector={"line": {"color": "rgb(63, 63, 63)"}},
    cliponaxis=False
))
fig_waterfall_contract.update_layout(
    title="Situation contrat",
    showlegend=False
)
st.plotly_chart(fig_waterfall_contract, use_container_width=True)

# Waterfall par typologie simplifiée (entre Situation contrat et Performance allocation)
df_alloc_contrat_all = df_allocations[df_allocations['Numéro contrat'] == contrat].copy()
df_alloc_uc = df_alloc_contrat_all[~df_alloc_contrat_all['Type'].isin(["Fonds en Euros"])].copy()

if not df_alloc_uc.empty and 'Encours en €' in df_alloc_uc.columns and '+/- value (en €)' in df_alloc_uc.columns:
    df_alloc_uc['Encours en €'] = pd.to_numeric(df_alloc_uc['Encours en €'], errors='coerce').fillna(0.0)
    df_alloc_uc['+/- value (en €)'] = pd.to_numeric(df_alloc_uc['+/- value (en €)'], errors='coerce').fillna(0.0)
    if 'Type' not in df_alloc_uc.columns:
        df_alloc_uc['Type'] = 'Support UC'

    mapping_simplifie, support_rules = load_typage_config(MAPPING_PATH)
    df_alloc_uc['Type simplifié'] = df_alloc_uc.apply(
        lambda row: map_simplified_type(row.get('Type'), row.get('Support'), mapping_simplifie, support_rules),
        axis=1,
    )

    df_typo_wf = (
        df_alloc_uc.groupby('Type simplifié', as_index=False)
        .agg({'Encours en €': 'sum', '+/- value (en €)': 'sum'})
        .sort_values('Encours en €', ascending=False)
    )
    df_typo_wf['measure'] = 'relative'
    df_typo_wf_total = pd.DataFrame(
        [
            {
                'Type simplifié': 'Total',
                'Encours en €': float(df_typo_wf['Encours en €'].sum()),
                '+/- value (en €)': float(df_typo_wf['+/- value (en €)'].sum()),
                'measure': 'total',
            }
        ]
    )
    df_typo_wf = pd.concat([df_typo_wf, df_typo_wf_total], ignore_index=True)

    fig_waterfall_typologie = go.Figure(
        go.Waterfall(
            name="20",
            orientation="v",
            measure=df_typo_wf['measure'],
            x=df_typo_wf['Type simplifié'],
            textposition="auto",
            text=df_typo_wf['+/- value (en €)'].apply(lambda x: str(int(round(x, 0))) if pd.notna(x) else ''),
            y=df_typo_wf['+/- value (en €)'],
            connector={"line": {"color": "rgb(63, 63, 63)"}},
            cliponaxis=False,
        )
    )
    fig_waterfall_typologie.update_layout(
        title="Performance allocation par typologie simplifiée",
        showlegend=False,
    )
    st.plotly_chart(fig_waterfall_typologie, use_container_width=True)
    ss['fig_waterfall_typologie'] = fig_waterfall_typologie

df_allocations_waterfall = generate_allocations_waterfall(
    df_allocations, contrat)
fig_waterfall_allocation = go.Figure(go.Waterfall(
    name="20", orientation="v",
    measure=df_allocations_waterfall['measure'],
    x=df_allocations_waterfall['Support'],
    textposition="auto",
    text=df_allocations_waterfall['+/- value (en €)'].apply(
        lambda x: str(int(round(x, 0)))),
    y=df_allocations_waterfall['+/- value (en €)'],
    connector={"line": {"color": "rgb(63, 63, 63)"}},
    cliponaxis=False
))
fig_waterfall_allocation.update_layout(
    title="Performance allocation",
    showlegend=False,
    # plot_bgcolor="#f0f2f6"
)
st.plotly_chart(fig_waterfall_allocation, use_container_width=True)
ss['fig_waterfall_contract'] = fig_waterfall_contract
ss['fig_waterfall_allocation'] = fig_waterfall_allocation

# --- Analyse Poids dans l'allocation vs Contribution au rendement ---
if not df_alloc_uc.empty and 'Encours en €' in df_alloc_uc.columns and '+/- value (en €)' in df_alloc_uc.columns:
    encours_total_contrat = pd.to_numeric(df_alloc_contrat_all['Encours en €'], errors='coerce').fillna(0.0).sum()
    encours_total_uc = df_alloc_uc['Encours en €'].sum()
    pv_totale_uc = df_alloc_uc['+/- value (en €)'].sum()

    denom_contrat = encours_total_contrat if encours_total_contrat > 0 else (encours_total_uc if encours_total_uc > 0 else 1.0)
    denom_uc = encours_total_uc if encours_total_uc > 0 else 1.0

    # Capital investi global sur la poche UC (somme des capitaux investis par support)
    df_support_tmp = df_alloc_uc.groupby('Support', as_index=False).agg(
        {'Encours en €': 'sum', '+/- value (en €)': 'sum'}
    )
    capital_investi_uc = (df_support_tmp['Encours en €'] - df_support_tmp['+/- value (en €)']).clip(lower=0.0).sum()
    denom_cap = capital_investi_uc if capital_investi_uc > 0 else denom_uc
    rendement_global_uc_pct = (pv_totale_uc / denom_cap) * 100.0

    def _prepare_contrib_df(df_source: pd.DataFrame, group_col: str, subtitle_col: str) -> pd.DataFrame:
        if group_col == 'Support':
            df_g = df_source.groupby('Support', as_index=False).agg(
                {'Encours en €': 'sum', '+/- value (en €)': 'sum', 'Type': 'first', 'Type simplifié': 'first'}
            )
            df_g['Label'] = df_g['Support']
            df_g['Sous_label'] = df_g[subtitle_col]
        else:
            df_g = (
                df_source.groupby(group_col, as_index=False)
                .agg(
                    {
                        'Encours en €': 'sum',
                        '+/- value (en €)': 'sum',
                        'Support': 'nunique',
                    }
                )
            )
            df_g['Label'] = df_g[group_col]
            df_g['Sous_label'] = df_g['Support'].apply(lambda n: f"{int(n)} support{'s' if int(n) > 1 else ''}")

        df_g['Capital investi (€)'] = (df_g['Encours en €'] - df_g['+/- value (en €)']).clip(lower=0.0)
        df_g['Part contrat (%)'] = (df_g['Encours en €'] / denom_contrat) * 100.0
        df_g['Part UC (%)'] = (df_g['Encours en €'] / denom_uc) * 100.0
        # Poids en capital investi UC (meme base que la contribution) : V_i = C_i / somme(C)
        df_g['Part capital UC (%)'] = (df_g['Capital investi (€)'] / denom_cap) * 100.0
        df_g['Perf ligne (%)'] = np.where(
            df_g['Capital investi (€)'] > 0,
            (df_g['+/- value (en €)'] / df_g['Capital investi (€)']) * 100.0,
            0.0,
        )
        df_g['Contribution rendement (pts %)'] = (df_g['+/- value (en €)'] / denom_cap) * 100.0
        return df_g

    def _fr(value, decimals=2, signed=False):
        """Formatage FR (espace milliers, virgule decimale) pour les infobulles et etiquettes."""
        if value is None or pd.isna(value):
            return "N/A"
        txt = f"{float(value):{'+' if signed else ''},.{decimals}f}"
        return txt.replace(",", " ").replace(".", ",")

    def _build_mekko_and_quadrant_figures(df_c: pd.DataFrame, entity_label: str, entity_plural: str):
        # 1. Graphique Mekko / Marimekko
        df_mekko = df_c.sort_values('Part contrat (%)', ascending=False).copy()
        df_mekko['width'] = df_mekko['Part contrat (%)']
        df_mekko['cum_w'] = df_mekko['width'].cumsum()
        df_mekko['x_center'] = df_mekko['cum_w'] - (df_mekko['width'] / 2.0)

        def _short_label(val, max_len=22):
            s = str(val)
            return s[:max_len] + "…" if len(s) > max_len else s

        # Formatage FR des infobulles cote Python (les formats d3 signes "+.2f" ne sont pas appliques par Plotly).
        def _hover_mekko(r):
            return (
                f"<b>{r['Label']}</b> ({r['Sous_label']})<br>"
                f"Largeur — Part dans le contrat : <b>{_fr(r['Part contrat (%)'], 1)} %</b> "
                f"({_fr(r['Encours en €'], 0)} € | {_fr(r['Part UC (%)'], 1)} % des UC)<br>"
                f"Hauteur — Performance ({entity_label.lower()}) : <b>{_fr(r['Perf ligne (%)'], 2, True)} %</b><br>"
                f"Surface — Contribution au rendement : <b>{_fr(r['Contribution rendement (pts %)'], 2, True)} pt</b> "
                f"({_fr(r['+/- value (en €)'], 0, True)} €)"
            )

        def _hover_quadrant(r):
            return (
                f"<b>{r['Label']}</b> ({r['Sous_label']})<br>"
                f"Part du capital investi UC : <b>{_fr(r['Part capital UC (%)'], 1)} %</b> "
                f"({_fr(r['Capital investi (€)'], 0)} € investis)<br>"
                f"Encours : {_fr(r['Encours en €'], 0)} € "
                f"({_fr(r['Part contrat (%)'], 1)} % du contrat | {_fr(r['Part UC (%)'], 1)} % des UC)<br>"
                f"Contribution au rendement : <b>{_fr(r['Contribution rendement (pts %)'], 2, True)} pt</b><br>"
                f"Performance ({entity_label.lower()}) : <b>{_fr(r['Perf ligne (%)'], 2, True)} %</b> "
                f"({_fr(r['+/- value (en €)'], 0, True)} €)"
            )

        mekko_ticktext = [
            f"{_short_label(r['Label'], 22)}<br><b>{r['Part contrat (%)']:.1f} %</b>"
            for _, r in df_mekko.iterrows()
        ]
        mekko_bar_text = [
            f"<b>{r['Contribution rendement (pts %)']:+.2f} pt</b><br>({r['+/- value (en €)']:+,.0f} €)".replace(",", " ")
            for _, r in df_mekko.iterrows()
        ]

        fig_mekko = go.Figure()

        fig_mekko.add_trace(
            go.Bar(
                x=df_mekko['x_center'],
                y=df_mekko['Perf ligne (%)'],
                width=df_mekko['width'],
                text=mekko_bar_text,
                textposition='outside',
                cliponaxis=False,
                name=entity_plural,
                marker=dict(
                    color=df_mekko['Contribution rendement (pts %)'],
                    colorscale='RdYlGn',
                    cmid=0,
                    showscale=True,
                    colorbar=dict(title="Contrib. (pts %)"),
                    line=dict(color='#ffffff', width=1.8),
                    opacity=0.9,
                ),
                customdata=[[_hover_mekko(r)] for _, r in df_mekko.iterrows()],
                hovertemplate="%{customdata[0]}<extra></extra>",
            )
        )

        fig_mekko.add_hline(
            y=0,
            line_dash="solid",
            line_color="rgba(80, 80, 80, 0.7)",
            line_width=1.5,
        )
        fig_mekko.add_hline(
            y=rendement_global_uc_pct,
            line_dash="dash",
            line_color="#1f77b4",
            line_width=1.8,
            annotation_text=f"Rendement moyen UC ({rendement_global_uc_pct:+.2f} %)",
            annotation_position="top right",
        )

        total_w_mekko = max(float(df_mekko['cum_w'].max()) if not df_mekko.empty else 100.0, 1.0)
        y_min_mekko = min(float(df_mekko['Perf ligne (%)'].min()), 0.0)
        y_max_mekko = max(float(df_mekko['Perf ligne (%)'].max()), rendement_global_uc_pct, 1.0)
        y_span = max(y_max_mekko - y_min_mekko, 5.0)

        fig_mekko.update_layout(
            title=(
                f"Graphique Mekko par {entity_label.lower()} — Poids dans l'allocation (largeur) × Performance (hauteur) "
                f"= Contribution au rendement (Total UC : {rendement_global_uc_pct:+.2f} %)"
            ),
            xaxis=dict(
                title=f"{entity_plural} classé(e)s par poids décroissant (largeur proportionnelle à la part dans le contrat en %)",
                range=[0, total_w_mekko * 1.01],
                tickmode='array',
                tickvals=df_mekko['x_center'],
                ticktext=mekko_ticktext,
                tickangle=-35,
                showgrid=False,
            ),
            yaxis=dict(
                title=f"Performance ({entity_label.lower()}) (%)",
                range=[
                    y_min_mekko - (0.22 * y_span if y_min_mekko < 0 else 0.05 * y_span),
                    y_max_mekko + 0.25 * y_span,
                ],
                ticksuffix=" %",
            ),
            bargap=0.0,
            height=560,
            margin=dict(l=40, r=40, t=75, b=130),
            showlegend=False,
        )

        # 2. Matrice Quadrant
        # X = V_i = C_i / somme(C)            (part du capital investi UC, en %)
        # Y = R_i x V_i = PV_i / somme(C)     (contribution au rendement, en points de %)
        # Droite neutre : Y = R_moyen x X, avec R_moyen = somme(R_i x V_i) / somme(V_i) (rendement global UC pondere)
        # -> un support est au-dessus de la droite si son rendement R_i depasse R_moyen.
        x_col = 'Part capital UC (%)'
        poids_moyen = float(df_c[x_col].mean())
        x_max_q = max(float(df_c[x_col].max()) * 1.18, 5.0)

        fig_quadrant = go.Figure()

        pente_neutre = rendement_global_uc_pct / 100.0
        fig_quadrant.add_trace(
            go.Scatter(
                x=[0, x_max_q],
                y=[0, x_max_q * pente_neutre],
                mode='lines',
                name=f'Contribution proportionnelle au poids (pente = rendement moyen UC {rendement_global_uc_pct:+.2f} %)',
                line=dict(color='rgba(120, 120, 120, 0.6)', width=1.5, dash='dot'),
                hoverinfo='skip',
            )
        )

        fig_quadrant.add_trace(
            go.Scatter(
                x=df_c[x_col],
                y=df_c['Contribution rendement (pts %)'],
                mode='markers+text',
                name=entity_plural,
                text=df_c['Label'].apply(lambda s: s[:28] + '…' if len(str(s)) > 28 else str(s)),
                textposition='top center',
                textfont=dict(size=10),
                marker=dict(
                    size=18,
                    color=df_c['Perf ligne (%)'],
                    colorscale='RdYlGn',
                    cmid=0,
                    showscale=True,
                    colorbar=dict(title="Perf. (%)"),
                    line=dict(width=1.2, color='#333333'),
                    opacity=0.88,
                ),
                customdata=[[_hover_quadrant(r)] for _, r in df_c.iterrows()],
                hovertemplate="%{customdata[0]}<extra></extra>",
                cliponaxis=False,
            )
        )

        fig_quadrant.add_hline(
            y=0,
            line_dash="solid",
            line_color="rgba(180, 40, 40, 0.55)",
            line_width=1.5,
            annotation_text="Seuil 0 pt (Gain / Perte)",
            annotation_position="bottom right",
        )
        fig_quadrant.add_vline(
            x=poids_moyen,
            line_dash="dash",
            line_color="rgba(100, 100, 100, 0.5)",
            line_width=1.2,
            annotation_text=f"Poids moyen ({poids_moyen:.1f} %)",
            annotation_position="top right",
        )

        fig_quadrant.update_layout(
            title=f"Matrice Poids dans l'allocation vs Contribution au rendement par {entity_label.lower()} (couleur = Perf. %)",
            xaxis_title="Part du capital investi en UC (%)",
            yaxis_title="Contribution au rendement global (en points de %)",
            xaxis=dict(range=[0, x_max_q], ticksuffix=" %"),
            yaxis=dict(ticksuffix=" pt"),
            height=540,
            showlegend=True,
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0),
        )

        return fig_mekko, fig_quadrant

    def _build_escalier_figure(df_c: pd.DataFrame, entity_label: str, entity_plural: str):
        """Graphique en escalier (version 'rectangulaire' du Mekko), base sur V_i = part du capital investi UC."""
        df_v = df_c[df_c['Capital investi (€)'] > 0].copy()
        df_v['Encours en €'] = pd.to_numeric(df_v['Encours en €'], errors='coerce').fillna(0.0)
        label_short = lambda s, n=22: str(s)[:n] + "…" if len(str(s)) > n else str(s)

        # Escalier cumule
        # X cumule = somme des V_i (0 -> 100 %), Y cumule = somme des R_i x V_i (0 -> R_moyen).
        # Chaque bloc : largeur V_i, hauteur R_i x V_i -> la pente de sa diagonale vaut R_i.
        # La diagonale du rectangle (0,0) -> (100 %, R_moyen) a pour pente R_moyen.
        df1 = df_v.sort_values('Perf ligne (%)', ascending=False).copy()
        df1['x_end'] = df1['Part capital UC (%)'].cumsum()
        df1['x_start'] = df1['x_end'] - df1['Part capital UC (%)']
        df1['x_center'] = (df1['x_start'] + df1['x_end']) / 2.0
        df1['y_end'] = df1['Contribution rendement (pts %)'].cumsum()
        df1['y_start'] = df1['y_end'] - df1['Contribution rendement (pts %)']
        x_total = float(df1['x_end'].max()) if not df1.empty else 100.0

        fig_escalier = go.Figure()
        # Rectangle global et diagonale (rendement moyen)
        fig_escalier.add_shape(
            type="rect", x0=0, y0=0, x1=x_total, y1=rendement_global_uc_pct,
            line=dict(color="rgba(80,80,80,0.5)", width=1), fillcolor="rgba(200,200,200,0.12)", layer="below",
        )
        fig_escalier.add_trace(
            go.Scatter(
                x=[0, x_total], y=[0, rendement_global_uc_pct], mode='lines',
                name=f"Diagonale = rendement moyen UC ({_fr(rendement_global_uc_pct, 2, True)} %)",
                line=dict(color='#1f77b4', width=1.8, dash='dash'), hoverinfo='skip',
            )
        )
        fig_escalier.add_trace(
            go.Bar(
                x=df1['x_center'],
                y=df1['Contribution rendement (pts %)'],
                base=df1['y_start'],
                width=df1['Part capital UC (%)'],
                name=entity_plural,
                marker=dict(
                    color=df1['Perf ligne (%)'], colorscale='RdYlGn', cmid=rendement_global_uc_pct,
                    showscale=True, colorbar=dict(title="Perf. (%)"),
                    line=dict(color='#ffffff', width=1.2), opacity=0.9,
                ),
                text=[f"{label_short(r['Label'], 18)}<br>{_fr(r['Contribution rendement (pts %)'], 2, True)} pt" for _, r in df1.iterrows()],
                textposition='outside',
                cliponaxis=False,
                customdata=[[
                    f"<b>{r['Label']}</b> ({r['Sous_label']})<br>"
                    f"Largeur — Part du capital investi UC : <b>{_fr(r['Part capital UC (%)'], 1)} %</b> ({_fr(r['Capital investi (€)'], 0)} €)<br>"
                    f"Hauteur — Contribution au rendement : <b>{_fr(r['Contribution rendement (pts %)'], 2, True)} pt</b> ({_fr(r['+/- value (en €)'], 0, True)} €)<br>"
                    f"Pente du bloc — Performance : <b>{_fr(r['Perf ligne (%)'], 2, True)} %</b> (moyenne UC : {_fr(rendement_global_uc_pct, 2, True)} %)<br>"
                    f"Cumul : {_fr(r['x_end'], 1)} % du capital → {_fr(r['y_end'], 2, True)} pt"
                ] for _, r in df1.iterrows()],
                hovertemplate="%{customdata[0]}<extra></extra>",
            )
        )
        y_vals = [0.0, rendement_global_uc_pct] + df1['y_end'].tolist() + df1['y_start'].tolist()
        y_lo, y_hi = min(y_vals), max(y_vals)
        y_pad = max((y_hi - y_lo) * 0.18, 0.2)
        fig_escalier.update_layout(
            title=(
                f"Escalier par {entity_label.lower()} : largeur = part du capital investi, "
                f"hauteur = contribution (pente de chaque bloc = performance)"
            ),
            xaxis=dict(title="Part du capital investi en UC, cumulée (%)", range=[0, x_total * 1.02], ticksuffix=" %"),
            yaxis=dict(title="Contribution au rendement, cumulée (pts de %)", range=[y_lo - y_pad, y_hi + y_pad], ticksuffix=" pt"),
            bargap=0.0,
            height=560,
            showlegend=True,
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0),
        )

        return fig_escalier

    df_contrib_support = _prepare_contrib_df(df_alloc_uc, 'Support', 'Type simplifié')
    df_contrib_typo = _prepare_contrib_df(df_alloc_uc, 'Type simplifié', 'Type simplifié')

    fig_alloc_contrib_mekko, fig_alloc_contrib_quadrant = _build_mekko_and_quadrant_figures(
        df_contrib_support, "Support", "Supports du contrat"
    )
    fig_typo_contrib_mekko, fig_typo_contrib_quadrant = _build_mekko_and_quadrant_figures(
        df_contrib_typo, "Typologie simplifiée", "Typologies simplifiées"
    )
    fig_alloc_escalier = _build_escalier_figure(
        df_contrib_support, "Support", "Supports du contrat"
    )
    fig_typo_escalier = _build_escalier_figure(
        df_contrib_typo, "Typologie simplifiée", "Typologies simplifiées"
    )

    tab_supports, tab_typologie = st.tabs(["Par support", "Par typologie simplifiée"])

    with tab_supports:
        st.plotly_chart(fig_alloc_contrib_mekko, use_container_width=True)
        st.plotly_chart(fig_alloc_escalier, use_container_width=True)
        st.plotly_chart(fig_alloc_contrib_quadrant, use_container_width=True)

    with tab_typologie:
        st.plotly_chart(fig_typo_contrib_mekko, use_container_width=True)
        st.plotly_chart(fig_typo_escalier, use_container_width=True)
        st.plotly_chart(fig_typo_contrib_quadrant, use_container_width=True)

    ss['fig_alloc_contrib_mekko'] = fig_alloc_contrib_mekko
    ss['fig_alloc_contrib_quadrant'] = fig_alloc_contrib_quadrant
    ss['fig_typo_contrib_mekko'] = fig_typo_contrib_mekko
    ss['fig_typo_contrib_quadrant'] = fig_typo_contrib_quadrant
    ss['fig_alloc_contrib_escalier'] = fig_alloc_escalier
    ss['fig_typo_contrib_escalier'] = fig_typo_escalier

    # --- Trajectoires dans la matrice Poids vs Contribution (historique des exports) ---
    st.subheader("Trajectoires dans la matrice Poids vs Contribution")
    st.caption(
        "Chaque point est recalculé à partir d'un export historique des situations détaillées : "
        "X = part du capital investi UC, Y = contribution au rendement (pts)."
    )

    with st.spinner("Chargement de l'historique des allocations..."):
        df_alloc_hist_all = get_allocation_history(allocation_history_signature())

    df_alloc_hist = (
        df_alloc_hist_all[df_alloc_hist_all['Numéro contrat'].astype(str) == str(contrat)].copy()
        if not df_alloc_hist_all.empty else pd.DataFrame()
    )

    def _snapshot_contrib(df_date: pd.DataFrame, group_col: str) -> pd.DataFrame:
        """Meme calcul que la matrice actuelle, applique a un export historique."""
        d = df_date[~df_date['Type'].isin(["Fonds en Euros"])].copy()
        if d.empty:
            return pd.DataFrame()
        d['Type simplifié'] = d.apply(
            lambda row: map_simplified_type(row.get('Type'), row.get('Support'), mapping_simplifie, support_rules),
            axis=1,
        )
        # Cle de suivi d'un support dans le temps : ISIN si disponible, sinon nom du support.
        isin = d['Code ISIN'].astype(str).str.strip() if 'Code ISIN' in d.columns else pd.Series('', index=d.index)
        d['Cle support'] = np.where(isin.str.len() >= 8, isin, d['Support'].astype(str).str.upper())

        sup = d.groupby('Cle support', as_index=False).agg(
            {'Encours en €': 'sum', '+/- value (en €)': 'sum', 'Support': 'last', 'Type simplifié': 'last'}
        )
        sup['Capital investi (€)'] = (sup['Encours en €'] - sup['+/- value (en €)']).clip(lower=0.0)
        cap_tot = float(sup['Capital investi (€)'].sum())
        if cap_tot <= 0:
            return pd.DataFrame()

        if group_col == 'Support':
            g = sup.rename(columns={'Cle support': 'Cle'})
            g['Label'] = g['Support']
        else:
            g = d.groupby('Type simplifié', as_index=False).agg({'Encours en €': 'sum', '+/- value (en €)': 'sum'})
            g['Capital investi (€)'] = (g['Encours en €'] - g['+/- value (en €)']).clip(lower=0.0)
            g['Cle'] = g['Type simplifié']
            g['Label'] = g['Type simplifié']
        g['X'] = g['Capital investi (€)'] / cap_tot * 100.0
        g['Y'] = g['+/- value (en €)'] / cap_tot * 100.0
        g['Perf'] = np.where(g['Capital investi (€)'] > 0, g['+/- value (en €)'] / g['Capital investi (€)'] * 100.0, 0.0)
        g['R moyen'] = float(sup['+/- value (en €)'].sum()) / cap_tot * 100.0
        return g[['Cle', 'Label', 'X', 'Y', 'Perf', 'R moyen', 'Encours en €', '+/- value (en €)', 'Capital investi (€)']]

    if df_alloc_hist.empty or df_alloc_hist['Date export'].nunique() < 2:
        st.info("Historique insuffisant pour ce contrat (moins de deux exports de situations détaillées).")
    else:
        dates_dispo = sorted(df_alloc_hist['Date export'].dropna().unique())
        c_freq, c_start, c_mode = st.columns([1, 1, 1])
        frequence = c_freq.selectbox(
            "Fréquence des points", ["Mensuelle (dernier export du mois)", "Trimestrielle", "Tous les exports"],
            key=f"traj_freq_{contrat}",
        )
        date_min = pd.Timestamp(dates_dispo[0]).date()
        date_max = pd.Timestamp(dates_dispo[-1]).date()
        date_debut_traj = c_start.date_input(
            "Depuis le", value=date_min, min_value=date_min, max_value=date_max, key=f"traj_start_{contrat}"
        )
        mode_traj = c_mode.radio("Affichage", ["Trajectoires", "Animation"], horizontal=True, key=f"traj_mode_{contrat}")

        s_dates = pd.Series(pd.to_datetime(dates_dispo))
        s_dates = s_dates[s_dates >= pd.Timestamp(date_debut_traj)]
        if frequence.startswith("Mensuelle"):
            s_dates = s_dates.groupby(s_dates.dt.to_period('M')).max()
        elif frequence == "Trimestrielle":
            s_dates = s_dates.groupby(s_dates.dt.to_period('Q')).max()
        dates_retenues = sorted(set(s_dates.tolist()) | {pd.Timestamp(dates_dispo[-1])})

        def _build_trajectory_data(group_col: str) -> pd.DataFrame:
            frames = []
            for dt in dates_retenues:
                snap = _snapshot_contrib(df_alloc_hist[df_alloc_hist['Date export'] == dt], group_col)
                if not snap.empty:
                    snap['Date'] = pd.Timestamp(dt)
                    frames.append(snap)
            if not frames:
                return pd.DataFrame()
            out = pd.concat(frames, ignore_index=True)
            # Libelle de chaque entite = dernier nom connu
            last_label = out.sort_values('Date').groupby('Cle')['Label'].last()
            out['Label'] = out['Cle'].map(last_label)
            return out

        def _build_trajectory_figure(traj: pd.DataFrame, entity_label: str, selected_keys: list) -> go.Figure:
            traj = traj[traj['Cle'].isin(selected_keys)].sort_values('Date')
            palette = px.colors.qualitative.Plotly + px.colors.qualitative.D3 + px.colors.qualitative.Set2
            fig = go.Figure()
            x_max = max(float(traj['X'].max()) * 1.15, 5.0)
            r_last = float(traj.loc[traj['Date'] == traj['Date'].max(), 'R moyen'].iloc[0])
            fig.add_trace(go.Scatter(
                x=[0, x_max], y=[0, x_max * r_last / 100.0], mode='lines',
                name=f"Droite neutre au dernier export (R moyen {_fr(r_last, 2, True)} %)",
                line=dict(color='rgba(120,120,120,0.6)', width=1.5, dash='dot'), hoverinfo='skip',
            ))
            for i, (key, g) in enumerate(traj.groupby('Cle', sort=False)):
                g = g.sort_values('Date')
                color = palette[i % len(palette)]
                n = len(g)
                sizes = [6 + 10 * (k / max(n - 1, 1)) for k in range(n)]
                opac = [0.35 + 0.65 * (k / max(n - 1, 1)) for k in range(n)]
                hover = [
                    f"<b>{r['Label']}</b> — {r['Date']:%d/%m/%Y}<br>"
                    f"Part du capital investi UC : <b>{_fr(r['X'], 1)} %</b> ({_fr(r['Capital investi (€)'], 0)} €)<br>"
                    f"Contribution : <b>{_fr(r['Y'], 2, True)} pt</b> ({_fr(r['+/- value (en €)'], 0, True)} €)<br>"
                    f"Performance : <b>{_fr(r['Perf'], 2, True)} %</b> (R moyen : {_fr(r['R moyen'], 2, True)} %)"
                    for _, r in g.iterrows()
                ]
                label = str(g['Label'].iloc[-1])
                fig.add_trace(go.Scatter(
                    x=g['X'], y=g['Y'], mode='lines+markers', name=label[:30],
                    line=dict(color=color, width=1.6),
                    marker=dict(color=color, size=sizes, opacity=opac, line=dict(width=0.8, color='#333')),
                    customdata=[[h] for h in hover], hovertemplate="%{customdata[0]}<extra></extra>",
                    legendgroup=key,
                ))
                # Point final mis en evidence + etiquette
                last = g.iloc[-1]
                fig.add_trace(go.Scatter(
                    x=[last['X']], y=[last['Y']], mode='markers+text',
                    text=[label[:24] + ("…" if len(label) > 24 else "")], textposition='top center', textfont=dict(size=10),
                    marker=dict(color=color, size=18, symbol='circle', line=dict(width=1.5, color='#333')),
                    showlegend=False, legendgroup=key, customdata=[[hover[-1]]],
                    hovertemplate="%{customdata[0]}<extra></extra>",
                ))
            fig.add_hline(y=0, line_color="rgba(180,40,40,0.55)", line_width=1.2)
            d0, d1 = traj['Date'].min(), traj['Date'].max()
            fig.update_layout(
                title=(
                    f"Trajectoires par {entity_label.lower()} du {d0:%d/%m/%Y} au {d1:%d/%m/%Y} "
                    f"(petits points pâles = anciens exports, gros point = dernier export)"
                ),
                xaxis=dict(title="Part du capital investi en UC (%)", range=[0, x_max], ticksuffix=" %"),
                yaxis=dict(title="Contribution au rendement global (pts de %)", ticksuffix=" pt"),
                height=620,
                legend=dict(orientation='h', yanchor='top', y=-0.15, xanchor='left', x=0),
                margin=dict(b=140),
            )
            return fig

        def _build_animation_figure(traj: pd.DataFrame, entity_label: str, selected_keys: list) -> go.Figure:
            traj = traj[traj['Cle'].isin(selected_keys)].sort_values('Date').copy()
            traj['Export'] = traj['Date'].dt.strftime('%Y-%m-%d')
            traj['Etiquette'] = traj['Label'].astype(str).str.slice(0, 24)
            traj['Taille'] = traj['Encours en €'].clip(lower=1.0)
            x_max = max(float(traj['X'].max()) * 1.15, 5.0)
            y_min, y_max = float(traj['Y'].min()), float(traj['Y'].max())
            pad = max((y_max - y_min) * 0.15, 0.2)
            fig = px.scatter(
                traj, x='X', y='Y', animation_frame='Export', animation_group='Cle',
                color='Label', text='Etiquette', size='Taille', size_max=40,
                hover_name='Label',
                hover_data={'X': ':.1f', 'Y': ':.2f', 'Perf': ':.2f', 'Taille': False, 'Etiquette': False,
                            'Export': False, 'Cle': False, 'Label': False},
                labels={'X': "Part du capital investi UC (%)", 'Y': "Contribution (pts)", 'Perf': "Performance (%)"},
                range_x=[0, x_max], range_y=[min(y_min, 0) - pad, max(y_max, 0) + pad],
                title=f"Animation par {entity_label.lower()} (taille des bulles = encours)",
            )
            fig.update_traces(textposition='top center', textfont_size=10)
            fig.add_hline(y=0, line_color="rgba(180,40,40,0.55)", line_width=1.2)
            fig.update_layout(height=640, showlegend=False)
            return fig

        tab_traj_sup, tab_traj_typo = st.tabs(["Par support", "Par typologie simplifiée"])
        for tab, group_col, entity_label in [
            (tab_traj_sup, 'Support', "Support"),
            (tab_traj_typo, 'Type simplifié', "Typologie simplifiée"),
        ]:
            with tab:
                traj = _build_trajectory_data(group_col)
                if traj.empty or traj['Date'].nunique() < 2:
                    st.info("Pas assez d'exports exploitables sur la période choisie.")
                    continue
                # Par defaut : entites presentes au dernier export, classees par poids (8 premieres pour les supports)
                last_snap = traj[traj['Date'] == traj['Date'].max()].sort_values('X', ascending=False)
                all_keys = traj.sort_values('X', ascending=False)['Cle'].drop_duplicates().tolist()
                label_of = traj.groupby('Cle')['Label'].last().to_dict()
                default_keys = last_snap['Cle'].tolist()[:8] if group_col == 'Support' else last_snap['Cle'].tolist()
                selected = st.multiselect(
                    f"{entity_label}s affiché(e)s",
                    options=all_keys, default=default_keys,
                    format_func=lambda k: str(label_of.get(k, k)),
                    key=f"traj_sel_{group_col}_{contrat}",
                )
                if not selected:
                    st.info("Sélectionnez au moins un élément.")
                    continue
                if mode_traj == "Animation":
                    st.plotly_chart(_build_animation_figure(traj, entity_label, selected), use_container_width=True)
                else:
                    st.plotly_chart(_build_trajectory_figure(traj, entity_label, selected), use_container_width=True)
                st.caption(f"{traj['Date'].nunique()} export(s) utilisé(s) sur la période.")

df_historical_for_contract = df_contrat_agg[df_contrat_agg['N° de contrat'] == contrat].copy()
df_current_for_contract = df_contrat_selected.copy()
show_evol_versements = True
show_evol_arbitrages = True
if tri_analysis is not None:
    evol_c1, evol_c2 = st.columns(2)
    with evol_c1:
        show_evol_versements = st.checkbox("Afficher versements (VL)", value=True, key=f"evol_events_contrib_{contrat}")
    with evol_c2:
        show_evol_arbitrages = st.checkbox("Afficher arbitrages (VL)", value=True, key=f"evol_events_arb_{contrat}")

fig_evol = build_evolution_figure(
    df_historical_for_contract,
    df_current_for_contract,
    contrat,
    tri_analysis,
    source_context,
    add_reduction_ir=add_reduction_IR,
    ir_num=IR_num,
    include_versements=show_evol_versements,
    include_arbitrages=show_evol_arbitrages,
)

ss['fig_evol'] = fig_evol
if fig_evol is not None:
    st.plotly_chart(fig_evol, use_container_width=True)

if tri_analysis is not None:
    movements_for_audit = tri_analysis.get("movements")
    if movements_for_audit is not None and not movements_for_audit.empty:
        contrib_audit = movements_for_audit[movements_for_audit["movement_type"] == "contribution"].copy()
        if not contrib_audit.empty:
            contrib_audit["date"] = pd.to_datetime(contrib_audit["date"], errors="coerce").dt.normalize()
            contrib_audit["amount_net"] = pd.to_numeric(contrib_audit["amount_net"], errors="coerce")
            contrib_audit["amount_gross"] = pd.to_numeric(contrib_audit["amount_gross"], errors="coerce")
            contrib_audit = contrib_audit.dropna(subset=["date", "amount_net", "amount_gross"]).sort_values("date")
            if not contrib_audit.empty:
                contrib_audit["Cumul brut"] = contrib_audit["amount_gross"].cumsum()
                contrib_audit_display = contrib_audit[["date", "label", "amount_net", "amount_gross", "Cumul brut"]].copy()
                contrib_audit_display.columns = ["Date", "Libelle", "Versement net", "Versement brut", "Cumul brut"]
                contrib_audit_display["Date"] = pd.to_datetime(contrib_audit_display["Date"]).dt.strftime("%d/%m/%Y")

                with st.expander("Controle versements extraits du releve d'operations"):
                    st.caption(f"Source retenue pour la page: {source_context['source_effective']}")
                    st.dataframe(contrib_audit_display, hide_index=True, use_container_width=True)
                    st.caption(
                        (
                            f"Total brut extrait: {contrib_audit['amount_gross'].sum():,.0f} EUR | "
                            f"Total net extrait: {contrib_audit['amount_net'].sum():,.0f} EUR"
                        ).replace(",", " ")
                    )

st.divider()
st.subheader("TRI du contrat")

if tri_analysis is None:
    st.info("Aucune analyse TRI PDF n'a ete appariee a ce contrat.")
else:
    tri_history_source = pd.concat(
        [
            df_historical_for_contract[["N° de contrat", "Date de valorisation", "Valorisation"]],
            df_current_for_contract[["N° de contrat", "Date de valorisation", "Valorisation"]],
        ],
        ignore_index=True,
    )
    tri_history_source = tri_history_source.drop_duplicates(
        subset=["N° de contrat", "Date de valorisation"],
        keep="last",
    )

    tri_history = build_contract_tri_history(tri_analysis, tri_history_source)

    if tri_history.empty:
        st.warning("Le TRI n'a pas pu etre recalcule sur l'historique de valorisation de ce contrat.")
    else:
        current_tri = tri_history.iloc[-1]
        t1, t2, t3, t4 = st.columns(4)
        t1.metric("TRI net actuel", format_pct(current_tri["TRI net"]))
        t2.metric("TRI brut actuel", format_pct(current_tri["TRI brut"]))
        t3.metric("Points historiques", f"{len(tri_history)}")
        t4.metric(
            "Date de reference",
            pd.Timestamp(current_tri["Date de valorisation"]).strftime("%d/%m/%Y"),
        )

        if tri_analysis.get("assumption_note"):
            st.caption(tri_analysis["assumption_note"])

        fig_tri = go.Figure()
        fig_tri.add_trace(
            go.Scatter(
                x=tri_history["Date de valorisation"],
                y=tri_history["TRI net"] * 100,
                mode="lines+markers",
                name="TRI net",
                line=dict(color="#1f77b4", width=3),
                hovertemplate="<b>%{x|%d/%m/%Y}</b><br>TRI net: %{y:.2f}%<extra></extra>",
            )
        )
        tri_y_values_for_scale = pd.to_numeric(tri_history["TRI net"] * 100, errors="coerce").dropna().tolist()
        fig_tri.add_trace(
            go.Scatter(
                x=tri_history["Date de valorisation"],
                y=tri_history["TRI brut"] * 100,
                mode="lines+markers",
                name="TRI brut",
                line=dict(color="#ff7f0e", width=3, dash="dot"),
                hovertemplate="<b>%{x|%d/%m/%Y}</b><br>TRI brut: %{y:.2f}%<extra></extra>",
            )
        )
        tri_y_values_for_scale.extend(
            pd.to_numeric(tri_history["TRI brut"] * 100, errors="coerce").dropna().tolist()
        )

        show_col1, show_col2, show_col3 = st.columns(3)
        with show_col1:
            show_versements = st.checkbox("Afficher versements", value=True, key=f"tri_events_contrib_{contrat}")
        with show_col2:
            show_arbitrages = st.checkbox("Afficher arbitrages", value=True, key=f"tri_events_arb_{contrat}")
        with show_col3:
            show_frais = st.checkbox("Afficher frais", value=True, key=f"tri_events_fees_{contrat}")
        fig_tri = build_tri_figure(
            df_historical_for_contract,
            df_current_for_contract,
            contrat,
            tri_analysis,
            tri_history=tri_history,
            include_versements=show_versements,
            include_arbitrages=show_arbitrages,
            include_frais=show_frais,
        )
        ss['fig_tri'] = fig_tri
        if fig_tri is not None:
            st.plotly_chart(fig_tri, use_container_width=True)

        if montant_versements_bruts is not None and montant_versements_nets is not None and montant_versements_bruts > 0:
            st.caption(f"KPI versements (source retenue: {source_context['source_effective']})")
            f1, f2, f3, f4 = st.columns(4)
            f1.metric("Versements bruts (cumul)", kpi_data["montant_versements_bruts_str"])
            f2.metric("Versements nets (cumul)", kpi_data["montant_versements_nets_kpi_str"])
            f3.metric("Frais d'entree estimes", kpi_data["frais_entree_str"])
            f4.metric("Taux frais estime", kpi_data["taux_frais_str"].replace(",", "."))

        with st.expander("Voir l'historique TRI"):
            tri_display = tri_history.copy()
            tri_display["Date de valorisation"] = pd.to_datetime(
                tri_display["Date de valorisation"]
            ).dt.strftime("%d/%m/%Y")
            tri_display["TRI net"] = tri_display["TRI net"].map(format_pct)
            tri_display["TRI brut"] = tri_display["TRI brut"].map(format_pct)
            st.dataframe(tri_display, hide_index=True, use_container_width=True)

# --- Évolution des fonds du contrat (base 100) ---
st.divider()
st.subheader("Évolution des fonds du contrat (base 100)")

import os
fonds_dir = "/Users/jean-philippenavarro/Documents/10_CGP/20_Outils - Simulateurs/01_Suivi_AV_PER/00_Exports/3_Fonds"
df_perfs, latest_file = load_latest_fund_perf_file(fonds_dir)

if df_perfs.empty or latest_file is None:
    st.info("Aucun fichier de performance fonds trouvé dans 00_Exports/3_Fonds.")
else:
    # ISIN du contrat sélectionné
    if 'Numéro contrat' in df_allocations.columns:
        df_alloc_ctr = df_allocations[df_allocations['Numéro contrat'] == contrat]
    else:
        df_alloc_ctr = pd.DataFrame()

    if df_alloc_ctr.empty or 'Code ISIN' not in df_alloc_ctr.columns:
        st.warning("Aucun fonds détecté pour ce contrat dans les allocations.")
    else:
        # Sélecteur de période (borné au dataset)
        min_date = df_perfs['Date'].min().date()
        max_date = df_perfs['Date'].max().date()
        default_start = (df_perfs['Date'].max() - pd.DateOffset(years=1)).date()
        if default_start < min_date:
            default_start = min_date
        c1, c2 = st.columns(2)
        with c1:
            date_debut = st.date_input("Date de début", value=default_start, min_value=min_date, max_value=max_date, key="perfo_ctr_start")
        with c2:
            date_fin = st.date_input("Date de fin", value=max_date, min_value=min_date, max_value=max_date, key="perfo_ctr_end")
        evt_c1, evt_c2 = st.columns(2)
        with evt_c1:
            show_fonds_versements = st.checkbox("Afficher versements", value=True, key=f"fonds_events_contrib_{contrat}")
        with evt_c2:
            show_fonds_arbitrages = st.checkbox("Afficher arbitrages", value=True, key=f"fonds_events_arb_{contrat}")

        if date_debut >= date_fin:
            st.error("La date de début doit être antérieure à la date de fin")
        else:
            funds_bundle = build_contract_and_class_fund_figures(
                df_perfs=df_perfs,
                df_alloc_ctr=df_alloc_ctr,
                contrat_num=contrat,
                date_debut=date_debut,
                date_fin=date_fin,
                tri_analysis=tri_analysis,
                show_versements=show_fonds_versements,
                show_arbitrages=show_fonds_arbitrages,
                mapping_path=MAPPING_PATH,
            )
            missing_labels = funds_bundle["missing_labels"]
            if missing_labels:
                st.warning(
                    f"{len(missing_labels)} fonds du contrat sans historique dans {os.path.basename(latest_file)}: "
                    f"{', '.join(missing_labels[:5])}{'…' if len(missing_labels) > 5 else ''}"
                )

            if len(funds_bundle["isins_dispo"]) == 0:
                st.info("Aucun des fonds du contrat n'est présent dans le fichier de performances.")
            elif funds_bundle["fig_all_funds"] is None or funds_bundle["df_perf_ctr"].empty:
                st.info("Aucune donnée sur la période pour les fonds du contrat.")
            else:
                df_perf_ctr = funds_bundle["df_perf_ctr"]
                fig = funds_bundle["fig_all_funds"]
                ss['fig_fonds_contrat'] = fig
                st.plotly_chart(fig, use_container_width=True)

                figures_by_class = funds_bundle["figures_by_class"]
                if figures_by_class:
                    st.subheader("Évolution des fonds par classe d'actifs simplifiée (base 100)")
                    for asset_class, fig_cls in figures_by_class:
                        st.plotly_chart(fig_cls, use_container_width=True)

                # Statistiques par fonds
                st.caption(f"Données: {os.path.basename(latest_file)}")
                stats_rows = []
                for name in sorted(df_perf_ctr['Nom_fonds'].unique()):
                    dff = df_perf_ctr[df_perf_ctr['Nom_fonds'] == name]
                    perf_tot = dff['Performance_base_100'].iloc[-1] - 100
                    nb_j = (date_fin - date_debut).days
                    rend_ann = ((dff['Performance_base_100'].iloc[-1] / 100) ** (365 / nb_j) - 1) * 100 if nb_j > 0 else 0
                    vola = dff['Rendement'].std() * np.sqrt(252) * 100
                    stats_rows.append({
                        'Fonds': name,
                        'Performance totale (%)': round(float(perf_tot), 2),
                        'Rendement annualisé (%)': round(float(rend_ann), 2),
                        'Volatilité annualisée (%)': round(float(vola), 2),
                        'Nombre de jours': int(len(dff)),
                    })

                df_stats = pd.DataFrame(stats_rows).sort_values('Performance totale (%)', ascending=False)
                st.dataframe(df_stats, hide_index=True, use_container_width=True)

                # Données + export
                with st.expander("📊 Voir les données"):
                    df_disp = df_perf_ctr[['Date', 'Nom_fonds', 'Rendement', 'Performance_base_100']].copy()
                    df_disp['Date'] = df_disp['Date'].dt.strftime('%d/%m/%Y')
                    df_disp.columns = ['Date', 'Fonds', 'Rendement quotidien', 'Performance (base 100)']
                    st.dataframe(df_disp, hide_index=True, use_container_width=True)
                with st.expander("📥 Télécharger (CSV)"):
                    st.download_button(
                        "💾 Télécharger",
                        data=df_disp.to_csv(index=False, sep=';', decimal=','),
                        file_name=f"performance_fonds_contrat_{contrat}_{pd.to_datetime(date_debut).strftime('%Y%m%d')}_{pd.to_datetime(date_fin).strftime('%Y%m%d')}.csv",
                        mime='text/csv'
                    )
