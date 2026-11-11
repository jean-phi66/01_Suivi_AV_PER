"""
Module de génération de bilans de contrat au format PowerPoint (.pptx).
"""

from __future__ import annotations

import io
import os
import stat
import tempfile
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches, Pt

from report_generator import safe_date_format
from reporting_helpers import (
    build_allocation_waterfall_figure,
    build_composition_figures,
    build_contract_and_class_fund_figures,
    build_contract_waterfall_figure,
    build_evolution_figure,
    build_kpi_overrides,
    load_latest_fund_perf_file,
    resolve_payment_source,
)
from tri_integration import load_tri_analyses, match_tri_analyses_to_contracts

# Palette corporate sobre et lisible
NAVY = RGBColor(0x1B, 0x36, 0x5D)
ACCENT_BLUE = RGBColor(0x2E, 0x75, 0xB6)
LIGHT_BLUE_TEXT = RGBColor(0xDC, 0xE6, 0xF2)
DARK_TEXT = RGBColor(0x1F, 0x29, 0x37)
MUTED_TEXT = RGBColor(0x6B, 0x72, 0x80)
CARD_BG = RGBColor(0xF3, 0xF6, 0xFA)
CARD_BORDER = RGBColor(0xD1, 0xD9, 0xE6)
ZEBRA_BG = RGBColor(0xF8, 0xFA, 0xFC)
TOTAL_ROW_BG = RGBColor(0xE6, 0xEE, 0xF8)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

SLIDE_WIDTH = Inches(13.333)
SLIDE_HEIGHT = Inches(7.5)

_KALEIDO_PATCHED = False


def _ensure_kaleido_space_safe() -> None:
    """Contournement Kaleido 0.2.1 lorsque le chemin du venv contient des espaces (macOS/Linux)."""
    global _KALEIDO_PATCHED
    if _KALEIDO_PATCHED or os.name == "nt":
        return
    try:
        from kaleido.scopes.base import BaseScope

        orig_exec = BaseScope.executable_path()
        if " " in orig_exec and os.path.exists(orig_exec):
            exec_dir = os.path.dirname(orig_exec)
            bin_kaleido = os.path.join(exec_dir, "bin", "kaleido")
            if os.path.exists(bin_kaleido):
                wrapper = os.path.join(tempfile.gettempdir(), "kaleido_space_safe_wrapper.sh")
                content = f'#!/bin/bash\ncd "{exec_dir}"\nexec ./bin/kaleido "$@"\n'
                needs_write = True
                if os.path.exists(wrapper):
                    try:
                        with open(wrapper, "r", encoding="utf-8") as handle:
                            needs_write = handle.read() != content
                    except OSError:
                        needs_write = True
                if needs_write:
                    with open(wrapper, "w", encoding="utf-8") as handle:
                        handle.write(content)
                    os.chmod(wrapper, os.stat(wrapper).st_mode | stat.S_IEXEC)
                BaseScope.executable_path = classmethod(lambda cls, _w=wrapper: _w)
        _KALEIDO_PATCHED = True
    except Exception:
        # Ne pas bloquer si Kaleido n'est pas encore initialisé ou utilise un autre backend
        pass


def convert_figure_to_png_bytes(
    fig: go.Figure | None,
    width_px: int = 1200,
    height_px: int = 620,
    scale: int = 2,
    legend_bottom: bool = False,
) -> bytes | None:
    """Convertit une figure Plotly en image PNG haute résolution avec fond blanc propre."""
    if fig is None:
        return None

    _ensure_kaleido_space_safe()
    fig_export = go.Figure(fig)
    layout_updates: dict[str, Any] = {
        "paper_bgcolor": "white",
        "plot_bgcolor": "white",
        "font": {"color": "#1F2937"},
        "width": width_px,
        "height": height_px,
    }
    if legend_bottom:
        layout_updates["legend"] = {
            "orientation": "h",
            "yanchor": "top",
            "y": -0.08,
            "xanchor": "center",
            "x": 0.5,
            "font": {"size": 10},
        }
        layout_updates["margin"] = {"t": 60, "b": 110, "l": 20, "r": 20}

    fig_export.update_layout(**layout_updates)
    return fig_export.to_image(format="png", engine="kaleido", width=width_px, height=height_px, scale=scale)


def _add_slide_chrome(
    slide,
    slide_title: str,
    contract_badge: str,
    subtitle: str,
    footer_left: str,
    slide_index: int,
    total_slides: int,
) -> None:
    """Ajoute l'en-tête, la barre de contexte et le pied de page sur une slide."""
    # Bandeau supérieur bleu nuit
    header_bar = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), SLIDE_WIDTH, Inches(0.78)
    )
    header_bar.fill.solid()
    header_bar.fill.fore_color.rgb = NAVY
    header_bar.line.fill.background()

    # Titre de la slide
    title_box = slide.shapes.add_textbox(Inches(0.45), Inches(0.14), Inches(8.2), Inches(0.5))
    tf = title_box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.text = slide_title
    p.font.name = "Calibri"
    p.font.size = Pt(20)
    p.font.bold = True
    p.font.color.rgb = WHITE

    # Badge contrat à droite dans le bandeau
    badge_box = slide.shapes.add_textbox(Inches(8.7), Inches(0.14), Inches(4.2), Inches(0.5))
    tf_badge = badge_box.text_frame
    tf_badge.word_wrap = True
    tf_badge.vertical_anchor = MSO_ANCHOR.MIDDLE
    p_badge = tf_badge.paragraphs[0]
    p_badge.alignment = PP_ALIGN.RIGHT
    p_badge.text = contract_badge
    p_badge.font.name = "Calibri"
    p_badge.font.size = Pt(11)
    p_badge.font.color.rgb = LIGHT_BLUE_TEXT

    # Sous-titre contexte contrat
    sub_box = slide.shapes.add_textbox(Inches(0.45), Inches(0.84), Inches(12.4), Inches(0.32))
    tf_sub = sub_box.text_frame
    tf_sub.word_wrap = True
    p_sub = tf_sub.paragraphs[0]
    p_sub.text = subtitle
    p_sub.font.name = "Calibri"
    p_sub.font.size = Pt(11)
    p_sub.font.color.rgb = MUTED_TEXT

    # Ligne d'accentuation fine
    accent_line = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0.45), Inches(1.18), Inches(12.43), Inches(0.025)
    )
    accent_line.fill.solid()
    accent_line.fill.fore_color.rgb = ACCENT_BLUE
    accent_line.line.fill.background()

    # Pied de page
    footer_l = slide.shapes.add_textbox(Inches(0.45), Inches(7.12), Inches(9.5), Inches(0.28))
    p_fl = footer_l.text_frame.paragraphs[0]
    p_fl.text = footer_left
    p_fl.font.name = "Calibri"
    p_fl.font.size = Pt(9)
    p_fl.font.color.rgb = MUTED_TEXT

    footer_r = slide.shapes.add_textbox(Inches(10.5), Inches(7.12), Inches(2.38), Inches(0.28))
    p_fr = footer_r.text_frame.paragraphs[0]
    p_fr.alignment = PP_ALIGN.RIGHT
    p_fr.text = f"Slide {slide_index} / {total_slides}"
    p_fr.font.name = "Calibri"
    p_fr.font.size = Pt(9)
    p_fr.font.color.rgb = MUTED_TEXT


