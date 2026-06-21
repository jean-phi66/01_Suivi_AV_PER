"""
Module pour la génération de rapports PDF
Contient la classe PDF personnalisée et les fonctions de génération de rapport
"""

import pandas as pd
import plotly.io as pio
from fpdf import FPDF

pio.templates.default = "none"

# Essayer d'importer FontFace, sinon utiliser une alternative
try:
    from fpdf.fonts import FontFace
except ImportError:
    # Créer une classe FontFace simple pour compatibilité
    class FontFace:
        def __init__(self, family=None, style=None, size_pt=None, emphasis=None, color=None):
            self.family = family
            self.style = style
            self.size_pt = size_pt
            self.emphasis = emphasis
            self.color = color


def safe_date_format(date_value, date_format='%d/%m/%Y', default="N/A"):
    """
    Formate une date de manière sécurisée en gérant les cas NaT et les valeurs invalides
    """
    try:
        if pd.isna(date_value):
            return default
        
        # Convertir en datetime si ce n'est pas déjà fait
        if not isinstance(date_value, pd.Timestamp):
            parsed_date = pd.to_datetime(date_value)
        else:
            parsed_date = date_value
            
        # Vérifier si la date est valide (pas NaT)
        if pd.isna(parsed_date):
            return default
            
        return parsed_date.strftime(date_format)
    except (ValueError, TypeError, AttributeError):
        return default


class PDF(FPDF):
    """Classe PDF personnalisée pour la génération de rapports de contrat"""
    
    def __init__(self, client, contrat, df_contrat_selected):
        super().__init__()
        self.client = client
        self.contrat = contrat
        self.df_contrat = df_contrat_selected
        
        # Gérer le cas où df_contrat_selected pourrait être vide ou manquer de colonnes
        if not self.df_contrat.empty:
            self.enveloppe = self.df_contrat['Enveloppe'].iloc[0] if 'Enveloppe' in self.df_contrat.columns else "N/A"
            self.partenaire = self.df_contrat['Partenaire'].iloc[0] if 'Partenaire' in self.df_contrat.columns else "N/A"
            self.valorisation = self.df_contrat['Valorisation'].iloc[0] if 'Valorisation' in self.df_contrat.columns else 0.0
            
            # Utiliser la fonction sécurisée pour formater les dates
            date_val_raw = self.df_contrat['Date de valorisation'].iloc[0] if 'Date de valorisation' in self.df_contrat.columns else None
            self.date_valorisation_report = safe_date_format(date_val_raw, '%d/%m/%Y', "N/A")
            
            date_ouv_raw = self.df_contrat['Ouverture'].iloc[0] if 'Ouverture' in self.df_contrat.columns else None
            self.date_ouverture = safe_date_format(date_ouv_raw, '%d/%m/%Y', "N/A")
        else:
            self.enveloppe = "N/A"
            self.partenaire = "N/A"
            self.valorisation = 0.0
            self.date_valorisation_report = "N/A"
            self.date_ouverture = "N/A"
        
        # Configuration des polices
        self._setup_fonts()

    def _setup_fonts(self):
        """Configuration des polices personnalisées"""
        try:
            # Enregistrer explicitement les styles de police pour la famille "Calibri"
            # uni=True est recommandé pour le support Unicode avec les polices TTF.
            self.add_font(family="Calibri", style="", fname="Calibri.ttf", uni=True)
            self.add_font(family="Calibri", style="B", fname="Calibri Bold.ttf", uni=True)
            self.add_font(family="Calibri", style="I", fname="Calibri Italic.ttf", uni=True) 
            self.font_family = "Calibri"
        except RuntimeError as e:
            # Fallback to helvetica if Calibri is not found
            self.font_family = "helvetica"
            print(f"Attention: Police Calibri non trouvée ou erreur de chargement ({e}). Utilisation de Helvetica.")

    def header(self):
        """En-tête personnalisé du rapport"""
        current_font_family = self.font_family if hasattr(self, 'font_family') else "helvetica"
        self.set_font(current_font_family, "B", 12)
        self.cell(0, 8, f"Rapport de Contrat : {self.client}", ln=True, align="L")
        self.set_font(current_font_family, "", 10)
        self.cell(0, 6, f"Contrat {self.enveloppe} - {self.partenaire} - N° {self.contrat} (Ouvert le {self.date_ouverture})", ln=True, align="L")
        self.cell(0, 6, f"Date de valorisation du rapport : {self.date_valorisation_report}", ln=True, align="L")
        self.ln(5) # Espace après l'en-tête

    def footer(self):
        """Pied de page personnalisé"""
        current_font_family = self.font_family if hasattr(self, 'font_family') else "helvetica"
        self.set_y(-15)
        self.set_font(current_font_family, "I", 8)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    def get_montant_versements_nets(self):
        """Récupère le montant total des versements nets"""
        if not self.df_contrat.empty and 'Montant total des versements nets' in self.df_contrat.columns:
            return self.df_contrat['Montant total des versements nets'].iloc[0]
        return 0.0


