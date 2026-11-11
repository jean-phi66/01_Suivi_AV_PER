"""
Chargement de l'historique des situations detaillees (allocations par support) a partir des exports CSV
archives dans 00_Exports/old/ et de l'export courant (00_Exports/2_Situations_Detaillées/).

Formats de nom de fichier pris en charge :
- Export_situations_detaillees_adv_XXXXXX_DD_MM_YYYY_HH_MM.csv (ancien format)
- Export_Supports_YYYY_MM_DD.csv (nouveau format Proxeema)
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from config import BASE_EXPORTS_PATH, REAL_DATA_ALLOCATIONS_PATH

HISTORY_DIRS = [Path(BASE_EXPORTS_PATH) / "old", Path(REAL_DATA_ALLOCATIONS_PATH)]
NUMERIC_COLS = ["+/- value (en €)", "Encours en €", "Nombre de parts", "Valeur unitaire en €"]
PCT_COL = "+/- value (en %))"


def _is_allocation_export(name: str) -> bool:
    lower = name.lower()
    return lower.endswith(".csv") and ("situations_detaillees" in lower or lower.startswith("export_supports"))


def _export_date_from_name(name: str) -> pd.Timestamp | None:
    m = re.search(r"(\d{4})_(\d{2})_(\d{2})", name)  # Export_Supports_YYYY_MM_DD
    if m and name.lower().startswith("export_supports"):
        y, mo, d = m.groups()
        return pd.Timestamp(f"{y}-{mo}-{d}")
    m = re.search(r"_(\d{2})_(\d{2})_(\d{4})", name)  # ..._DD_MM_YYYY_HH_MM
    if m:
        d, mo, y = m.groups()
        return pd.Timestamp(f"{y}-{mo}-{d}")
    return None


def list_allocation_exports() -> list[Path]:
    files: list[Path] = []
    for directory in HISTORY_DIRS:
        if directory.exists():
            files.extend(p for p in directory.iterdir() if p.is_file() and _is_allocation_export(p.name))
    return sorted(files)


def allocation_history_signature() -> tuple:
    """Cle de cache : (nom, mtime, taille) des exports d'allocations."""
    return tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in list_allocation_exports())


def normalize_contract_number(series: pd.Series) -> pd.Series:
    # Meme logique que views/data_ingestion.py ('9E 271718089' -> '271718089').
    s = series.astype(str).str.strip()
    return s.str.replace(r"^[A-Z0-9]{1,4}\s+(?=\d{6,}$)", "", regex=True)


def _read_one(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, header=0, sep=";", decimal=",", thousands=" ", dtype=str, encoding="utf-8-sig")
    needed = {"Numéro contrat", "Support", "Encours en €"}
    if not needed.issubset(df.columns):
        return pd.DataFrame()

    keep = [c for c in ["Numéro contrat", "Support", "Code ISIN", "Type", "Encours en €", "+/- value (en €)", PCT_COL, "Date valeur"] if c in df.columns]
    df = df[keep].copy()
    df["Numéro contrat"] = normalize_contract_number(df["Numéro contrat"])

    def _num(col):
        return pd.to_numeric(
            df[col].astype(str).str.replace("\xa0", "", regex=False).str.replace(" ", "", regex=False).str.replace(",", ".", regex=False),
            errors="coerce",
        )

    for col in ["Encours en €", "+/- value (en €)"]:
        df[col] = _num(col).fillna(0.0) if col in df.columns else 0.0

    # Si +/- value (en €) est absente, la recalculer depuis le % et l'encours (meme regle que l'ingestion courante).
    if PCT_COL in df.columns:
        pct = _num(PCT_COL) / 100.0
        mask = (df["+/- value (en €)"] == 0) & pct.notna()
        df.loc[mask, "+/- value (en €)"] = df.loc[mask, "Encours en €"] * pct[mask] / (1 + pct[mask]).replace(0, float("nan"))
        df["+/- value (en €)"] = df["+/- value (en €)"].fillna(0.0)

    df["Date export"] = _export_date_from_name(path.name)
    df["Fichier source"] = path.name
    return df


def load_allocation_history() -> pd.DataFrame:
    frames = []
    for path in list_allocation_exports():
        try:
            df = _read_one(path)
        except Exception:
            continue
        if not df.empty and df["Date export"].notna().any():
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    hist = pd.concat(frames, ignore_index=True)
    # Plusieurs fichiers le meme jour (ex: doublons '(1)') : garder le dernier fichier de la journee.
    last_file = hist.groupby("Date export")["Fichier source"].transform("max")
    hist = hist[hist["Fichier source"] == last_file].copy()
    return hist.sort_values("Date export").reset_index(drop=True)