def _add_cover_slide(
    slide,
    client_name: str,
    contrat_num: str,
    enveloppe: str,
    partenaire: str,
    is_per: bool,
    valorisation_str: str,
    date_val_str: str,
    date_ouv_str: str,
    total_slides: int,
) -> None:
    """Ajoute une page de garde sobre et légère présentant les informations clés du contrat."""
    is_per_effective = bool(is_per or "PER" in str(enveloppe or "").upper())
    if is_per_effective:
        badge_label = "CONTRAT PER  •  PLAN D'ÉPARGNE RETRAITE"
        contract_kind_label = "PER (Plan d'Épargne Retraite)"
    else:
        badge_label = "CONTRAT D'ASSURANCE-VIE"
        contract_kind_label = "Assurance-vie"

    env_clean = str(enveloppe or "").strip()
    if env_clean and env_clean.lower() not in {"n/a", "per", "assurance-vie", "assurance vie"}:
        type_detail = f"{contract_kind_label} — {env_clean}"
    else:
        type_detail = contract_kind_label

    # Liseré supérieur sobre (fond blanc conservé sur toute la slide)
    top_strip = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), SLIDE_WIDTH, Inches(0.10)
    )
    top_strip.fill.solid()
    top_strip.fill.fore_color.rgb = NAVY
    top_strip.line.fill.background()

    sub_strip = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0), Inches(0.10), SLIDE_WIDTH, Inches(0.03)
    )
    sub_strip.fill.solid()
    sub_strip.fill.fore_color.rgb = ACCENT_BLUE
    sub_strip.line.fill.background()

    # Badge type de contrat (PER vs Assurance-vie)
    badge = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.95), Inches(0.98), Inches(4.75), Inches(0.44)
    )
    badge.fill.solid()
    badge.fill.fore_color.rgb = TOTAL_ROW_BG
    badge.line.color.rgb = ACCENT_BLUE
    badge.line.width = Pt(1)
    tf_b = badge.text_frame
    tf_b.word_wrap = True
    tf_b.vertical_anchor = MSO_ANCHOR.MIDDLE
    p_b = tf_b.paragraphs[0]
    p_b.alignment = PP_ALIGN.CENTER
    p_b.text = badge_label
    p_b.font.name = "Calibri"
    p_b.font.size = Pt(11)
    p_b.font.bold = True
    p_b.font.color.rgb = NAVY

    # Titre principal & sous-titres
    title_box = slide.shapes.add_textbox(Inches(0.95), Inches(1.66), Inches(11.4), Inches(0.70))
    p_t = title_box.text_frame.paragraphs[0]
    p_t.text = "Bilan de contrat"
    p_t.font.name = "Calibri"
    p_t.font.size = Pt(38)
    p_t.font.bold = True
    p_t.font.color.rgb = NAVY

    kind_box = slide.shapes.add_textbox(Inches(0.95), Inches(2.42), Inches(11.4), Inches(0.42))
    p_k = kind_box.text_frame.paragraphs[0]
    p_k.text = f"{contract_kind_label}   •   {partenaire}   •   N° {contrat_num}"
    p_k.font.name = "Calibri"
    p_k.font.size = Pt(17)
    p_k.font.bold = True
    p_k.font.color.rgb = ACCENT_BLUE

    cli_box = slide.shapes.add_textbox(Inches(0.95), Inches(2.92), Inches(11.4), Inches(0.36))
    p_c = cli_box.text_frame.paragraphs[0]
    p_c.text = f"Titulaire : {client_name}"
    p_c.font.name = "Calibri"
    p_c.font.size = Pt(14)
    p_c.font.color.rgb = DARK_TEXT

    # Ligne de séparation légère
    sep = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0.95), Inches(3.48), Inches(11.43), Inches(0.02)
    )
    sep.fill.solid()
    sep.fill.fore_color.rgb = CARD_BORDER
    sep.line.fill.background()

    # Carte d'informations synthétiques du contrat
    info_card = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.95), Inches(3.78), Inches(11.43), Inches(2.50)
    )
    info_card.fill.solid()
    info_card.fill.fore_color.rgb = CARD_BG
    info_card.line.color.rgb = CARD_BORDER
    info_card.line.width = Pt(1)

    info_items = [
        ("TYPE DE CONTRAT", type_detail),
        ("NUMÉRO DE CONTRAT", str(contrat_num)),
        ("ASSUREUR / PARTENAIRE", partenaire),
        ("DATE D'OUVERTURE", date_ouv_str),
        (f"VALORISATION (AU {date_val_str})", valorisation_str),
        ("TITULAIRE(S)", client_name),
    ]
    for idx, (lbl, val) in enumerate(info_items):
        col = idx % 2
        row = idx // 2
        item_x = 1.28 + col * 5.65
        item_y = 3.98 + row * 0.74
        box = slide.shapes.add_textbox(Inches(item_x), Inches(item_y), Inches(5.30), Inches(0.64))
        tf_i = box.text_frame
        tf_i.word_wrap = True
        p_lbl = tf_i.paragraphs[0]
        p_lbl.text = lbl
        p_lbl.font.name = "Calibri"
        p_lbl.font.size = Pt(9.5)
        p_lbl.font.bold = True
        p_lbl.font.color.rgb = MUTED_TEXT

        p_val = tf_i.add_paragraph()
        p_val.text = str(val)
        p_val.font.name = "Calibri"
        p_val.font.size = Pt(14)
        p_val.font.bold = True
        p_val.font.color.rgb = NAVY if idx in (0, 4) else DARK_TEXT

    # Pied de page léger
    foot_l = slide.shapes.add_textbox(Inches(0.95), Inches(6.98), Inches(8.0), Inches(0.28))
    p_fl = foot_l.text_frame.paragraphs[0]
    p_fl.text = f"Situation arrêtée au {date_val_str}"
    p_fl.font.name = "Calibri"
    p_fl.font.size = Pt(9.5)
    p_fl.font.color.rgb = MUTED_TEXT

    foot_r = slide.shapes.add_textbox(Inches(10.0), Inches(6.98), Inches(2.38), Inches(0.28))
    p_fr = foot_r.text_frame.paragraphs[0]
    p_fr.alignment = PP_ALIGN.RIGHT
    p_fr.text = f"Slide 1 / {total_slides}"
    p_fr.font.name = "Calibri"
    p_fr.font.size = Pt(9.5)
    p_fr.font.color.rgb = MUTED_TEXT


