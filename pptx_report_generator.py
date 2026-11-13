"""
Module de génération de bilans de contrat au format PowerPoint (.pptx).
"""

from __future__ import annotations

import io
import json
import os
import re
import stat
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Callable

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
    prepare_portfolio_lines_table,
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

# Couleurs pour la mise en valeur des performances (vert/rouge sobre)
GREEN_ROW_BG = RGBColor(0xF0, 0xF9, 0xF4)
GREEN_CELL_BG = RGBColor(0xDC, 0xF2, 0xE4)
GREEN_TEXT = RGBColor(0x13, 0x73, 0x33)

RED_ROW_BG = RGBColor(0xFD, 0xF4, 0xF4)
RED_CELL_BG = RGBColor(0xFD, 0xDE, 0xDC)
RED_TEXT = RGBColor(0xC5, 0x22, 0x1F)

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
    has_cartesian_axes = any(
        getattr(tr, "type", "") not in ("pie", "sunburst", "treemap")
        for tr in fig_export.data
    )
    visible_legend_items = sum(
        1 for tr in fig_export.data if getattr(tr, "showlegend", True) is not False
    )

    layout_updates: dict[str, Any] = {
        "paper_bgcolor": "white",
        "plot_bgcolor": "white",
        "font": {"color": "#1F2937"},
        "width": width_px,
        "height": height_px,
    }
    if has_cartesian_axes:
        fig_export.update_xaxes(automargin=True, title_standoff=12)
        fig_export.update_yaxes(automargin=True, title_standoff=14)

    if legend_bottom:
        if has_cartesian_axes:
            est_rows = max(1, (visible_legend_items + 3) // 4)
            bottom_margin = min(200, 95 + est_rows * 24)
            layout_updates["legend"] = {
                "orientation": "h",
                "yanchor": "top",
                "y": -0.18,
                "xanchor": "center",
                "x": 0.5,
                "font": {"size": 10},
            }
            layout_updates["margin"] = {
                "t": 60,
                "b": bottom_margin,
                "l": 85,
                "r": 55,
                "autoexpand": True,
            }
        else:
            est_rows = max(1, (visible_legend_items + 2) // 3)
            bottom_margin = min(190, 80 + est_rows * 22)
            layout_updates["legend"] = {
                "orientation": "h",
                "yanchor": "top",
                "y": -0.06,
                "xanchor": "center",
                "x": 0.5,
                "font": {"size": 10},
            }
            layout_updates["margin"] = {
                "t": 55,
                "b": bottom_margin,
                "l": 25,
                "r": 25,
                "autoexpand": True,
            }
    elif has_cartesian_axes:
        layout_updates["margin"] = {
            "t": 65,
            "b": 85,
            "l": 80,
            "r": 35,
            "autoexpand": True,
        }

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


def _load_mandataire_info() -> dict[str, str]:
    """Charge les coordonnées du cabinet / mandataire depuis mandataire.json ou defaults/mandataire.json."""
    base_dir = Path(__file__).resolve().parent
    candidates = [
        base_dir / "mandataire.json",
        base_dir / "defaults" / "mandataire.json",
        Path.cwd() / "mandataire.json",
        Path.cwd() / "defaults" / "mandataire.json",
    ]
    for p in candidates:
        try:
            if p.is_file():
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return {
                            "nom": str(data.get("nom", "Navarro")).strip(),
                            "prenom": str(data.get("prenom", "Jean-Philippe")).strip(),
                            "raison_sociale": str(data.get("raison_sociale", "Avenir-Patrimoine")).strip(),
                        }
        except Exception:
            pass
    return {
        "nom": "Navarro",
        "prenom": "Jean-Philippe",
        "raison_sociale": "Avenir-Patrimoine",
    }


def _add_back_cover_slide(
    slide,
    client_name: str,
    contrat_num: str,
    enveloppe: str,
    partenaire: str,
    valorisation_str: str,
    date_val_str: str,
    date_ouv_str: str,
    slide_index: int,
    total_slides: int,
) -> None:
    """Ajoute une slide de 4ème de couverture pour clôturer la présentation proprement."""
    mandataire = _load_mandataire_info()
    cgp_name = f"{mandataire.get('prenom', 'Jean-Philippe')} {mandataire.get('nom', 'Navarro').upper()}".strip()
    cabinet = mandataire.get("raison_sociale", "Avenir-Patrimoine").strip()

    # Liserés supérieurs corporate (fond blanc conservé sur toute la slide)
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

    # Liserés inférieurs corporate
    sub_bottom = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0), Inches(7.37), SLIDE_WIDTH, Inches(0.03)
    )
    sub_bottom.fill.solid()
    sub_bottom.fill.fore_color.rgb = ACCENT_BLUE
    sub_bottom.line.fill.background()

    bottom_strip = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0), Inches(7.40), SLIDE_WIDTH, Inches(0.10)
    )
    bottom_strip.fill.solid()
    bottom_strip.fill.fore_color.rgb = NAVY
    bottom_strip.line.fill.background()

    # Badge de conclusion
    badge = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.95), Inches(0.68), Inches(4.30), Inches(0.38)
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
    p_b.text = "SYNTHÈSE DU BILAN  •  CLÔTURE"
    p_b.font.name = "Calibri"
    p_b.font.size = Pt(10.5)
    p_b.font.bold = True
    p_b.font.color.rgb = NAVY

    # Titre principal & sous-titre
    title_box = slide.shapes.add_textbox(Inches(0.95), Inches(1.18), Inches(11.43), Inches(0.65))
    p_t = title_box.text_frame.paragraphs[0]
    p_t.text = "Merci pour votre confiance"
    p_t.font.name = "Calibri"
    p_t.font.size = Pt(34)
    p_t.font.bold = True
    p_t.font.color.rgb = NAVY

    sub_box = slide.shapes.add_textbox(Inches(0.95), Inches(1.84), Inches(11.43), Inches(0.42))
    p_s = sub_box.text_frame.paragraphs[0]
    p_s.text = (
        "Votre conseiller reste à votre entière disposition pour tout échange, bilan périodique "
        "ou ajustement de votre stratégie d'investissement."
    )
    p_s.font.name = "Calibri"
    p_s.font.size = Pt(13)
    p_s.font.color.rgb = DARK_TEXT

    # Ligne de séparation fine
    sep = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0.95), Inches(2.36), Inches(11.43), Inches(0.02)
    )
    sep.fill.solid()
    sep.fill.fore_color.rgb = CARD_BORDER
    sep.line.fill.background()

    # --- Carte Gauche : Cabinet & Mandataire ---
    card_left = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.95), Inches(2.55), Inches(5.55), Inches(2.95)
    )
    card_left.fill.solid()
    card_left.fill.fore_color.rgb = CARD_BG
    card_left.line.color.rgb = CARD_BORDER
    card_left.line.width = Pt(1)

    tf_cl = card_left.text_frame
    tf_cl.word_wrap = True
    tf_cl.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf_cl.margin_left = Inches(0.40)
    tf_cl.margin_right = Inches(0.40)
    tf_cl.margin_top = Inches(0.25)
    tf_cl.margin_bottom = Inches(0.25)

    p0 = tf_cl.paragraphs[0]
    p0.text = "VOTRE CABINET CONSEIL"
    p0.font.name = "Calibri"
    p0.font.size = Pt(9.5)
    p0.font.bold = True
    p0.font.color.rgb = ACCENT_BLUE

    p1 = tf_cl.add_paragraph()
    p1.text = cabinet
    p1.font.name = "Calibri"
    p1.font.size = Pt(21)
    p1.font.bold = True
    p1.font.color.rgb = NAVY

    p2 = tf_cl.add_paragraph()
    p2.text = cgp_name
    p2.font.name = "Calibri"
    p2.font.size = Pt(15)
    p2.font.bold = True
    p2.font.color.rgb = DARK_TEXT

    p3 = tf_cl.add_paragraph()
    p3.text = "Conseil en Gestion de Patrimoine"
    p3.font.name = "Calibri"
    p3.font.size = Pt(11.5)
    p3.font.color.rgb = MUTED_TEXT

    # --- Carte Droite : Références du Contrat ---
    card_right = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(6.83), Inches(2.55), Inches(5.55), Inches(2.95)
    )
    card_right.fill.solid()
    card_right.fill.fore_color.rgb = CARD_BG
    card_right.line.color.rgb = CARD_BORDER
    card_right.line.width = Pt(1)

    tf_cr = card_right.text_frame
    tf_cr.word_wrap = True
    tf_cr.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf_cr.margin_left = Inches(0.40)
    tf_cr.margin_right = Inches(0.40)
    tf_cr.margin_top = Inches(0.25)
    tf_cr.margin_bottom = Inches(0.25)

    pr0 = tf_cr.paragraphs[0]
    pr0.text = "RÉFÉRENCES DU DOSSIER"
    pr0.font.name = "Calibri"
    pr0.font.size = Pt(9.5)
    pr0.font.bold = True
    pr0.font.color.rgb = ACCENT_BLUE

    pr1 = tf_cr.add_paragraph()
    pr1.text = client_name
    pr1.font.name = "Calibri"
    pr1.font.size = Pt(19)
    pr1.font.bold = True
    pr1.font.color.rgb = NAVY

    pr2 = tf_cr.add_paragraph()
    pr2.text = f"{enveloppe}  •  N° {contrat_num}"
    pr2.font.name = "Calibri"
    pr2.font.size = Pt(13.5)
    pr2.font.bold = True
    pr2.font.color.rgb = DARK_TEXT

    pr3 = tf_cr.add_paragraph()
    pr3.text = f"Partenaire : {partenaire}"
    pr3.font.name = "Calibri"
    pr3.font.size = Pt(11.5)
    pr3.font.color.rgb = DARK_TEXT

    # --- Bloc avertissement / mentions légales ---
    legal_box = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.95), Inches(5.75), Inches(11.43), Inches(0.85)
    )
    legal_box.fill.solid()
    legal_box.fill.fore_color.rgb = WHITE
    legal_box.line.color.rgb = CARD_BORDER
    legal_box.line.width = Pt(1)

    tf_l = legal_box.text_frame
    tf_l.word_wrap = True
    tf_l.margin_left = Inches(0.25)
    tf_l.margin_right = Inches(0.25)
    tf_l.margin_top = Inches(0.12)
    tf_l.margin_bottom = Inches(0.10)
    pl = tf_l.paragraphs[0]
    pl.text = (
        "Avertissement & Mentions réglementaires : Le présent bilan est un document de synthèse confidentiel "
        "établi pour le titulaire désigné. Les performances passées ne préjugent pas des performances futures "
        "et ne sont pas constantes dans le temps. Les investissements sur des supports en unités de compte comportent "
        "un risque de perte en capital. Document non contractuel rédigé sur la base des données valorisées fournies par l'assureur."
    )
    pl.font.name = "Calibri"
    pl.font.size = Pt(8.5)
    pl.font.color.rgb = MUTED_TEXT

    # Pied de page
    foot_l = slide.shapes.add_textbox(Inches(0.95), Inches(6.98), Inches(8.0), Inches(0.28))
    pfl = foot_l.text_frame.paragraphs[0]
    pfl.text = f"{cabinet}  •  {cgp_name}  •  Bilan de contrat"
    pfl.font.name = "Calibri"
    pfl.font.size = Pt(9.5)
    pfl.font.color.rgb = MUTED_TEXT

    foot_r = slide.shapes.add_textbox(Inches(10.0), Inches(6.98), Inches(2.38), Inches(0.28))
    pfr = foot_r.text_frame.paragraphs[0]
    pfr.alignment = PP_ALIGN.RIGHT
    pfr.text = f"Slide {slide_index} / {total_slides}"
    pfr.font.name = "Calibri"
    pfr.font.size = Pt(9.5)
    pfr.font.color.rgb = MUTED_TEXT


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
    color_evolution: bool = False,
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
    elif len(rows) <= 20:
        font_pt = 8.0
        row_h_in = min(0.225, max_height_in / max(n_rows, 1))
    else:
        font_pt = 7.5
        row_h_in = min(0.20, max_height_in / max(n_rows, 1))

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

    # Détecter la colonne d'évolution en % si color_evolution activé
    evol_col_idx = -1
    if color_evolution:
        for c_idx, h in enumerate(headers):
            h_clean = h.lower()
            if "évol" in h_clean or "perf" in h_clean:
                evol_col_idx = c_idx
                break

    # Lignes de données + total
    for idx, row_vals in enumerate(all_rows):
        is_total = total_row is not None and idx == len(all_rows) - 1
        row_bg = TOTAL_ROW_BG if is_total else (ZEBRA_BG if idx % 2 == 1 else WHITE)
        is_pos_fund = False
        is_neg_fund = False

        if color_evolution and not is_total and evol_col_idx >= 0 and evol_col_idx < len(row_vals):
            evol_str = str(row_vals[evol_col_idx]).strip()
            if evol_str.startswith("+") and not evol_str.startswith("+0.00") and not evol_str.startswith("+0,00"):
                is_pos_fund = True
                row_bg = GREEN_ROW_BG
            elif evol_str.startswith("-") and not evol_str.startswith("-0.00") and not evol_str.startswith("-0,00"):
                is_neg_fund = True
                row_bg = RED_ROW_BG

        for c_idx, val in enumerate(row_vals):
            cell_bg = row_bg
            cell_fg = NAVY if is_total else DARK_TEXT
            cell_bold = is_total

            if color_evolution and c_idx == evol_col_idx:
                if is_total:
                    tot_evol_str = str(val).strip()
                    if tot_evol_str.startswith("+") and not tot_evol_str.startswith("+0"):
                        cell_fg = GREEN_TEXT
                    elif tot_evol_str.startswith("-") and not tot_evol_str.startswith("-0"):
                        cell_fg = RED_TEXT
                    cell_bold = True
                elif is_pos_fund:
                    cell_bg = GREEN_CELL_BG
                    cell_fg = GREEN_TEXT
                    cell_bold = True
                elif is_neg_fund:
                    cell_bg = RED_CELL_BG
                    cell_fg = RED_TEXT
                    cell_bold = True

            _style_cell(table.cell(idx + 1, c_idx), str(val), col_alignments[c_idx], cell_bg, cell_fg, cell_bold, font_pt)


