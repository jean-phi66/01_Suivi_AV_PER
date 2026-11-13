from __future__ import annotations

import glob
import os
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from config import REAL_DATA_FONDS_PATH
from tri_integration import build_contract_tri_history
from typage_fonds_utils import load_typage_config, map_simplified_type
from waterfall_graphs import generate_allocations_waterfall, generate_contrats_waterfall

DEFAULT_MAPPING_PATH = Path(__file__).resolve().parent / "defaults" / "typage_fonds_portefeuille.json"


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


def resolve_payment_source(df_contrat_selected: pd.DataFrame, tri_analysis: dict | None, preferred_source: str) -> dict[str, object]:
    def _safe_float(val, default=0.0):
        try:
            if val is None or pd.isna(val):
                return default
            return float(str(val).replace(' ', '').replace(',', '.'))
        except (ValueError, TypeError):
            return default

    gross_csv = _safe_float(df_contrat_selected['Montant total des versements bruts'].iloc[0]) if ('Montant total des versements bruts' in df_contrat_selected.columns and not df_contrat_selected.empty) else 0.0
    net_csv = _safe_float(df_contrat_selected['Montant total des versements nets'].iloc[0]) if ('Montant total des versements nets' in df_contrat_selected.columns and not df_contrat_selected.empty) else 0.0

    gross_pdf = None
    net_pdf = None
    tri_net = None
    tri_brut = None
    if tri_analysis:
        tri_net = tri_analysis.get("tri_net")
        tri_brut = tri_analysis.get("tri_gross")
        gross_raw = tri_analysis.get("gross_payments_total")
        net_raw = tri_analysis.get("net_payments_total")
        if gross_raw is not None and net_raw is not None and not pd.isna(gross_raw) and not pd.isna(net_raw):
            gross_pdf = float(gross_raw)
            net_pdf = float(net_raw)

    source_effective = preferred_source
    fallback_to_csv = False
    if preferred_source == "Releve d'operations TRI" and (gross_pdf is None or net_pdf is None):
        source_effective = "CSV contrats"
        fallback_to_csv = True

    if source_effective == "Releve d'operations TRI":
        gross_used = gross_pdf
        net_used = net_pdf
    else:
        gross_used = gross_csv
        net_used = net_csv

    fees_total = None
    fees_rate = None
    if gross_used is not None and net_used is not None and gross_used > 0:
        fees_total = float(gross_used) - float(net_used)
        fees_rate = fees_total / float(gross_used)

    return {
        "source_requested": preferred_source,
        "source_effective": source_effective,
        "fallback_to_csv": fallback_to_csv,
        "gross_csv": gross_csv,
        "net_csv": net_csv,
        "gross_pdf": gross_pdf,
        "net_pdf": net_pdf,
        "gross_used": gross_used,
        "net_used": net_used,
        "fees_total": fees_total,
        "fees_rate": fees_rate,
        "tri_net": tri_net,
        "tri_brut": tri_brut,
    }


def build_kpi_overrides(df_contrat_selected: pd.DataFrame, source_context: dict[str, object]) -> dict[str, object]:
    valorisation = float(df_contrat_selected['Valorisation'].iloc[0]) if 'Valorisation' in df_contrat_selected.columns else 0.0
    date_ouverture_raw = df_contrat_selected['Ouverture'].iloc[0] if 'Ouverture' in df_contrat_selected.columns else None
    date_val_raw = df_contrat_selected['Date de valorisation'].iloc[0] if 'Date de valorisation' in df_contrat_selected.columns else None
    gross_used = float(source_context.get("gross_used") or 0.0)
    net_used = float(source_context.get("net_used") or 0.0)

    tra_str = "N/A"
    if pd.notna(date_ouverture_raw) and pd.notna(date_val_raw) and valorisation > 0:
        date_ouverture_dt = pd.to_datetime(date_ouverture_raw, errors='coerce')
        date_val_dt = pd.to_datetime(date_val_raw, errors='coerce')
        if pd.notna(date_ouverture_dt) and pd.notna(date_val_dt) and date_val_dt > date_ouverture_dt and net_used > 0:
            years = (date_val_dt - date_ouverture_dt).days / 365.25
            if years > 0:
                tra = ((valorisation / net_used) ** (1 / years) - 1) * 100
                tra_str = f"{tra:.2f}%".replace(".", ",")

    var_vs_brut_pct_str = "N/A"
    if gross_used > 0:
        var_vs_brut_pct = ((valorisation - gross_used) / gross_used) * 100
        var_vs_brut_pct_str = f"{var_vs_brut_pct:.2f}%".replace(".", ",")

    var_vs_net_pct_str = "N/A"
    if net_used > 0:
        var_vs_net_pct = ((valorisation - net_used) / net_used) * 100
        var_vs_net_pct_str = f"{var_vs_net_pct:.2f}%".replace(".", ",")

    gross_str = f"{gross_used:,.0f} €".replace(",", " ")
    net_str = f"{net_used:,.0f} €".replace(",", " ")
    fees_total = source_context.get("fees_total")
    fees_rate = source_context.get("fees_rate")
    tri_net = source_context.get("tri_net")
    tri_brut = source_context.get("tri_brut")

    return {
        "tra_str": tra_str,
        "montant_versements_bruts_str": gross_str,
        "montant_versements_nets_kpi_str": net_str,
        "var_vs_brut_pct_str": var_vs_brut_pct_str,
        "var_vs_net_pct_str": var_vs_net_pct_str,
        "source_versements_label": source_context.get("source_effective", "CSV contrats"),
        "frais_entree_str": f"{fees_total:,.0f} €".replace(",", " ") if fees_total is not None else "N/A",
        "taux_frais_str": f"{fees_rate * 100:.2f}%".replace(".", ",") if fees_rate is not None else "N/A",
        "tri_net_str": f"{float(tri_net) * 100:.2f}%".replace(".", ",") if tri_net is not None and not pd.isna(tri_net) else "N/A",
        "tri_brut_str": f"{float(tri_brut) * 100:.2f}%".replace(".", ",") if tri_brut is not None and not pd.isna(tri_brut) else "N/A",
    }


