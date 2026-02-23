import json
import unicodedata
from pathlib import Path


SIMPLIFIED_CATEGORIES = [
    "Fonds euros",
    "Obligataire",
    "Actions",
    "Allocation flexible",
    "Immobilier",
    "Long-Short",
    "Private Equity",
    "Produit structuré",
]

DEFAULT_SUPPORT_RULES = [
    {"Mot-clé support": "exceltis", "Catégorie simplifiée": "Produit structuré"},
    {"Mot-clé support": "sci", "Catégorie simplifiée": "Immobilier"},
]


def normalize_text(value):
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return text


def suggest_simplified_category(quantalys_category):
    normalized = normalize_text(quantalys_category)

    if "capital risque" in normalized or "private equity" in normalized:
        return "Private Equity"
    if "opci" in normalized:
        return "Immobilier"
    if "tresorerie reguliere" in normalized:
        return "Fonds euros"
    if any(token in normalized for token in ["euro", "garanti"]):
        return "Fonds euros"
    if any(token in normalized for token in ["long short", "long/short", "market neutral", "absolute return"]):
        return "Long-Short"
    if any(token in normalized for token in ["structur", "autocall", "phoenix", "certificat"]):
        return "Produit structuré"
    if any(token in normalized for token in ["immo", "scpi", "sci", "real estate"]):
        return "Immobilier"
    if any(token in normalized for token in ["oblig", "bond", "fixed income", "moneta"]):
        return "Obligataire"
    if any(token in normalized for token in ["action", "equity", "stock"]):
        return "Actions"
    if any(token in normalized for token in ["alloc", "flex", "mixte", "diversif", "multi asset", "patrimoine"]):
        return "Allocation flexible"

    return "Allocation flexible"


def default_support_rules():
    return [dict(rule) for rule in DEFAULT_SUPPORT_RULES]


def _sanitize_support_rules(support_rules):
    if not isinstance(support_rules, list):
        return []

    sanitized = []
    for rule in support_rules:
        if not isinstance(rule, dict):
            continue
        keyword = str(rule.get("Mot-clé support", "")).strip()
        category = str(rule.get("Catégorie simplifiée", "")).strip()
        if not keyword:
            continue
        if category not in SIMPLIFIED_CATEGORIES:
            continue
        sanitized.append({
            "Mot-clé support": keyword,
            "Catégorie simplifiée": category,
        })
    return sanitized


def _sanitize_category_mapping(category_mapping):
    if not isinstance(category_mapping, dict):
        return {}

    mapping = {}
    for key, value in category_mapping.items():
        quantalys_category = str(key).strip()
        simplified_category = str(value).strip()
        if quantalys_category and simplified_category in SIMPLIFIED_CATEGORIES:
            mapping[quantalys_category] = simplified_category
    return mapping


def load_typage_config(mapping_path: Path):
    if not mapping_path.exists():
        return {}, default_support_rules()

    try:
        with mapping_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}, default_support_rules()

    if not isinstance(payload, dict):
        return {}, default_support_rules()

    if "category_mapping" in payload or "support_rules" in payload:
        category_mapping = _sanitize_category_mapping(payload.get("category_mapping", {}))
        support_rules = _sanitize_support_rules(payload.get("support_rules", []))
        if not support_rules:
            support_rules = default_support_rules()
        return category_mapping, support_rules

    category_mapping = _sanitize_category_mapping(payload)
    return category_mapping, default_support_rules()


def save_typage_config(mapping_path: Path, category_mapping, support_rules):
    sanitized_mapping = _sanitize_category_mapping(category_mapping)
    sanitized_rules = _sanitize_support_rules(support_rules)

    payload = {
        "category_mapping": sanitized_mapping,
        "support_rules": sanitized_rules,
    }

    with mapping_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    return sanitized_mapping, sanitized_rules


def map_simplified_type(type_value, support_value, category_mapping, support_rules):
    support_normalized = normalize_text(support_value)
    for rule in support_rules:
        keyword = normalize_text(rule.get("Mot-clé support", ""))
        if keyword and keyword in support_normalized:
            return rule.get("Catégorie simplifiée", "Allocation flexible")

    if type_value is None:
        return "Allocation flexible"

    type_text = str(type_value).strip()
    if not type_text:
        return "Allocation flexible"

    if type_text in category_mapping:
        return category_mapping[type_text]

    normalized_mapping = {normalize_text(key): value for key, value in category_mapping.items()}
    type_normalized = normalize_text(type_text)
    if type_normalized in normalized_mapping:
        return normalized_mapping[type_normalized]

    return suggest_simplified_category(type_text)
