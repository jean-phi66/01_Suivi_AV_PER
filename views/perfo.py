import streamlit as st
from streamlit import session_state as ss

import pandas as pd
import numpy as np

import plotly.express as px
from waterfall_graphs import generate_contrats_waterfall, generate_allocations_waterfall
import plotly.graph_objects as go
from tri_integration import load_tri_analyses, match_tri_analyses_to_contracts, build_contract_tri_history


def format_pct(value):
    if value is None or pd.isna(value):
        return "N/A"
    return f"{value * 100:.2f}%"


@st.cache_resource(show_spinner=False)
def get_tri_analyses_resource():
    return load_tri_analyses()


def apply_readable_yaxis(
    fig,
    values,
    min_abs_margin=100.0,
    clamp_min_zero=True,
    min_span=1.0,
):
    vals = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    if vals.empty:
        return False

    vmin = float(vals.min())
    vmax = float(vals.max())
    full_span = max(vmax - vmin, float(min_span))

    if len(vals) >= 10:
        q_low = float(vals.quantile(0.05))
        q_high = float(vals.quantile(0.95))
        robust_span = max(q_high - q_low, float(min_span))
        if full_span > robust_span * 2.5:
            margin = robust_span * 0.15
            y_low = q_low - margin
            if clamp_min_zero:
                y_low = max(0.0, y_low)
            y_high = q_high + margin
            fig.update_yaxes(range=[y_low, y_high])
            return True

    margin = max(full_span * 0.12, abs(vmax) * 0.02, float(min_abs_margin))
    y_low = vmin - margin
    if clamp_min_zero:
        y_low = max(0.0, y_low)
    y_high = vmax + margin
    fig.update_yaxes(range=[y_low, y_high])
    return False


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

tri_contracts_df, tri_contracts_map = match_tri_analyses_to_contracts(
    get_tri_analyses_resource(),
    df_contrats[["N° de contrat", "Titulaire(s)", "Enveloppe", "Partenaire"]].drop_duplicates().copy(),
)
tri_analysis = tri_contracts_map.get(str(contrat))