def build_evolution_figure(
    df_historical_for_contract: pd.DataFrame,
    df_current_for_contract: pd.DataFrame,
    contrat_num: str,
    tri_analysis: dict | None,
    source_context: dict[str, object],
    add_reduction_ir: bool = False,
    ir_num: float = 0.0,
    include_versements: bool = True,
    include_arbitrages: bool = True,
):
    required_cols = ['N° de contrat', 'Date de valorisation', 'Valorisation', 'Titulaire(s)']
    missing_historical = [col for col in required_cols if col not in df_historical_for_contract.columns]
    missing_current = [col for col in required_cols if col not in df_current_for_contract.columns]
    if missing_historical or missing_current:
        return None

    df_historical_for_plot = df_historical_for_contract[required_cols].copy()
    df_current_for_plot = df_current_for_contract[required_cols].copy()
    df_combined_plot_data = pd.concat([df_historical_for_plot, df_current_for_plot], ignore_index=True)
    df_combined_plot_data['Date de valorisation'] = pd.to_datetime(
        df_combined_plot_data['Date de valorisation'], errors='coerce'
    ).dt.normalize()
    df_combined_plot_data['Valorisation'] = pd.to_numeric(
        df_combined_plot_data['Valorisation'], errors='coerce'
    )
    df_combined_plot_data = df_combined_plot_data.dropna(subset=['Date de valorisation', 'Valorisation'])
    df_combined_plot_data.drop_duplicates(subset=['N° de contrat', 'Date de valorisation'], inplace=True)
    df_combined_plot_data.sort_values(by='Date de valorisation', inplace=True)
    if df_combined_plot_data.empty:
        return None

    points_avant_filtrage = len(df_combined_plot_data)
    df_combined_plot_data_filtered = df_combined_plot_data.copy()
    est_filtre = False
    if points_avant_filtrage > 1:
        variation = df_combined_plot_data_filtered['Valorisation'].pct_change()
        condition_filtrage = (variation >= -0.30) | variation.isnull()
        df_combined_plot_data_filtered = df_combined_plot_data_filtered[condition_filtrage]
        est_filtre = points_avant_filtrage > len(df_combined_plot_data_filtered)

    titulaire_pour_titre = ""
    if not df_combined_plot_data_filtered.empty and 'Titulaire(s)' in df_combined_plot_data_filtered.columns:
        titulaire_pour_titre = df_combined_plot_data_filtered['Titulaire(s)'].iloc[0]
    elif not df_combined_plot_data.empty and 'Titulaire(s)' in df_combined_plot_data.columns:
        titulaire_pour_titre = df_combined_plot_data['Titulaire(s)'].iloc[0]

    if titulaire_pour_titre:
        fig_evol_title = f"Évolution de la valorisation pour {titulaire_pour_titre} - Contrat {contrat_num}"
    else:
        fig_evol_title = f"Évolution de la valorisation du contrat {contrat_num}"
    if est_filtre:
        fig_evol_title += " (filtrée)"

    fig_evol = px.line(df_combined_plot_data_filtered, x='Date de valorisation', y='Valorisation', title=fig_evol_title, markers=True)
    fig_evol.update_traces(name='Valorisation', showlegend=True)
    fig_evol.update_xaxes(title_text='Date de valorisation')
    fig_evol.update_yaxes(title_text='Valorisation (€)', tickformat=",.0f")
    fig_evol.update_layout(
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.22,
            xanchor="center",
            x=0.5,
        ),
        margin=dict(b=110),
    )

    y_values_for_scale = pd.to_numeric(df_combined_plot_data_filtered['Valorisation'], errors='coerce').dropna().tolist()
    used_operation_gross_curve = False
    gross_used = source_context.get("gross_used")
    source_effective = source_context.get("source_effective", "CSV contrats")

    if source_effective == "Releve d'operations TRI" and tri_analysis is not None:
        movements = tri_analysis.get("movements")
        if movements is not None and not movements.empty and "amount_gross" in movements.columns:
            gross_movements = movements[movements["movement_type"] == "contribution"].copy()
            if not gross_movements.empty:
                gross_movements["date"] = pd.to_datetime(gross_movements["date"], errors="coerce").dt.normalize()
                gross_movements = gross_movements.dropna(subset=["date"])
                gross_by_date = gross_movements.groupby("date", as_index=False)["amount_gross"].sum().sort_values("date")
                if not gross_by_date.empty:
                    gross_by_date["Versements bruts cumulés"] = gross_by_date["amount_gross"].cumsum()
                    valuation_dates = df_combined_plot_data_filtered[["Date de valorisation"]].copy()
                    valuation_dates["Date de valorisation"] = pd.to_datetime(valuation_dates["Date de valorisation"], errors="coerce").dt.normalize()
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
                        y_values_for_scale.extend(pd.to_numeric(gross_curve["Versements bruts cumulés"], errors="coerce").dropna().tolist())
                        used_operation_gross_curve = True
                        if ('Enveloppe' in df_current_for_contract.columns and 'PER' in str(df_current_for_contract['Enveloppe'].iloc[0]).upper()) and add_reduction_ir:
                            gross_curve["Effort d'épargne"] = gross_curve["Versements bruts cumulés"] * (1 - ir_num)
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
                            y_values_for_scale.extend(pd.to_numeric(gross_curve["Effort d'épargne"], errors="coerce").dropna().tolist())

    if not used_operation_gross_curve and gross_used is not None:
        fig_evol.add_hline(
            y=float(gross_used),
            line_dash="dash",
            line_color="red",
            annotation_text=f"Versements Bruts ({source_effective}): {float(gross_used):,.0f} €",
            annotation_position="bottom right",
            annotation_font_size=10,
            annotation_font_color="red",
        )
        y_values_for_scale.append(float(gross_used))
        if ('Enveloppe' in df_current_for_contract.columns and 'PER' in str(df_current_for_contract['Enveloppe'].iloc[0]).upper()) and add_reduction_ir:
            effort_epargne = float(gross_used) * (1 - ir_num)
            fig_evol.add_hline(
                y=effort_epargne,
                line_dash="dash",
                line_color="green",
                annotation_text=f"Effort d'épargne (après avantage fiscal): {effort_epargne:,.0f} €",
                annotation_position="top right",
                annotation_font_size=10,
                annotation_font_color="green",
            )
            y_values_for_scale.append(float(effort_epargne))

    # Superposer les événements (versements / arbitrages) sur la courbe de VL du contrat
    if tri_analysis is not None and (include_versements or include_arbitrages):
        movements = tri_analysis.get("movements")
        if movements is not None and not movements.empty and not df_combined_plot_data_filtered.empty:
            vl_anchor = df_combined_plot_data_filtered[["Date de valorisation", "Valorisation"]].copy().sort_values("Date de valorisation")
            vl_anchor["anchor_y"] = pd.to_numeric(vl_anchor["Valorisation"], errors="coerce")
            vl_anchor = vl_anchor.dropna(subset=["Date de valorisation", "anchor_y"])
            events = movements.copy()
            events["date"] = pd.to_datetime(events["date"], errors="coerce").dt.normalize()
            if "label" not in events.columns:
                events["label"] = "Mouvement"
            if "amount_net" not in events.columns:
                events["amount_net"] = 0.0
            if "amount_gross" not in events.columns:
                events["amount_gross"] = events["amount_net"]
            events = events.dropna(subset=["date"]).sort_values("date")
            if not events.empty and not vl_anchor.empty:
                events = pd.merge_asof(
                    events,
                    vl_anchor[["Date de valorisation", "anchor_y"]],
                    left_on="date",
                    right_on="Date de valorisation",
                    direction="backward",
                )
                if events["anchor_y"].isna().any():
                    events["anchor_y"] = events["anchor_y"].fillna(vl_anchor["anchor_y"].iloc[0])

                if include_versements:
                    subset_v = events[events["movement_type"] == "contribution"].copy()
                    if not subset_v.empty:
                        subset_v["amount_gross"] = pd.to_numeric(subset_v["amount_gross"], errors="coerce").fillna(0.0)
                        subset_v["amount_net"] = pd.to_numeric(subset_v["amount_net"], errors="coerce").fillna(0.0)
                        y_values_for_scale.extend(pd.to_numeric(subset_v["anchor_y"], errors="coerce").dropna().tolist())
                        fig_evol.add_trace(
                            go.Scatter(
                                x=subset_v["date"],
                                y=subset_v["anchor_y"],
                                mode="markers",
                                name="Versements",
                                marker=dict(color="#2ca02c", size=11, symbol="diamond", line=dict(width=1, color="#145214")),
                                customdata=subset_v[["label", "amount_gross", "amount_net"]],
                                hovertemplate="<b>%{x|%d/%m/%Y}</b><br>%{customdata[0]}<br>Brut: %{customdata[1]:,.0f} € | Net: %{customdata[2]:,.0f} €<extra></extra>",
                            )
                        )

                if include_arbitrages:
                    subset_a = events[events["movement_type"] == "arbitrage"].copy()
                    if not subset_a.empty:
                        subset_a["amount_net"] = pd.to_numeric(subset_a["amount_net"], errors="coerce").fillna(0.0)
                        y_values_for_scale.extend(pd.to_numeric(subset_a["anchor_y"], errors="coerce").dropna().tolist())
                        fig_evol.add_trace(
                            go.Scatter(
                                x=subset_a["date"],
                                y=subset_a["anchor_y"],
                                mode="markers",
                                name="Arbitrages",
                                marker=dict(color="#d62728", size=11, symbol="x", line=dict(width=1, color="#7f1d1d")),
                                customdata=subset_a[["label", "amount_net"]],
                                hovertemplate="<b>%{x|%d/%m/%Y}</b><br>%{customdata[0]}<br>Montant: %{customdata[1]:,.0f} €<extra></extra>",
                            )
                        )

    apply_readable_yaxis(fig_evol, y_values_for_scale)
    return fig_evol


