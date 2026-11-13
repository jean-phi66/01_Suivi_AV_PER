"""
Module d'aide au calcul et à la visualisation des projections long terme pour les contrats d'assurance-vie et PER.
Permet de resituer l'historique et de projeter la valorisation future selon plusieurs scénarios de rendement
en intégrant les frais (contrat, supports, versements) et les versements programmés.
"""

from __future__ import annotations

import datetime
import io
from typing import Any

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from pptx_report_generator import convert_figure_to_png_bytes


# Palette de couleurs corporate claire et harmonieuse
COLOR_PRUDENT = "#D97706"     # Ambre / Orange chaleureux
COLOR_EQUILIBRE = "#2563EB"   # Bleu royal institutionnel (scénario central)
COLOR_DYNAMIQUE = "#059669"   # Vert émeraude performant
COLOR_CUSTOM = "#7C3AED"      # Violet pour scénario personnalisé
COLOR_HISTORICAL = "#0F172A"  # Ardoise foncée / Noir d'encre pour l'historique réel
COLOR_CAPITAL = "#64748B"     # Gris ardoise pour les versements
COLOR_PER_EFFORT = "#EA580C"  # Orange vif pour effort d'épargne après avantage fiscal
COLOR_FEES = "#DC2626"        # Rouge doux pour les frais
COLOR_CARD_BG = "#F8FAFC"


def detect_default_monthly_contribution(
    tri_analysis: dict | None = None,
    df_contrat_selected: pd.DataFrame | None = None,
) -> float:
    """Détecte le montant mensuel habituel des versements programmés depuis le contrat CSV ou le relevé TRI."""
    # 1. Vérification prioritaire dans la fiche contrat (données officielles assureur / CSV)
    if df_contrat_selected is not None and not df_contrat_selected.empty:
        if "Montant VP" in df_contrat_selected.columns:
            amt_raw = df_contrat_selected["Montant VP"].iloc[0]
            if pd.notna(amt_raw):
                try:
                    amt_num = float(str(amt_raw).replace(" ", "").replace(",", "."))
                    if amt_num > 0:
                        perio = "mois"
                        if "Periodicité VP" in df_contrat_selected.columns:
                            p_raw = str(df_contrat_selected["Periodicité VP"].iloc[0]).strip().lower()
                            if p_raw:
                                perio = p_raw
                        if "trim" in perio:
                            return round(amt_num / 3.0, 2)
                        elif "sem" in perio:
                            return round(amt_num / 6.0, 2)
                        elif "an" in perio:
                            return round(amt_num / 12.0, 2)
                        else:
                            return amt_num
                except (ValueError, TypeError):
                    pass

    # 2. Vérification dans les mouvements du relevé d'opérations TRI
    if tri_analysis and "movements" in tri_analysis:
        movements = tri_analysis.get("movements")
        if movements is not None and isinstance(movements, pd.DataFrame) and not movements.empty:
            if "operation_subtype" in movements.columns:
                vp = movements[movements["operation_subtype"] == "Versement programmé"]
                if not vp.empty:
                    last_amt = vp["amount_gross"].iloc[-1]
                    if pd.notna(last_amt) and float(last_amt) > 0:
                        return float(last_amt)

            # Repli sur le libellé
            if "label" in movements.columns and "amount_gross" in movements.columns:
                vp_mask = movements["label"].astype(str).str.upper().str.contains("PROGRAMM", na=False)
                vp = movements[vp_mask]
                if not vp.empty:
                    last_amt = vp["amount_gross"].iloc[-1]
                    if pd.notna(last_amt) and float(last_amt) > 0:
                        return float(last_amt)

    return 0.0