def _add_portfolio_lines_slide(
    slide,
    df_allocations_client: pd.DataFrame | None,
) -> None:
    """Remplit la première slide de contenu avec le tableau détaillé des lignes du portefeuille groupé par type."""
    df_display, rows, total_row, meta = prepare_portfolio_lines_table(df_allocations_client)
    if df_display.empty or not rows:
        _add_picture_fit(
            slide,
            None,
            left_in=0.61,
            top_in=1.35,
            max_width_in=12.1,
            max_height_in=3.0,
            aspect_ratio=3.0,
            empty_message="Aucune ligne de portefeuille disponible pour ce contrat.",
        )
        return

    n_rows = len(rows)
    kpis = [
        ("Nombre de supports", f"{meta.get('n_supports', n_rows)} fonds"),
        ("Classes d'actifs", f"{meta.get('n_types', 1)} typologies"),
        ("Encours total", f"{meta.get('total_encours', 0.0):,.0f} €".replace(",", " ")),
        ("Plus-value latente globale", f"{meta.get('total_pct', 0.0):+.2f} %"),
    ]
    _add_kpi_strip(slide, kpis, top_in=1.28)
    tbl_top = 2.04
    tbl_max_h = 4.88

    headers = ["Type (simplifié)", "Nom du support", "Code ISIN", "Encours", "Évolution"]
    col_widths = [2.4, 4.4, 1.8, 1.8, 1.7]
    col_aligns = [PP_ALIGN.LEFT, PP_ALIGN.LEFT, PP_ALIGN.CENTER, PP_ALIGN.RIGHT, PP_ALIGN.RIGHT]

    _add_styled_table(
        slide,
        left_in=0.61,
        top_in=tbl_top,
        width_in=12.1,
        max_height_in=tbl_max_h,
        headers=headers,
        col_widths_in=col_widths,
        col_alignments=col_aligns,
        rows=rows,
        total_row=total_row,
        empty_message="Aucune ligne de portefeuille disponible.",
        color_evolution=True,
    )


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
    df_perfs: pd.DataFrame | None = None,
    latest_funds_file: str | None = None,
    monthly_contribution: float | None = None,
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
    df_alloc_work, _, fig_typologie_simplifiee, fig_supports = build_composition_figures(df_allocations_client)

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
    if df_perfs is None:
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

    # 7. Projections de valorisation à 8 ans et 2 ans
    fig_projection_8ans = None
    fig_projection_2ans = None
    try:
        import datetime
        from projection_helpers import (
            calculate_contract_projection,
            detect_initial_contribution,
            detect_default_monthly_contribution,
            build_projection_trajectory_figure,
        )
        init_info = detect_initial_contribution(df_contrat_selected, tri_analysis, df_hist_ctr)
        vp_auto = detect_default_monthly_contribution(tri_analysis, df_contrat_selected)
        eff_vp = float(monthly_contribution) if monthly_contribution is not None else float(vp_auto)
        hist_movements = tri_analysis.get("movements") if (tri_analysis and isinstance(tri_analysis.get("movements"), pd.DataFrame)) else None

        current_val = (
            float(df_contrat_selected["Valorisation"].iloc[0])
            if not df_contrat_selected.empty and "Valorisation" in df_contrat_selected.columns
            else 0.0
        )
        date_val_raw = (
            df_contrat_selected["Date de valorisation"].iloc[0]
            if not df_contrat_selected.empty and "Date de valorisation" in df_contrat_selected.columns
            else None
        )
        current_dt = pd.to_datetime(date_val_raw).date() if pd.notna(date_val_raw) else datetime.date.today()

        scenarios_std = {
            "Prudent": 0.025,
            "Équilibré": 0.050,
            "Dynamique": 0.060,
        }

        # Projection 8 ans
        proj_8 = calculate_contract_projection(
            current_valuation=current_val,
            current_date=current_dt,
            initial_amount=init_info["initial_amount_net"],
            initial_amount_gross=init_info["initial_amount_gross"],
            initial_date=init_info["initial_date"],
            years=8,
            monthly_contribution=eff_vp if eff_vp > 0 else 0.0,
            annual_contribution=0.0,
            contribution_fee_pct=0.0,
            contract_fee_pct=1.0,
            fund_fee_pct=0.0,
            scenarios=scenarios_std,
            is_per=is_per,
            tmi_pct=30.0 if is_per else 0.0,
            historical_movements=hist_movements,
            future_anchor_mode="origin",
        )
        fig_projection_8ans = build_projection_trajectory_figure(
            projection_data=proj_8,
            historical_df=df_hist_ctr,
            contrat_num=contrat_num,
            client_name=client_name,
            future_anchor_mode="origin",
            filter_early_anomalies=True,
            anomaly_min_ratio=0.95,
            filter_transient_dips=True,
            height=600,
        )

        # Projection 2 ans
        proj_2 = calculate_contract_projection(
            current_valuation=current_val,
            current_date=current_dt,
            initial_amount=init_info["initial_amount_net"],
            initial_amount_gross=init_info["initial_amount_gross"],
            initial_date=init_info["initial_date"],
            years=2,
            monthly_contribution=eff_vp if eff_vp > 0 else 0.0,
            annual_contribution=0.0,
            contribution_fee_pct=0.0,
            contract_fee_pct=1.0,
            fund_fee_pct=0.0,
            scenarios=scenarios_std,
            is_per=is_per,
            tmi_pct=30.0 if is_per else 0.0,
            historical_movements=hist_movements,
            future_anchor_mode="origin",
        )
        fig_projection_2ans = build_projection_trajectory_figure(
            projection_data=proj_2,
            historical_df=df_hist_ctr,
            contrat_num=contrat_num,
            client_name=client_name,
            future_anchor_mode="origin",
            filter_early_anomalies=True,
            anomaly_min_ratio=0.95,
            filter_transient_dips=True,
            height=600,
        )
    except Exception:
        fig_projection_8ans = None
        fig_projection_2ans = None

    return {
        "client_name": client_name,
        "contrat_num": contrat_num,
        "is_per": is_per,
        "tri_analysis": tri_analysis,
        "df_allocations_client": df_alloc_work if df_alloc_work is not None and not df_alloc_work.empty else df_allocations_client,
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
        "fig_projection_8ans": fig_projection_8ans,
        "fig_projection_2ans": fig_projection_2ans,
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
    fig_projection_8ans: go.Figure | None = None,
    fig_projection_2ans: go.Figure | None = None,
    df_allocations_client: pd.DataFrame | None = None,
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
    # 1 (Page de garde) + 1 (Lignes du portefeuille) + 1 (Composition) + 1 (Fonds global) + N (Fonds par classe d'actifs)
    # + 1 (Évolution VL) + 1 (Projection 8 ans) + 1 (Projection 2 ans) + 1 (4ème de couverture)
    # + 1 (WF contrat) + 1 (WF allocation) + 1 (Versements & Arbitrages)
    class_slides = figures_by_class or []
    has_proj_8 = 1 if fig_projection_8ans is not None else 0
    has_proj_2 = 1 if fig_projection_2ans is not None else 0
    total_slides = 9 + len(class_slides) + has_proj_8 + has_proj_2
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

    def _new_slide(title: str, is_annex: bool = False):
        nonlocal slide_idx
        slide_idx += 1
        s = prs.slides.add_slide(blank_layout)
        badge = f"ANNEXE TECHNIQUE  •  {contract_badge}" if is_annex else contract_badge
        foot = f"Annexe — {footer_left}" if is_annex else footer_left
        _add_slide_chrome(
            slide=s,
            slide_title=title,
            contract_badge=badge,
            subtitle=subtitle,
            footer_left=foot,
            slide_index=slide_idx,
            total_slides=total_slides,
        )
        return s

    # --- Slide 2 : Détail des lignes du portefeuille groupé par type (simplifié) ---
    slide_lines = _new_slide("Détail des lignes du portefeuille")
    _add_portfolio_lines_slide(slide_lines, df_allocations_client)

    # --- Slide 3 : Composition par classes d'actifs simplifiées et par fonds (donuts du GUI) ---
    slide_comp = _new_slide("Composition du portefeuille")
    img_donut_typo = convert_figure_to_png_bytes(
        fig_typologie_simplifiee, width_px=720, height_px=600, scale=2, legend_bottom=True
    )
    img_donut_supports = convert_figure_to_png_bytes(
        fig_supports, width_px=720, height_px=600, scale=2, legend_bottom=True
    )
    _add_picture_fit(
        slide_comp,
        img_donut_typo,
        left_in=0.35,
        top_in=1.32,
        max_width_in=6.20,
        max_height_in=5.65,
        aspect_ratio=720 / 600,
        empty_message="Graphique des classes d'actifs simplifiées indisponible.",
    )
    _add_picture_fit(
        slide_comp,
        img_donut_supports,
        left_in=6.78,
        top_in=1.32,
        max_width_in=6.20,
        max_height_in=5.65,
        aspect_ratio=720 / 600,
        empty_message="Graphique de répartition par fonds indisponible.",
    )

    # --- Slide 4 : Évolution dans le temps des fonds (reprend celui du GUI) ---
    slide_funds = _new_slide("Évolution dans le temps des fonds du contrat (base 100)")
    img_all_funds = convert_figure_to_png_bytes(
        fig_all_funds, width_px=1320, height_px=620, scale=2, legend_bottom=True
    )
    _add_picture_fit(
        slide_funds,
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

    # --- Slide : Évolution temporelle de la VL du contrat avec versements et arbitrages ---
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

    # --- Slide : Plan de projection de la valorisation (Horizon 8 ans) ---
    if fig_projection_8ans is not None:
        slide_proj_8 = _new_slide("Plan de projection de la valorisation (Horizon 8 ans)")
        img_proj_8 = convert_figure_to_png_bytes(
            fig_projection_8ans, width_px=1320, height_px=620, scale=2, legend_bottom=True
        )
        _add_picture_fit(
            slide_proj_8,
            img_proj_8,
            left_in=0.45,
            top_in=1.32,
            max_width_in=12.43,
            max_height_in=5.65,
            aspect_ratio=1320 / 620,
            empty_message="Graphique de projection à 8 ans indisponible.",
        )

    # --- Slide : Plan de projection de la valorisation (Horizon 2 ans) ---
    if fig_projection_2ans is not None:
        slide_proj_2 = _new_slide("Plan de projection de la valorisation (Horizon 2 ans)")
        img_proj_2 = convert_figure_to_png_bytes(
            fig_projection_2ans, width_px=1320, height_px=620, scale=2, legend_bottom=True
        )
        _add_picture_fit(
            slide_proj_2,
            img_proj_2,
            left_in=0.45,
            top_in=1.32,
            max_width_in=12.43,
            max_height_in=5.65,
            aspect_ratio=1320 / 620,
            empty_message="Graphique de projection à 2 ans indisponible.",
        )

    # --- Slide : 4ème de couverture (Clôture de la présentation) ---
    slide_idx += 1
    back_cover_slide = prs.slides.add_slide(blank_layout)
    _add_back_cover_slide(
        slide=back_cover_slide,
        client_name=client_name,
        contrat_num=contrat_num,
        enveloppe=enveloppe,
        partenaire=partenaire,
        valorisation_str=valorisation_str,
        date_val_str=date_val_str,
        date_ouv_str=date_ouv_str,
        slide_index=slide_idx,
        total_slides=total_slides,
    )

    # =========================================================================
    # --- ANNEXES (placées après la 4ème de couverture) ---
    # =========================================================================

    # --- Annexe 1 : Waterfall de la performance du contrat (avec IR 30% si PER) ---
    wf_title = (
        "Annexe — Performance du contrat (avec réduction d'IR à 30 %)"
        if is_per
        else "Annexe — Performance globale du contrat"
    )
    slide_wf_c = _new_slide(wf_title, is_annex=True)
    if kpis:
        kpi_cards = [
            ("Valorisation", valorisation_str),
            ("Versements bruts", str(kpis.get("montant_versements_bruts_str", "N/A"))),
            ("Versements nets", str(kpis.get("montant_versements_nets_kpi_str", "N/A"))),
            ("Perf. / Versements bruts", str(kpis.get("var_vs_brut_pct_str", "N/A"))),
            ("TRI net / TRA", str(kpis.get("tri_net_str") if kpis.get("tri_net_str") not in (None, "N/A") else kpis.get("tra_str", "N/A"))),
        ]
        _add_kpi_strip(slide_wf_c, kpi_cards, top_in=1.28)
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
        slide_wf_c,
        img_wf_contract,
        left_in=0.45,
        top_in=wf_top,
        max_width_in=12.43,
        max_height_in=wf_max_h,
        aspect_ratio=1320 / wf_h_px,
        empty_message="Waterfall de performance du contrat indisponible.",
    )

    # --- Annexe 2 : Waterfall de l'allocation ---
    slide_wf_a = _new_slide("Annexe — Waterfall de l'allocation par support", is_annex=True)
    img_wf_alloc = convert_figure_to_png_bytes(
        fig_waterfall_allocation, width_px=1320, height_px=620, scale=2
    )
    _add_picture_fit(
        slide_wf_a,
        img_wf_alloc,
        left_in=0.45,
        top_in=1.32,
        max_width_in=12.43,
        max_height_in=5.65,
        aspect_ratio=1320 / 620,
        empty_message="Waterfall de l'allocation indisponible (aucun support UC détecté).",
    )

    # --- Annexe 3 : Tableaux détaillés des versements et arbitrages ---
    slide_ops = _new_slide("Annexe — Détail des versements et des arbitrages", is_annex=True)
    _add_operations_slide(slide_ops, tri_analysis=tri_analysis)

    output = io.BytesIO()
    prs.save(output)
    return output.getvalue()


def sanitize_pptx_filename(value: str, fallback: str = "contrat") -> str:
    """Nettoie un libellé pour construire un nom de fichier ou de dossier sûr."""
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", str(value or "")).strip()
    return cleaned or fallback


def build_batch_pptx_targets(
    selected_clients: list[str],
    df_contrats: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Liste tous les contrats associés aux clients sélectionnés pour l'export multi-PPT."""
    if df_contrats is None or df_contrats.empty or not selected_clients:
        return []

    targets: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    titulaire_series = df_contrats["Titulaire(s)"].astype(str)

    for client in selected_clients:
        client_str = str(client)
        df_cli = df_contrats[titulaire_series == client_str]
        if df_cli.empty or "N° de contrat" not in df_cli.columns:
            continue
        for _, row in df_cli.iterrows():
            contrat_val = row.get("N° de contrat")
            if pd.isna(contrat_val):
                continue
            contrat_str = str(contrat_val).strip()
            if not contrat_str or (client_str, contrat_str) in seen:
                continue
            seen.add((client_str, contrat_str))
            enveloppe = str(row.get("Enveloppe", "N/A") or "N/A")
            partenaire = str(row.get("Partenaire", "N/A") or "N/A")
            val_num = pd.to_numeric(row.get("Valorisation", 0.0), errors="coerce")
            valorisation = 0.0 if pd.isna(val_num) else float(val_num)
            targets.append(
                {
                    "client_name": client_str,
                    "contrat_num": contrat_str,
                    "enveloppe": enveloppe,
                    "partenaire": partenaire,
                    "valorisation": valorisation,
                    "is_per": "PER" in enveloppe.upper(),
                }
            )
    return targets


def _deduplicate_archive_path(path: str, used_paths: set[str]) -> str:
    """Garantit l'unicité d'un chemin dans l'archive ZIP."""
    if path not in used_paths:
        used_paths.add(path)
        return path
    stem, ext = os.path.splitext(path)
    counter = 2
    candidate = f"{stem}_{counter}{ext}"
    while candidate in used_paths:
        counter += 1
        candidate = f"{stem}_{counter}{ext}"
    used_paths.add(candidate)
    return candidate


def generate_batch_contract_pptx(
    selected_clients: list[str],
    df_contrats_all: pd.DataFrame,
    df_allocations_all: pd.DataFrame,
    df_contrat_agg: pd.DataFrame | None = None,
    tri_contracts_map: dict[str, dict] | None = None,
    preferred_source: str = "Releve d'operations TRI",
    date_debut=None,
    date_fin=None,
    show_versements: bool = True,
    show_arbitrages: bool = True,
    fonds_dir: str | None = None,
    auto_extract_tri: bool = True,
    group_by_client_folder: bool = False,
    progress_callback: Callable[[int, int, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Génère un .pptx par contrat pour chaque client sélectionné et assemble une archive ZIP."""
    targets = build_batch_pptx_targets(selected_clients, df_contrats_all)
    if not targets:
        return {"items": [], "zip_bytes": None, "errors": []}

    resolved_tri_map = tri_contracts_map
    if resolved_tri_map is None and auto_extract_tri:
        cols = [c for c in ["N° de contrat", "Titulaire(s)", "Enveloppe", "Partenaire"] if c in df_contrats_all.columns]
        if "N° de contrat" in cols:
            _, resolved_tri_map = match_tri_analyses_to_contracts(
                load_tri_analyses(),
                df_contrats_all[cols].drop_duplicates().copy(),
            )
        else:
            resolved_tri_map = {}
    elif resolved_tri_map is None:
        resolved_tri_map = {}

    df_perfs, latest_funds_file = load_latest_fund_perf_file(fonds_dir)

    alloc_col = None
    if df_allocations_all is not None and not df_allocations_all.empty:
        if "Numéro contrat" in df_allocations_all.columns:
            alloc_col = "Numéro contrat"
        elif "Contrat" in df_allocations_all.columns:
            alloc_col = "Contrat"

    items: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    used_zip_paths: set[str] = set()
    used_file_names: set[str] = set()
    total = len(targets)

    for idx, target in enumerate(targets, start=1):
        client_name = target["client_name"]
        contrat_num = target["contrat_num"]
        if progress_callback is not None:
            progress_callback(idx, total, target)

        try:
            df_contrat_sel = df_contrats_all[
                (df_contrats_all["Titulaire(s)"].astype(str) == client_name)
                & (df_contrats_all["N° de contrat"].astype(str) == contrat_num)
            ].copy()
            if df_contrat_sel.empty:
                df_contrat_sel = df_contrats_all[df_contrats_all["N° de contrat"].astype(str) == contrat_num].copy()

            if alloc_col:
                df_alloc_cli = df_allocations_all[df_allocations_all[alloc_col].astype(str) == contrat_num].copy()
            else:
                df_alloc_cli = pd.DataFrame()

            if df_contrat_sel.empty:
                errors.append(
                    {
                        "client_name": client_name,
                        "contrat_num": contrat_num,
                        "error": "Ligne contrat introuvable.",
                    }
                )
                continue

            tri_analysis = resolved_tri_map.get(contrat_num)
            ctx = build_contract_pptx_context(
                client_name=client_name,
                contrat_num=contrat_num,
                df_contrats_all=df_contrats_all,
                df_allocations_all=df_allocations_all,
                df_contrat_selected=df_contrat_sel,
                df_allocations_client=df_alloc_cli,
                df_contrat_agg=df_contrat_agg,
                tri_analysis=tri_analysis,
                preferred_source=preferred_source,
                date_debut=date_debut,
                date_fin=date_fin,
                show_versements=show_versements,
                show_arbitrages=show_arbitrages,
                fonds_dir=fonds_dir,
                auto_extract_tri=False,
                df_perfs=df_perfs,
                latest_funds_file=latest_funds_file,
            )

            pptx_bytes = generate_contract_pptx(
                client_name=client_name,
                contrat_num=contrat_num,
                df_contrat_sel=df_contrat_sel,
                fig_typologie_simplifiee=ctx["fig_typologie_simplifiee"],
                fig_supports=ctx["fig_supports"],
                fig_waterfall_contract=ctx["fig_waterfall_contract"],
                fig_waterfall_allocation=ctx["fig_waterfall_allocation"],
                fig_all_funds=ctx["fig_all_funds"],
                figures_by_class=ctx["figures_by_class"],
                fig_evol=ctx["fig_evol"],
                fig_projection_8ans=ctx.get("fig_projection_8ans"),
                fig_projection_2ans=ctx.get("fig_projection_2ans"),
                df_allocations_client=ctx.get("df_allocations_client"),
                kpis=ctx["kpis"],
                is_per=ctx["is_per"],
                tri_analysis=ctx["tri_analysis"],
                auto_extract_tri=False,
            )

            safe_client = sanitize_pptx_filename(client_name, "client")
            safe_contrat = sanitize_pptx_filename(contrat_num, "contrat")
            base_name = f"{safe_client} - {safe_contrat} - Bilan.pptx"
            unique_file_name = _deduplicate_archive_path(base_name, used_file_names)
            raw_archive_path = f"{safe_client}/{unique_file_name}" if group_by_client_folder else unique_file_name
            archive_path = _deduplicate_archive_path(raw_archive_path, used_zip_paths)

            has_proj = (1 if ctx.get("fig_projection_8ans") else 0) + (1 if ctx.get("fig_projection_2ans") else 0)
            items.append(
                {
                    "client_name": client_name,
                    "contrat_num": contrat_num,
                    "enveloppe": target["enveloppe"],
                    "is_per": ctx["is_per"],
                    "slides_count": 9 + len(ctx["figures_by_class"]) + has_proj,
                    "file_name": unique_file_name,
                    "archive_path": archive_path,
                    "data": pptx_bytes,
                }
            )
        except Exception as exc:
            errors.append(
                {
                    "client_name": client_name,
                    "contrat_num": contrat_num,
                    "error": str(exc),
                }
            )

    zip_bytes: bytes | None = None
    if items:
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for item in items:
                zf.writestr(item["archive_path"], item["data"])
        zip_bytes = zip_buf.getvalue()

    return {"items": items, "zip_bytes": zip_bytes, "errors": errors}