def build_tri_history(
    df_historical_for_contract: pd.DataFrame,
    df_current_for_contract: pd.DataFrame,
    tri_analysis: dict | None,
):
    if tri_analysis is None:
        return pd.DataFrame()

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
    return build_contract_tri_history(tri_analysis, tri_history_source)


def build_tri_figure(
    df_historical_for_contract: pd.DataFrame,
    df_current_for_contract: pd.DataFrame,
    contrat_num: str,
    tri_analysis: dict | None,
    tri_history: pd.DataFrame | None = None,
    include_versements: bool = True,
    include_arbitrages: bool = True,
    include_frais: bool = True,
):
    if tri_analysis is None:
        return None

    if tri_history is None:
        tri_history = build_tri_history(
            df_historical_for_contract,
            df_current_for_contract,
            tri_analysis,
        )
    if tri_history.empty:
        return None

    fig_tri = go.Figure()
    tri_y_values = pd.to_numeric(tri_history["TRI net"] * 100, errors="coerce").dropna().tolist()
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
    tri_y_values.extend(pd.to_numeric(tri_history["TRI brut"] * 100, errors="coerce").dropna().tolist())

    movements = tri_analysis.get("movements")
    if movements is not None and not movements.empty:
        tri_anchor = tri_history[["Date de valorisation", "TRI net"]].copy().sort_values("Date de valorisation")
        tri_anchor["anchor_y"] = tri_anchor["TRI net"] * 100
        events = movements.copy()
        events["date"] = pd.to_datetime(events["date"], errors="coerce").dt.normalize()
        events = events.dropna(subset=["date"]).sort_values("date")
        if not events.empty and not tri_anchor.empty:
            events = pd.merge_asof(
                events,
                tri_anchor[["Date de valorisation", "anchor_y"]],
                left_on="date",
                right_on="Date de valorisation",
                direction="backward",
            )
            if events["anchor_y"].isna().any():
                events["anchor_y"] = events["anchor_y"].fillna(tri_anchor["anchor_y"].iloc[0])

            event_styles = {
                "contribution": ("Versements", "#2ca02c", "diamond"),
                "arbitrage": ("Arbitrages", "#d62728", "x"),
                "ignored_fee": ("Frais", "#9467bd", "triangle-down"),
            }
            enabled = {
                "contribution": include_versements,
                "arbitrage": include_arbitrages,
                "ignored_fee": include_frais,
            }
            for movement_type, (label, color, symbol) in event_styles.items():
                if not enabled.get(movement_type, True):
                    continue
                subset = events[events["movement_type"] == movement_type]
                if subset.empty:
                    continue
                tri_y_values.extend(pd.to_numeric(subset["anchor_y"], errors="coerce").dropna().tolist())
                fig_tri.add_trace(
                    go.Scatter(
                        x=subset["date"],
                        y=subset["anchor_y"],
                        mode="markers",
                        name=label,
                        marker=dict(color=color, size=10, symbol=symbol),
                        customdata=subset[["label", "amount_net"]],
                        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>%{customdata[0]}<br>Montant net: %{customdata[1]:,.2f} €<extra></extra>",
                    )
                )

    fig_tri.add_hline(y=0, line_dash="dash", line_color="gray")
    fig_tri.update_layout(
        title=f"Evolution du TRI recalcule - contrat {contrat_num}",
        xaxis_title="Date de valorisation",
        yaxis_title="TRI (%)",
        hovermode="x unified",
        height=420,
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.22,
            xanchor="center",
            x=0.5,
        ),
        margin=dict(b=110),
    )
    apply_readable_yaxis(fig_tri, tri_y_values, min_abs_margin=0.25, clamp_min_zero=False, min_span=0.5)
    return fig_tri