def calculate_kpis(pdf, df_contrat_sel, kpi_overrides=None):
    """Calcule les KPIs du contrat (TRA, performances, etc.)"""
    if kpi_overrides:
        return {
            'tra_str': kpi_overrides.get('tra_str', 'N/A'),
            'montant_versements_bruts_str': kpi_overrides.get('montant_versements_bruts_str', 'N/A'),
            'montant_versements_nets_kpi_str': kpi_overrides.get('montant_versements_nets_kpi_str', 'N/A'),
            'var_vs_brut_pct_str': kpi_overrides.get('var_vs_brut_pct_str', 'N/A'),
            'var_vs_net_pct_str': kpi_overrides.get('var_vs_net_pct_str', 'N/A'),
            'source_versements_label': kpi_overrides.get('source_versements_label', 'CSV contrats'),
            'frais_entree_str': kpi_overrides.get('frais_entree_str', 'N/A'),
            'taux_frais_str': kpi_overrides.get('taux_frais_str', 'N/A'),
            'tri_net_str': kpi_overrides.get('tri_net_str', 'N/A'),
            'tri_brut_str': kpi_overrides.get('tri_brut_str', 'N/A'),
        }

    # Calcul du TRA (approximation simple)
    tra_str = "N/A"
    if pdf.date_ouverture != "N/A" and pdf.date_valorisation_report != "N/A" and pdf.valorisation > 0:
        date_ouverture_dt = pd.to_datetime(pdf.date_ouverture, dayfirst=True, errors='coerce')
        date_valorisation_dt = pd.to_datetime(pdf.date_valorisation_report, dayfirst=True, errors='coerce')
        
        if pd.notna(date_ouverture_dt) and pd.notna(date_valorisation_dt):
            years = (date_valorisation_dt - date_ouverture_dt).days / 365.25
            if years > 0:
                montant_versements_nets_initial = pdf.get_montant_versements_nets()
                if montant_versements_nets_initial > 0:
                    tra = ((pdf.valorisation / montant_versements_nets_initial) ** (1 / years) - 1) * 100
                    tra_str = f"{tra:.2f}%".replace(".", ",")
                else:
                    tra_str = "N/A (V.N. nuls)"
            else:
                tra_str = "N/A (Durée <0)"
        else:
            tra_str = "N/A (Date invalide)"

    # Calcul des autres KPIs
    montant_versements_bruts = 0.0
    montant_versements_nets_kpi = 0.0

    if not df_contrat_sel.empty:
        if 'Montant total des versements bruts' in df_contrat_sel.columns:
            montant_versements_bruts = df_contrat_sel['Montant total des versements bruts'].iloc[0]
        if 'Montant total des versements nets' in df_contrat_sel.columns:
            montant_versements_nets_kpi = df_contrat_sel['Montant total des versements nets'].iloc[0]

    var_vs_brut_pct_str = "N/A"
    if montant_versements_bruts != 0:
        var_vs_brut_pct = ((pdf.valorisation - montant_versements_bruts) / montant_versements_bruts) * 100
        var_vs_brut_pct_str = f"{var_vs_brut_pct:.2f}%".replace(".", ",")

    var_vs_net_pct_str = "N/A"
    if montant_versements_nets_kpi != 0:
        var_vs_net_pct = ((pdf.valorisation - montant_versements_nets_kpi) / montant_versements_nets_kpi) * 100
        var_vs_net_pct_str = f"{var_vs_net_pct:.2f}%".replace(".", ",")

    montant_versements_bruts_str = f"{montant_versements_bruts:,.0f} €".replace(",", " ")
    montant_versements_nets_kpi_str = f"{montant_versements_nets_kpi:,.0f} €".replace(",", " ")

    return {
        'tra_str': tra_str,
        'montant_versements_bruts_str': montant_versements_bruts_str,
        'montant_versements_nets_kpi_str': montant_versements_nets_kpi_str,
        'var_vs_brut_pct_str': var_vs_brut_pct_str,
        'var_vs_net_pct_str': var_vs_net_pct_str,
        'source_versements_label': 'CSV contrats',
        'frais_entree_str': 'N/A',
        'taux_frais_str': 'N/A',
        'tri_net_str': 'N/A',
        'tri_brut_str': 'N/A',
    }