# --- START: KPI Calculations ---
if not df_contrat_selected.empty:
    # Extract data
    valorisation = df_contrat_selected['Valorisation'].iloc[0]
    date_ouverture_raw = df_contrat_selected['Ouverture'].iloc[0] if 'Ouverture' in df_contrat_selected.columns else None
    date_valorisation_raw = df_contrat_selected['Date de valorisation'].iloc[0] if 'Date de valorisation' in df_contrat_selected.columns else None
    montant_versements_bruts_csv = df_contrat_selected['Montant total des versements bruts'].iloc[0] if 'Montant total des versements bruts' in df_contrat_selected.columns else 0.0
    montant_versements_nets_csv = df_contrat_selected['Montant total des versements nets'].iloc[0] if 'Montant total des versements nets' in df_contrat_selected.columns else 0.0

    # Par defaut, les calculs utilisent les versements issus des CSV contrats.
    montant_versements_bruts = float(montant_versements_bruts_csv)
    montant_versements_nets = float(montant_versements_nets_csv)

    # Frais d'entree estimes depuis le rapport d'operations TRI (si disponible)
    frais_entree_estimes = None
    taux_frais_entree_estime = None
    tri_net_kpi = None
    tri_brut_kpi = None
    if tri_analysis is not None:
        tri_net_kpi = tri_analysis.get("tri_net")
        tri_brut_kpi = tri_analysis.get("tri_gross")
        gross_total = tri_analysis.get("gross_payments_total")
        net_total = tri_analysis.get("net_payments_total")
        if gross_total is not None and net_total is not None and not pd.isna(gross_total) and not pd.isna(net_total):
            gross_total = float(gross_total)
            net_total = float(net_total)
            if gross_total > 0 and net_total >= 0:
                frais_entree_estimes = gross_total - net_total
                taux_frais_entree_estime = frais_entree_estimes / gross_total

                # Controle d'ecart CSV vs releves d'operations et choix utilisateur de la source a considerer.
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
                if source_versements == "Releve d'operations TRI":
                    montant_versements_bruts = gross_total
                    montant_versements_nets = net_total

    # Calculate TRA
    tra_str = "N/A"
    if pd.notna(date_ouverture_raw) and pd.notna(date_valorisation_raw) and valorisation > 0:
        date_ouverture_dt = pd.to_datetime(date_ouverture_raw)
        date_valorisation_dt = pd.to_datetime(date_valorisation_raw)
        
        if date_valorisation_dt > date_ouverture_dt:
            years = (date_valorisation_dt - date_ouverture_dt).days / 365.25
            if montant_versements_nets > 0:
                # Simplified TRA calculation
                tra = ((valorisation / montant_versements_nets) ** (1 / years) - 1) * 100
                tra_str = f"{tra:.2f}%"
            else:
                tra_str = "N/A (V.N. nuls)"
        else:
             tra_str = "N/A (Durée <= 0)"
    
    # Calculate Performance vs Payments
    var_vs_brut_pct_str = "N/A"
    if montant_versements_bruts > 0:
        var_vs_brut_pct = ((valorisation - montant_versements_bruts) / montant_versements_bruts) * 100
        var_vs_brut_pct_str = f"{var_vs_brut_pct:.2f}%"

    var_vs_net_pct_str = "N/A"
    if montant_versements_nets > 0:
        var_vs_net_pct = ((valorisation - montant_versements_nets) / montant_versements_nets) * 100
        var_vs_net_pct_str = f"{var_vs_net_pct:.2f}%"

    # Display KPIs
    st.subheader("Indicateurs Clés de Performance")
    
    col1, col2 = st.columns(2)
    col1.metric("Valorisation", f"{valorisation:,.0f} €".replace(",", " "))
    col2.metric("TRA (estimé)", tra_str)

    col3, col4 = st.columns(2)
    col3.metric("Versements Bruts", f"{montant_versements_bruts:,.0f} €".replace(",", " "))
    col4.metric("Performance / VB (%)", var_vs_brut_pct_str)

    col5, col6 = st.columns(2)
    col5.metric("Versements Nets", f"{montant_versements_nets:,.0f} €".replace(",", " "))
    col6.metric("Performance / VN (%)", var_vs_net_pct_str)

    st.caption(f"Source des versements retenue pour ces KPI: {source_versements}")

    col7, col8 = st.columns(2)
    col7.metric(
        "Frais d'entree estimes",
        (f"{frais_entree_estimes:,.0f} €".replace(",", " ")) if frais_entree_estimes is not None else "N/A",
    )
    col8.metric(
        "Taux frais d'entree estime",
        (f"{taux_frais_entree_estime * 100:.2f}%") if taux_frais_entree_estime is not None else "N/A",
    )

    col9, col10 = st.columns(2)
    col9.metric(
        "TRI net",
        (f"{float(tri_net_kpi) * 100:.2f}%") if tri_net_kpi is not None and not pd.isna(tri_net_kpi) else "N/A",
    )
    col10.metric(
        "TRI brut",
        (f"{float(tri_brut_kpi) * 100:.2f}%") if tri_brut_kpi is not None and not pd.isna(tri_brut_kpi) else "N/A",
    )
    
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

# Historical evolution
# df_contrat_selected est le point de données actuel pour le contrat sélectionné (depuis ss)
# df_contrat_agg contient toutes les données historiques pour tous les contrats (depuis ss)

# 1. Filtrer les données historiques pour le contrat sélectionné
df_historical_for_contract = df_contrat_agg[df_contrat_agg['N° de contrat'] == contrat].copy()

# 2. Les données actuelles pour le contrat sont dans df_contrat_selected (qui vient de ss['df_contrat_selected'])
df_current_for_contract = df_contrat_selected.copy()

# 3. Colonnes nécessaires pour le graphique et la fusion
required_cols = ['N° de contrat', 'Date de valorisation', 'Valorisation', 'Titulaire(s)']

# S'assurer que les deux DataFrames ont ces colonnes
df_historical_for_plot = df_historical_for_contract[required_cols]
df_current_for_plot = df_current_for_contract[required_cols]

# 4. Combiner les données historiques et actuelles
df_combined_plot_data = pd.concat([df_historical_for_plot, df_current_for_plot], ignore_index=True)

# 5. Supprimer les doublons potentiels et trier par date
df_combined_plot_data.drop_duplicates(subset=['N° de contrat', 'Date de valorisation'], inplace=True)
df_combined_plot_data.sort_values(by='Date de valorisation', inplace=True)