def build_composition_figures(
    df_allocations_client: pd.DataFrame,
    mapping_path: Path | None = None,
) -> tuple[pd.DataFrame, go.Figure | None, go.Figure | None, go.Figure | None]:
    """Construit les graphiques donut de composition (typologie, typologie simplifiée et supports)."""
    if df_allocations_client is None or df_allocations_client.empty:
        return pd.DataFrame(), None, None, None

    cfg_path = mapping_path or DEFAULT_MAPPING_PATH
    mapping_simplifie, support_rules = load_typage_config(cfg_path)
    df_alloc_work = df_allocations_client.copy()
    if 'Encours en €' in df_alloc_work.columns:
        df_alloc_work['Encours en €'] = pd.to_numeric(df_alloc_work['Encours en €'], errors='coerce').fillna(0.0)

    df_alloc_work['Type simplifié'] = df_alloc_work.apply(
        lambda row: map_simplified_type(row.get('Type'), row.get('Support'), mapping_simplifie, support_rules),
        axis=1,
    )

    fig_typologie = None
    if 'Type' in df_alloc_work.columns:
        fig_typologie = px.pie(df_alloc_work, values='Encours en €', names='Type', hole=0.5)
        fig_typologie.update_layout(title="Typologie des supports")

    fig_typologie_simplifiee = px.pie(
        df_alloc_work,
        values='Encours en €',
        names='Type simplifié',
        hole=0.5,
    )
    fig_typologie_simplifiee.update_layout(title="Typologie simplifiée des supports")

    fig_supports = None
    if 'Support' in df_alloc_work.columns:
        fig_supports = px.pie(df_alloc_work, values='Encours en €', names='Support', hole=0.5)
        fig_supports.update_layout(title="Répartition par support")

    return df_alloc_work, fig_typologie, fig_typologie_simplifiee, fig_supports