def add_kpis_section(pdf, kpis):
    """Ajoute la section des KPIs au rapport PDF"""
    current_font_family = pdf.font_family
    kpi_font_size = 10
    w_label_versement = 45 
    w_valeur_versement = 40 
    w_label_performance = 55

    # Ligne pour les KPIs Bruts
    pdf.set_font(current_font_family, "B", kpi_font_size)
    pdf.cell(w_label_versement, 6, "Versements Bruts :", border=0, ln=0)
    pdf.set_font(current_font_family, "", kpi_font_size)
    pdf.cell(w_valeur_versement, 6, kpis['montant_versements_bruts_str'], border=0, ln=0, align="R")
    pdf.set_font(current_font_family, "B", kpi_font_size)
    pdf.cell(w_label_performance, 6, " | Perf. / VB (%) :", border=0, ln=0, align="L")
    pdf.set_font(current_font_family, "", kpi_font_size)
    pdf.cell(0, 6, kpis['var_vs_brut_pct_str'], border=0, ln=True, align="R")
    
    # Ligne pour les KPIs Nets
    pdf.set_font(current_font_family, "B", kpi_font_size)
    pdf.cell(w_label_versement, 6, "Versements Nets :", border=0, ln=0)
    pdf.set_font(current_font_family, "", kpi_font_size)
    pdf.cell(w_valeur_versement, 6, kpis['montant_versements_nets_kpi_str'], border=0, ln=0, align="R")
    pdf.set_font(current_font_family, "B", kpi_font_size)
    pdf.cell(w_label_performance, 6, " | Perf. / VN (%) :", border=0, ln=0, align="L")
    pdf.set_font(current_font_family, "", kpi_font_size)
    pdf.cell(0, 6, kpis['var_vs_net_pct_str'], border=0, ln=True, align="R")

    # Affichage du TRA
    pdf.set_font(current_font_family, "B", kpi_font_size)
    pdf.cell(w_label_versement, 6, "TRA (estimé) :", border=0, ln=0)
    pdf.set_font(current_font_family, "", kpi_font_size)
    pdf.cell(0, 6, kpis['tra_str'], border=0, ln=True, align="R")

    pdf.set_font(current_font_family, "", 8)
    pdf.cell(0, 5, f"Source des versements : {kpis['source_versements_label']}", border=0, ln=True)

    pdf.set_font(current_font_family, "B", kpi_font_size)
    pdf.cell(w_label_versement, 6, "Frais d'entrée :", border=0, ln=0)
    pdf.set_font(current_font_family, "", kpi_font_size)
    pdf.cell(w_valeur_versement, 6, kpis['frais_entree_str'], border=0, ln=0, align="R")
    pdf.set_font(current_font_family, "B", kpi_font_size)
    pdf.cell(w_label_performance, 6, " | Taux frais :", border=0, ln=0, align="L")
    pdf.set_font(current_font_family, "", kpi_font_size)
    pdf.cell(0, 6, kpis['taux_frais_str'], border=0, ln=True, align="R")

    pdf.set_font(current_font_family, "B", kpi_font_size)
    pdf.cell(w_label_versement, 6, "TRI net :", border=0, ln=0)
    pdf.set_font(current_font_family, "", kpi_font_size)
    pdf.cell(w_valeur_versement, 6, kpis['tri_net_str'], border=0, ln=0, align="R")
    pdf.set_font(current_font_family, "B", kpi_font_size)
    pdf.cell(w_label_performance, 6, " | TRI brut :", border=0, ln=0, align="L")
    pdf.set_font(current_font_family, "", kpi_font_size)
    pdf.cell(0, 6, kpis['tri_brut_str'], border=0, ln=True, align="R")
    
    pdf.ln(5)


