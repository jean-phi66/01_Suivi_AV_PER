from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from tri_integration import build_contract_tri_history


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
    gross_csv = float(df_contrat_selected['Montant total des versements bruts'].iloc[0]) if 'Montant total des versements bruts' in df_contrat_selected.columns else 0.0
    net_csv = float(df_contrat_selected['Montant total des versements nets'].iloc[0]) if 'Montant total des versements nets' in df_contrat_selected.columns else 0.0

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
):
    required_cols = ['N° de contrat', 'Date de valorisation', 'Valorisation', 'Titulaire(s)']
    missing_historical = [col for col in required_cols if col not in df_historical_for_contract.columns]
    missing_current = [col for col in required_cols if col not in df_current_for_contract.columns]
    if missing_historical or missing_current:
        return None

    df_historical_for_plot = df_historical_for_contract[required_cols].copy()
    df_current_for_plot = df_current_for_contract[required_cols].copy()
    df_combined_plot_data = pd.concat([df_historical_for_plot, df_current_for_plot], ignore_index=True)
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
                        if ('Enveloppe' in df_current_for_contract.columns and df_current_for_contract['Enveloppe'].iloc[0] == "PER") and add_reduction_ir:
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
        if ('Enveloppe' in df_current_for_contract.columns and df_current_for_contract['Enveloppe'].iloc[0] == "PER") and add_reduction_ir:
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

    apply_readable_yaxis(fig_evol, y_values_for_scale)
    return fig_evol


def build_tri_figure(
    df_historical_for_contract: pd.DataFrame,
    df_current_for_contract: pd.DataFrame,
    contrat_num: str,
    tri_analysis: dict | None,
):
    if tri_analysis is None:
        return None

    tri_history_source = pd.concat(
        [
            df_historical_for_contract[["N° de contrat", "Date de valorisation", "Valorisation"]],
            df_current_for_contract[["N° de contrat", "Date de valorisation", "Valorisation"]],
        ],
        ignore_index=True,
    )
    tri_history_source = tri_history_source.drop_duplicates(subset=["N° de contrat", "Date de valorisation"], keep="last")
    tri_history = build_contract_tri_history(tri_analysis, tri_history_source)
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
            for movement_type, (label, color, symbol) in event_styles.items():
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
    )
    apply_readable_yaxis(fig_tri, tri_y_values, min_abs_margin=0.25, clamp_min_zero=False, min_span=0.5)
    return fig_tri