def prepare_portfolio_lines_table(
    df_allocations_client: pd.DataFrame,
    mapping_path: Path | None = None,
) -> tuple[pd.DataFrame, list[list[str]], list[str] | None, dict[str, Any]]:
    """Prépare le tableau des lignes du portefeuille groupé par type simplifié.

    Retourne :
      - df_display : DataFrame nettoyé et trié avec colonnes :
          ['Type (simplifié)', 'Nom du support', 'Code ISIN', 'Encours (€)', 'Évolution (%)']
      - rows : liste des lignes formatées en string pour l'export PPTX
      - total_row : ligne de total formatée [Type, Nom, ISIN, Encours, Évolution]
      - meta : dictionnaire avec kpis (total_encours, total_pct, n_supports, n_types)
    """
    if df_allocations_client is None or df_allocations_client.empty:
        empty_df = pd.DataFrame(
            columns=["Type (simplifié)", "Nom du support", "Code ISIN", "Encours (€)", "Évolution (%)"]
        )
        return empty_df, [], None, {"total_encours": 0.0, "total_pct": 0.0, "n_supports": 0, "n_types": 0}

    cfg_path = mapping_path or DEFAULT_MAPPING_PATH
    mapping_simplifie, support_rules = load_typage_config(cfg_path)
    work = df_allocations_client.copy()

    # Nettoyage Encours
    enc_col = "Encours en €" if "Encours en €" in work.columns else "Encours"
    if enc_col in work.columns:
        work["encours_clean"] = pd.to_numeric(
            work[enc_col].astype(str).str.replace(" ", "").str.replace(",", "."),
            errors="coerce",
        ).fillna(0.0)
    else:
        work["encours_clean"] = 0.0

    # Type simplifié
    if "Type simplifié" not in work.columns:
        work["Type simplifié"] = work.apply(
            lambda row: map_simplified_type(row.get("Type"), row.get("Support"), mapping_simplifie, support_rules),
            axis=1,
        )
    work["type_clean"] = work["Type simplifié"].fillna("Autre").astype(str).str.strip()
    work.loc[work["type_clean"] == "", "type_clean"] = "Autre"

    # Nom du support
    nom_col = "Support" if "Support" in work.columns else "Nom"
    if nom_col in work.columns:
        work["nom_clean"] = work[nom_col].fillna("").astype(str).str.strip()
    else:
        work["nom_clean"] = ""

    # Code ISIN
    isin_col = "Code ISIN" if "Code ISIN" in work.columns else "ISIN"
    if isin_col in work.columns:
        work["isin_clean"] = work[isin_col].fillna("-").astype(str).str.strip()
    else:
        work["isin_clean"] = "-"
    work.loc[work["isin_clean"].isin(["", "nan", "None", "<NA>"]), "isin_clean"] = "-"

    # Évolution en %
    pct_col = None
    for c in ["+/- value (en %))", "+/- value (en %)", "Evolution %", "Performance %"]:
        if c in work.columns:
            pct_col = c
            break
    if pct_col:
        work["pct_clean"] = pd.to_numeric(
            work[pct_col].astype(str).str.replace(" ", "").str.replace(",", ".").str.replace("%", ""),
            errors="coerce",
        ).fillna(0.0)
    else:
        work["pct_clean"] = 0.0

    # Plus / Moins-value en €
    pv_col = "+/- value (en €)" if "+/- value (en €)" in work.columns else None
    if pv_col:
        work["pv_eur_clean"] = pd.to_numeric(
            work[pv_col].astype(str).str.replace(" ", "").str.replace(",", "."),
            errors="coerce",
        ).fillna(0.0)
    else:
        work["pv_eur_clean"] = 0.0

    # Groupement : on ordonne les catégories par leur encours total décroissant,
    # puis à l'intérieur de chaque catégorie par encours décroissant
    type_totals = work.groupby("type_clean")["encours_clean"].sum().to_dict()
    work["type_total"] = work["type_clean"].map(type_totals)
    work = work.sort_values(
        by=["type_total", "type_clean", "encours_clean"],
        ascending=[False, True, False],
    ).reset_index(drop=True)

    df_display = pd.DataFrame(
        {
            "Type (simplifié)": work["type_clean"],
            "Nom du support": work["nom_clean"],
            "Code ISIN": work["isin_clean"],
            "Encours (€)": work["encours_clean"],
            "Évolution (%)": work["pct_clean"],
        }
    )

    total_encours = float(work["encours_clean"].sum())
    total_pv = float(work["pv_eur_clean"].sum())
    total_investi = total_encours - total_pv

    if total_pv != 0.0 and total_investi > 0:
        total_pct = (total_pv / total_investi) * 100.0
    elif total_encours > 0:
        total_pct = float((work["encours_clean"] * work["pct_clean"]).sum() / total_encours)
    else:
        total_pct = 0.0

    n_supports = len(df_display)
    n_types = int(work["type_clean"].nunique())

    rows = [
        [
            str(r["Type (simplifié)"]),
            str(r["Nom du support"]),
            str(r["Code ISIN"]),
            f"{float(r['Encours (€)']):,.0f} €".replace(",", " "),
            f"{float(r['Évolution (%)']):+.2f} %",
        ]
        for _, r in df_display.iterrows()
    ]

    total_row = [
        "Total",
        f"{n_supports} supports",
        "-",
        f"{total_encours:,.0f} €".replace(",", " "),
        f"{total_pct:+.2f} %",
    ]

    meta = {
        "total_encours": total_encours,
        "total_pct": total_pct,
        "n_supports": n_supports,
        "n_types": n_types,
    }

    return df_display, rows, total_row, meta