def add_section_title(pdf, title_text):
    """Ajoute un titre de section formaté"""
    pdf.set_font(pdf.font_family, "B", 12)
    pdf.set_fill_color(220, 220, 220)  # Gris clair pour le fond du titre
    pdf.cell(0, 8, title_text, ln=True, fill=True, align="L", border=0)
    pdf.ln(4)


def add_pie_charts_section(pdf, image_data_fig_typologie, image_data_fig_type_support):
    """Ajoute la section des graphiques en secteurs"""
    add_section_title(pdf, "Répartition de l'Allocation")
    pie_chart_y_start = pdf.get_y()
    pie_img_width = pdf.epw / 2 - 10  # Largeur pour chaque graphique en secteurs

    if image_data_fig_typologie:
        pdf.image(image_data_fig_typologie, x=10, y=pie_chart_y_start, w=pie_img_width, keep_aspect_ratio=True)
    
    if image_data_fig_type_support:
        pdf.image(image_data_fig_type_support, x=10 + pie_img_width + 5, y=pie_chart_y_start, w=pie_img_width, keep_aspect_ratio=True)
    
    # Estimer la hauteur des graphiques pour passer à la ligne correctement
    estimated_pie_height = pie_img_width * 0.75  # Supposons un ratio d'aspect typique
    pdf.set_y(pie_chart_y_start + estimated_pie_height + 5)
    pdf.ln(5)


def add_allocation_table(pdf, df_alloc_client_data):
    """Ajoute le tableau détaillé de l'allocation"""
    add_section_title(pdf, "Détail de l'Allocation")
    
    df_allocation_report = df_alloc_client_data[[
        'Support',
        'Type',
        'Encours en €',
        '+/- value (en €)',
        '+/- value (en %))']].sort_values(by='Encours en €', ascending=False).copy()

    # Formatage des colonnes numériques
    for col_name in ['Encours en €', '+/- value (en €)']:
        if col_name in df_allocation_report.columns:
            df_allocation_report[col_name] = pd.to_numeric(df_allocation_report[col_name], errors='coerce').fillna(0)
            df_allocation_report[col_name] = df_allocation_report[col_name].apply(lambda x: f"{x:,.0f}".replace(",", " "))
    
    if '+/- value (en %))' in df_allocation_report.columns:
        df_allocation_report['+/- value (en %))'] = pd.to_numeric(df_allocation_report['+/- value (en %))'], errors='coerce').fillna(0)
        df_allocation_report['+/- value (en %))'] = df_allocation_report['+/- value (en %))'].apply(lambda x: f"{x:.2f}%".replace(".", ","))
    
    df_allocation_report = df_allocation_report.astype(str)

    COLUMNS = [list(df_allocation_report)]
    ROWS = df_allocation_report.values.tolist()
    DATA = COLUMNS + ROWS

    pdf.set_font(pdf.font_family, "", 8)
    headings_style = FontFace(emphasis="BOLD", color=(255,255,255), fill_color=(80,80,80))
    
    table_width = pdf.epw - 15
    col_widths_ratio = (0.35, 0.25, 0.15, 0.15, 0.10)

    with pdf.table(
        borders_layout="HORIZONTAL_LINES",
        headings_style=headings_style,
        line_height=pdf.font_size * 1.8,
        text_align=("LEFT", "LEFT", "RIGHT", "RIGHT", "RIGHT"),
        width=table_width,
        col_widths=tuple(w * table_width for w in col_widths_ratio)
    ) as table:
        for data_row in DATA:
            row = table.row()
            for datum in data_row:
                row.cell(datum)


