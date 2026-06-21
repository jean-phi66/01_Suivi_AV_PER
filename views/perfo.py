import streamlit as st
from streamlit import session_state as ss

import pandas as pd
import numpy as np

from waterfall_graphs import generate_contrats_waterfall, generate_allocations_waterfall
import plotly.graph_objects as go
from tri_integration import load_tri_analyses, match_tri_analyses_to_contracts
from reporting_helpers import build_evolution_figure, build_kpi_overrides, build_tri_figure, build_tri_history, resolve_payment_source


def format_pct(value):
    if value is None or pd.isna(value):
        return "N/A"
    return f"{value * 100:.2f}%"


@st.cache_resource(show_spinner=False)
def get_tri_analyses_resource():
    return load_tri_analyses()


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
    get_tri_analyses_resource(),
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

if (df_contrat_selected.Enveloppe.values[0] == "PER"):
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
    text=df_client_waterfall['value'].apply(lambda x: str(int(round(x, 0)))),
    y=df_client_waterfall['value'],
    connector={"line": {"color": "rgb(63, 63, 63)"}},
    cliponaxis=False
))
fig_waterfall_contract.update_layout(
    title="Situation contrat",
    showlegend=False
)
st.plotly_chart(fig_waterfall_contract, use_container_width=True)

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