def detect_initial_contribution(
    df_contrat_selected: pd.DataFrame | None = None,
    tri_analysis: dict | None = None,
    historical_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """
    Détecte la date et les montants net et brut du premier versement (souscription / versement initial).
    Priorité :
    1. Relevé d'opérations TRI (mouvements 'contribution' ordonnés par date)
    2. Relevé TRI (date d'ouverture et totaux versements bruts/nets)
    3. Fiche contrat sélectionné ('Ouverture', 'Montant total des versements bruts/nets')
    4. Historique de valorisation agrégé ('Date de valorisation', 'Valorisation')
    """
    initial_date: datetime.date | None = None
    initial_amount_gross: float | None = None
    initial_amount_net: float | None = None
    source = "défaut (estimation)"
    first_label = "Souscription / 1er versement"

    # 1. Depuis les mouvements du relevé TRI
    if tri_analysis and "movements" in tri_analysis:
        m = tri_analysis.get("movements")
        if m is not None and isinstance(m, pd.DataFrame) and not m.empty:
            contribs = (
                m[m.get("movement_type", pd.Series(dtype=str)) == "contribution"]
                if "movement_type" in m.columns
                else pd.DataFrame()
            )
            if not contribs.empty:
                c_sorted = contribs.sort_values("date")
                first_row = c_sorted.iloc[0]
                if pd.notna(first_row.get("date")):
                    initial_date = pd.to_datetime(first_row["date"]).date()
                amt_g = first_row.get("amount_gross")
                amt_n = first_row.get("amount_net")
                if pd.notna(amt_g) and amt_g is not None and float(amt_g) > 0:
                    initial_amount_gross = float(amt_g)
                if pd.notna(amt_n) and amt_n is not None and float(amt_n) > 0:
                    initial_amount_net = float(amt_n)
                lbl = str(first_row.get("label", "")).strip()
                if lbl:
                    first_label = lbl
                source = f"relevé TRI ({first_label})"

    # 2. Depuis les métadonnées globales du relevé TRI
    if tri_analysis:
        if initial_date is None and tri_analysis.get("opening_date"):
            raw_open = tri_analysis["opening_date"]
            if pd.notna(raw_open):
                initial_date = pd.to_datetime(raw_open).date()
                source = "relevé TRI (date ouverture)"
        if initial_amount_gross is None:
            g_tot = tri_analysis.get("gross_payments_total")
            if g_tot is not None and pd.notna(g_tot) and float(g_tot) > 0:
                initial_amount_gross = float(g_tot)
        if initial_amount_net is None:
            n_tot = tri_analysis.get("net_payments_total")
            if n_tot is not None and pd.notna(n_tot) and float(n_tot) > 0:
                initial_amount_net = float(n_tot)

    # 3. Depuis la fiche contrat
    if df_contrat_selected is not None and not df_contrat_selected.empty:
        if initial_date is None and "Ouverture" in df_contrat_selected.columns:
            raw_op = df_contrat_selected["Ouverture"].iloc[0]
            if pd.notna(raw_op):
                initial_date = pd.to_datetime(raw_op).date()
                source = "fiche contrat (date ouverture)"
        if initial_amount_gross is None and "Montant total des versements bruts" in df_contrat_selected.columns:
            raw_val = df_contrat_selected["Montant total des versements bruts"].iloc[0]
            if pd.notna(raw_val) and float(raw_val) > 0:
                initial_amount_gross = float(raw_val)
        if initial_amount_net is None and "Montant total des versements nets" in df_contrat_selected.columns:
            raw_val = df_contrat_selected["Montant total des versements nets"].iloc[0]
            if pd.notna(raw_val) and float(raw_val) > 0:
                initial_amount_net = float(raw_val)
        if initial_amount_net is None and initial_amount_gross is None and "Valorisation" in df_contrat_selected.columns:
            raw_val = df_contrat_selected["Valorisation"].iloc[0]
            if pd.notna(raw_val) and float(raw_val) > 0:
                initial_amount_net = float(raw_val)
                initial_amount_gross = float(raw_val)

    # 4. Depuis l'historique d'agrégation
    if historical_df is not None and not historical_df.empty:
        if "Date de valorisation" in historical_df.columns and "Valorisation" in historical_df.columns:
            h = historical_df.dropna(subset=["Date de valorisation", "Valorisation"]).sort_values("Date de valorisation")
            if not h.empty:
                if initial_date is None:
                    initial_date = pd.to_datetime(h["Date de valorisation"].iloc[0]).date()
                    source = "historique aggregé"
                if initial_amount_net is None:
                    initial_amount_net = float(h["Valorisation"].iloc[0])

    # Cohérence finale
    if initial_amount_gross is None and initial_amount_net is not None:
        initial_amount_gross = initial_amount_net
    elif initial_amount_net is None and initial_amount_gross is not None:
        initial_amount_net = initial_amount_gross * 0.98
    elif initial_amount_gross is None and initial_amount_net is None:
        initial_amount_gross = 10000.0
        initial_amount_net = 9800.0

    if initial_date is None:
        initial_date = datetime.date.today() - datetime.timedelta(days=365 * 3)

    return {
        "initial_date": initial_date,
        "initial_amount_net": initial_amount_net,
        "initial_amount_gross": initial_amount_gross,
        "initial_amount": initial_amount_net,  # La projection débute sur le versement initial net
        "source": source,
        "first_label": first_label,
    }


def detect_contract_fee_rate(
    df_contrat_selected: pd.DataFrame | None,
    df_allocations_client: pd.DataFrame | None,
) -> tuple[float, float, float]:
    """
    Détecte ou estime les taux de frais annuels du contrat et des supports :
    Renvoie (frais_contrat_pct, frais_supports_pct, frais_versement_pct).
    """
    frais_contrat = 0.60
    frais_supports = 0.90
    frais_versement = 0.0

    # Détection enveloppe pour frais contrat par défaut
    if df_contrat_selected is not None and not df_contrat_selected.empty:
        env = str(df_contrat_selected.get("Enveloppe", pd.Series([""])).iloc[0]).upper()
        if "SPIRICA" in str(df_contrat_selected.get("Partenaire", pd.Series([""])).iloc[0]).upper():
            frais_contrat = 0.50
        elif "SURAVENIR" in str(df_contrat_selected.get("Partenaire", pd.Series([""])).iloc[0]).upper():
            frais_contrat = 0.60
        elif "GENERALI" in str(df_contrat_selected.get("Partenaire", pd.Series([""])).iloc[0]).upper():
            frais_contrat = 0.70

    # Détection des frais des supports depuis df_allocations si présents
    if (
        df_allocations_client is not None
        and not df_allocations_client.empty
        and "Encours en €" in df_allocations_client.columns
    ):
        encours_total = pd.to_numeric(df_allocations_client["Encours en €"], errors="coerce").sum()
        if encours_total > 0:
            if "Frais gestion fonds" in df_allocations_client.columns:
                frais_fonds_col = pd.to_numeric(df_allocations_client["Frais gestion fonds"], errors="coerce").fillna(0)
                ponderes = (frais_fonds_col * df_allocations_client["Encours en €"]).sum() / encours_total
                if ponderes > 0:
                    frais_supports = round(float(ponderes), 2)
            elif "Type" in df_allocations_client.columns:
                # Si fonds en euros prédominant, frais de supports plus bas
                is_fonds_euro = df_allocations_client["Type"].astype(str).str.contains("Euros|Euro", case=False, na=False)
                part_euro = df_allocations_client.loc[is_fonds_euro, "Encours en €"].sum() / encours_total
                if part_euro > 0.7:
                    frais_supports = 0.0
                elif part_euro > 0.3:
                    frais_supports = 0.60

    return frais_contrat, frais_supports, frais_versement


def calculate_contract_projection(
    current_valuation: float,
    current_date: pd.Timestamp | datetime.date,
    initial_amount: float | None = None,
    initial_date: pd.Timestamp | datetime.date | None = None,
    initial_amount_gross: float | None = None,
    years: int = 8,
    monthly_contribution: float = 0.0,
    annual_contribution: float = 0.0,
    contribution_fee_pct: float = 0.0,
    contract_fee_pct: float = 1.0,
    fund_fee_pct: float = 0.0,
    scenarios: dict[str, float] | None = None,
    is_per: bool = False,
    tmi_pct: float = 30.0,
    historical_movements: pd.DataFrame | None = None,
    future_anchor_mode: str = "origin",
) -> dict[str, Any]:
    """
    Calcule la projection mensuelle et annuelle du contrat sur l'ensemble de son cycle de vie :
    - Démarre au montant du versement initial net à la date d'ouverture / 1er versement.
    - Conserve le versement initial brut comme repère de référence.
    - Reconstitue le passé jusqu'à la situation actuelle (intégrant les versements historiques).
    - Projette la valorisation future sur `years` années selon plusieurs scénarios de rendement brut
      en déduisant les frais et en comptabilisant les versements programmés et l'avantage fiscal éventuel (si PER).
    """
    if scenarios is None:
        scenarios = {
            "Prudent": 0.025,
            "Équilibré": 0.050,
            "Dynamique": 0.060,
        }

    now_dt = pd.to_datetime(current_date).normalize()
    if initial_date is None:
        start_dt = now_dt
    else:
        start_dt = pd.to_datetime(initial_date).normalize()

    if start_dt > now_dt:
        start_dt = now_dt

    # Le capital de départ de la projection est le versement initial NET investi
    if initial_amount is None or float(initial_amount) <= 0:
        init_net = float(current_valuation)
    else:
        init_net = float(initial_amount)

    if initial_amount_gross is None or float(initial_amount_gross) <= 0:
        init_gross = init_net
    else:
        init_gross = float(initial_amount_gross)

    total_annual_fee_rate = max(0.0, (contract_fee_pct + fund_fee_pct) / 100.0)
    monthly_fee_rate = total_annual_fee_rate / 12.0
    fee_on_contrib_rate = max(0.0, contribution_fee_pct / 100.0)
    tmi_rate = max(0.0, min(1.0, tmi_pct / 100.0)) if is_per else 0.0

    end_dt = now_dt + pd.DateOffset(years=max(1, int(years)))

    # Construction de la grille temporelle mensuelle
    if start_dt >= now_dt:
        dates_past = [now_dt]
        dates_future = [now_dt + pd.DateOffset(months=m) for m in range(1, int(years * 12) + 1)]
    else:
        dates_past = []
        curr = start_dt
        while curr < now_dt:
            dates_past.append(curr)
            curr = curr + pd.DateOffset(months=1)
        if not dates_past or dates_past[-1] != now_dt:
            dates_past.append(now_dt)

        dates_future = []
        curr = now_dt + pd.DateOffset(months=1)
        while curr <= end_dt:
            dates_future.append(curr)
            curr = curr + pd.DateOffset(months=1)

    date_range = dates_past + dates_future
    idx_today = len(dates_past) - 1
    total_steps = len(date_range)

    # Préparation des versements historiques (hors 1er versement initial comptabilisé à t=0)
    subsequent_contribs = pd.DataFrame()
    if historical_movements is not None and not historical_movements.empty:
        h_m = historical_movements.copy()
        if "movement_type" in h_m.columns:
            c_df = h_m[h_m["movement_type"] == "contribution"].copy()
        else:
            c_df = h_m.copy()
        if not c_df.empty and "date" in c_df.columns:
            c_df["date"] = pd.to_datetime(c_df["date"]).dt.normalize()
            c_df = c_df.sort_values("date")
            if len(c_df) > 1:
                subsequent_contribs = c_df.iloc[1:].copy()

    # Initialisation des structures
    monthly_records = []

    # États initiaux pour chaque scénario à t=0 (démarre sur le NET investi)
    scenario_vals = {name: float(init_net) for name in scenarios}
    scenario_reanchored_vals = {name: float(init_net) for name in scenarios}
    scenario_gross_vals = {name: float(init_gross) for name in scenarios}
    scenario_cumul_mgt_fees = {name: 0.0 for name in scenarios}
    scenario_cumul_gains = {name: 0.0 for name in scenarios}

    cumul_contrib_gross = float(init_gross)
    cumul_contrib_net = float(init_net)
    cumul_contrib_fees = max(0.0, float(init_gross) - float(init_net))
    cumul_tax_savings = float(init_gross) * tmi_rate
    cumul_savings_effort = float(init_gross) - cumul_tax_savings

    # Enregistrement t=0 (Date du 1er versement net)
    t0_record = {
        "Month": 0,
        "Year": 0.0,
        "Date": start_dt,
        "Is_Past": True if start_dt < now_dt else False,
        "Is_Today": True if start_dt == now_dt else False,
        "Versements_cumules": cumul_contrib_gross,
        "Versements_nets_cumules": cumul_contrib_net,
        "Frais_versements_cumules": cumul_contrib_fees,
        "Effort_epargne_cumule": cumul_savings_effort,
        "Economie_IR_cumulee": cumul_tax_savings,
    }
    for name in scenarios:
        t0_record[f"Val_{name}"] = scenario_vals[name]
        t0_record[f"ValReanchored_{name}"] = scenario_reanchored_vals[name]
        t0_record[f"ValBrute_{name}"] = scenario_gross_vals[name]
        t0_record[f"FraisGestion_{name}"] = 0.0
        t0_record[f"GainsNets_{name}"] = 0.0
    monthly_records.append(t0_record)

    # Calcul pas-à-pas de t=1 à la fin
    for step in range(1, total_steps):
        dt = date_range[step]
        prev_dt = date_range[step - 1]
        is_past = (step < idx_today)
        is_today = (step == idx_today)

        # Détermination du versement brut du mois
        if step <= idx_today:
            # Période passée / aujourd'hui : extraction des versements réels dans l'intervalle
            p_gross = 0.0
            if not subsequent_contribs.empty and "amount_gross" in subsequent_contribs.columns:
                mask = (subsequent_contribs["date"] > prev_dt) & (subsequent_contribs["date"] <= dt)
                p_gross = float(subsequent_contribs.loc[mask, "amount_gross"].fillna(0).sum())
        else:
            # Période future : versements programmés futurs
            month_future = step - idx_today
            is_year_end = (month_future % 12 == 0)
            p_gross = float(monthly_contribution) + (float(annual_contribution) if is_year_end else 0.0)

        fee_p = p_gross * fee_on_contrib_rate
        p_net = p_gross - fee_p
        tax_save = p_gross * tmi_rate
        effort_p = p_gross - tax_save

        cumul_contrib_gross += p_gross
        cumul_contrib_net += p_net
        cumul_contrib_fees += fee_p
        cumul_tax_savings += tax_save
        cumul_savings_effort += effort_p

        elapsed_years = (dt - start_dt).days / 365.25

        step_record = {
            "Month": step,
            "Year": round(elapsed_years, 2),
            "Date": dt,
            "Is_Past": is_past,
            "Is_Today": is_today,
            "Versements_cumules": cumul_contrib_gross,
            "Versements_nets_cumules": cumul_contrib_net,
            "Frais_versements_cumules": cumul_contrib_fees,
            "Effort_epargne_cumule": cumul_savings_effort,
            "Economie_IR_cumulee": cumul_tax_savings,
        }

        for name, annual_gross_rate in scenarios.items():
            r_gross_month = (1.0 + annual_gross_rate) ** (1.0 / 12.0) - 1.0

            # 1. Trajectoire théorique depuis l'origine (1er versement)
            prev_val = scenario_vals[name]
            gross_gain = prev_val * r_gross_month
            mgt_fee = prev_val * monthly_fee_rate
            net_val = prev_val + gross_gain - mgt_fee + p_net

            prev_gross_val = scenario_gross_vals[name]
            gross_gain_theorique = prev_gross_val * r_gross_month
            net_gross_val = prev_gross_val + gross_gain_theorique + p_gross

            scenario_vals[name] = max(0.0, net_val)
            scenario_gross_vals[name] = max(0.0, net_gross_val)
            scenario_cumul_mgt_fees[name] += mgt_fee
            scenario_cumul_gains[name] += (gross_gain - mgt_fee)

            # 2. Trajectoire recalée sur l'encours réel d'aujourd'hui
            if step < idx_today:
                scenario_reanchored_vals[name] = scenario_vals[name]
            elif step == idx_today:
                # Re-calibrage exact sur la valorisation actuelle à aujourd'hui
                scenario_reanchored_vals[name] = float(current_valuation)
            else:
                prev_reanc = scenario_reanchored_vals[name]
                r_gain = prev_reanc * r_gross_month
                r_fee = prev_reanc * monthly_fee_rate
                net_reanc = prev_reanc + r_gain - r_fee + p_net
                scenario_reanchored_vals[name] = max(0.0, net_reanc)

            step_record[f"Val_{name}"] = scenario_vals[name]
            step_record[f"ValReanchored_{name}"] = scenario_reanchored_vals[name]
            step_record[f"ValBrute_{name}"] = scenario_gross_vals[name]
            step_record[f"FraisGestion_{name}"] = scenario_cumul_mgt_fees[name]
            step_record[f"GainsNets_{name}"] = scenario_vals[name] - cumul_contrib_gross

        monthly_records.append(step_record)

    monthly_df = pd.DataFrame(monthly_records)

    # Extraction des jalons annuels pour tableaux et stacked area
    # Inclut l'année 0 (1er versement), les anniversaires annuels, la situation actuelle et la fin
    yearly_mask = (
        (monthly_df["Month"] == 0)
        | (monthly_df["Month"] == idx_today)
        | (monthly_df["Month"] == total_steps - 1)
        | (monthly_df["Month"] % 12 == 0)
    )
    yearly_df = monthly_df[yearly_mask].copy().drop_duplicates(subset=["Date"]).reset_index(drop=True)
    yearly_df["Annee"] = ((yearly_df["Date"] - start_dt).dt.days / 365.25).round(1)

    # Synthèse des KPIs par scénario à l'horizon
    final_row = monthly_df.iloc[-1]
    total_invested = float(final_row["Versements_cumules"])
    total_effort = float(final_row["Effort_epargne_cumule"])

    summary_by_scenario: dict[str, dict[str, Any]] = {}
    for name, rate in scenarios.items():
        v_final_origin = float(final_row[f"Val_{name}"])
        v_final_reanchored = float(final_row[f"ValReanchored_{name}"])
        v_final = v_final_origin if future_anchor_mode == "origin" else v_final_reanchored

        v_gross_final = float(final_row[f"ValBrute_{name}"])
        mgt_fees = float(final_row[f"FraisGestion_{name}"])
        total_fees = mgt_fees + cumul_contrib_fees
        net_gain = v_final - total_invested
        gain_pct = (net_gain / total_invested * 100.0) if total_invested > 0 else 0.0
        multiplier = (v_final / total_invested) if total_invested > 0 else 1.0
        fee_drag = v_gross_final - v_final
        net_annual_rate = rate - total_annual_fee_rate

        summary_by_scenario[name] = {
            "name": name,
            "gross_rate_pct": rate * 100.0,
            "net_rate_pct": net_annual_rate * 100.0,
            "final_valuation": v_final,
            "final_valuation_from_origin": v_final_origin,
            "final_valuation_reanchored": v_final_reanchored,
            "gross_valuation_without_fees": v_gross_final,
            "total_invested": total_invested,
            "total_effort_with_tax": total_effort,
            "net_gain": net_gain,
            "net_gain_pct": gain_pct,
            "total_fees_paid": total_fees,
            "mgt_fees_paid": mgt_fees,
            "contrib_fees_paid": cumul_contrib_fees,
            "fee_drag_value": fee_drag,
            "capital_multiplier": multiplier,
            "tax_savings_total": cumul_tax_savings,
        }

    elapsed_years_total = (now_dt - start_dt).days / 365.25

    return {
        "initial_amount": float(init_net),
        "initial_amount_net": float(init_net),
        "initial_amount_gross": float(init_gross),
        "initial_date": start_dt,
        "current_valuation": float(current_valuation),
        "current_date": now_dt,
        "idx_today": idx_today,
        "elapsed_years": elapsed_years_total,
        "years": years,
        "end_date": date_range[-1],
        "future_anchor_mode": future_anchor_mode,
        "monthly_contribution": float(monthly_contribution),
        "annual_contribution": float(annual_contribution),
        "contribution_fee_pct": float(contribution_fee_pct),
        "contract_fee_pct": float(contract_fee_pct),
        "fund_fee_pct": float(fund_fee_pct),
        "total_annual_fee_pct": float(contract_fee_pct + fund_fee_pct),
        "is_per": is_per,
        "tmi_pct": float(tmi_pct),
        "scenarios": scenarios,
        "monthly_df": monthly_df,
        "yearly_df": yearly_df,
        "summary": summary_by_scenario,
    }


def filter_early_valuation_anomalies(
    df_hist: pd.DataFrame,
    start_dt: datetime.date | pd.Timestamp,
    initial_net: float,
    min_ratio: float = 0.95,
    max_window_days: int = 90,
    filter_transient_dips: bool = True,
    dip_threshold_pct: float = 0.06,
    max_dip_days: int = 25,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """
    Filtre les points de valorisation historiques anormaux survenant :
    1. À l'ouverture du contrat (valorisations d'onboarding incomplètes tant que tous les supports ne sont pas cotés).
    2. En cours de vie (délais d'arbitrage / désinvestissements temporaires où une ligne est débouclée avant réinvestissement).

    Lors de l'ouverture d'un contrat multi-supports (assurance-vie ou PER), les fonds en euros sont généralement
    valorisés très rapidement, tandis que certaines unités de compte (fonds actions, non coté, SCPI, produits
    structurés) nécessitent un délai de règlement et de première valorisation de quelques jours à quelques semaines.
    Dans les exports intermédiaires de l'assureur, l'encours affiché peut alors être temporairement inférieur
    au montant net investi (ex: 40 965 € ou 15 000 € au lieu de 48 200 €), créant un décrochage artificiel trompeur.

    De même, lors d'un arbitrage en cours de vie, le support cédé est débité avant que les nouvelles parts ne soient
    enregistrées, créant un creux transitoire en "V" résorbé en quelques jours.

    Paramètres :
        df_hist : DataFrame contenant au moins 'Date de valorisation' et 'Valorisation'.
        start_dt : Date de versement initial / souscription.
        initial_net : Montant net investi d'origine.
        min_ratio : Ratio minimal de valorisation d'ouverture admissible (défaut: 0.95 = 95% du net investi).
        max_window_days : Durée maximale d'observation en jours après l'ouverture (défaut: 90 jours).
        filter_transient_dips : Active la détection des creux transitoires d'arbitrage (défaut: True).
        dip_threshold_pct : Seuil de chute temporaire caractérisant un arbitrage (défaut: 0.06 = 6%).
        max_dip_days : Durée maximale de résorption du creux en jours (défaut: 25 jours).

    Retourne :
        (df_filtered, anomalies) :
            - df_filtered : DataFrame purgé des anomalies de valorisation.
            - anomalies : Liste des dictionnaires décrivant chaque point filtré et sa nature.
    """
    if df_hist is None or df_hist.empty or initial_net <= 0:
        return (df_hist.copy() if df_hist is not None else pd.DataFrame(), [])

    if "Date de valorisation" not in df_hist.columns or "Valorisation" not in df_hist.columns:
        return (df_hist.copy(), [])

    start_ts = pd.to_datetime(start_dt).normalize()
    threshold_open = float(initial_net) * float(min_ratio)

    df_work = df_hist.copy()
    df_work["Date_ts"] = pd.to_datetime(df_work["Date de valorisation"], errors="coerce").dt.normalize()
    df_work["Val_num"] = pd.to_numeric(df_work["Valorisation"], errors="coerce")
    df_work = df_work.dropna(subset=["Date_ts", "Val_num"]).drop_duplicates(subset=["Date_ts"]).sort_values("Date_ts").reset_index(drop=True)

    anomalies: list[dict[str, Any]] = []
    keep_indices_step1: list[int] = []

    # Étape 1 : Filtrage des valorisations initiales incomplètes (Ouverture)
    for idx, r in df_work.iterrows():
        dt = r["Date_ts"]
        val = r["Val_num"]
        days = (dt - start_ts).days
        if 0 <= days <= max_window_days and val < threshold_open:
            ratio = val / float(initial_net) if initial_net > 0 else 0.0
            anomalies.append({
                "type": "Ouverture incomplète",
                "Date": dt,
                "Valorisation": float(val),
                "DaysFromStart": int(days),
                "Ratio": float(ratio),
                "Threshold": float(threshold_open),
                "Desc": f"{val:,.0f} € (soit {ratio:.0%} du net investi)",
            })
        else:
            keep_indices_step1.append(idx)

    df_step1 = df_work.loc[keep_indices_step1].reset_index(drop=True)

    # Étape 2 : Filtrage des creux transitoires en cours de vie (Délais d'arbitrage / exports incomplets)
    if not filter_transient_dips or len(df_step1) < 3:
        cols_to_drop = [c for c in ["Date_ts", "Val_num"] if c in df_step1.columns]
        return (df_step1.drop(columns=cols_to_drop), anomalies)

    keep_indices_final: list[int] = []
    i = 0
    n = len(df_step1)
    while i < n:
        # Les points extrêmes (premier et dernier) ne sont pas des creux intermédiaires
        if i == 0 or i == n - 1:
            keep_indices_final.append(i)
            i += 1
            continue

        prev_v = df_step1.loc[i - 1, "Val_num"]
        curr_v = df_step1.loc[i, "Val_num"]
        next_v = df_step1.loc[i + 1, "Val_num"]
        prev_dt = df_step1.loc[i - 1, "Date_ts"]
        curr_dt = df_step1.loc[i, "Date_ts"]
        next_dt = df_step1.loc[i + 1, "Date_ts"]

        baseline = min(prev_v, next_v)
        span_days = (next_dt - prev_dt).days

        # Décrochage temporaire brutal en V : chute >= dip_threshold_pct par rapport au min des voisins résorbée en <= max_dip_days
        if baseline > 0 and curr_v < (1.0 - dip_threshold_pct) * baseline and span_days <= max_dip_days:
            drop_pct = (1.0 - curr_v / baseline) * 100.0
            anomalies.append({
                "type": "Délai d'arbitrage / export partiel",
                "Date": curr_dt,
                "Valorisation": float(curr_v),
                "DaysFromStart": int((curr_dt - start_ts).days),
                "Ratio": float(curr_v / baseline),
                "Threshold": float(baseline * (1.0 - dip_threshold_pct)),
                "Desc": f"{curr_v:,.0f} € (chute temporaire de {drop_pct:.1f}% résorbée en {span_days} j)",
            })
            i += 1
            continue

        keep_indices_final.append(i)
        i += 1

    df_final = df_step1.loc[keep_indices_final].reset_index(drop=True)
    cols_to_drop = [c for c in ["Date_ts", "Val_num"] if c in df_final.columns]
    return (df_final.drop(columns=cols_to_drop), anomalies)


def build_projection_trajectory_figure(
    projection_data: dict[str, Any],
    historical_df: pd.DataFrame | None = None,
    contrat_num: str = "",
    client_name: str = "",
    future_anchor_mode: str | None = None,
    filter_early_anomalies: bool = True,
    anomaly_min_ratio: float = 0.95,
    anomaly_window_days: int = 90,
    filter_transient_dips: bool = True,
    dip_threshold_pct: float = 0.06,
    max_dip_days: int = 25,
    height: int = 560,
) -> go.Figure:
    """
    Graphique 1 : Trajectoire temporelle unifiée
    Part de la date et du montant du premier versement net (investi), affiche une ligne
    repère horizontale pour le versement brut, retrace l'historique réel jusqu'à aujourd'hui,
    et projette le faisceau de scénarios (Prudent, Équilibré, Dynamique) vers l'horizon à long terme.
    Filtre automatiquement :
    - Les premières valorisations incomplètes post-ouverture liées aux délais de dénouement des différents supports.
    - Les creux transitoires en cours de vie liés aux délais d'exécution des arbitrages.
    """
    monthly_df = projection_data["monthly_df"]
    scenarios = projection_data["scenarios"]
    start_dt = projection_data.get("initial_date", monthly_df["Date"].iloc[0])
    init_net = projection_data.get("initial_amount_net", projection_data.get("initial_amount", monthly_df["Versements_nets_cumules"].iloc[0]))
    init_gross = projection_data.get("initial_amount_gross", monthly_df["Versements_cumules"].iloc[0])
    current_dt = projection_data["current_date"]
    current_val = projection_data["current_valuation"]
    is_per = projection_data.get("is_per", False)
    mode = future_anchor_mode or projection_data.get("future_anchor_mode", "origin")

    fig = go.Figure()

    # 1. Historique réel du contrat (démarre au versement initial net et va jusqu'à aujourd'hui)
    hist_points = []
    # Point initial (1er versement net)
    hist_points.append({"Date": start_dt, "Valorisation": init_net, "Label": "1er versement net"})

    filtered_anomalies: list[dict[str, Any]] = []
    if historical_df is not None and not historical_df.empty:
        h_df = historical_df.copy()
        if "Date de valorisation" in h_df.columns and "Valorisation" in h_df.columns:
            h_df["Date de valorisation"] = pd.to_datetime(h_df["Date de valorisation"], errors="coerce").dt.normalize()
            h_df["Valorisation"] = pd.to_numeric(h_df["Valorisation"], errors="coerce")
            h_df = h_df.dropna(subset=["Date de valorisation", "Valorisation"]).drop_duplicates(subset=["Date de valorisation"]).sort_values("Date de valorisation")
            # Points intermédiaires strictement compris entre start_dt et current_dt
            mid_points = h_df[(h_df["Date de valorisation"] > start_dt) & (h_df["Date de valorisation"] < current_dt)].copy()

            # Filtrage des valorisations anormales (ouverture et arbitrages) si demandé
            if filter_early_anomalies and init_net and init_net > 0:
                mid_points, filtered_anomalies = filter_early_valuation_anomalies(
                    mid_points,
                    start_dt=start_dt,
                    initial_net=init_net,
                    min_ratio=anomaly_min_ratio,
                    max_window_days=anomaly_window_days,
                    filter_transient_dips=filter_transient_dips,
                    dip_threshold_pct=dip_threshold_pct,
                    max_dip_days=max_dip_days,
                )

            for _, r in mid_points.iterrows():
                hist_points.append({"Date": r["Date de valorisation"], "Valorisation": float(r["Valorisation"]), "Label": "Historique"})

    # Point actuel (situation actuelle) si start_dt < current_dt
    if start_dt < current_dt:
        hist_points.append({"Date": current_dt, "Valorisation": float(current_val), "Label": "Aujourd'hui"})

    df_hist_unified = pd.DataFrame(hist_points).drop_duplicates(subset=["Date"]).sort_values("Date")

    fig.add_trace(
        go.Scatter(
            x=df_hist_unified["Date"],
            y=df_hist_unified["Valorisation"],
            mode="lines+markers",
            name="Historique réel (constaté)",
            line=dict(color=COLOR_HISTORICAL, width=3.0),
            marker=dict(size=6, color=COLOR_HISTORICAL),
            hovertemplate="<b>Historique réel</b><br>%{x|%d/%m/%Y}<br>Valorisation : <b>%{y:,.0f} €</b><extra></extra>",
        )
    )

    # 2. Ligne repère horizontale : Versement initial brut
    if init_gross is not None and float(init_gross) > 0:
        fig.add_trace(
            go.Scatter(
                x=[monthly_df["Date"].iloc[0], monthly_df["Date"].iloc[-1]],
                y=[float(init_gross), float(init_gross)],
                mode="lines",
                name=f"Versement brut initial ({float(init_gross):,.0f} €)".replace(",", " "),
                line=dict(color="#D97706", width=2.0, dash="dashdot"),
                hovertemplate=f"<b>Versement initial brut</b> : {float(init_gross):,.0f} €<extra></extra>".replace(",", " "),
            )
        )

    # 3. Enveloppe de dispersion entre Prudent et Dynamique (Fan chart)
    scenario_names = list(scenarios.keys())
    first_scen = scenario_names[0]
    last_scen = scenario_names[-1]
    col_prefix = "Val_" if mode == "origin" else "ValReanchored_"

    fan_df = monthly_df if mode == "origin" else monthly_df[monthly_df["Date"] >= current_dt]

    if len(scenario_names) >= 2 and not fan_df.empty:
        # Trace inférieure (masquée)
        fig.add_trace(
            go.Scatter(
                x=fan_df["Date"],
                y=fan_df[f"{col_prefix}{first_scen}"],
                mode="lines",
                line=dict(width=0),
                showlegend=False,
                hoverinfo="skip",
            )
        )
        # Trace supérieure avec remplissage
        fig.add_trace(
            go.Scatter(
                x=fan_df["Date"],
                y=fan_df[f"{col_prefix}{last_scen}"],
                mode="lines",
                line=dict(width=0),
                fill="tonexty",
                fillcolor="rgba(37, 99, 235, 0.08)",  # Voile bleuté léger
                name="Enveloppe des scénarios",
                hoverinfo="skip",
            )
        )

    # 4. Ligne de base : Versements cumulés (Capital total investi depuis le 1er versement)
    fig.add_trace(
        go.Scatter(
            x=monthly_df["Date"],
            y=monthly_df["Versements_cumules"],
            mode="lines",
            name="Capital total versé (avec versements futurs)",
            line=dict(color=COLOR_CAPITAL, width=2.2, dash="dash"),
            hovertemplate="<b>Capital versé</b><br>%{x|%d/%m/%Y} : <b>%{y:,.0f} €</b><extra></extra>",
        )
    )

    # 5. Si PER : Effort d'épargne net après réduction d'IR
    if is_per and projection_data.get("tmi_pct", 0) > 0:
        fig.add_trace(
            go.Scatter(
                x=monthly_df["Date"],
                y=monthly_df["Effort_epargne_cumule"],
                mode="lines",
                name=f"Effort d'épargne réel (IR -{projection_data['tmi_pct']:.0f}%)",
                line=dict(color=COLOR_PER_EFFORT, width=1.8, dash="dot"),
                hovertemplate="<b>Effort réel après IR</b><br>%{x|%d/%m/%Y} : <b>%{y:,.0f} €</b><extra></extra>",
            )
        )

    # 6. Courbes des scénarios
    color_palette = {
        first_scen: COLOR_PRUDENT,
        scenario_names[1] if len(scenario_names) > 1 else "Équilibré": COLOR_EQUILIBRE,
        last_scen: COLOR_DYNAMIQUE,
    }

    scen_plot_df = monthly_df if mode == "origin" else monthly_df[monthly_df["Date"] >= current_dt]

    for idx, (name, gross_rate) in enumerate(scenarios.items()):
        color = color_palette.get(name, px.colors.qualitative.Safe[idx % 10])
        is_central = (idx == 1 and len(scenarios) == 3) or ("équilibr" in name.lower())
        line_width = 3.2 if is_central else 2.2
        net_rate = gross_rate - (projection_data["total_annual_fee_pct"] / 100.0)

        fig.add_trace(
            go.Scatter(
                x=scen_plot_df["Date"],
                y=scen_plot_df[f"{col_prefix}{name}"],
                mode="lines",
                name=f"{name} (brut {gross_rate*100:.1f}% • net {net_rate*100:.1f}%)",
                line=dict(color=color, width=line_width),
                hovertemplate=f"<b>Scénario {name}</b><br>%{{x|%d/%m/%Y}}<br>Valorisation : <b>%{{y:,.0f}} €</b><extra></extra>",
            )
        )

    # 7. Marqueur du premier versement net (Point de départ)
    fig.add_annotation(
        x=start_dt,
        y=init_net,
        text=f"<b>1er versement net :</b><br>{init_net:,.0f} € le {start_dt.strftime('%d/%m/%Y')}".replace(",", " "),
        showarrow=True,
        arrowhead=2,
        arrowsize=1,
        arrowwidth=1.5,
        arrowcolor="#0F172A",
        ax=55,
        ay=40 if (init_gross is not None and init_net < init_gross) else -40,
        bgcolor="#FFFFFF",
        bordercolor="#94A3B8",
        borderwidth=1,
        borderpad=4,
        font=dict(size=10.5, color="#0F172A", family="Calibri, Arial"),
    )

    # 8. Marqueur du versement brut initial si distinct
    if init_gross is not None and float(init_gross) > float(init_net):
        fig.add_annotation(
            x=start_dt,
            y=float(init_gross),
            text=f"<b>Versement brut initial :</b> {float(init_gross):,.0f} €".replace(",", " "),
            showarrow=True,
            arrowhead=2,
            arrowsize=1,
            arrowwidth=1.2,
            arrowcolor="#D97706",
            ax=60,
            ay=-32,
            bgcolor="#FFFBEB",
            bordercolor="#FCD34D",
            borderwidth=1,
            borderpad=3,
            font=dict(size=10, color="#92400E", family="Calibri, Arial"),
        )

    # 9. Marqueur vertical de situation actuelle
    if start_dt < current_dt:
        fig.add_vline(
            x=current_dt,
            line_dash="dot",
            line_color="#94A3B8",
            line_width=1.5,
        )
        fig.add_annotation(
            x=current_dt,
            y=current_val,
            text=f"<b>Aujourd'hui</b><br>{current_val:,.0f} € au {current_dt.strftime('%d/%m/%Y')}".replace(",", " "),
            showarrow=True,
            arrowhead=2,
            arrowsize=1,
            arrowwidth=1.5,
            arrowcolor="#0F172A",
            ax=-70,
            ay=-38,
            bgcolor="#FFFFFF",
            bordercolor="#CBD5E1",
            borderwidth=1,
            borderpad=4,
            font=dict(size=10.5, color="#0F172A", family="Calibri, Arial"),
        )

    # Mise en page soignée
    title_text = f"Plan de projection du contrat {contrat_num}"
    if client_name:
        title_text = f"Plan de projection pour {client_name} — Contrat {contrat_num}"

    mode_label = "Trajectoire continue depuis le 1er versement" if mode == "origin" else "Projection future calée sur l'encours actuel"

    fig.update_layout(
        title=dict(
            text=f"{title_text}<br><span style='font-size:12px;color:#64748B;'>Départ net : {init_net:,.0f} € (brut : {init_gross:,.0f} € au {start_dt.strftime('%d/%m/%Y')})  •  {mode_label}</span>",
            x=0.5,
            xanchor="center",
            font=dict(size=18, color="#1F2937"),
        ),
        xaxis=dict(
            title="Horizon temporel",
            automargin=True,
            title_standoff=14,
            gridcolor="#F1F5F9",
            showline=True,
            linecolor="#CBD5E1",
        ),
        yaxis=dict(
            title="Valorisation (€)",
            automargin=True,
            title_standoff=16,
            tickformat=",.0f",
            gridcolor="#F1F5F9",
            showline=True,
            linecolor="#CBD5E1",
        ),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.20,
            xanchor="center",
            x=0.5,
            font=dict(size=10.5),
        ),
        margin=dict(t=80, b=130, l=85, r=45, autoexpand=True),
        paper_bgcolor="white",
        plot_bgcolor="white",
        hovermode="x unified",
        height=height,
    )
    # Attachement des métadonnées d'anomalies filtrées pour inspection/information UI
    fig._filtered_anomalies = filtered_anomalies
    return fig


def build_projection_breakdown_figure(
    projection_data: dict[str, Any],
    height: int = 480,
) -> go.Figure:
    """
    Graphique 2 : Décomposition du capital projeté à l'horizon cible
    Met en valeur la composition du capital final pour chaque scénario :
    Capital investi + Plus-values nettes perçues + Frais totaux prélevés (en comparaison).
    """
    summary = projection_data["summary"]
    scenarios = list(summary.keys())

    capital_investi = [summary[s]["total_invested"] for s in scenarios]
    gains_nets = [max(0.0, summary[s]["net_gain"]) for s in scenarios]
    frais_totaux = [summary[s]["total_fees_paid"] for s in scenarios]
    val_finales = [summary[s]["final_valuation"] for s in scenarios]

    fig = go.Figure()

    # Barre 1 : Capital initial et versements (Capital investi)
    fig.add_trace(
        go.Bar(
            name="Capital investi",
            x=scenarios,
            y=capital_investi,
            marker_color="#94A3B8",
            text=[f"{v:,.0f} €".replace(",", " ") for v in capital_investi],
            textposition="inside",
            hovertemplate="<b>Capital investi</b> : %{y:,.0f} €<extra></extra>",
        )
    )

    # Barre 2 : Plus-value financière nette
    fig.add_trace(
        go.Bar(
            name="Intérêts nets générés",
            x=scenarios,
            y=gains_nets,
            marker_color="#10B981",
            text=[f"+{v:,.0f} €".replace(",", " ") if v > 0 else "0 €" for v in gains_nets],
            textposition="inside",
            hovertemplate="<b>Intérêts nets perçus</b> : +%{y:,.0f} €<extra></extra>",
        )
    )

    # Barre 3 (Séparée / groupée) : Frais cumulés prélevés (pour illustrer l'impact des frais en transparence)
    fig.add_trace(
        go.Bar(
            name="Frais cumulés prélevés",
            x=scenarios,
            y=frais_totaux,
            marker_color="#F87171",
            text=[f"-{v:,.0f} €".replace(",", " ") for v in frais_totaux],
            textposition="outside",
            hovertemplate="<b>Frais totaux prélevés</b> : -%{y:,.0f} €<extra></extra>",
        )
    )

    # Annotations au sommet avec la valorisation finale
    for idx, s in enumerate(scenarios):
        v = val_finales[idx]
        mult = summary[s]["capital_multiplier"]
        fig.add_annotation(
            x=s,
            y=capital_investi[idx] + gains_nets[idx],
            text=f"<b>{v:,.0f} €</b><br>({mult:.2f}x)".replace(",", " "),
            showarrow=False,
            yshift=18,
            font=dict(size=12, color="#1F2937"),
        )

    fig.update_layout(
        title=dict(
            text=f"Décomposition du capital à {projection_data['years']} ans (Capital vs Intérêts nets vs Frais)",
            x=0.5,
            xanchor="center",
            font=dict(size=17, color="#1F2937"),
        ),
        barmode="stack",
        xaxis=dict(title="Scénarios", automargin=True, title_standoff=10),
        yaxis=dict(title="Montant (€)", automargin=True, tickformat=",.0f", gridcolor="#F1F5F9"),
        legend=dict(orientation="h", yanchor="top", y=-0.16, xanchor="center", x=0.5),
        margin=dict(t=70, b=90, l=75, r=35, autoexpand=True),
        paper_bgcolor="white",
        plot_bgcolor="white",
        height=height,
    )
    return fig


def build_projection_stacked_area_figure(
    projection_data: dict[str, Any],
    scenario_name: str = "Équilibré",
    height: int = 480,
) -> go.Figure:
    """
    Graphique 3 : Dynamique d'enrichissement année après année (Stacked Area)
    Montre la croissance du patrimoine par couche : Capital de départ -> Nouveaux versements -> Plus-values cumulées.
    """
    yearly_df = projection_data["yearly_df"].copy()
    scenarios = projection_data["scenarios"]
    if scenario_name not in scenarios:
        scenario_name = list(scenarios.keys())[min(1, len(scenarios) - 1)]

    initial_val = projection_data.get("initial_amount", projection_data["current_valuation"])

    # Calcul des couches
    yearly_df["Couche_Capital_Initial"] = initial_val
    yearly_df["Couche_Nouveaux_Versements"] = (yearly_df["Versements_cumules"] - initial_val).clip(lower=0.0)
    yearly_df["Couche_PlusValues_Nettes"] = (yearly_df[f"Val_{scenario_name}"] - yearly_df["Versements_cumules"]).clip(lower=0.0)

    fig = go.Figure()

    # Couche 1 : 1er versement initial
    fig.add_trace(
        go.Scatter(
            x=yearly_df["Date"],
            y=yearly_df["Couche_Capital_Initial"],
            mode="lines",
            line=dict(width=0.5, color="#64748B"),
            stackgroup="one",
            fillcolor="#CBD5E1",
            name="1er versement initial",
            hovertemplate="<b>1er versement initial</b> : %{y:,.0f} €<extra></extra>",
        )
    )

    # Couche 2 : Versements complémentaires
    fig.add_trace(
        go.Scatter(
            x=yearly_df["Date"],
            y=yearly_df["Couche_Nouveaux_Versements"],
            mode="lines",
            line=dict(width=0.5, color="#38BDF8"),
            stackgroup="one",
            fillcolor="#BAE6FD",
            name="Versements complémentaires",
            hovertemplate="<b>Versements complémentaires</b> : %{y:,.0f} €<extra></extra>",
        )
    )

    # Couche 3 : Plus-values nettes accumulées
    fig.add_trace(
        go.Scatter(
            x=yearly_df["Date"],
            y=yearly_df["Couche_PlusValues_Nettes"],
            mode="lines",
            line=dict(width=0.5, color="#10B981"),
            stackgroup="one",
            fillcolor="#A7F3D0",
            name="Intérêts & Plus-values nettes",
            hovertemplate="<b>Intérêts nets cumulés</b> : %{y:,.0f} €<extra></extra>",
        )
    )

    # Ligne de contour de la valorisation finale
    fig.add_trace(
        go.Scatter(
            x=yearly_df["Date"],
            y=yearly_df[f"Val_{scenario_name}"],
            mode="lines+markers",
            line=dict(color=COLOR_EQUILIBRE, width=2.5),
            marker=dict(size=5, color=COLOR_EQUILIBRE),
            name=f"Valorisation totale ({scenario_name})",
            hovertemplate="<b>Valorisation totale</b> : <b>%{y:,.0f} €</b><extra></extra>",
        )
    )

    fig.update_layout(
        title=dict(
            text=f"Dynamique d'enrichissement année par année — Scénario {scenario_name}",
            x=0.5,
            xanchor="center",
            font=dict(size=17, color="#1F2937"),
        ),
        xaxis=dict(title="Années", automargin=True, title_standoff=10, gridcolor="#F1F5F9"),
        yaxis=dict(title="Capital total (€)", automargin=True, tickformat=",.0f", gridcolor="#F1F5F9"),
        legend=dict(orientation="h", yanchor="top", y=-0.16, xanchor="center", x=0.5),
        margin=dict(t=70, b=90, l=75, r=35, autoexpand=True),
        paper_bgcolor="white",
        plot_bgcolor="white",
        height=height,
    )
    return fig


def build_projection_fee_comparison_figure(
    projection_data: dict[str, Any],
    height: int = 460,
) -> go.Figure:
    """
    Graphique 4 : Comparatif de l'impact des frais de gestion sur le capital final.
    Compare la valorisation nette obtenue vs la valorisation brute théorique sans aucun frais.
    """
    summary = projection_data["summary"]
    scenarios = list(summary.keys())

    val_nettes = [summary[s]["final_valuation"] for s in scenarios]
    val_brutes = [summary[s]["gross_valuation_without_fees"] for s in scenarios]
    frais_cumules = [summary[s]["total_fees_paid"] for s in scenarios]

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            name="Valorisation nette finale",
            x=scenarios,
            y=val_nettes,
            marker_color=COLOR_EQUILIBRE,
            text=[f"{v:,.0f} €".replace(",", " ") for v in val_nettes],
            textposition="auto",
            hovertemplate="<b>Valorisation nette perçue</b> : %{y:,.0f} €<extra></extra>",
        )
    )

    fig.add_trace(
        go.Bar(
            name="Valorisation brute (sans frais)",
            x=scenarios,
            y=val_brutes,
            marker_color="#CBD5E1",
            text=[f"{v:,.0f} €".replace(",", " ") for v in val_brutes],
            textposition="auto",
            hovertemplate="<b>Valorisation théorique sans frais</b> : %{y:,.0f} €<extra></extra>",
        )
    )

    fig.update_layout(
        title=dict(
            text=f"Impact des frais annuels ({projection_data['total_annual_fee_pct']:.2f}%) à l'horizon {projection_data['years']} ans",
            x=0.5,
            xanchor="center",
            font=dict(size=17, color="#1F2937"),
        ),
        barmode="group",
        xaxis=dict(title="Scénarios", automargin=True, title_standoff=10),
        yaxis=dict(title="Valorisation (€)", automargin=True, tickformat=",.0f", gridcolor="#F1F5F9"),
        legend=dict(orientation="h", yanchor="top", y=-0.16, xanchor="center", x=0.5),
        margin=dict(t=70, b=90, l=75, r=35, autoexpand=True),
        paper_bgcolor="white",
        plot_bgcolor="white",
        height=height,
    )
    return fig