def convert_figure_to_image(fig, img_scale=1.5):
    """Convertit une figure Plotly en bytes d'image PNG"""
    return fig.to_image(format="png", engine="kaleido", scale=img_scale) if fig else None


def generate_rapport_pdf(client_name, contrat_num, df_contrat_sel,
                         fig_typologie_plot, fig_supports_plot,
                         fig_waterfall_contract_plot, fig_waterfall_allocation_plot,
                         fig_distribution_SRI_plot, fig_SRI_contrat_plot,
                         fig_evol_plot, df_alloc_client_data,
                         fig_tri_plot=None, kpi_overrides=None):
    """
    Génère un rapport PDF complet pour un contrat donné
    
    Args:
        client_name: Nom du client
        contrat_num: Numéro du contrat
        df_contrat_sel: DataFrame avec les données du contrat sélectionné
        fig_*_plot: Figures Plotly pour les différents graphiques
        df_alloc_client_data: DataFrame avec les données d'allocation du client
        
    Returns:
        bytes: Données PDF en format bytes
    """
    img_scale = 1.5  # Échelle cohérente pour une meilleure qualité

    # Conversion des figures en images
    image_data_fig_typologie = convert_figure_to_image(fig_typologie_plot, img_scale)
    image_data_fig_type_support = convert_figure_to_image(fig_supports_plot, img_scale)
    image_data_fig_waterfall_contract = convert_figure_to_image(fig_waterfall_contract_plot, img_scale)
    image_data_fig_waterfall_allocation = convert_figure_to_image(fig_waterfall_allocation_plot, img_scale)
    image_data_fig_distribution_SRI = convert_figure_to_image(fig_distribution_SRI_plot, img_scale)
    image_data_fig_SRI_contrat = convert_figure_to_image(fig_SRI_contrat_plot, img_scale)
    image_data_fig_evol = convert_figure_to_image(fig_evol_plot, img_scale)
    image_data_fig_tri = convert_figure_to_image(fig_tri_plot, img_scale)

    # Création du PDF
    pdf = PDF(client=client_name, contrat=contrat_num, df_contrat_selected=df_contrat_sel)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # --- Page 1: Valorisation, Répartition Allocation, Détail Allocation ---
    pdf.set_font(pdf.font_family, "B", 13)
    pdf.cell(60, 8, "Valorisation Actuelle :", border=0, ln=0)
    pdf.set_font(pdf.font_family, "", 13)
    valorisation_text = f"{pdf.valorisation:,.0f} €".replace(",", " ")
    pdf.cell(0, 8, valorisation_text, border=0, ln=True)

    # Calcul et affichage des KPIs
    kpis = calculate_kpis(pdf, df_contrat_sel, kpi_overrides=kpi_overrides)
    add_kpis_section(pdf, kpis)

    # Graphiques en secteurs
    add_pie_charts_section(pdf, image_data_fig_typologie, image_data_fig_type_support)

    # Tableau détaillé de l'allocation
    add_allocation_table(pdf, df_alloc_client_data)

    # --- Page 2: Analyse de Performance du Contrat ---
    pdf.add_page()
    add_section_title(pdf, "Analyse de Performance du Contrat")
    img_center_x = pdf.w / 2 - (pdf.epw * 0.8) / 2  # Pour centrer les images
    
    if image_data_fig_waterfall_contract:
        pdf.image(image_data_fig_waterfall_contract, x=img_center_x, w=pdf.epw * 0.8, keep_aspect_ratio=True)
        pdf.ln(5)
    if image_data_fig_waterfall_allocation:
        pdf.image(image_data_fig_waterfall_allocation, x=img_center_x, w=pdf.epw * 0.8, keep_aspect_ratio=True)
        pdf.ln(5)

    # --- Page 3: Évolution de la Valorisation (si disponible) ---
    if image_data_fig_evol:
        pdf.add_page()
        add_section_title(pdf, "Évolution de la Valorisation du Contrat")
        pdf.image(image_data_fig_evol, x=pdf.w / 2 - (pdf.epw * 0.9) / 2, w=pdf.epw * 0.9, keep_aspect_ratio=True)
        pdf.ln(5)

    if image_data_fig_tri:
        pdf.add_page()
        add_section_title(pdf, "Évolution du TRI du Contrat")
        pdf.image(image_data_fig_tri, x=pdf.w / 2 - (pdf.epw * 0.9) / 2, w=pdf.epw * 0.9, keep_aspect_ratio=True)
        pdf.ln(5)

    # --- Page 4: Analyse du Risque (SRI) ---
    pdf.add_page()
    add_section_title(pdf, "Analyse du Risque (SRI)")
    
    if image_data_fig_distribution_SRI:
        pdf.image(image_data_fig_distribution_SRI, x=img_center_x, w=pdf.epw * 0.8, keep_aspect_ratio=True)
        pdf.ln(5)
    if image_data_fig_SRI_contrat:
        pdf.image(image_data_fig_SRI_contrat, x=pdf.w / 2 - (pdf.epw * 0.4) / 2, w=pdf.epw * 0.4, keep_aspect_ratio=True)
        pdf.ln(5)

    # Génération du PDF final
    pdf_data = pdf.output(dest='S')
    if isinstance(pdf_data, bytearray):
        return bytes(pdf_data)
    return pdf_data