df_historical_for_contract = df_contrat_agg[df_contrat_agg['N° de contrat'] == contrat].copy()
df_current_for_contract = df_contrat_selected.copy()
fig_evol = build_evolution_figure(
    df_historical_for_contract,
    df_current_for_contract,
    contrat,
    tri_analysis,
    source_context,
    add_reduction_ir=add_reduction_IR,
    ir_num=IR_num,
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

# Charger le fichier de performances des fonds
import os, glob
fonds_dir = "/Users/jean-philippenavarro/Documents/10_CGP/20_Outils - Simulateurs/01_Suivi_AV_PER/00_Exports/3_Fonds"
top_files = []
try:
    top_files = glob.glob(os.path.join(fonds_dir, "*Top*.csv"))
except Exception:
    top_files = []

if not top_files:
    st.info("Aucun fichier de performance fonds trouvé dans 00_Exports/3_Fonds.")
else:
    # Prendre le plus récent par mtime
    latest_file = max(top_files, key=os.path.getmtime)
    try:
        df_perfs = pd.read_csv(latest_file, sep=';', decimal=',', encoding='latin-1')
    except UnicodeDecodeError:
        df_perfs = pd.read_csv(latest_file, sep=';', decimal=',', encoding='utf-8', errors='ignore')

    # Dates et rendements
    df_perfs['Date'] = pd.to_datetime(df_perfs['Date'], format='%d/%m/%Y', errors='coerce')
    if df_perfs['Rendement'].dtype == 'object':
        df_perfs['Rendement'] = df_perfs['Rendement'].astype(str).str.replace(',', '.').astype(float)
    df_perfs = df_perfs.sort_values('Date')

    # ISIN du contrat sélectionné
    if 'Numéro contrat' in df_allocations.columns:
        df_alloc_ctr = df_allocations[df_allocations['Numéro contrat'] == contrat]
    else:
        df_alloc_ctr = pd.DataFrame()

    if df_alloc_ctr.empty or 'Code ISIN' not in df_alloc_ctr.columns:
        st.warning("Aucun fonds détecté pour ce contrat dans les allocations.")
    else:
        isins_ctr = set(df_alloc_ctr['Code ISIN'].dropna().unique())
        # Mapping ISIN -> Nom depuis fichier perfs
        map_isin_nom = (df_perfs[['Code ISIN','Nom']]
                        .dropna(subset=['Code ISIN'])
                        .drop_duplicates()
                        .set_index('Code ISIN')['Nom'])

        isins_dispo = [i for i in isins_ctr if i in set(df_perfs['Code ISIN'].dropna().unique())]
        manq = isins_ctr.difference(isins_dispo)
        if manq:
            st.warning(f"{len(manq)} fonds du contrat sans historique dans {os.path.basename(latest_file)}: {', '.join(list(manq)[:5])}{'…' if len(manq)>5 else ''}")

        if len(isins_dispo) == 0:
            st.info("Aucun des fonds du contrat n'est présent dans le fichier de performances.")
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
            if date_debut >= date_fin:
                st.error("La date de début doit être antérieure à la date de fin")
            else:
                df_sel = df_perfs[df_perfs['Code ISIN'].isin(isins_dispo)]
                df_periode = df_sel[(df_sel['Date'] >= pd.to_datetime(date_debut)) & (df_sel['Date'] <= pd.to_datetime(date_fin))].copy()

                perf_list = []
                for isin in isins_dispo:
                    d = df_periode[df_periode['Code ISIN'] == isin].copy()
                    if d.empty:
                        continue
                    d['Valeur_cumul'] = (1 + d['Rendement']).cumprod()
                    base = d['Valeur_cumul'].iloc[0]
                    d['Performance_base_100'] = (d['Valeur_cumul'] / base) * 100
                    d['Nom_fonds'] = map_isin_nom.get(isin, isin)
                    perf_list.append(d)

                if len(perf_list) == 0:
                    st.info("Aucune donnée sur la période pour les fonds du contrat.")
                else:
                    df_perf_ctr = pd.concat(perf_list, ignore_index=True)
                    fig = go.Figure()
                    colors = px.colors.qualitative.T10
                    for i, name in enumerate(sorted(df_perf_ctr['Nom_fonds'].unique())):
                        d = df_perf_ctr[df_perf_ctr['Nom_fonds'] == name]
                        fig.add_trace(go.Scatter(
                            x=d['Date'], y=d['Performance_base_100'], mode='lines', name=name,
                            line=dict(color=colors[i % len(colors)], width=2),
                            hovertemplate='<b>%{x|%d/%m/%Y}</b><br>Performance: %{y:.2f}<extra></extra>'
                        ))
                    fig.add_hline(y=100, line_dash='dash', line_color='gray', annotation_text='Base 100', annotation_position='right')
                    fig.update_layout(title=f"Fonds du contrat {contrat} (base 100 au {date_debut.strftime('%d/%m/%Y')})", xaxis_title='Date', yaxis_title='Performance (base 100)', hovermode='x unified', height=500)
                    st.plotly_chart(fig, use_container_width=True)

                    # Statistiques par fonds
                    st.caption(f"Données: {os.path.basename(latest_file)}")
                    for name in sorted(df_perf_ctr['Nom_fonds'].unique()):
                        dff = df_perf_ctr[df_perf_ctr['Nom_fonds'] == name]
                        st.subheader(name)
                        c1, c2, c3, c4 = st.columns(4)
                        perf_tot = dff['Performance_base_100'].iloc[-1] - 100
                        nb_j = (date_fin - date_debut).days
                        rend_ann = ((dff['Performance_base_100'].iloc[-1] / 100) ** (365 / nb_j) - 1) * 100 if nb_j > 0 else 0
                        vola = dff['Rendement'].std() * np.sqrt(252) * 100
                        with c1:
                            st.metric("Performance totale", f"{perf_tot:.2f}%")
                        with c2:
                            st.metric("Rendement annualisé", f"{rend_ann:.2f}%")
                        with c3:
                            st.metric("Volatilité annualisée", f"{vola:.2f}%")
                        with c4:
                            st.metric("Nombre de jours", f"{len(dff)}")

                    # Données + export
                    with st.expander("📊 Voir les données"):
                        df_disp = df_perf_ctr[['Date','Nom_fonds','Rendement','Performance_base_100']].copy()
                        df_disp['Date'] = df_disp['Date'].dt.strftime('%d/%m/%Y')
                        df_disp.columns = ['Date','Fonds','Rendement quotidien','Performance (base 100)']
                        st.dataframe(df_disp, hide_index=True, use_container_width=True)
                    with st.expander("📥 Télécharger (CSV)"):
                        st.download_button(
                            "💾 Télécharger",
                            data=df_disp.to_csv(index=False, sep=';', decimal=','),
                            file_name=f"performance_fonds_contrat_{contrat}_{pd.to_datetime(date_debut).strftime('%Y%m%d')}_{pd.to_datetime(date_fin).strftime('%Y%m%d')}.csv",
                            mime='text/csv'
                        )