def build_contract_waterfall_figure(
    df_contrats_all: pd.DataFrame,
    df_allocations_all: pd.DataFrame,
    df_contrat_selected: pd.DataFrame,
    contrat_num: str,
    source_context: dict[str, object],
    add_reduction_ir: bool | None = None,
    ir_num: float = 0.30,
) -> go.Figure | None:
    """Construit le waterfall de performance du contrat (avec avantage fiscal 30% auto pour les PER)."""
    if df_contrat_selected is None or df_contrat_selected.empty or df_allocations_all is None:
        return None

    is_per_contract = (
        'Enveloppe' in df_contrat_selected.columns
        and 'PER' in str(df_contrat_selected['Enveloppe'].iloc[0]).upper()
    )
    if add_reduction_ir is None:
        effective_add_ir = is_per_contract
        effective_ir = float(ir_num) if is_per_contract else 0.0
    else:
        effective_add_ir = bool(add_reduction_ir) and is_per_contract
        effective_ir = float(ir_num) if effective_add_ir else 0.0

    df_contrats = df_contrats_all.copy()
    df_summary_allocations = df_allocations_all[~df_allocations_all['Type'].isin(["Fonds en Euros"])].copy()
    df_summary_allocations['+/- value (en €)'] = pd.to_numeric(
        df_summary_allocations['+/- value (en €)'], errors='coerce'
    ).fillna(0.0)
    df_summary_allocations = (
        df_summary_allocations.groupby('Numéro contrat')['+/- value (en €)'].sum().reset_index()
    )

    df_contrats_upd = pd.merge(
        df_contrats,
        df_summary_allocations,
        how='left',
        left_on='N° de contrat',
        right_on='Numéro contrat',
    )
    for c in [
        'Montant total des versements bruts',
        'Montant total des versements nets',
        'Valorisation',
        'Performance financière en euros (perf du contrat)',
    ]:
        if c in df_contrats_upd.columns:
            cleaned_s = (
                df_contrats_upd[c]
                .astype(str)
                .str.replace('\u202f', '', regex=False)
                .str.replace('\xa0', '', regex=False)
                .str.replace(' ', '', regex=False)
                .str.replace(',', '.', regex=False)
            )
            df_contrats_upd[c] = pd.to_numeric(cleaned_s, errors='coerce').fillna(0.0)

    df_contrats_upd['+/- value (en €)'] = pd.to_numeric(
        df_contrats_upd['+/- value (en €)'], errors='coerce'
    ).fillna(0.0)
    df_contrats_upd['Performance embarquée'] = (
        df_contrats_upd['Performance financière en euros (perf du contrat)'] - df_contrats_upd['+/- value (en €)']
    )
    df_contrats_upd.rename(columns={'+/- value (en €)': 'Performance allocation'}, inplace=True)

    if 'Frais' not in df_contrats_upd.columns:
        if (
            'Montant total des versements bruts' in df_contrats_upd.columns
            and 'Montant total des versements nets' in df_contrats_upd.columns
        ):
            df_contrats_upd['Frais'] = -(
                pd.to_numeric(df_contrats_upd['Montant total des versements bruts'], errors='coerce').fillna(0.0)
                - pd.to_numeric(df_contrats_upd['Montant total des versements nets'], errors='coerce').fillna(0.0)
            )
        else:
            df_contrats_upd['Frais'] = 0.0

    if (
        source_context.get('source_effective') == "Releve d'operations TRI"
        and source_context.get('gross_used') is not None
        and source_context.get('net_used') is not None
    ):
        mask_contrat = df_contrats_upd['N° de contrat'].astype(str) == str(contrat_num)
        if mask_contrat.any():
            gross_used = float(source_context['gross_used'])
            net_used = float(source_context['net_used'])
            df_contrats_upd.loc[mask_contrat, 'Montant total des versements bruts'] = gross_used
            df_contrats_upd.loc[mask_contrat, 'Montant total des versements nets'] = net_used
            df_contrats_upd.loc[mask_contrat, 'Frais'] = net_used - gross_used
            df_contrats_upd.loc[mask_contrat, 'Performance financière en euros (perf du contrat)'] = (
                df_contrats_upd.loc[mask_contrat, 'Valorisation'] - net_used
            )
            df_contrats_upd.loc[mask_contrat, 'Performance embarquée'] = (
                df_contrats_upd.loc[mask_contrat, 'Performance financière en euros (perf du contrat)']
                - df_contrats_upd.loc[mask_contrat, 'Performance allocation']
            )

    df_client_waterfall, measure = generate_contrats_waterfall(
        df_contrats_upd, contrat_num, effective_add_ir, effective_ir
    )
    if df_client_waterfall.empty:
        return None

    fig = go.Figure(
        go.Waterfall(
            name="20",
            orientation="v",
            measure=measure,
            x=df_client_waterfall['variable'],
            textposition="auto",
            text=df_client_waterfall['value'].apply(lambda x: str(int(round(x, 0))) if pd.notna(x) else ''),
            y=df_client_waterfall['value'],
            connector={"line": {"color": "rgb(63, 63, 63)"}},
            cliponaxis=False,
        )
    )
    if effective_add_ir:
        title = f"Situation contrat PER (avec avantage fiscal {int(round(effective_ir * 100))}%)"
    else:
        title = "Situation contrat"
    fig.update_layout(title=title, showlegend=False)
    return fig


def build_allocation_waterfall_figure(
    df_allocations_all: pd.DataFrame,
    contrat_num: str,
) -> go.Figure | None:
    """Construit le waterfall de performance de l'allocation par support."""
    if df_allocations_all is None or df_allocations_all.empty:
        return None

    df_alloc_ctr = df_allocations_all[df_allocations_all['Numéro contrat'] == contrat_num].copy()
    if df_alloc_ctr.empty:
        return None

    df_allocations_waterfall = generate_allocations_waterfall(df_allocations_all.copy(), contrat_num)
    if df_allocations_waterfall.empty:
        return None

    if '+/- value (en €)' in df_allocations_waterfall.columns:
        s_val = (
            df_allocations_waterfall['+/- value (en €)']
            .astype(str)
            .str.replace('\u202f', '', regex=False)
            .str.replace('\xa0', '', regex=False)
            .str.replace(' ', '', regex=False)
            .str.replace(',', '.', regex=False)
        )
        df_allocations_waterfall['+/- value (en €)'] = pd.to_numeric(s_val, errors='coerce').fillna(0.0)

    fig = go.Figure(
        go.Waterfall(
            name="20",
            orientation="v",
            measure=df_allocations_waterfall['measure'],
            x=df_allocations_waterfall['Support'],
            textposition="auto",
            text=df_allocations_waterfall['+/- value (en €)'].apply(
                lambda x: str(int(round(x, 0))) if pd.notna(x) else ''
            ),
            y=df_allocations_waterfall['+/- value (en €)'],
            connector={"line": {"color": "rgb(63, 63, 63)"}},
            cliponaxis=False,
        )
    )
    fig.update_layout(title="Performance allocation", showlegend=False)
    return fig


def load_latest_fund_perf_file(fonds_dir: str | Path | None = None) -> tuple[pd.DataFrame, str | None]:
    """Charge le fichier CSV de performances quotidiennes (*Top*.csv) le plus récent."""
    target_dir = str(fonds_dir or REAL_DATA_FONDS_PATH)
    try:
        top_files = glob.glob(os.path.join(target_dir, "*Top*.csv"))
    except Exception:
        top_files = []

    if not top_files:
        return pd.DataFrame(), None

    latest_file = max(top_files, key=os.path.getmtime)
    try:
        df_perfs = pd.read_csv(latest_file, sep=';', decimal=',', encoding='latin-1')
    except UnicodeDecodeError:
        df_perfs = pd.read_csv(latest_file, sep=';', decimal=',', encoding='utf-8', errors='ignore')

    df_perfs['Date'] = pd.to_datetime(df_perfs['Date'], format='%d/%m/%Y', errors='coerce')
    if df_perfs['Rendement'].dtype == 'object':
        df_perfs['Rendement'] = df_perfs['Rendement'].astype(str).str.replace(',', '.', regex=False).astype(float)
    df_perfs = df_perfs.dropna(subset=['Date']).sort_values('Date')
    return df_perfs, latest_file