# Sauvegarder le nombre de points avant filtrage
points_avant_filtrage = len(df_combined_plot_data)
df_combined_plot_data_filtered = df_combined_plot_data.copy() # Initialiser avec une copie

# 5b. Filtrer les baisses de valorisation > 30%
est_filtre = False
if points_avant_filtrage > 1: # Le filtrage n'a de sens que s'il y a au moins 2 points
    # .pct_change() calcule (actuel - précédent) / précédent
    # Une baisse de 30% est -0.3. On veut garder ce qui est >= -0.3
    variation = df_combined_plot_data_filtered['Valorisation'].pct_change()
    # Le premier point aura NaN pour la variation, on le garde.
    # Les autres points sont gardés si leur variation est >= -0.30
    condition_filtrage = (variation >= -0.30) | variation.isnull()
    df_combined_plot_data_filtered = df_combined_plot_data_filtered[condition_filtrage]

points_apres_filtrage = len(df_combined_plot_data_filtered)

if points_avant_filtrage > points_apres_filtrage:
    est_filtre = True
    points_filtres_count = points_avant_filtrage - points_apres_filtrage
    st.info(f"{points_filtres_count} point(s) de données ont été filtrés en raison d'une baisse de valorisation supérieure à 30% par rapport au point précédent.")


# 6. Créer le graphique
# Déterminer le titulaire à partir du dataframe filtré si possible, sinon du non-filtré
titulaire_pour_titre = ""
if not df_combined_plot_data_filtered.empty and 'Titulaire(s)' in df_combined_plot_data_filtered.columns:
    titulaire_pour_titre = df_combined_plot_data_filtered['Titulaire(s)'].iloc[0]
elif not df_combined_plot_data.empty and 'Titulaire(s)' in df_combined_plot_data.columns: # Fallback au df non filtré
    titulaire_pour_titre = df_combined_plot_data['Titulaire(s)'].iloc[0]

if titulaire_pour_titre:
    fig_evol_title = f"Évolution de la valorisation pour {titulaire_pour_titre} - Contrat {contrat}"
else:
    fig_evol_title = f"Évolution de la valorisation du contrat {contrat}"

if est_filtre:
    fig_evol_title += " (filtrée)"

fig_evol = px.line(df_combined_plot_data_filtered, x='Date de valorisation', y='Valorisation',
                   title=fig_evol_title, markers=True) # Passage à un graphique en ligne avec marqueurs
fig_evol.update_traces(name='Valorisation', showlegend=True)
fig_evol.update_xaxes(title_text='Date de valorisation')
fig_evol.update_yaxes(title_text='Valorisation (€)', tickformat=",.0f")
y_values_for_scale = pd.to_numeric(df_combined_plot_data_filtered['Valorisation'], errors='coerce').dropna().tolist()