def _add_proj_slide_header(slide, title: str, subtitle: str, slide_num: int, total_slides: int) -> None:
    """Ajoute le bandeau supérieur et le pied de page corporate sur une slide de projection."""
    NAVY = RGBColor(0x1B, 0x36, 0x5D)
    ACCENT_BLUE = RGBColor(0x2E, 0x75, 0xB6)
    WHITE_RGB = RGBColor(0xFF, 0xFF, 0xFF)
    MUTED_TEXT = RGBColor(0x6B, 0x72, 0x80)

    # Bandeau bleu nuit
    header_bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.78))
    header_bar.fill.solid()
    header_bar.fill.fore_color.rgb = NAVY
    header_bar.line.fill.background()

    # Titre
    t_box = slide.shapes.add_textbox(Inches(0.45), Inches(0.14), Inches(8.5), Inches(0.5))
    tf = t_box.text_frame
    p = tf.paragraphs[0]
    p.text = title
    p.font.name = "Calibri"
    p.font.size = Pt(20)
    p.font.bold = True
    p.font.color.rgb = WHITE_RGB

    # Sous-titre
    s_box = slide.shapes.add_textbox(Inches(0.45), Inches(0.84), Inches(12.4), Inches(0.32))
    tf_s = s_box.text_frame
    p_s = tf_s.paragraphs[0]
    p_s.text = subtitle
    p_s.font.name = "Calibri"
    p_s.font.size = Pt(11)
    p_s.font.color.rgb = MUTED_TEXT

    # Ligne d'accentuation
    acc = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.45), Inches(1.18), Inches(12.43), Inches(0.025))
    acc.fill.solid()
    acc.fill.fore_color.rgb = ACCENT_BLUE
    acc.line.fill.background()

    # Pied de page
    foot = slide.shapes.add_textbox(Inches(10.5), Inches(7.12), Inches(2.38), Inches(0.28))
    p_f = foot.text_frame.paragraphs[0]
    p_f.alignment = PP_ALIGN.RIGHT
    p_f.text = f"Slide {slide_num} / {total_slides}"
    p_f.font.name = "Calibri"
    p_f.font.size = Pt(9)
    p_f.font.color.rgb = MUTED_TEXT