def _add_picture_fit(
    slide,
    png_bytes: bytes | None,
    left_in: float,
    top_in: float,
    max_width_in: float,
    max_height_in: float,
    aspect_ratio: float,
    empty_message: str = "Graphique non disponible pour ce contrat.",
) -> None:
    """Insère une image PNG centrée dans la zone cible en conservant son ratio d'aspect."""
    if not png_bytes:
        box = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE,
            Inches(left_in),
            Inches(top_in),
            Inches(max_width_in),
            Inches(max_height_in),
        )
        box.fill.solid()
        box.fill.fore_color.rgb = CARD_BG
        box.line.color.rgb = CARD_BORDER
        tf = box.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        p.text = empty_message
        p.font.name = "Calibri"
        p.font.size = Pt(14)
        p.font.color.rgb = MUTED_TEXT
        return

    # Calculer dimensions maximales respectant le ratio largeur / hauteur
    target_w = max_width_in
    target_h = target_w / aspect_ratio
    if target_h > max_height_in:
        target_h = max_height_in
        target_w = target_h * aspect_ratio

    centered_left = left_in + (max_width_in - target_w) / 2.0
    centered_top = top_in + (max_height_in - target_h) / 2.0
    slide.shapes.add_picture(
        io.BytesIO(png_bytes),
        Inches(centered_left),
        Inches(centered_top),
        width=Inches(target_w),
        height=Inches(target_h),
    )


def _add_kpi_strip(slide, kpis: list[tuple[str, str]], top_in: float = 1.28) -> None:
    """Ajoute une rangée de cartes KPI compactes en haut de la zone de contenu."""
    if not kpis:
        return
    margin_x = 0.45
    gap = 0.16
    total_w = 12.43
    card_w = (total_w - gap * (len(kpis) - 1)) / len(kpis)
    card_h = 0.68

    for idx, (label, value) in enumerate(kpis):
        x = margin_x + idx * (card_w + gap)
        card = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(top_in), Inches(card_w), Inches(card_h)
        )
        card.fill.solid()
        card.fill.fore_color.rgb = CARD_BG
        card.line.color.rgb = CARD_BORDER
        card.line.width = Pt(1)

        tf = card.text_frame
        tf.word_wrap = True
        tf.margin_left = Inches(0.1)
        tf.margin_right = Inches(0.1)
        tf.margin_top = Inches(0.06)
        tf.margin_bottom = Inches(0.04)

        p_lbl = tf.paragraphs[0]
        p_lbl.alignment = PP_ALIGN.CENTER
        p_lbl.text = label
        p_lbl.font.name = "Calibri"
        p_lbl.font.size = Pt(9.5)
        p_lbl.font.color.rgb = MUTED_TEXT

        p_val = tf.add_paragraph()
        p_val.alignment = PP_ALIGN.CENTER
        p_val.text = value
        p_val.font.name = "Calibri"
        p_val.font.size = Pt(14)
        p_val.font.bold = True
        p_val.font.color.rgb = NAVY


def _fmt_eur(val: float, decimals: int = 2) -> str:
    if val is None or pd.isna(val):
        return "0,00 €"
    formatted = f"{float(val):,.{decimals}f}".replace(",", " ").replace(".", ",")
    return f"{formatted} €"


def _set_cell_borders(cell, color_hex: str = "D1D9E6", sz_pt: float = 0.5) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    sz_emu = str(int(sz_pt * 12700))
    for edge in ("lnL", "lnR", "lnT", "lnB"):
        for existing in tcPr.findall(qn(f"a:{edge}")):
            tcPr.remove(existing)
        ln = OxmlElement(f"a:{edge}")
        ln.set("w", sz_emu)
        ln.set("cap", "flat")
        ln.set("cmpd", "sng")
        ln.set("algn", "ctr")
        solidFill = OxmlElement("a:solidFill")
        srgbClr = OxmlElement("a:srgbClr")
        srgbClr.set("val", color_hex)
        solidFill.append(srgbClr)
        ln.append(solidFill)
        tcPr.append(ln)


def _resolve_tri_analysis_for_contract(
    contrat_num: str,
    df_contrats_all: pd.DataFrame,
    df_contrat_selected: pd.DataFrame,
    tri_analysis: dict | None,
) -> dict | None:
    """Extrait et apparie automatiquement les relevés TRI PDF si tri_analysis n'est pas fourni."""
    if tri_analysis is not None:
        return tri_analysis

    source_df = df_contrats_all if (df_contrats_all is not None and not df_contrats_all.empty) else df_contrat_selected
    if source_df is None or source_df.empty:
        return None
    req = ["N° de contrat", "Titulaire(s)", "Enveloppe", "Partenaire"]
    if not set(req).issubset(source_df.columns):
        return None

    analyses = load_tri_analyses()
    if not analyses:
        return None
    _, matched_map = match_tri_analyses_to_contracts(
        analyses,
        source_df[req].drop_duplicates().copy(),
    )
    return matched_map.get(str(contrat_num))