# Ajouter la courbe des versements bruts selon la source retenue.
used_operation_gross_curve = False
if source_versements == "Releve d'operations TRI" and tri_analysis is not None:
    movements = tri_analysis.get("movements")
    if movements is not None and not movements.empty and "amount_gross" in movements.columns:
        gross_movements = movements[movements["movement_type"] == "contribution"].copy()
        if not gross_movements.empty:
            gross_movements["date"] = pd.to_datetime(gross_movements["date"], errors="coerce").dt.normalize()
            gross_movements = gross_movements.dropna(subset=["date"])
            gross_by_date = (
                gross_movements.groupby("date", as_index=False)["amount_gross"]
                .sum()
                .sort_values("date")
            )
            if not gross_by_date.empty:
                gross_by_date["Versements bruts cumulés"] = gross_by_date["amount_gross"].cumsum()

                valuation_dates = df_combined_plot_data_filtered[["Date de valorisation"]].copy()
                valuation_dates["Date de valorisation"] = pd.to_datetime(
                    valuation_dates["Date de valorisation"], errors="coerce"
                ).dt.normalize()
                valuation_dates = valuation_dates.dropna(subset=["Date de valorisation"]).sort_values("Date de valorisation")

                if not valuation_dates.empty:
                    gross_curve = pd.merge_asof(
                        valuation_dates,
                        gross_by_date[["date", "Versements bruts cumulés"]],
                        left_on="Date de valorisation",
                        right_on="date",
                        direction="backward",
                    )
                    gross_curve["Versements bruts cumulés"] = gross_curve["Versements bruts cumulés"].fillna(0.0)

                    fig_evol.add_trace(
                        go.Scatter(
                            x=gross_curve["Date de valorisation"],
                            y=gross_curve["Versements bruts cumulés"],
                            mode="lines+markers",
                            name="Versements bruts (operations)",
                            line=dict(color="red", width=2, dash="dash"),
                            hovertemplate="<b>%{x|%d/%m/%Y}</b><br>Versements bruts cumulés: %{y:,.0f} €<extra></extra>",
                        )
                    )
                    y_values_for_scale.extend(
                        pd.to_numeric(gross_curve["Versements bruts cumulés"], errors="coerce").dropna().tolist()
                    )
                    used_operation_gross_curve = True

                    if df_contrat_selected.Enveloppe.values[0] == "PER" and add_reduction_IR:
                        gross_curve["Effort d'épargne"] = gross_curve["Versements bruts cumulés"] * (1 - IR_num)
                        fig_evol.add_trace(
                            go.Scatter(
                                x=gross_curve["Date de valorisation"],
                                y=gross_curve["Effort d'épargne"],
                                mode="lines+markers",
                                name="Effort d'épargne (après avantage fiscal)",
                                line=dict(color="green", width=2, dash="dot"),
                                hovertemplate="<b>%{x|%d/%m/%Y}</b><br>Effort d'épargne: %{y:,.0f} €<extra></extra>",
                            )
                        )
                        y_values_for_scale.extend(
                            pd.to_numeric(gross_curve["Effort d'épargne"], errors="coerce").dropna().tolist()
                        )

# Fallback: ligne statique sur la source retenue (CSV ou releve indisponible).
if (not used_operation_gross_curve) and 'Montant total des versements bruts' in df_current_for_contract.columns:
    montant_versements_bruts_fallback = (
        float(montant_versements_bruts)
        if montant_versements_bruts is not None
        else float(df_current_for_contract['Montant total des versements bruts'].iloc[0])
    )
    fig_evol.add_hline(y=montant_versements_bruts_fallback,
                        line_dash="dash",
                        line_color="red",
                        annotation_text=f"Versements Bruts ({source_versements}): {montant_versements_bruts_fallback:,.0f} €",
                        annotation_position="bottom right",
                        annotation_font_size=10,
                        annotation_font_color="red")
    y_values_for_scale.append(float(montant_versements_bruts_fallback))

    if df_contrat_selected.Enveloppe.values[0] == "PER" and add_reduction_IR:
        effort_epargne = montant_versements_bruts_fallback * (1 - IR_num)
        fig_evol.add_hline(y=effort_epargne,
                            line_dash="dash",
                            line_color="green",
                            annotation_text=f"Effort d'épargne (après avantage fiscal): {effort_epargne:,.0f} €",
                            annotation_position="top right",
                            annotation_font_size=10,
                            annotation_font_color="green")
        y_values_for_scale.append(float(effort_epargne))

robust_zoom_used = apply_readable_yaxis(fig_evol, y_values_for_scale)
if robust_zoom_used:
    st.caption("Echelle Y ajustee automatiquement pour ameliorer la lisibilite (reduction de l'impact des valeurs extremes).")