def prepare_contract_fund_perf_data(
    df_perfs: pd.DataFrame,
    df_alloc_ctr: pd.DataFrame,
    date_debut,
    date_fin,
    mapping_path: Path | None = None,
) -> dict[str, object]:
    """Prépare les séries base 100 des fonds du contrat et leur rattachement aux classes d'actifs simplifiées."""
    empty_result: dict[str, object] = {
        "df_perf_ctr": pd.DataFrame(),
        "isins_dispo": [],
        "missing_labels": [],
        "type_order": [],
    }
    if df_perfs.empty or df_alloc_ctr.empty or 'Code ISIN' not in df_alloc_ctr.columns:
        return empty_result

    cfg_path = mapping_path or DEFAULT_MAPPING_PATH
    mapping_simplifie, support_rules = load_typage_config(cfg_path)

    df_alloc_work = df_alloc_ctr.copy()
    df_alloc_work['Type simplifié'] = df_alloc_work.apply(
        lambda row: map_simplified_type(row.get('Type'), row.get('Support'), mapping_simplifie, support_rules),
        axis=1,
    )
    if 'Encours en €' in df_alloc_work.columns:
        df_alloc_work['Encours en €'] = pd.to_numeric(df_alloc_work['Encours en €'], errors='coerce').fillna(0.0)
    else:
        df_alloc_work['Encours en €'] = 0.0

    isins_ctr = set(df_alloc_work['Code ISIN'].dropna().astype(str).str.strip().unique()) - {''}
    if not isins_ctr:
        return empty_result

    map_isin_nom_alloc = pd.Series(dtype=object)
    if 'Support' in df_alloc_work.columns:
        map_isin_nom_alloc = (
            df_alloc_work[['Code ISIN', 'Support']]
            .dropna(subset=['Code ISIN'])
            .drop_duplicates(subset=['Code ISIN'])
            .set_index('Code ISIN')['Support']
        )

    map_isin_type = (
        df_alloc_work[['Code ISIN', 'Type simplifié']]
        .dropna(subset=['Code ISIN'])
        .drop_duplicates(subset=['Code ISIN'])
        .set_index('Code ISIN')['Type simplifié']
    )

    map_isin_nom = (
        df_perfs[['Code ISIN', 'Nom']]
        .dropna(subset=['Code ISIN'])
        .drop_duplicates(subset=['Code ISIN'])
        .set_index('Code ISIN')['Nom']
    )

    perfs_isins = set(df_perfs['Code ISIN'].dropna().astype(str).str.strip().unique())
    isins_dispo = [i for i in isins_ctr if i in perfs_isins]
    manq = isins_ctr.difference(isins_dispo)
    missing_labels = []
    for isin in sorted(manq):
        nom = map_isin_nom_alloc.get(isin, map_isin_nom.get(isin, "Nom inconnu"))
        missing_labels.append(f"{isin} - {nom}")

    if not isins_dispo:
        empty_result["missing_labels"] = missing_labels
        return empty_result

    start_ts = pd.to_datetime(date_debut)
    end_ts = pd.to_datetime(date_fin)
    df_sel = df_perfs[df_perfs['Code ISIN'].isin(isins_dispo)]
    df_periode = df_sel[(df_sel['Date'] >= start_ts) & (df_sel['Date'] <= end_ts)].copy()

    perf_list = []
    for isin in isins_dispo:
        d = df_periode[df_periode['Code ISIN'] == isin].copy()
        if d.empty:
            continue
        d['Valeur_cumul'] = (1 + d['Rendement']).cumprod()
        base = d['Valeur_cumul'].iloc[0]
        if pd.isna(base) or base == 0:
            continue
        d['Performance_base_100'] = (d['Valeur_cumul'] / base) * 100
        d['Nom_fonds'] = map_isin_nom.get(isin, map_isin_nom_alloc.get(isin, isin))
        d['Type simplifié'] = map_isin_type.get(isin, 'Allocation flexible')
        perf_list.append(d)

    if not perf_list:
        empty_result["isins_dispo"] = isins_dispo
        empty_result["missing_labels"] = missing_labels
        return empty_result

    df_perf_ctr = pd.concat(perf_list, ignore_index=True)

    # Ordonner les classes d'actifs présentes par encours décroissant dans le contrat
    present_types = set(df_perf_ctr['Type simplifié'].dropna().unique())
    encours_by_type = (
        df_alloc_work[df_alloc_work['Type simplifié'].isin(present_types)]
        .groupby('Type simplifié')['Encours en €']
        .sum()
        .sort_values(ascending=False)
    )
    type_order = encours_by_type.index.tolist()
    for t in sorted(present_types):
        if t not in type_order:
            type_order.append(t)

    return {
        "df_perf_ctr": df_perf_ctr,
        "isins_dispo": isins_dispo,
        "missing_labels": missing_labels,
        "type_order": type_order,
    }