def generate_projection_pptx(
    projection_data: dict[str, Any],
    client_name: str,
    contrat_num: str,
    enveloppe: str,
    partenaire: str,
    fig_trajectory: go.Figure | None = None,
    fig_breakdown: go.Figure | None = None,
    fig_stacked: go.Figure | None = None,
) -> bytes:
    """Génère un document PowerPoint (.pptx) synthétique du plan de projection long terme."""
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank_layout = prs.slide_layouts[6]

    NAVY = RGBColor(0x1B, 0x36, 0x5D)
    ACCENT_BLUE = RGBColor(0x2E, 0x75, 0xB6)
    DARK_TEXT = RGBColor(0x1F, 0x29, 0x37)
    MUTED_TEXT = RGBColor(0x6B, 0x72, 0x80)
    CARD_BG_RGB = RGBColor(0xF3, 0xF6, 0xFA)
    CARD_BORDER_RGB = RGBColor(0xD1, 0xD9, 0xE6)
    TOTAL_ROW_RGB = RGBColor(0xE6, 0xEE, 0xF8)

    is_per = projection_data.get("is_per", False)
    kind_label = "PER (Plan d'Épargne Retraite)" if is_per else "Assurance-vie"
    badge_label = "PLAN DE PROJECTION  •  PER" if is_per else "PLAN DE PROJECTION  •  ASSURANCE-VIE"
    years = projection_data["years"]
    target_year = projection_data["end_date"].year
    current_val_str = f"{projection_data['current_valuation']:,.0f} €".replace(",", " ")
    date_val_str = projection_data["current_date"].strftime("%d/%m/%Y")

    init_net = projection_data.get("initial_amount_net", projection_data.get("initial_amount", projection_data["current_valuation"]))
    init_gross = projection_data.get("initial_amount_gross", init_net)
    init_dt = projection_data.get("initial_date", projection_data["current_date"])
    init_val_str = f"{init_net:,.0f} €".replace(",", " ")
    init_gross_str = f"{init_gross:,.0f} €".replace(",", " ")
    date_init_str = init_dt.strftime("%d/%m/%Y")
    elapsed_years = projection_data.get("elapsed_years", 0.0)

    subtitle_base = f"{client_name}  •  {enveloppe}  •  {partenaire}  •  N° {contrat_num}  •  Horizon {years} ans ({target_year})"

    has_extra_slides = (fig_breakdown is not None or fig_stacked is not None)
    total_slides = 3 if has_extra_slides else 2

    # --- Slide 1 : Page de garde & Paramètres clés du plan ---
    s1 = prs.slides.add_slide(blank_layout)

    # Liseré supérieur
    top_strip = s1.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.10))
    top_strip.fill.solid()
    top_strip.fill.fore_color.rgb = NAVY
    top_strip.line.fill.background()

    sub_strip = s1.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0.10), Inches(13.333), Inches(0.03))
    sub_strip.fill.solid()
    sub_strip.fill.fore_color.rgb = ACCENT_BLUE
    sub_strip.line.fill.background()

    # Badge type
    badge = s1.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.95), Inches(0.92), Inches(4.8), Inches(0.44))
    badge.fill.solid()
    badge.fill.fore_color.rgb = TOTAL_ROW_RGB
    badge.line.color.rgb = ACCENT_BLUE
    p_b = badge.text_frame.paragraphs[0]
    p_b.alignment = PP_ALIGN.CENTER
    p_b.text = badge_label
    p_b.font.name = "Calibri"
    p_b.font.size = Pt(11)
    p_b.font.bold = True
    p_b.font.color.rgb = NAVY

    # Titre
    t_box = s1.shapes.add_textbox(Inches(0.95), Inches(1.55), Inches(11.4), Inches(0.70))
    p_t = t_box.text_frame.paragraphs[0]
    p_t.text = f"Plan de projection financière ({years} ans)"
    p_t.font.name = "Calibri"
    p_t.font.size = Pt(36)
    p_t.font.bold = True
    p_t.font.color.rgb = NAVY

    sub_box = s1.shapes.add_textbox(Inches(0.95), Inches(2.32), Inches(11.4), Inches(0.38))
    p_s = sub_box.text_frame.paragraphs[0]
    p_s.text = f"{kind_label}   •   {partenaire}   •   N° {contrat_num}   •   Titulaire : {client_name}"
    p_s.font.name = "Calibri"
    p_s.font.size = Pt(16)
    p_s.font.bold = True
    p_s.font.color.rgb = ACCENT_BLUE

    # Carte des paramètres
    card_p = s1.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.95), Inches(2.95), Inches(11.43), Inches(3.80))
    card_p.fill.solid()
    card_p.fill.fore_color.rgb = CARD_BG_RGB
    card_p.line.color.rgb = CARD_BORDER_RGB

    summary = projection_data["summary"]
    cent = summary.get("Équilibré", summary[list(summary.keys())[0]])

    p_items = [
        ("PREMIER VERSEMENT NET (ORIGINE)", f"{init_val_str} (le {date_init_str})"),
        ("VERSEMENT INITIAL BRUT (REPÈRE)", f"{init_gross_str}"),
        ("VALORISATION ACTUELLE", f"{current_val_str} (au {date_val_str})"),
        ("HISTORIQUE CONSTATÉ", f"{elapsed_years:.1f} ans écoulés depuis la souscription"),
        ("HORIZON PROJETÉ", f"{years} ans supplémentaires (atterrissage en {target_year})"),
        ("VERSEMENTS PROGRAMMÉS FUTURS", f"{projection_data['monthly_contribution']:,.0f} € / mois".replace(",", " ") + (f" + {projection_data['annual_contribution']:,.0f} € / an".replace(",", " ") if projection_data['annual_contribution'] > 0 else "")),
        ("FRAIS DE GESTION SUR ENCOURS", f"{projection_data['total_annual_fee_pct']:.2f} % / an (contrat {projection_data['contract_fee_pct']:.2f}% + supports {projection_data['fund_fee_pct']:.2f}%)"),
        ("VALORISATION ATTEINTE (ÉQUILIBRÉ)", f"{cent['final_valuation']:,.0f} € ({cent['capital_multiplier']:.2f}x le capital versé)".replace(",", " ")),
        ("TOTAL INVESTI DEPUIS L'ORIGINE", f"{cent['total_invested']:,.0f} €".replace(",", " ")),
        ("GAIN FINANCIER NET ESTIMÉ", f"+{cent['net_gain']:,.0f} € (+{cent['net_gain_pct']:.1f}%)".replace(",", " ")),
    ]
    if is_per:
        p_items.append(("AVANTAGE FISCAL ESTIMÉ (PER)", f"{cent['tax_savings_total']:,.0f} € d'économie d'IR (TMI {projection_data['tmi_pct']:.0f}%)".replace(",", " ")))

    for idx, (lbl, val) in enumerate(p_items):
        col = idx % 2
        row = idx // 2
        bx = s1.shapes.add_textbox(Inches(1.25 + col * 5.65), Inches(3.15 + row * 0.72), Inches(5.4), Inches(0.65))
        tf_i = bx.text_frame
        p_l = tf_i.paragraphs[0]
        p_l.text = lbl
        p_l.font.name = "Calibri"
        p_l.font.size = Pt(9.5)
        p_l.font.bold = True
        p_l.font.color.rgb = MUTED_TEXT

        p_v = tf_i.add_paragraph()
        p_v.text = str(val)
        p_v.font.name = "Calibri"
        p_v.font.size = Pt(13)
        p_v.font.bold = True
        p_v.font.color.rgb = NAVY if idx in (0, 2, 7) else DARK_TEXT

    # --- Slide 2 : Trajectoire temporelle unifiée ---
    s2 = prs.slides.add_slide(blank_layout)
    _add_proj_slide_header(s2, "Trajectoire temporelle : Historique réel et Projections", subtitle_base, 2, total_slides)
    if fig_trajectory is not None:
        png_traj = convert_figure_to_png_bytes(fig_trajectory, width_px=1320, height_px=620, scale=2, legend_bottom=True)
        if png_traj:
            s2.shapes.add_picture(io.BytesIO(png_traj), Inches(0.45), Inches(1.32), width=Inches(12.43), height=Inches(5.65))

    # --- Slide 3 : Décomposition du capital et dynamique d'enrichissement (si fournie) ---
    if has_extra_slides:
        s3 = prs.slides.add_slide(blank_layout)
        _add_proj_slide_header(s3, "Décomposition du capital à terme et Enrichissement", subtitle_base, 3, total_slides)
        if fig_breakdown is not None:
            png_bd = convert_figure_to_png_bytes(fig_breakdown, width_px=700, height_px=600, scale=2)
            if png_bd:
                s3.shapes.add_picture(io.BytesIO(png_bd), Inches(0.35), Inches(1.32), width=Inches(6.20), height=Inches(5.65))

        if fig_stacked is not None:
            png_st = convert_figure_to_png_bytes(fig_stacked, width_px=700, height_px=600, scale=2)
            if png_st:
                s3.shapes.add_picture(io.BytesIO(png_st), Inches(6.78), Inches(1.32), width=Inches(6.20), height=Inches(5.65))

    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()