def generate_exposition_filters_pdf(contrats_resume: pd.DataFrame,
                                    fonds_selectionnes: list,
                                    df_allocations: pd.DataFrame) -> bytes:
    """
    Génère un PDF tabulaire listant les résultats des filtres d'exposition.

        Colonnes :
            - Nom
            - Prénom
            - Type du contrat (utilise la colonne 'Prestation')
            - Fonds du filtre (une ligne par fond dans la cellule)
            - Encours des fonds sélectionnés
            - % du contrat représenté par ces fonds

    Args:
        contrats_resume: DataFrame agrégé avec au moins les colonnes
            ['Numéro contrat', 'Nom', 'Prénom', 'Prestation'].
        fonds_selectionnes: Liste des fonds sélectionnés par l'utilisateur.
        df_allocations: DataFrame des allocations contenant au moins
            ['Numéro contrat', 'Support'].

    Returns:
        bytes: Le contenu du PDF.
    """
    # Création simple d'un PDF
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Titre
    pdf.set_font("helvetica", "B", 14)
    pdf.cell(0, 9, "Export Exposition - Résultats des filtres", ln=True)
    pdf.set_font("helvetica", "", 10)
    if fonds_selectionnes:
        filtre_txt = ", ".join(fonds_selectionnes)
        pdf.multi_cell(0, 6, f"Fonds filtrés : {filtre_txt}")
    pdf.ln(3)

    # Préparer les données du tableau
    columns = [
        "Nom",
        "Prénom",
        "Type du contrat",
        "Fonds du filtre",
        "Encours fonds sélectionnés",
        "% du contrat",
        "",
        ""
    ]

    # Calcul des fonds par contrat (limités aux fonds sélectionnés)
    def fonds_du_contrat(contrat_num: str) -> str:
        df_fonds = df_allocations[(df_allocations['Numéro contrat'] == contrat_num) &
                                  (df_allocations['Support'].isin(fonds_selectionnes))]
        fonds_list = df_fonds['Support'].dropna().astype(str).tolist()
        # Une ligne par fond dans la cellule
        return "\n".join(sorted(fonds_list)) if fonds_list else ""

    def encours_fonds_selectionnes(contrat_num: str) -> float:
        df_fonds = df_allocations[(df_allocations['Numéro contrat'] == contrat_num) &
                                  (df_allocations['Support'].isin(fonds_selectionnes))]
        if 'Encours en €' in df_fonds.columns:
            return float(pd.to_numeric(df_fonds['Encours en €'], errors='coerce').fillna(0).sum())
        return 0.0

    # Construction des lignes
    rows = []
    required_cols = {'Numéro contrat', 'Nom', 'Prénom', 'Prestation', 'Encours en €'}
    if not set(required_cols).issubset(set(contrats_resume.columns)):
        # Si les colonnes ne sont pas toutes présentes, renvoyer un PDF minimal avec message
        pdf.set_text_color(200, 0, 0)
        pdf.multi_cell(0, 6, "Colonnes manquantes pour générer l'export. Veuillez vérifier les données.")
        pdf_data = pdf.output(dest='S')
        return bytes(pdf_data) if isinstance(pdf_data, bytearray) else pdf_data

    rows_data = []
    for _, row in contrats_resume.iterrows():
        nom = str(row.get('Nom', ''))
        prenom = str(row.get('Prénom', ''))
        type_contrat = str(row.get('Prestation', ''))
        contrat_num = row.get('Numéro contrat')
        fonds_cell = fonds_du_contrat(contrat_num)
        encours_sel = encours_fonds_selectionnes(contrat_num)
        encours_total_contrat = float(row.get('Encours en €', 0) or 0)
        pct = (encours_sel / encours_total_contrat * 100.0) if encours_total_contrat > 0 else 0.0
        rows_data.append({
            'Nom': nom,
            'Prénom': prenom,
            'Type du contrat': type_contrat,
            'Fonds du filtre': fonds_cell,
            'Encours': encours_sel,
            'Pct': pct
        })

    # Trier par % du contrat décroissant
    rows_data.sort(key=lambda r: r['Pct'], reverse=True)

    # Formater les lignes pour affichage
    rows = []
    for r in rows_data:
        encours_str = f"{r['Encours']:,.0f}".replace(',', ' ')
        pct_str = f"{r['Pct']:.1f}%".replace('.', ',')
        rows.append([
            r['Nom'], r['Prénom'], r['Type du contrat'], r['Fonds du filtre'], encours_str, pct_str, "", ""
        ])

    # Styles d'entêtes
    try:
        from fpdf.fonts import FontFace as _FontFace
        headings_style = _FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=(80, 80, 80))
    except Exception:
        headings_style = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=(80, 80, 80))

    # Paramètres de tableau
    table_width = pdf.epw
    # Ratios de colonnes (ajuster pour laisser de l'espace au champ multi-lignes)
    # Ajustement des largeurs pour intégrer 2 colonnes vides (OUI/NON)
    # Total = 1.00
    col_widths_ratio = (0.14, 0.14, 0.12, 0.28, 0.12, 0.08, 0.06, 0.06)

    # Construire le tableau
    pdf.set_font("helvetica", "", 9)
    with pdf.table(
        borders_layout="ALL",
        headings_style=headings_style,
        line_height=pdf.font_size * 1.9,
        text_align=("LEFT", "LEFT", "LEFT", "LEFT", "RIGHT", "RIGHT", "CENTER", "CENTER"),
        width=table_width,
        col_widths=tuple(w * table_width for w in col_widths_ratio)
    ) as table:
        # Ligne d'entête
        header_row = table.row()
        for col in columns:
            header_row.cell(col)

        # Lignes de données
        for data_row in rows:
            row_obj = table.row()
            for datum in data_row:
                # Le moteur de table de fpdf2 supporte MultiCell et les \n
                row_obj.cell(str(datum))

    # Sortie
    pdf_data = pdf.output(dest='S')
    if isinstance(pdf_data, bytearray):
        return bytes(pdf_data)
    return pdf_data