def build_fund_evolution_figure(
    df_perf_subset: pd.DataFrame,
    title: str,
    tri_analysis: dict | None = None,
    date_debut=None,
    date_fin=None,
    show_versements: bool = True,
    show_arbitrages: bool = True,
    height: int = 500,
    color_map: dict[str, str] | None = None,
) -> go.Figure | None:
    """Construit un graphique base 100 pour un sous-ensemble de fonds avec versements/arbitrages."""
    if df_perf_subset is None or df_perf_subset.empty:
        return None

    fig = go.Figure()
    colors = px.colors.qualitative.T10
    for i, name in enumerate(sorted(df_perf_subset['Nom_fonds'].unique())):
        d = df_perf_subset[df_perf_subset['Nom_fonds'] == name]
        line_color = color_map[name] if (color_map and name in color_map) else colors[i % len(colors)]
        fig.add_trace(
            go.Scatter(
                x=d['Date'],
                y=d['Performance_base_100'],
                mode='lines',
                name=name,
                line=dict(color=line_color, width=2),
                hovertemplate='<b>%{x|%d/%m/%Y}</b><br>Performance: %{y:.2f}<extra></extra>',
            )
        )

    movements = tri_analysis.get("movements") if tri_analysis is not None else None
    if movements is not None and not movements.empty and (show_versements or show_arbitrages):
        mv = movements.copy()
        mv['date'] = pd.to_datetime(mv['date'], errors='coerce').dt.normalize()
        if 'label' not in mv.columns:
            mv['label'] = 'Mouvement'
        if 'amount_gross' not in mv.columns:
            mv['amount_gross'] = 0
        if 'amount_net' not in mv.columns:
            mv['amount_net'] = 0
        mv = mv.dropna(subset=['date'])
        if date_debut is not None:
            mv = mv[mv['date'] >= pd.to_datetime(date_debut)]
        if date_fin is not None:
            mv = mv[mv['date'] <= pd.to_datetime(date_fin)]

        y_min = pd.to_numeric(df_perf_subset['Performance_base_100'], errors='coerce').min()
        y_evt = float(y_min) - 0.25 if pd.notna(y_min) else 99.5

        if show_versements:
            mv_contrib = mv[mv['movement_type'] == 'contribution'].copy()
            if not mv_contrib.empty:
                mv_contrib['amount_gross'] = pd.to_numeric(mv_contrib['amount_gross'], errors='coerce').fillna(0)
                mv_contrib['amount_net'] = pd.to_numeric(mv_contrib['amount_net'], errors='coerce').fillna(0)
                fig.add_trace(
                    go.Scatter(
                        x=mv_contrib['date'],
                        y=[y_evt] * len(mv_contrib),
                        mode='markers',
                        name='Versements',
                        marker=dict(symbol='triangle-up', size=10, color='#2ca02c', line=dict(width=1, color='#1f7a1f')),
                        customdata=mv_contrib[['label', 'amount_gross', 'amount_net']],
                        hovertemplate='<b>%{x|%d/%m/%Y}</b><br>%{customdata[0]}<br>Brut: %{customdata[1]:,.0f} €<br>Net: %{customdata[2]:,.0f} €<extra></extra>',
                    )
                )

        if show_arbitrages:
            mv_arb = mv[mv['movement_type'] == 'arbitrage'].copy()
            if not mv_arb.empty:
                mv_arb['amount_net'] = pd.to_numeric(mv_arb['amount_net'], errors='coerce').fillna(0)
                fig.add_trace(
                    go.Scatter(
                        x=mv_arb['date'],
                        y=[y_evt - 0.12] * len(mv_arb),
                        mode='markers',
                        name='Arbitrages',
                        marker=dict(symbol='diamond', size=9, color='#ff7f0e', line=dict(width=1, color='#c65f00')),
                        customdata=mv_arb[['label', 'amount_net']],
                        hovertemplate='<b>%{x|%d/%m/%Y}</b><br>%{customdata[0]}<br>Montant: %{customdata[1]:,.0f} €<extra></extra>',
                    )
                )

    fig.add_hline(y=100, line_dash='dash', line_color='gray', annotation_text='Base 100', annotation_position='top right')
    fig.update_layout(
        title=title,
        xaxis_title='Date',
        yaxis_title='Performance (base 100)',
        hovermode='x unified',
        height=height,
    )
    return fig


def build_contract_and_class_fund_figures(
    df_perfs: pd.DataFrame,
    df_alloc_ctr: pd.DataFrame,
    contrat_num: str,
    date_debut,
    date_fin,
    tri_analysis: dict | None = None,
    show_versements: bool = True,
    show_arbitrages: bool = True,
    mapping_path: Path | None = None,
) -> dict[str, object]:
    """Construit le graphique d'évolution de tous les fonds du contrat et ceux par classe d'actifs simplifiée."""
    prep = prepare_contract_fund_perf_data(
        df_perfs=df_perfs,
        df_alloc_ctr=df_alloc_ctr,
        date_debut=date_debut,
        date_fin=date_fin,
        mapping_path=mapping_path,
    )
    df_perf_ctr = prep["df_perf_ctr"]
    if df_perf_ctr.empty:
        return {
            **prep,
            "fig_all_funds": None,
            "figures_by_class": [],
        }

    palette = px.colors.qualitative.T10
    color_map = {
        name: palette[i % len(palette)]
        for i, name in enumerate(sorted(df_perf_ctr['Nom_fonds'].unique()))
    }
    start_str = pd.to_datetime(date_debut).strftime('%d/%m/%Y')
    fig_all_funds = build_fund_evolution_figure(
        df_perf_subset=df_perf_ctr,
        title=f"Fonds du contrat {contrat_num} (base 100 au {start_str})",
        tri_analysis=tri_analysis,
        date_debut=date_debut,
        date_fin=date_fin,
        show_versements=show_versements,
        show_arbitrages=show_arbitrages,
        height=500,
        color_map=color_map,
    )

    figures_by_class: list[tuple[str, go.Figure]] = []
    for asset_class in prep["type_order"]:
        df_cls = df_perf_ctr[df_perf_ctr['Type simplifié'] == asset_class]
        if df_cls.empty:
            continue
        fig_cls = build_fund_evolution_figure(
            df_perf_subset=df_cls,
            title=f"Fonds {asset_class} — contrat {contrat_num} (base 100 au {start_str})",
            tri_analysis=tri_analysis,
            date_debut=date_debut,
            date_fin=date_fin,
            show_versements=show_versements,
            show_arbitrages=show_arbitrages,
            height=460,
            color_map=color_map,
        )
        if fig_cls is not None:
            figures_by_class.append((asset_class, fig_cls))

    return {
        **prep,
        "fig_all_funds": fig_all_funds,
        "figures_by_class": figures_by_class,
    }