def prepare_operations_tables(tri_analysis: dict | None) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Prépare les tableaux détaillés des versements et des arbitrages à partir du relevé TRI."""
    empty_v = pd.DataFrame(columns=["Date", "Opération", "Type", "Montant brut", "Montant net", "Frais", "Taux frais"])
    empty_a = pd.DataFrame(columns=["Date", "Libellé", "Nature", "Montant"])
    meta: dict[str, Any] = {
        "has_tri": tri_analysis is not None,
        "v_count": 0,
        "v_total_gross": 0.0,
        "v_total_net": 0.0,
        "v_total_fees": 0.0,
        "v_avg_fee_rate": 0.0,
        "a_count": 0,
        "a_total_amount": 0.0,
        "assumption_note": "",
    }
    if tri_analysis is None:
        return empty_v, empty_a, meta

    meta["assumption_note"] = str(tri_analysis.get("assumption_note") or "")
    movements = tri_analysis.get("movements")
    if movements is None or movements.empty:
        return empty_v, empty_a, meta

    mv = movements.copy()
    mv["date"] = pd.to_datetime(mv["date"], errors="coerce")
    mv = mv.dropna(subset=["date"]).sort_values(["date", "label"])
    mv["amount_net"] = pd.to_numeric(mv.get("amount_net"), errors="coerce").fillna(0.0)
    mv["amount_gross"] = pd.to_numeric(mv.get("amount_gross", mv["amount_net"]), errors="coerce").fillna(0.0)
    if "fees_amount" in mv.columns:
        mv["fees_amount"] = pd.to_numeric(mv["fees_amount"], errors="coerce").fillna(0.0)
    else:
        mv["fees_amount"] = mv["amount_gross"] - mv["amount_net"]

    # Tableau Versements
    df_c = mv[mv["movement_type"] == "contribution"].copy()
    if not df_c.empty:
        if "operation_subtype" not in df_c.columns:
            df_c["operation_subtype"] = df_c["label"].astype(str).apply(
                lambda lbl: "Souscription / Adhésion"
                if ("SOUSCRIPTION" in lbl.upper() or "ADHESION" in lbl.upper())
                else ("Versement programmé" if "PROGRAM" in lbl.upper() else "Versement libre")
            )
        df_c["Taux frais (%)"] = df_c.apply(
            lambda r: (r["fees_amount"] / r["amount_gross"] * 100.0) if r["amount_gross"] > 0 else 0.0,
            axis=1,
        )
        df_versements = pd.DataFrame(
            {
                "Date": df_c["date"],
                "Opération": df_c["label"].astype(str),
                "Type": df_c["operation_subtype"].astype(str),
                "Montant brut": df_c["amount_gross"],
                "Montant net": df_c["amount_net"],
                "Frais": df_c["fees_amount"],
                "Taux frais": df_c["Taux frais (%)"],
            }
        ).reset_index(drop=True)
        tot_g = float(df_c["amount_gross"].sum())
        tot_n = float(df_c["amount_net"].sum())
        tot_f = float(df_c["fees_amount"].sum())
        meta["v_count"] = len(df_versements)
        meta["v_total_gross"] = tot_g
        meta["v_total_net"] = tot_n
        meta["v_total_fees"] = tot_f
        meta["v_avg_fee_rate"] = (tot_f / tot_g * 100.0) if tot_g > 0 else 0.0
    else:
        df_versements = empty_v

    # Tableau Arbitrages
    df_a = mv[mv["movement_type"] == "arbitrage"].copy()
    if not df_a.empty:
        if "operation_subtype" not in df_a.columns:
            df_a["operation_subtype"] = df_a["label"].astype(str).apply(
                lambda lbl: "Fusion / Absorption"
                if ("FUSION" in lbl.upper() or "ABSORPTION" in lbl.upper())
                else ("Arbitrage invest. progressif" if "PROGRESSIF" in lbl.upper() else "Arbitrage libre")
            )
        df_arbitrages = pd.DataFrame(
            {
                "Date": df_a["date"],
                "Libellé": df_a["label"].astype(str),
                "Nature": df_a["operation_subtype"].astype(str),
                "Montant": df_a["amount_net"],
            }
        ).reset_index(drop=True)
        meta["a_count"] = len(df_arbitrages)
        meta["a_total_amount"] = float(df_a["amount_net"].sum())
    else:
        df_arbitrages = empty_a

    return df_versements, df_arbitrages, meta


def _compact_versements_rows(df_v: pd.DataFrame, max_rows: int = 16) -> tuple[list[list[str]], str | None]:
    """Formate les versements pour la slide en regroupant les VP par année si la liste est longue."""
    if df_v.empty:
        return [], None

    work = df_v.copy()
    work["Date"] = pd.to_datetime(work["Date"])
    note = None

    if len(work) > max_rows:
        is_vp = work["Type"] == "Versement programmé"
        non_vp = work[~is_vp].copy()
        vp = work[is_vp].copy()
        grouped_rows = []
        for _, r in non_vp.iterrows():
            grouped_rows.append(
                {
                    "sort_date": r["Date"],
                    "date_str": r["Date"].strftime("%d/%m/%Y"),
                    "label": str(r["Opération"]),
                    "gross": float(r["Montant brut"]),
                    "net": float(r["Montant net"]),
                    "fees": float(r["Frais"]),
                }
            )
        if not vp.empty:
            vp["Annee"] = vp["Date"].dt.year
            for year, grp in vp.groupby("Annee", sort=True):
                grouped_rows.append(
                    {
                        "sort_date": grp["Date"].max(),
                        "date_str": f"Année {year}",
                        "label": f"Versements programmés ({len(grp)} op.)",
                        "gross": float(grp["Montant brut"].sum()),
                        "net": float(grp["Montant net"].sum()),
                        "fees": float(grp["Frais"].sum()),
                    }
                )
            note = f"Versements programmés regroupés par année ({len(vp)} échéances au total)."

        df_compact = pd.DataFrame(grouped_rows).sort_values("sort_date").reset_index(drop=True)
        if len(df_compact) > max_rows:
            keep_recent = max_rows - 1
            older = df_compact.iloc[:-keep_recent]
            recent = df_compact.iloc[-keep_recent:]
            agg_row = pd.DataFrame(
                [
                    {
                        "sort_date": older["sort_date"].min(),
                        "date_str": f"{older['sort_date'].min():%m/%y}–{older['sort_date'].max():%m/%y}",
                        "label": f"Opérations antérieures ({len(older)} lignes)",
                        "gross": float(older["gross"].sum()),
                        "net": float(older["net"].sum()),
                        "fees": float(older["fees"].sum()),
                    }
                ]
            )
            df_compact = pd.concat([agg_row, recent], ignore_index=True)

        rows = [
            [r["date_str"], r["label"], _fmt_eur(r["gross"]), _fmt_eur(r["net"]), _fmt_eur(r["fees"])]
            for _, r in df_compact.iterrows()
        ]
        return rows, note

    rows = [
        [
            r["Date"].strftime("%d/%m/%Y"),
            str(r["Opération"]),
            _fmt_eur(r["Montant brut"]),
            _fmt_eur(r["Montant net"]),
            _fmt_eur(r["Frais"]),
        ]
        for _, r in work.iterrows()
    ]
    return rows, None


def _compact_arbitrages_rows(df_a: pd.DataFrame, max_rows: int = 16) -> tuple[list[list[str]], str | None]:
    """Formate les arbitrages pour la slide en agrégeant les plus anciens si la liste dépasse max_rows."""
    if df_a.empty:
        return [], None

    work = df_a.copy()
    work["Date"] = pd.to_datetime(work["Date"])
    note = None

    if len(work) > max_rows:
        keep_recent = max_rows - 1
        older = work.iloc[:-keep_recent]
        recent = work.iloc[-keep_recent:]
        rows = [
            [
                f"{older['Date'].min():%m/%y}–{older['Date'].max():%m/%y}",
                f"Arbitrages antérieurs ({len(older)} op.)",
                "Cumul période",
                _fmt_eur(float(older["Montant"].sum())),
            ]
        ]
        for _, r in recent.iterrows():
            rows.append(
                [
                    r["Date"].strftime("%d/%m/%Y"),
                    str(r["Libellé"]),
                    str(r["Nature"]),
                    _fmt_eur(r["Montant"]),
                ]
            )
        note = f"{len(older)} arbitrage(s) antérieur(s) cumulé(s) sur la première ligne."
        return rows, note

    rows = [
        [
            r["Date"].strftime("%d/%m/%Y"),
            str(r["Libellé"]),
            str(r["Nature"]),
            _fmt_eur(r["Montant"]),
        ]
        for _, r in work.iterrows()
    ]
    return rows, None


def _add_styled_table(
    slide,
    left_in: float,
    top_in: float,
    width_in: float,
    max_height_in: float,
    headers: list[str],
    col_widths_in: list[float],
    col_alignments: list[PP_ALIGN],
    rows: list[list[str]],
    total_row: list[str] | None = None,
    empty_message: str = "Aucune opération enregistrée.",
) -> None:
    """Insère un tableau PowerPoint stylé dans la zone cible."""
    if not rows:
        _add_picture_fit(
            slide,
            None,
            left_in=left_in,
            top_in=top_in,
            max_width_in=width_in,
            max_height_in=min(max_height_in, 2.2),
            aspect_ratio=2.5,
            empty_message=empty_message,
        )
        return

    all_rows = list(rows) + ([total_row] if total_row else [])
    n_rows = 1 + len(all_rows)
    n_cols = len(headers)

    if len(rows) <= 10:
        font_pt = 9.0
        row_h_in = 0.30
    elif len(rows) <= 14:
        font_pt = 8.5
        row_h_in = 0.255
    else:
        font_pt = 8.0
        row_h_in = min(0.225, max_height_in / max(n_rows, 1))

    header_h_in = min(0.32, max(0.24, row_h_in + 0.04))
    table_h_in = min(max_height_in, header_h_in + len(all_rows) * row_h_in)

    shape = slide.shapes.add_table(
        n_rows, n_cols, Inches(left_in), Inches(top_in), Inches(width_in), Inches(table_h_in)
    )
    table = shape.table

    for c_idx, col_w in enumerate(col_widths_in):
        table.columns[c_idx].width = Inches(col_w)

    table.rows[0].height = Inches(header_h_in)
    body_row_h = (table_h_in - header_h_in) / max(len(all_rows), 1)
    for r_idx in range(1, n_rows):
        table.rows[r_idx].height = Inches(body_row_h)

    def _style_cell(cell, text: str, align: PP_ALIGN, bg_rgb: RGBColor, fg_rgb: RGBColor, bold: bool, size_pt: float) -> None:
        cell.fill.solid()
        cell.fill.fore_color.rgb = bg_rgb
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        cell.margin_left = Inches(0.05)
        cell.margin_right = Inches(0.05)
        cell.margin_top = Inches(0.015)
        cell.margin_bottom = Inches(0.015)
        _set_cell_borders(cell)
        tf = cell.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.alignment = align
        p.text = text
        p.font.name = "Calibri"
        p.font.size = Pt(size_pt)
        p.font.bold = bold
        p.font.color.rgb = fg_rgb

    # En-tête
    for c_idx, h_text in enumerate(headers):
        _style_cell(table.cell(0, c_idx), h_text, col_alignments[c_idx], NAVY, WHITE, True, font_pt)

    # Lignes de données + total
    for idx, row_vals in enumerate(all_rows):
        is_total = total_row is not None and idx == len(all_rows) - 1
        bg = TOTAL_ROW_BG if is_total else (ZEBRA_BG if idx % 2 == 1 else WHITE)
        fg = NAVY if is_total else DARK_TEXT
        for c_idx, val in enumerate(row_vals):
            _style_cell(table.cell(idx + 1, c_idx), str(val), col_alignments[c_idx], bg, fg, is_total, font_pt)


def _add_operations_slide(
    slide,
    tri_analysis: dict | None,
) -> None:
    """Remplit la slide dédiée aux tableaux détaillés des versements et arbitrages."""
    df_v, df_a, meta = prepare_operations_tables(tri_analysis)

    left_x, right_x = 0.45, 6.80
    panel_w = 6.08

    # Bandeaux titres + synthèse de chaque tableau
    for x, title, summary in [
        (
            left_x,
            "Détail des versements",
            (
                f"{meta['v_count']} op.  •  Brut : {_fmt_eur(meta['v_total_gross'], 0)}  •  "
                f"Net : {_fmt_eur(meta['v_total_net'], 0)}  •  Frais : {_fmt_eur(meta['v_total_fees'], 0)} "
                f"({meta['v_avg_fee_rate']:.2f} %)".replace(".", ",")
                if meta["has_tri"]
                else "Relevé TRI non apparié"
            ),
        ),
        (
            right_x,
            "Détail des arbitrages",
            (
                f"{meta['a_count']} op.  •  Volume total arbitré : {_fmt_eur(meta['a_total_amount'], 0)}"
                if meta["has_tri"]
                else "Relevé TRI non apparié"
            ),
        ),
    ]:
        pill = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(1.28), Inches(panel_w), Inches(0.52))
        pill.fill.solid()
        pill.fill.fore_color.rgb = CARD_BG
        pill.line.color.rgb = CARD_BORDER
        pill.line.width = Pt(1)
        tf = pill.text_frame
        tf.word_wrap = True
        tf.margin_left = Inches(0.10)
        tf.margin_right = Inches(0.10)
        tf.margin_top = Inches(0.03)
        tf.margin_bottom = Inches(0.03)
        p1 = tf.paragraphs[0]
        p1.text = title
        p1.font.name = "Calibri"
        p1.font.size = Pt(12)
        p1.font.bold = True
        p1.font.color.rgb = NAVY
        p2 = tf.add_paragraph()
        p2.text = summary
        p2.font.name = "Calibri"
        p2.font.size = Pt(9.5)
        p2.font.color.rgb = MUTED_TEXT

    if not meta["has_tri"]:
        no_tri_msg = "Aucun relevé d'opérations TRI PDF n'a été apparié à ce contrat (00_Exports/04_Opérations)."
        _add_styled_table(
            slide, left_x, 1.90, panel_w, 4.75,
            ["Date", "Opération", "Brut", "Net", "Frais"],
            [0.95, 2.18, 1.05, 1.05, 0.85],
            [PP_ALIGN.LEFT, PP_ALIGN.LEFT, PP_ALIGN.RIGHT, PP_ALIGN.RIGHT, PP_ALIGN.RIGHT],
            [], empty_message=no_tri_msg,
        )
        _add_styled_table(
            slide, right_x, 1.90, panel_w, 4.75,
            ["Date", "Libellé", "Nature", "Montant"],
            [1.00, 2.28, 1.55, 1.25],
            [PP_ALIGN.LEFT, PP_ALIGN.LEFT, PP_ALIGN.LEFT, PP_ALIGN.RIGHT],
            [], empty_message=no_tri_msg,
        )
        return

    v_rows, v_compact_note = _compact_versements_rows(df_v, max_rows=16)
    v_total = (
        [
            "Total",
            f"{meta['v_count']} opération(s)",
            _fmt_eur(meta["v_total_gross"]),
            _fmt_eur(meta["v_total_net"]),
            _fmt_eur(meta["v_total_fees"]),
        ]
        if v_rows
        else None
    )
    _add_styled_table(
        slide,
        left_in=left_x,
        top_in=1.90,
        width_in=panel_w,
        max_height_in=4.72,
        headers=["Date", "Opération", "Brut", "Net", "Frais"],
        col_widths_in=[0.95, 2.18, 1.05, 1.05, 0.85],
        col_alignments=[PP_ALIGN.LEFT, PP_ALIGN.LEFT, PP_ALIGN.RIGHT, PP_ALIGN.RIGHT, PP_ALIGN.RIGHT],
        rows=v_rows,
        total_row=v_total,
        empty_message="Aucun versement enregistré sur le relevé TRI.",
    )

    a_rows, a_compact_note = _compact_arbitrages_rows(df_a, max_rows=16)
    a_total = (
        [
            "Total",
            f"{meta['a_count']} arbitrage(s)",
            "—",
            _fmt_eur(meta["a_total_amount"]),
        ]
        if a_rows
        else None
    )
    _add_styled_table(
        slide,
        left_in=right_x,
        top_in=1.90,
        width_in=panel_w,
        max_height_in=4.72,
        headers=["Date", "Libellé", "Nature", "Montant"],
        col_widths_in=[1.00, 2.28, 1.55, 1.25],
        col_alignments=[PP_ALIGN.LEFT, PP_ALIGN.LEFT, PP_ALIGN.LEFT, PP_ALIGN.RIGHT],
        rows=a_rows,
        total_row=a_total,
        empty_message="Aucun arbitrage enregistré sur le relevé TRI.",
    )

    # Notes méthodologiques discrètes sous les tableaux
    notes_left = " ".join(part for part in [v_compact_note, meta["assumption_note"]] if part)
    if notes_left:
        note_l = slide.shapes.add_textbox(Inches(left_x), Inches(6.68), Inches(panel_w), Inches(0.38))
        tf_nl = note_l.text_frame
        tf_nl.word_wrap = True
        p_nl = tf_nl.paragraphs[0]
        p_nl.text = notes_left
        p_nl.font.name = "Calibri"
        p_nl.font.size = Pt(8)
        p_nl.font.italic = True
        p_nl.font.color.rgb = MUTED_TEXT

    if a_compact_note:
        note_r = slide.shapes.add_textbox(Inches(right_x), Inches(6.68), Inches(panel_w), Inches(0.38))
        tf_nr = note_r.text_frame
        tf_nr.word_wrap = True
        p_nr = tf_nr.paragraphs[0]
        p_nr.text = a_compact_note
        p_nr.font.name = "Calibri"
        p_nr.font.size = Pt(8)
        p_nr.font.italic = True
        p_nr.font.color.rgb = MUTED_TEXT


def build_contract_pptx_context(
    client_name: str,
    contrat_num: str,
    df_contrats_all: pd.DataFrame,
    df_allocations_all: pd.DataFrame,
    df_contrat_selected: pd.DataFrame,
    df_allocations_client: pd.DataFrame,
    df_contrat_agg: pd.DataFrame | None = None,
    tri_analysis: dict | None = None,
    preferred_source: str = "CSV contrats",
    date_debut=None,
    date_fin=None,
    show_versements: bool = True,
    show_arbitrages: bool = True,
    fonds_dir: str | None = None,
    auto_extract_tri: bool = True,
) -> dict[str, Any]:
    """Prépare toutes les figures nécessaires au bilan PowerPoint à partir des helpers du GUI."""
    if auto_extract_tri:
        tri_analysis = _resolve_tri_analysis_for_contract(
            contrat_num=contrat_num,
            df_contrats_all=df_contrats_all,
            df_contrat_selected=df_contrat_selected,
            tri_analysis=tri_analysis,
        )

    source_context = resolve_payment_source(df_contrat_selected, tri_analysis, preferred_source)
    kpis = build_kpi_overrides(df_contrat_selected, source_context)
    df_versements, df_arbitrages, ops_meta = prepare_operations_tables(tri_analysis)

    enveloppe = (
        str(df_contrat_selected["Enveloppe"].iloc[0])
        if not df_contrat_selected.empty and "Enveloppe" in df_contrat_selected.columns
        else "N/A"
    )
    is_per = "PER" in enveloppe.upper()

    # 1. Donuts composition (GUI)
    _, _, fig_typologie_simplifiee, fig_supports = build_composition_figures(df_allocations_client)

    # 2. Waterfall performance du contrat (IR 30% automatique si PER)
    fig_waterfall_contract = build_contract_waterfall_figure(
        df_contrats_all=df_contrats_all,
        df_allocations_all=df_allocations_all,
        df_contrat_selected=df_contrat_selected,
        contrat_num=contrat_num,
        source_context=source_context,
        add_reduction_ir=is_per,
        ir_num=0.30 if is_per else 0.0,
    )

    # 3. Waterfall allocation
    fig_waterfall_allocation = build_allocation_waterfall_figure(
        df_allocations_all=df_allocations_all,
        contrat_num=contrat_num,
    )

    # 4 & 5. Évolution des fonds (tous les fonds + par classe d'actifs simplifiée)
    df_perfs, latest_funds_file = load_latest_fund_perf_file(fonds_dir)
    fig_all_funds = None
    figures_by_class: list[tuple[str, go.Figure]] = []
    missing_funds_labels: list[str] = []

    if not df_perfs.empty and not df_allocations_client.empty:
        min_d = df_perfs["Date"].min().date()
        max_d = df_perfs["Date"].max().date()
        eff_end = date_fin or max_d
        if date_debut is not None:
            eff_start = date_debut
        else:
            default_start = (df_perfs["Date"].max() - pd.DateOffset(years=1)).date()
            eff_start = max(default_start, min_d)

        if eff_start < eff_end:
            bundle = build_contract_and_class_fund_figures(
                df_perfs=df_perfs,
                df_alloc_ctr=df_allocations_client,
                contrat_num=contrat_num,
                date_debut=eff_start,
                date_fin=eff_end,
                tri_analysis=tri_analysis,
                show_versements=show_versements,
                show_arbitrages=show_arbitrages,
            )
            fig_all_funds = bundle.get("fig_all_funds")
            figures_by_class = bundle.get("figures_by_class", [])
            missing_funds_labels = bundle.get("missing_labels", [])

    # 6. Évolution temporelle de la VL du contrat avec versements et arbitrages
    df_hist_ctr = (
        df_contrat_agg[df_contrat_agg["N° de contrat"] == contrat_num].copy()
        if df_contrat_agg is not None and not df_contrat_agg.empty and "N° de contrat" in df_contrat_agg.columns
        else pd.DataFrame(columns=df_contrat_selected.columns)
    )
    fig_evol = build_evolution_figure(
        df_historical_for_contract=df_hist_ctr,
        df_current_for_contract=df_contrat_selected.copy(),
        contrat_num=contrat_num,
        tri_analysis=tri_analysis,
        source_context=source_context,
        add_reduction_ir=is_per,
        ir_num=0.30 if is_per else 0.0,
        include_versements=show_versements,
        include_arbitrages=show_arbitrages,
    )

    return {
        "client_name": client_name,
        "contrat_num": contrat_num,
        "is_per": is_per,
        "tri_analysis": tri_analysis,
        "df_versements": df_versements,
        "df_arbitrages": df_arbitrages,
        "ops_meta": ops_meta,
        "source_context": source_context,
        "kpis": kpis,
        "fig_typologie_simplifiee": fig_typologie_simplifiee,
        "fig_supports": fig_supports,
        "fig_waterfall_contract": fig_waterfall_contract,
        "fig_waterfall_allocation": fig_waterfall_allocation,
        "fig_all_funds": fig_all_funds,
        "figures_by_class": figures_by_class,
        "fig_evol": fig_evol,
        "latest_funds_file": latest_funds_file,
        "missing_funds_labels": missing_funds_labels,
    }


def generate_contract_pptx(
    client_name: str,
    contrat_num: str,
    df_contrat_sel: pd.DataFrame,
    fig_typologie_simplifiee: go.Figure | None,
    fig_supports: go.Figure | None,
    fig_waterfall_contract: go.Figure | None,
    fig_waterfall_allocation: go.Figure | None,
    fig_all_funds: go.Figure | None,
    figures_by_class: list[tuple[str, go.Figure]],
    fig_evol: go.Figure | None,
    kpis: dict[str, Any] | None = None,
    is_per: bool = False,
    tri_analysis: dict | None = None,
    auto_extract_tri: bool = True,
) -> bytes:
    """Génère le document PowerPoint (.pptx) complet en mémoire et renvoie ses bytes."""
    if tri_analysis is None and auto_extract_tri:
        tri_analysis = _resolve_tri_analysis_for_contract(
            contrat_num=contrat_num,
            df_contrats_all=df_contrat_sel,
            df_contrat_selected=df_contrat_sel,
            tri_analysis=None,
        )

    prs = Presentation()
    prs.slide_width = SLIDE_WIDTH
    prs.slide_height = SLIDE_HEIGHT
    blank_layout = prs.slide_layouts[6]

    enveloppe = (
        str(df_contrat_sel["Enveloppe"].iloc[0])
        if not df_contrat_sel.empty and "Enveloppe" in df_contrat_sel.columns
        else "N/A"
    )
    partenaire = (
        str(df_contrat_sel["Partenaire"].iloc[0])
        if not df_contrat_sel.empty and "Partenaire" in df_contrat_sel.columns
        else "N/A"
    )
    valorisation = (
        float(df_contrat_sel["Valorisation"].iloc[0])
        if not df_contrat_sel.empty and "Valorisation" in df_contrat_sel.columns
        else 0.0
    )
    date_val_raw = (
        df_contrat_sel["Date de valorisation"].iloc[0]
        if not df_contrat_sel.empty and "Date de valorisation" in df_contrat_sel.columns
        else None
    )
    date_ouv_raw = (
        df_contrat_sel["Ouverture"].iloc[0]
        if not df_contrat_sel.empty and "Ouverture" in df_contrat_sel.columns
        else None
    )
    date_val_str = safe_date_format(date_val_raw, "%d/%m/%Y", "N/A")
    date_ouv_str = safe_date_format(date_ouv_raw, "%d/%m/%Y", "N/A")
    valorisation_str = f"{valorisation:,.0f} €".replace(",", " ")

    contract_badge = f"{enveloppe}  •  {partenaire}  •  N° {contrat_num}"
    subtitle = (
        f"Titulaire : {client_name}   |   Valorisation : {valorisation_str} "
        f"(au {date_val_str})   |   Ouverture : {date_ouv_str}"
    )
    footer_left = f"Bilan de contrat — {client_name} — {enveloppe} N° {contrat_num}"

    # Nombre total de slides :
    # 1 (Page de garde) + 1 (Composition) + 1 (WF contrat) + 1 (WF allocation)
    # + 1 (Fonds global) + N (Fonds par classe d'actifs) + 1 (Versements & Arbitrages) + 1 (Évolution VL)
    class_slides = figures_by_class or []
    total_slides = 7 + len(class_slides)
    slide_idx = 1

    # --- Slide 1 : Page de garde (informations clés du contrat) ---
    cover_slide = prs.slides.add_slide(blank_layout)
    _add_cover_slide(
        slide=cover_slide,
        client_name=client_name,
        contrat_num=contrat_num,
        enveloppe=enveloppe,
        partenaire=partenaire,
        is_per=is_per,
        valorisation_str=valorisation_str,
        date_val_str=date_val_str,
        date_ouv_str=date_ouv_str,
        total_slides=total_slides,
    )

    def _new_slide(title: str):
        nonlocal slide_idx
        slide_idx += 1
        s = prs.slides.add_slide(blank_layout)
        _add_slide_chrome(
            slide=s,
            slide_title=title,
            contract_badge=contract_badge,
            subtitle=subtitle,
            footer_left=footer_left,
            slide_index=slide_idx,
            total_slides=total_slides,
        )
        return s

    # --- Slide 1 : Composition par classes d'actifs simplifiées et par fonds (donuts du GUI) ---
    slide1 = _new_slide("Composition du portefeuille")
    img_donut_typo = convert_figure_to_png_bytes(
        fig_typologie_simplifiee, width_px=720, height_px=600, scale=2, legend_bottom=True
    )
    img_donut_supports = convert_figure_to_png_bytes(
        fig_supports, width_px=720, height_px=600, scale=2, legend_bottom=True
    )
    _add_picture_fit(
        slide1,
        img_donut_typo,
        left_in=0.35,
        top_in=1.32,
        max_width_in=6.20,
        max_height_in=5.65,
        aspect_ratio=720 / 600,
        empty_message="Graphique des classes d'actifs simplifiées indisponible.",
    )
    _add_picture_fit(
        slide1,
        img_donut_supports,
        left_in=6.78,
        top_in=1.32,
        max_width_in=6.20,
        max_height_in=5.65,
        aspect_ratio=720 / 600,
        empty_message="Graphique de répartition par fonds indisponible.",
    )

    # --- Slide 2 : Waterfall de la performance du contrat (avec IR 30% si PER) ---
    wf_title = (
        "Performance du contrat (avec réduction d'IR à 30 %)"
        if is_per
        else "Performance du contrat"
    )
    slide2 = _new_slide(wf_title)
    if kpis:
        kpi_cards = [
            ("Valorisation", valorisation_str),
            ("Versements bruts", str(kpis.get("montant_versements_bruts_str", "N/A"))),
            ("Versements nets", str(kpis.get("montant_versements_nets_kpi_str", "N/A"))),
            ("Perf. / Versements bruts", str(kpis.get("var_vs_brut_pct_str", "N/A"))),
            ("TRI net / TRA", str(kpis.get("tri_net_str") if kpis.get("tri_net_str") not in (None, "N/A") else kpis.get("tra_str", "N/A"))),
        ]
        _add_kpi_strip(slide2, kpi_cards, top_in=1.28)
        wf_top = 2.06
        wf_max_h = 4.92
        wf_h_px = 540
    else:
        wf_top = 1.32
        wf_max_h = 5.65
        wf_h_px = 620

    img_wf_contract = convert_figure_to_png_bytes(
        fig_waterfall_contract, width_px=1320, height_px=wf_h_px, scale=2
    )
    _add_picture_fit(
        slide2,
        img_wf_contract,
        left_in=0.45,
        top_in=wf_top,
        max_width_in=12.43,
        max_height_in=wf_max_h,
        aspect_ratio=1320 / wf_h_px,
        empty_message="Waterfall de performance du contrat indisponible.",
    )

    # --- Slide 3 : Waterfall de l'allocation ---
    slide3 = _new_slide("Waterfall de l'allocation par support")
    img_wf_alloc = convert_figure_to_png_bytes(
        fig_waterfall_allocation, width_px=1320, height_px=620, scale=2
    )
    _add_picture_fit(
        slide3,
        img_wf_alloc,
        left_in=0.45,
        top_in=1.32,
        max_width_in=12.43,
        max_height_in=5.65,
        aspect_ratio=1320 / 620,
        empty_message="Waterfall de l'allocation indisponible (aucun support UC détecté).",
    )

    # --- Slide 4 : Évolution dans le temps des fonds (reprend celui du GUI) ---
    slide4 = _new_slide("Évolution dans le temps des fonds du contrat (base 100)")
    img_all_funds = convert_figure_to_png_bytes(
        fig_all_funds, width_px=1320, height_px=620, scale=2, legend_bottom=True
    )
    _add_picture_fit(
        slide4,
        img_all_funds,
        left_in=0.45,
        top_in=1.32,
        max_width_in=12.43,
        max_height_in=5.65,
        aspect_ratio=1320 / 620,
        empty_message="Aucun historique de performance disponible pour les fonds de ce contrat.",
    )

    # --- Slides 5..K : Même graphe pour les fonds de chaque classe d'actifs simplifiée ---
    for asset_class, fig_cls in class_slides:
        slide_cls = _new_slide(f"Évolution des fonds — {asset_class} (base 100)")
        img_cls = convert_figure_to_png_bytes(
            fig_cls, width_px=1320, height_px=620, scale=2, legend_bottom=True
        )
        _add_picture_fit(
            slide_cls,
            img_cls,
            left_in=0.45,
            top_in=1.32,
            max_width_in=12.43,
            max_height_in=5.65,
            aspect_ratio=1320 / 620,
            empty_message=f"Aucun historique disponible pour la classe {asset_class}.",
        )

    # --- Slide avant-dernière : Tableaux détaillés des versements et arbitrages ---
    slide_ops = _new_slide("Détail des versements et des arbitrages")
    _add_operations_slide(slide_ops, tri_analysis=tri_analysis)

    # --- Dernière Slide : Évolution temporelle de la VL du contrat avec versements et arbitrages ---
    slide_vl = _new_slide("Évolution de la VL du contrat (versements et arbitrages)")
    img_evol = convert_figure_to_png_bytes(
        fig_evol, width_px=1320, height_px=620, scale=2, legend_bottom=True
    )
    _add_picture_fit(
        slide_vl,
        img_evol,
        left_in=0.45,
        top_in=1.32,
        max_width_in=12.43,
        max_height_in=5.65,
        aspect_ratio=1320 / 620,
        empty_message="Historique de valorisation insuffisant pour tracer l'évolution temporelle de la VL.",
    )

    output = io.BytesIO()
    prs.save(output)
    return output.getvalue()