ss['fig_evol'] = fig_evol
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
                    st.caption(f"Source retenue pour la page: {source_versements}")
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

        movements = tri_analysis.get("movements")
        if movements is not None and not movements.empty:
            tri_anchor = tri_history[["Date de valorisation", "TRI net"]].copy()
            tri_anchor = tri_anchor.sort_values("Date de valorisation")
            tri_anchor["anchor_y"] = tri_anchor["TRI net"] * 100

            events = movements.copy()
            events["date"] = pd.to_datetime(events["date"], errors="coerce").dt.normalize()
            events = events.dropna(subset=["date"])
            events = events.sort_values("date")

            if not events.empty and not tri_anchor.empty:
                events = pd.merge_asof(
                    events,
                    tri_anchor[["Date de valorisation", "anchor_y"]],
                    left_on="date",
                    right_on="Date de valorisation",
                    direction="backward",
                )
                # Si l'evenement est avant le premier point TRI, on l'aligne sur le premier point.
                if events["anchor_y"].isna().any():
                    events["anchor_y"] = events["anchor_y"].fillna(tri_anchor["anchor_y"].iloc[0])

                if show_versements:
                    versements = events[events["movement_type"] == "contribution"]
                    if not versements.empty:
                        tri_y_values_for_scale.extend(
                            pd.to_numeric(versements["anchor_y"], errors="coerce").dropna().tolist()
                        )
                        fig_tri.add_trace(
                            go.Scatter(
                                x=versements["date"],
                                y=versements["anchor_y"],
                                mode="markers",
                                name="Versements",
                                marker=dict(color="#2ca02c", size=10, symbol="diamond"),
                                customdata=versements[["label", "amount_net"]],
                                hovertemplate="<b>%{x|%d/%m/%Y}</b><br>%{customdata[0]}<br>Montant net: %{customdata[1]:,.2f} €<extra></extra>",
                            )
                        )

                if show_arbitrages:
                    arbitrages = events[events["movement_type"] == "arbitrage"]
                    if not arbitrages.empty:
                        tri_y_values_for_scale.extend(
                            pd.to_numeric(arbitrages["anchor_y"], errors="coerce").dropna().tolist()
                        )
                        fig_tri.add_trace(
                            go.Scatter(
                                x=arbitrages["date"],
                                y=arbitrages["anchor_y"],
                                mode="markers",
                                name="Arbitrages",
                                marker=dict(color="#d62728", size=10, symbol="x"),
                                customdata=arbitrages[["label", "amount_net"]],
                                hovertemplate="<b>%{x|%d/%m/%Y}</b><br>%{customdata[0]}<br>Montant net: %{customdata[1]:,.2f} €<extra></extra>",
                            )
                        )

                if show_frais:
                    frais = events[events["movement_type"] == "ignored_fee"]
                    if not frais.empty:
                        tri_y_values_for_scale.extend(
                            pd.to_numeric(frais["anchor_y"], errors="coerce").dropna().tolist()
                        )
                        fig_tri.add_trace(
                            go.Scatter(
                                x=frais["date"],
                                y=frais["anchor_y"],
                                mode="markers",
                                name="Frais",
                                marker=dict(color="#9467bd", size=9, symbol="triangle-down"),
                                customdata=frais[["label", "amount_net"]],
                                hovertemplate="<b>%{x|%d/%m/%Y}</b><br>%{customdata[0]}<br>Montant net: %{customdata[1]:,.2f} €<extra></extra>",
                            )
                        )

        fig_tri.add_hline(y=0, line_dash="dash", line_color="gray")
        fig_tri.update_layout(
            title=f"Evolution du TRI recalcule - contrat {contrat}",
            xaxis_title="Date de valorisation",
            yaxis_title="TRI (%)",
            hovermode="x unified",
            height=420,
        )
        robust_tri_zoom_used = apply_readable_yaxis(
            fig_tri,
            tri_y_values_for_scale,
            min_abs_margin=0.25,
            clamp_min_zero=False,
            min_span=0.5,
        )
        if robust_tri_zoom_used:
            st.caption("Echelle Y TRI ajustee automatiquement pour ameliorer la lisibilite.")
        st.plotly_chart(fig_tri, use_container_width=True)

        if montant_versements_bruts is not None and montant_versements_nets is not None and montant_versements_bruts > 0:
            frais_entree_total = float(montant_versements_bruts) - float(montant_versements_nets)
            taux_frais_entree = frais_entree_total / float(montant_versements_bruts)

            st.caption(f"KPI versements (source retenue: {source_versements})")
            f1, f2, f3, f4 = st.columns(4)
            f1.metric("Versements bruts (cumul)", f"{float(montant_versements_bruts):,.0f} €".replace(",", " "))
            f2.metric("Versements nets (cumul)", f"{float(montant_versements_nets):,.0f} €".replace(",", " "))
            f3.metric("Frais d'entree estimes", f"{frais_entree_total:,.0f} €".replace(",", " "))
            f4.metric("Taux frais estime", f"{taux_frais_entree * 100:.2f}%")

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
