import base64
import csv
import hashlib
import html as html_lib
import json
import re
import secrets
import shutil
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from cryptography.fernet import InvalidToken

from config import (
    BASE_EXPORTS_PATH,
    REAL_DATA_ALLOCATIONS_PATH,
    REAL_DATA_CONTRATS_PATH,
    REAL_DATA_FONDS_PATH,
)
from gemini_secret import GEMINI_SECRET_DIR, ensure_secret_dir, get_fernet
from pdf_tri_analysis import DEFAULT_PDF_DIR

PROXEEMA_VAULT_PATH = GEMINI_SECRET_DIR / "proxeema_credentials.enc"
SURAVENIR_VAULT_PATH = GEMINI_SECRET_DIR / "suravenir_credentials.enc"

CAS_AUTHORIZE_URL = "https://reseau.prodemial.fr/cas/oauth2.0/authorize"
CAS_CLIENT_ID = "AVHk0axUd7.prod.box"
PROXEEMA_REDIRECT_URI = "https://proxeema.finzzle-groupe.com/contrats-stellium"
GRAPHQL_URL = "https://business-gateway-api.finzzle-groupe.com/graphql"

ORIADYS_BASE_URL = "https://oriadys.suravenir.fr"
ORIADYS_CLIENTS_CONTRATS_URL = f"{ORIADYS_BASE_URL}/clients-contrats"
ORIADYS_GROUP_CONTRATS_URL = f"{ORIADYS_BASE_URL}/group/partenaire/clients-contrats"

QUANTALYS_BASE_URL = "https://optimiz-portfolio.quantalys.com"
QUANTALYS_STELLIUM_URL = f"{QUANTALYS_BASE_URL}/Stellium"
DEFAULT_TOP10_CSV_FILENAME = "Export_Top_10_test.csv"

MUTATION_EXPORT_CONTRATS = """
mutation GenerateContratsAgregationExport($filter: ContratConsultantFilterInput!) {
  generateContratsAgregationExport(filter: $filter) {
    fileName
    sasUrl
  }
}
"""

MUTATION_EXPORT_SUPPORTS = """
mutation GenerateSupportsAgregationExport($filter: SupportConsultantFilterInput!) {
  generateSupportsAgregationExport(filter: $filter) {
    fileName
    sasUrl
  }
}
"""

QUERY_CONTRATS_CONSULTANT_SURAVENIR = """
query contratsConsultantListe($filter: ContratConsultantFilterInput!, $take: Int, $skip: Int) {
  contratsConsultant(filter: $filter, take: $take, skip: $skip) {
    totalCount
    items {
      idContrat
      numeroContrat
      valorisation
      dateValorisation
      produit {
        designation
        enveloppe {
          libelle
        }
        partenaire {
          libelleLong
        }
      }
      contratsInvestisseurs {
        codeInvestisseur
        idPersonnePartenaire
        investisseur {
          nom
          prenom
        }
      }
    }
  }
}
"""

QUERY_CONTRATS_INVESTISSEUR = """
query contratsInvestisseurs($codeInvestisseur: String!) {
  contratsInvestisseur(codeInvestisseur: $codeInvestisseur) {
    idContrat
    idPersonnePartenaire
  }
}
"""


def load_proxeema_credentials() -> dict:
    if not PROXEEMA_VAULT_PATH.exists():
        return {"username": "", "password": ""}
    try:
        token = PROXEEMA_VAULT_PATH.read_bytes()
        data = json.loads(get_fernet().decrypt(token).decode("utf-8"))
        return {
            "username": str(data.get("username", "")).strip(),
            "password": str(data.get("password", "")),
        }
    except (OSError, InvalidToken, ValueError, json.JSONDecodeError):
        return {"username": "", "password": ""}


def save_proxeema_credentials(username: str, password: str):
    username = (username or "").strip()
    password = password or ""
    if not username or not password:
        raise ValueError("Veuillez renseigner l'identifiant et le mot de passe.")
    ensure_secret_dir()
    payload = json.dumps({"username": username, "password": password}).encode("utf-8")
    token = get_fernet().encrypt(payload)
    PROXEEMA_VAULT_PATH.write_bytes(token)
    try:
        PROXEEMA_VAULT_PATH.chmod(0o600)
    except OSError:
        pass


def delete_proxeema_credentials():
    if PROXEEMA_VAULT_PATH.exists():
        PROXEEMA_VAULT_PATH.unlink()


def proxeema_credentials_exist() -> bool:
    return PROXEEMA_VAULT_PATH.exists()


def load_suravenir_credentials() -> dict:
    if not SURAVENIR_VAULT_PATH.exists():
        return {"username": "", "password": ""}
    try:
        token = SURAVENIR_VAULT_PATH.read_bytes()
        data = json.loads(get_fernet().decrypt(token).decode("utf-8"))
        return {
            "username": str(data.get("username", "")).strip(),
            "password": str(data.get("password", "")),
        }
    except (OSError, InvalidToken, ValueError, json.JSONDecodeError):
        return {"username": "", "password": ""}


def save_suravenir_credentials(username: str, password: str):
    username = (username or "").strip()
    password = password or ""
    if not username or not password:
        raise ValueError("Veuillez renseigner l'identifiant et le mot de passe Suravenir.")
    ensure_secret_dir()
    payload = json.dumps({"username": username, "password": password}).encode("utf-8")
    token = get_fernet().encrypt(payload)
    SURAVENIR_VAULT_PATH.write_bytes(token)
    try:
        SURAVENIR_VAULT_PATH.chmod(0o600)
    except OSError:
        pass


def delete_suravenir_credentials():
    if SURAVENIR_VAULT_PATH.exists():
        SURAVENIR_VAULT_PATH.unlink()


def suravenir_credentials_exist() -> bool:
    return SURAVENIR_VAULT_PATH.exists()


def _extract_access_token_from_url(url: str) -> str | None:
    if not url:
        return None
    match = re.search(r"[#?&]access_token=([^&#\s]+)", url)
    if match:
        return match.group(1)
    parsed = urlparse(url)
    for part in (parsed.fragment, parsed.query):
        qs = parse_qs(part)
        if "access_token" in qs and qs["access_token"]:
            return qs["access_token"][0]
    return None


def authenticate_proxeema(username: str, password: str, timeout: int = 25) -> str:
    """
    Authentifie l'utilisateur sur le serveur CAS Prodemial / Finzzle et retourne le Bearer access_token OAuth2.
    """
    username = (username or "").strip()
    password = password or ""
    if not username or not password:
        raise ValueError("Identifiant et mot de passe requis.")

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        }
    )

    auth_params = {
        "response_type": "token",
        "client_id": CAS_CLIENT_ID,
        "redirect_uri": PROXEEMA_REDIRECT_URI,
    }
    resp = session.get(CAS_AUTHORIZE_URL, params=auth_params, allow_redirects=True, timeout=timeout)
    resp.raise_for_status()

    # Si déjà authentifié et redirigé avec un token
    token = _extract_access_token_from_url(resp.url)
    if token:
        return token

    html = resp.text
    exec_match = re.search(r'<input[^>]*name=["\']execution["\'][^>]*value=["\']([^"\']+)["\']', html)
    if not exec_match:
        exec_match = re.search(r'value=["\']([^"\']+)["\'][^>]*name=["\']execution["\']', html)
    if not exec_match:
        raise RuntimeError("Impossible de récupérer le jeton d'exécution sur la page de connexion CAS.")

    execution_token = exec_match.group(1)

    action_match = re.search(r'<form[^>]*id=["\']fm1["\'][^>]*action=["\']([^"\']+)["\']', html)
    post_url = urljoin(resp.url, action_match.group(1)) if action_match else resp.url

    form_data = {
        "username": username,
        "password": password,
        "execution": execution_token,
        "_eventId": "submit",
        "geolocation": "",
    }

    current_resp = session.post(post_url, data=form_data, allow_redirects=False, timeout=timeout)

    # Suivre manuellement la chaîne de redirections CAS -> OAuth2 -> Proxeema#access_token=...
    for _ in range(12):
        location = current_resp.headers.get("Location")
        if not location:
            break
        token = _extract_access_token_from_url(location)
        if token:
            return token
        next_url = urljoin(current_resp.url, location)
        token = _extract_access_token_from_url(next_url)
        if token:
            return token
        current_resp = session.get(next_url, allow_redirects=False, timeout=timeout)

    token = _extract_access_token_from_url(current_resp.url)
    if token:
        return token

    # Vérifier si la page contient un message d'erreur CAS
    body = current_resp.text or ""
    if "Invalid credentials" in body or "identifiants" in body.lower() or 'id="fm1"' in body:
        raise ValueError("Identifiant ou mot de passe incorrect (ou validation supplémentaire requise sur le portail).")

    raise RuntimeError(
        f"Authentification incomplète (statut HTTP {current_resp.status_code}). "
        "Aucun access_token n'a été retourné par le serveur CAS."
    )


def _call_export_mutation(access_token: str, query: str, variables: dict, timeout: int = 60) -> tuple[str, str]:
    headers = {
        "Authorization": f"Bearer {access_token.strip()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://proxeema.finzzle-groupe.com",
        "Referer": "https://proxeema.finzzle-groupe.com/contrats-stellium",
    }
    resp = requests.post(
        GRAPHQL_URL,
        json={"query": query, "variables": variables},
        headers=headers,
        timeout=timeout,
    )
    if resp.status_code == 401:
        raise PermissionError("Jeton d'accès expiré ou non autorisé (HTTP 401).")
    resp.raise_for_status()
    payload = resp.json()

    if payload.get("errors"):
        err_msg = "; ".join(str(e.get("message", e)) for e in payload["errors"])
        raise RuntimeError(f"Erreur GraphQL Proxeema : {err_msg}")

    data = payload.get("data") or {}
    export_obj = (
        data.get("generateContratsAgregationExport")
        or data.get("generateSupportsAgregationExport")
        or {}
    )
    sas_url = export_obj.get("sasUrl")
    file_name = export_obj.get("fileName")
    if not sas_url:
        raise RuntimeError("L'API Proxeema n'a pas retourné d'URL de téléchargement (sasUrl vide).")
    return sas_url, file_name or ""


def _archive_existing_csvs(target_dir: Path, old_dir: Path, keep_filename: str):
    old_dir.mkdir(parents=True, exist_ok=True)
    for csv_path in target_dir.glob("*.csv"):
        if csv_path.name == keep_filename:
            continue
        dest = old_dir / csv_path.name
        shutil.move(str(csv_path), str(dest))


def fetch_and_save_proxeema_exports(access_token: str, archive_previous: bool = True) -> dict:
    """
    Génère et télécharge les 2 exports CSV Proxeema :
    1) Contrats -> 00_Exports/1_Selection_Actifs/Export_Contrats_YYYY_MM_DD.csv
    2) Supports (Situations détaillées) -> 00_Exports/2_Situations_Detaillées/Export_Supports_YYYY_MM_DD.csv
    """
    date_suffix = datetime.now().strftime("%Y_%m_%d")
    contrats_dir = Path(REAL_DATA_CONTRATS_PATH)
    supports_dir = Path(REAL_DATA_ALLOCATIONS_PATH)
    old_dir = Path(BASE_EXPORTS_PATH) / "old"

    contrats_dir.mkdir(parents=True, exist_ok=True)
    supports_dir.mkdir(parents=True, exist_ok=True)

    # 1. Export Contrats
    contrats_vars = {
        "filter": {
            "filter": "",
            "enveloppes": [],
            "partenaires": [],
            "vp": [],
            "supports": [],
        }
    }
    contrats_sas_url, contrats_remote_name = _call_export_mutation(
        access_token, MUTATION_EXPORT_CONTRATS, contrats_vars
    )
    contrats_resp = requests.get(contrats_sas_url, timeout=60)
    contrats_resp.raise_for_status()

    contrats_filename = f"Export_Contrats_{date_suffix}.csv"
    contrats_path = contrats_dir / contrats_filename
    if archive_previous:
        _archive_existing_csvs(contrats_dir, old_dir, keep_filename=contrats_filename)
    contrats_path.write_bytes(contrats_resp.content)

    # 2. Export Supports (Situations détaillées)
    supports_vars = {
        "filter": {
            "filter": "",
            "societesGestion": [],
            "classesActif": [],
        }
    }
    supports_sas_url, supports_remote_name = _call_export_mutation(
        access_token, MUTATION_EXPORT_SUPPORTS, supports_vars
    )
    supports_resp = requests.get(supports_sas_url, timeout=60)
    supports_resp.raise_for_status()

    supports_filename = f"Export_Supports_{date_suffix}.csv"
    supports_path = supports_dir / supports_filename
    if archive_previous:
        _archive_existing_csvs(supports_dir, old_dir, keep_filename=supports_filename)
    supports_path.write_bytes(supports_resp.content)

    return {
        "contrats_path": contrats_path,
        "contrats_remote_name": contrats_remote_name,
        "contrats_size": len(contrats_resp.content),
        "supports_path": supports_path,
        "supports_remote_name": supports_remote_name,
        "supports_size": len(supports_resp.content),
    }


def fetch_suravenir_contracts_from_proxeema(access_token: str, timeout: int = 30) -> list[dict]:
    """
    Récupère la liste de tous les contrats Suravenir depuis l'API GraphQL Proxeema,
    avec leur numéro de contrat (`numeroContrat`) et l'identifiant personne partenaire
    Suravenir (`idPersonnePartenaire` / `externalPersonId`).
    """
    headers = {
        "Authorization": f"Bearer {access_token.strip()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://proxeema.finzzle-groupe.com",
        "Referer": "https://proxeema.finzzle-groupe.com/contrats-stellium",
    }

    all_items: list[dict] = []
    skip = 0
    page_size = 100

    while True:
        variables = {
            "filter": {
                "filter": "",
                "enveloppes": [],
                "partenaires": [],
                "vp": [],
                "supports": [],
            },
            "take": page_size,
            "skip": skip,
        }
        resp = requests.post(
            GRAPHQL_URL,
            json={"query": QUERY_CONTRATS_CONSULTANT_SURAVENIR, "variables": variables},
            headers=headers,
            timeout=timeout,
        )
        if resp.status_code == 401:
            raise PermissionError("Jeton d'accès Proxeema expiré ou non autorisé (HTTP 401).")
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("errors"):
            err_msg = "; ".join(str(e.get("message", e)) for e in payload["errors"])
            raise RuntimeError(f"Erreur GraphQL Proxeema (liste contrats) : {err_msg}")

        container = (payload.get("data") or {}).get("contratsConsultant") or {}
        items = container.get("items") or []
        total_count = int(container.get("totalCount") or 0)
        all_items.extend(items)
        skip += len(items)
        if not items or skip >= total_count:
            break

    suravenir_items = [
        it
        for it in all_items
        if "SURAVENIR"
        in str(((it.get("produit") or {}).get("partenaire") or {}).get("libelleLong", "")).upper()
    ]

    # Si certains contrats n'ont pas idPersonnePartenaire directement renseigné, le récupérer via contratsInvestisseur
    missing_investor_codes = sorted(
        {
            inv.get("codeInvestisseur")
            for it in suravenir_items
            for inv in (it.get("contratsInvestisseurs") or [])
            if inv.get("codeInvestisseur") and not inv.get("idPersonnePartenaire")
        }
    )

    fallback_person_map: dict[tuple[str, str], str] = {}
    if missing_investor_codes:
        def _fetch_inv(code_inv: str):
            r_inv = requests.post(
                GRAPHQL_URL,
                json={"query": QUERY_CONTRATS_INVESTISSEUR, "variables": {"codeInvestisseur": code_inv}},
                headers=headers,
                timeout=timeout,
            )
            r_inv.raise_for_status()
            rows = ((r_inv.json().get("data") or {}).get("contratsInvestisseur")) or []
            return code_inv, rows

        with ThreadPoolExecutor(max_workers=6) as executor:
            for code_inv, rows in executor.map(_fetch_inv, missing_investor_codes):
                for row in rows:
                    if row.get("idContrat") and row.get("idPersonnePartenaire"):
                        fallback_person_map[(row["idContrat"], code_inv)] = str(row["idPersonnePartenaire"])

    contracts: list[dict] = []
    for it in suravenir_items:
        id_contrat = str(it.get("idContrat") or "").strip()
        numero_contrat = str(it.get("numeroContrat") or "").strip()
        if not numero_contrat:
            continue

        invs = it.get("contratsInvestisseurs") or []
        external_person_id = ""
        titulaire_parts: list[str] = []
        for inv in invs:
            code_inv = str(inv.get("codeInvestisseur") or "").strip()
            pers_id = str(inv.get("idPersonnePartenaire") or "").strip()
            if not pers_id and id_contrat and code_inv:
                pers_id = fallback_person_map.get((id_contrat, code_inv), "")
            if pers_id and not external_person_id:
                external_person_id = pers_id

            inv_info = inv.get("investisseur") or {}
            prenom = str(inv_info.get("prenom") or "").strip()
            nom = str(inv_info.get("nom") or "").strip()
            full_name = f"{prenom} {nom}".strip()
            if full_name:
                titulaire_parts.append(full_name)

        produit_obj = it.get("produit") or {}
        enveloppe_obj = produit_obj.get("enveloppe") or {}
        contracts.append(
            {
                "id_contrat": id_contrat,
                "numero_contrat": numero_contrat,
                "external_person_id": external_person_id,
                "titulaire": ", ".join(titulaire_parts),
                "produit": str(produit_obj.get("designation") or "").strip(),
                "enveloppe": str(enveloppe_obj.get("libelle") or "").strip(),
                "valorisation": it.get("valorisation"),
                "date_valorisation": it.get("dateValorisation"),
            }
        )

    return contracts


def _extract_xml_or_input_value(tag_name: str, text: str) -> str:
    m = re.search(rf"<{tag_name}>(.*?)</{tag_name}>", text, re.S)
    if m:
        return html_lib.unescape(m.group(1).strip())
    m2 = re.search(rf'name=["\']{tag_name}["\'][^>]*value=["\']([^"\']*)["\']', text)
    return html_lib.unescape(m2.group(1)) if m2 else ""


def authenticate_oriadys_suravenir(username: str, password: str, timeout: int = 30) -> dict:
    """
    Authentifie l'utilisateur sur le portail Oriadys Suravenir (Liferay + OAuth2 PKCE)
    et retourne le contexte contenant la session et le Bearer access_token pour l'API Arkea/Suravenir.
    """
    username = (username or "").strip()
    password = password or ""
    if not username or not password:
        raise ValueError("Identifiant et mot de passe Oriadys Suravenir requis.")

    sess = requests.Session()
    sess.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        }
    )

    r_get = sess.get(ORIADYS_CLIENTS_CONTRATS_URL, allow_redirects=True, timeout=timeout)
    r_get.raise_for_status()
    page_html = r_get.text

    form_match = re.search(
        r'<form[^>]*id=["\']_com_liferay_login_web_portlet_LoginPortlet_loginForm["\'][^>]*>(.*?)</form>',
        page_html,
        re.S,
    )
    if form_match:
        action_match = re.search(
            r'<form[^>]*action=["\']([^"\']+)["\'][^>]*id=["\']_com_liferay_login_web_portlet_LoginPortlet_loginForm["\']',
            page_html,
        ) or re.search(
            r'<form[^>]*id=["\']_com_liferay_login_web_portlet_LoginPortlet_loginForm["\'][^>]*action=["\']([^"\']+)["\']',
            page_html,
        )
        if not action_match:
            raise RuntimeError("Impossible de trouver l'URL d'action du formulaire de connexion Oriadys.")
        action_url = html_lib.unescape(action_match.group(1))

        form_data: dict[str, str] = {}
        for inp in re.findall(r'<input[^>]*type=["\']hidden["\'][^>]*>', form_match.group(1)):
            nm = re.search(r'name=["\']([^"\']+)["\']', inp)
            vl = re.search(r'value=["\']([^"\']*)["\']', inp)
            if nm:
                form_data[nm.group(1)] = html_lib.unescape(vl.group(1)) if vl else ""

        ns = "_com_liferay_login_web_portlet_LoginPortlet_"
        form_data[f"{ns}login"] = username
        form_data[f"{ns}password"] = password

        r_login = sess.post(action_url, data=form_data, allow_redirects=True, timeout=timeout)
        r_login.raise_for_status()

    r_cc = sess.get(ORIADYS_GROUP_CONTRATS_URL, allow_redirects=True, timeout=timeout)
    r_cc.raise_for_status()
    cc_html = r_cc.text

    if "_com_liferay_login_web_portlet_LoginPortlet_loginForm" in cc_html:
        raise ValueError("Identifiant ou mot de passe Oriadys Suravenir incorrect.")

    m_params = re.search(
        r'id="com_arkea_suravenir_portal_common_life_consultation_LifeConsultationPortlet"\s+data-liferay-params="([^"]+)"',
        cc_html,
    )
    if m_params:
        liferay_params = json.loads(urllib.parse.unquote(m_params.group(1)))
    else:
        liferay_params = {}

    client_id = liferay_params.get("clientId", "id-d0911cf6-926a-b386-9e52-995c71d5aa61")
    portal_url = liferay_params.get("portalUrl", ORIADYS_BASE_URL).rstrip("/")
    redirect_uri = portal_url
    partner_code = liferay_params.get("partnerCode", "00344")

    plid_m = re.search(r'getPlid:function\(\)\{return"(\d+)"\}', cc_html)
    group_m = re.search(r'getScopeGroupId:function\(\)\{return"(\d+)"\}', cc_html)
    plid = plid_m.group(1) if plid_m else "457"
    group_id = group_m.group(1) if group_m else "64198"

    # Échange OAuth2 PKCE pour obtenir le Bearer token de LifeConsultationPortlet
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~"
    code_verifier = "".join(secrets.choice(alphabet) for _ in range(43))
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    auth_url = (
        f"{portal_url}/o/oauth2/authorize/?client_id={client_id}"
        f"&response_type=code&code_challenge={code_challenge}"
        f"&code_challenge_method=S256&redirect_uri={redirect_uri}"
    )
    r_auth = sess.get(auth_url, headers={"Accept": "*/*"}, allow_redirects=True, timeout=timeout)
    r_auth.raise_for_status()

    code = None
    if "?code=" in r_auth.url or "&code=" in r_auth.url:
        code = parse_qs(urlparse(r_auth.url).query).get("code", [None])[0]
    else:
        decision_data = {
            "scope": _extract_xml_or_input_value("proposedScope", r_auth.text),
            "response_type": _extract_xml_or_input_value("responseType", r_auth.text) or "code",
            "session_authenticity_token": _extract_xml_or_input_value("authenticityToken", r_auth.text),
            "redirect_uri": _extract_xml_or_input_value("redirectUri", r_auth.text) or redirect_uri,
            "code_challenge": _extract_xml_or_input_value("clientCodeChallenge", r_auth.text) or code_challenge,
            "client_id": _extract_xml_or_input_value("clientId", r_auth.text) or client_id,
            "oauthDecision": "allow",
        }
        r_dec = sess.post(
            f"{portal_url}/o/oauth2/authorize/decision",
            data=decision_data,
            headers={"Accept": "*/*", "Content-Type": "application/x-www-form-urlencoded"},
            allow_redirects=False,
            timeout=timeout,
        )
        loc = r_dec.headers.get("Location", "")
        if "code=" in loc:
            code = parse_qs(urlparse(loc).query).get("code", [None])[0]

    if not code:
        raise RuntimeError("Impossible d'obtenir le code d'autorisation OAuth2 sur Oriadys Suravenir.")

    r_tok = sess.post(
        f"{portal_url}/o/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=timeout,
    )
    r_tok.raise_for_status()
    tok_json = r_tok.json()
    access_token = tok_json.get("access_token")
    if not access_token:
        raise RuntimeError("Le serveur OAuth2 Oriadys n'a pas retourné d'access_token.")

    return {
        "session": sess,
        "access_token": access_token,
        "portal_url": portal_url,
        "partner_code": partner_code,
        "group_id": group_id,
        "plid": plid,
        "username": username,
        "password": password,
    }


def download_suravenir_contract_pdf(
    oriadys_ctx: dict,
    contract_reference: str,
    external_person_id: str,
    complete_situation: bool = True,
    timeout: int = 60,
) -> bytes:
    """
    Télécharge l'édition de situation PDF d'un contrat Suravenir depuis l'API REST Oriadys.
    """
    portal_url = oriadys_ctx["portal_url"]
    pdf_url = f"{portal_url}/o/arkea-rest-endpoint-contract-life/v1.0/contract-situation"
    headers = {
        "Authorization": f"Bearer {oriadys_ctx['access_token']}",
        "Accept": "application/octet-stream",
        "Content-Type": "application/json",
        "GROUP_ID": str(oriadys_ctx["group_id"]),
        "PAGE_LAYOUT_ID": str(oriadys_ctx["plid"]),
    }
    params = {
        "contractReference": contract_reference.strip(),
        "externalPersonId": external_person_id.strip(),
        "completeSituation": "true" if complete_situation else "false",
        "partnerCode": str(oriadys_ctx["partner_code"]),
    }
    sess: requests.Session = oriadys_ctx["session"]
    resp = sess.get(pdf_url, headers=headers, params=params, timeout=timeout)

    # Si le token OAuth2 (durée 600s) a expiré en cours de lot, on se ré-authentifie une fois
    if resp.status_code == 401 and oriadys_ctx.get("username") and oriadys_ctx.get("password"):
        refreshed = authenticate_oriadys_suravenir(
            oriadys_ctx["username"], oriadys_ctx["password"], timeout=timeout
        )
        oriadys_ctx.update(refreshed)
        headers["Authorization"] = f"Bearer {oriadys_ctx['access_token']}"
        resp = oriadys_ctx["session"].get(pdf_url, headers=headers, params=params, timeout=timeout)

    resp.raise_for_status()
    content = resp.content
    if not content.startswith(b"%PDF"):
        raise RuntimeError(
            f"La réponse pour le contrat {contract_reference} n'est pas un fichier PDF valide "
            f"({len(content)} octets reçus)."
        )
    return content


def _archive_contract_existing_pdfs(pdf_dir: Path, old_pdf_dir: Path, file_stem: str):
    """
    Déplace vers 00_Exports/old/04_Opérations/ tout ancien PDF correspondant au même contrat
    (ex: `9E_269197960.pdf`, `9E_269197960 (1).pdf`, `9E_269197960 (2).pdf`).
    """
    old_pdf_dir.mkdir(parents=True, exist_ok=True)
    pattern = re.compile(rf"^{re.escape(file_stem)}(\s+\(\d+\))?\.pdf$", re.IGNORECASE)
    for existing in pdf_dir.glob("*.pdf"):
        if pattern.match(existing.name):
            dest = old_pdf_dir / existing.name
            shutil.move(str(existing), str(dest))


def fetch_and_save_suravenir_pdfs(
    proxeema_token: str,
    suravenir_username: str,
    suravenir_password: str,
    complete_situation: bool = True,
    archive_previous: bool = True,
    selected_contract_numbers: list[str] | None = None,
    progress_callback=None,
) -> dict:
    """
    Récupère la liste des contrats Suravenir via Proxeema, s'authentifie sur Oriadys Suravenir,
    et télécharge l'édition de situation PDF de chaque contrat dans `00_Exports/04_Opérations/`.
    """
    contracts = fetch_suravenir_contracts_from_proxeema(proxeema_token)
    if selected_contract_numbers is not None:
        selected_set = {c.strip() for c in selected_contract_numbers}
        contracts = [c for c in contracts if c["numero_contrat"] in selected_set]

    if not contracts:
        return {
            "total": 0,
            "downloaded": [],
            "errors": [],
            "pdf_dir": Path(DEFAULT_PDF_DIR),
        }

    oriadys_ctx = authenticate_oriadys_suravenir(suravenir_username, suravenir_password)

    pdf_dir = Path(DEFAULT_PDF_DIR)
    old_pdf_dir = Path(BASE_EXPORTS_PATH) / "old" / "04_Opérations"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    downloaded: list[dict] = []
    errors: list[dict] = []
    total = len(contracts)

    for idx, contract in enumerate(contracts, start=1):
        num = contract["numero_contrat"]
        ext_id = contract["external_person_id"]
        titulaire = contract.get("titulaire") or ""
        if progress_callback:
            progress_callback(idx, total, num, titulaire)

        if not ext_id:
            errors.append(
                {
                    "numero_contrat": num,
                    "titulaire": titulaire,
                    "error": "Identifiant personne partenaire (idPersonnePartenaire) introuvable sur Proxeema.",
                }
            )
            continue

        try:
            pdf_bytes = download_suravenir_contract_pdf(
                oriadys_ctx,
                contract_reference=num,
                external_person_id=ext_id,
                complete_situation=complete_situation,
            )
            file_stem = re.sub(r"\s+", "_", num.strip())
            file_name = f"{file_stem}.pdf"
            file_path = pdf_dir / file_name

            if archive_previous:
                _archive_contract_existing_pdfs(pdf_dir, old_pdf_dir, file_stem)

            file_path.write_bytes(pdf_bytes)
            downloaded.append(
                {
                    "numero_contrat": num,
                    "titulaire": titulaire,
                    "produit": contract.get("produit", ""),
                    "file_name": file_name,
                    "file_path": file_path,
                    "size_bytes": len(pdf_bytes),
                }
            )
        except Exception as exc:
            errors.append(
                {
                    "numero_contrat": num,
                    "titulaire": titulaire,
                    "error": str(exc),
                }
            )

    return {
        "total": total,
        "downloaded": downloaded,
        "errors": errors,
        "pdf_dir": pdf_dir,
    }


def authenticate_quantalys(username: str, password: str, timeout: int = 30) -> requests.Session:
    """
    Authentifie l'utilisateur sur Quantalys Optimiz-Portfolio (https://optimiz-portfolio.quantalys.com/Stellium)
    via le portail CAS Prodemial / Finzzle Groupe (mêmes identifiants que Proxeema)
    et retourne une session `requests.Session` authentifiée.
    """
    username = (username or "").strip()
    password = password or ""
    if not username or not password:
        raise ValueError("Identifiant et mot de passe Proxeema / Quantalys requis.")

    sess = requests.Session()
    sess.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        }
    )

    resp = sess.get(QUANTALYS_STELLIUM_URL, allow_redirects=True, timeout=timeout)
    resp.raise_for_status()

    # Suivre les éventuelles redirections JavaScript anti-bot (window.location.href)
    for _ in range(5):
        m_js = re.search(r"window\.location\.href\s*=\s*['\"]([^'\"]+)['\"]", resp.text)
        if not m_js:
            break
        next_url = urljoin(resp.url, html_lib.unescape(m_js.group(1)))
        resp = sess.get(next_url, allow_redirects=True, timeout=timeout)
        resp.raise_for_status()

    if "reseau.prodemial.fr/cas/login" in resp.url or 'name="execution"' in resp.text:
        exec_match = re.search(r'name="execution"\s+value="([^"]+)"', resp.text)
        if not exec_match:
            raise RuntimeError("Impossible d'extraire le jeton d'exécution CAS pour Quantalys Optimiz-Portfolio.")
        execution_token = exec_match.group(1)

        action_match = re.search(r'<form[^>]*id="fm1"[^>]*action="([^"]+)"', resp.text) or re.search(
            r'<form[^>]*action="([^"]+)"[^>]*id="fm1"', resp.text
        )
        post_url = urljoin(resp.url, html_lib.unescape(action_match.group(1))) if action_match else resp.url

        resp = sess.post(
            post_url,
            data={
                "username": username,
                "password": password,
                "execution": execution_token,
                "_eventId": "submit",
                "geolocation": "",
            },
            allow_redirects=True,
            timeout=timeout,
        )
        resp.raise_for_status()

        for _ in range(5):
            m_js = re.search(r"window\.location\.href\s*=\s*['\"]([^'\"]+)['\"]", resp.text)
            if not m_js:
                break
            next_url = urljoin(resp.url, html_lib.unescape(m_js.group(1)))
            resp = sess.get(next_url, allow_redirects=True, timeout=timeout)
            resp.raise_for_status()

    if "reseau.prodemial.fr/cas/login" in resp.url or 'id="fm1"' in resp.text:
        raise ValueError("Identifiant ou mot de passe Proxeema / Quantalys incorrect.")

    return sess


def extract_portfolio_funds_from_exports(include_structured: bool = False) -> dict:
    """
    Extrait la liste unique des supports (Code ISIN, Support, Type) présents dans le dernier
    export `00_Exports/2_Situations_Detaillées/*.csv`.
    Par défaut, exclut les supports en euros (`Support en euro`) ainsi que les produits structurés
    (`Produits Structurés`, sauf si `include_structured=True`).
    """
    alloc_dir = Path(REAL_DATA_ALLOCATIONS_PATH)
    csv_files = sorted(alloc_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not csv_files:
        raise FileNotFoundError(
            f"Aucun fichier CSV de situations détaillées trouvé dans {alloc_dir}. "
            "Veuillez d'abord importer les supports depuis Proxeema."
        )

    latest_csv = csv_files[0]
    raw_bytes = latest_csv.read_bytes()
    text_content = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text_content = raw_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text_content is None:
        text_content = raw_bytes.decode("latin-1", errors="replace")

    reader = csv.DictReader(text_content.splitlines(), delimiter=";")
    unique_by_isin: dict[str, dict] = {}
    for row in reader:
        isin = (row.get("Code ISIN") or "").strip()
        support = (row.get("Support") or "").strip()
        support_type = (row.get("Type") or "").strip()
        if not isin:
            continue
        if isin not in unique_by_isin:
            unique_by_isin[isin] = {
                "code_isin": isin,
                "support": support,
                "type": support_type,
            }

    target_funds: list[dict] = []
    excluded_supports: list[dict] = []

    for isin, info in unique_by_isin.items():
        stype = info["type"]
        if stype.lower() == "support en euro":
            excluded_supports.append({**info, "raison": "Fonds en euros (non coté dans Quantalys)"})
        elif not include_structured and "structur" in stype.lower():
            excluded_supports.append({**info, "raison": "Produit structuré exclu par défaut"})
        else:
            target_funds.append(info)

    return {
        "source_file": latest_csv,
        "all_unique_count": len(unique_by_isin),
        "target_funds": target_funds,
        "excluded_supports": excluded_supports,
    }


def _query_quantalys_recherche_data(
    sess: requests.Session,
    search_text: str,
    timeout: int = 45,
) -> list[dict]:
    """
    Interroge l'endpoint DataTables `POST /Recherche/Data` de Quantalys Optimiz-Portfolio
    pour résoudre un lot de codes ISIN (séparés par retour à la ligne) ou un nom de support.
    """
    cols = [
        "ID_Produit",
        "cTypeFinancialItem",
        "cClasseFinancialItem",
        "sTypeFinancialObject",
        "checkbox",
        "sNom",
        "sCodeISIN",
    ]
    payload: dict[str, str] = {
        "draw": "1",
        "start": "0",
        "length": "500",
        "order[0][column]": "5",
        "order[0][dir]": "asc",
        "Values.isTypeProduitV2": "true",
        "Values.bOuvertAchat": "true",
        "Values.sNomOrISIN": search_text,
        "sNomOrISIN": search_text,
        "Values.isForProposition": "false",
    }
    for idx, col in enumerate(cols):
        payload[f"columns[{idx}][name]"] = col

    resp = sess.post(
        f"{QUANTALYS_BASE_URL}/Recherche/Data",
        data=payload,
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": QUANTALYS_STELLIUM_URL,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return (resp.json() or {}).get("data") or []


def _resolve_quantalys_products(
    sess: requests.Session,
    target_funds: list[dict],
    timeout: int = 45,
) -> dict:
    """
    Résout chaque support du portefeuille en produit Quantalys (`ID_Produit`, `cTypeFinancialItem`,
    `cClasseFinancialItem`, `sCodeISIN`, `sNom`).
    Si un code assureur spécifique (ex: `IGP11000043C` ou `QS0002005277` pour `SCI Capimmo`)
    n'est pas reconnu par son code ISIN, tente une résolution par le nom exact du support.
    """
    if not target_funds:
        return {
            "unique_products": [],
            "resolved_funds": [],
            "alias_mappings": [],
            "unresolved_funds": [],
        }

    isin_list = [f["code_isin"] for f in target_funds]
    batch_rows = _query_quantalys_recherche_data(sess, "\n".join(isin_list), timeout=timeout)
    by_isin: dict[str, dict] = {}
    for row in batch_rows:
        code = str(row.get("sCodeISIN") or "").strip().upper()
        if code and code not in by_isin:
            by_isin[code] = row

    unique_products_by_id: dict[int, dict] = {}
    resolved_funds: list[dict] = []
    alias_mappings: list[dict] = []
    unresolved_funds: list[dict] = []

    for fund in target_funds:
        code_upper = fund["code_isin"].strip().upper()
        q_row = by_isin.get(code_upper)
        matched_by = "ISIN"

        if not q_row and fund.get("support"):
            support_name = fund["support"].strip()
            name_rows = _query_quantalys_recherche_data(sess, support_name, timeout=timeout)
            norm_target = re.sub(r"\s+", " ", support_name).lower()
            for cand in name_rows:
                cand_name = re.sub(r"\s+", " ", str(cand.get("sNom") or "").strip()).lower()
                if cand_name == norm_target or cand_name.startswith(norm_target):
                    q_row = cand
                    matched_by = f"Nom ({cand.get('sCodeISIN')})"
                    break

        if not q_row:
            unresolved_funds.append(
                {
                    **fund,
                    "raison": "Introuvable dans la base Quantalys Optimiz-Portfolio",
                }
            )
            continue

        id_produit = int(q_row["ID_Produit"])
        c_type = int(q_row.get("cTypeFinancialItem") or 1)
        c_classe = int(q_row.get("cClasseFinancialItem") or 0)
        q_isin = str(q_row.get("sCodeISIN") or "").strip()
        q_nom = str(q_row.get("sNom") or "").strip()

        if id_produit not in unique_products_by_id:
            unique_products_by_id[id_produit] = {
                "ID_Produit": id_produit,
                "cTypeFinancialItem": c_type,
                "cClasseFinancialItem": c_classe,
                "sCodeISIN": q_isin,
                "sNom": q_nom,
            }

        resolved_funds.append(
            {
                "code_isin_portefeuille": fund["code_isin"],
                "support_portefeuille": fund["support"],
                "type_portefeuille": fund["type"],
                "code_isin_quantalys": q_isin,
                "nom_quantalys": q_nom,
                "id_produit": id_produit,
                "mode_resolution": matched_by,
            }
        )

        if q_isin.upper() != code_upper:
            alias_mappings.append(
                {
                    "portfolio_isin": fund["code_isin"],
                    "portfolio_support": fund["support"],
                    "quantalys_isin": q_isin,
                    "quantalys_nom": q_nom,
                }
            )

    return {
        "unique_products": list(unique_products_by_id.values()),
        "resolved_funds": resolved_funds,
        "alias_mappings": alias_mappings,
        "unresolved_funds": unresolved_funds,
    }


def _append_alias_isin_rows_to_csv(csv_text: str, alias_mappings: list[dict]) -> tuple[str, int]:
    """
    Duplique les lignes d'historique des fonds résolus par nom sous leur code ISIN assureur
    (ex: `IGP11000043C` et `QS0002005277` à partir de `FR0014004GX5` pour `SCI Capimmo`),
    afin que les vues qui joignent par `Code ISIN` trouvent directement l'historique.
    """
    if not alias_mappings:
        return csv_text, 0

    lines = csv_text.splitlines()
    if not lines:
        return csv_text, 0

    by_quantalys_isin: dict[str, list[dict]] = {}
    for mapping in alias_mappings:
        q_isin = mapping["quantalys_isin"].strip().upper()
        by_quantalys_isin.setdefault(q_isin, []).append(mapping)

    extra_lines: list[str] = []
    for line in lines[1:]:
        parts = line.split(";")
        if len(parts) < 5:
            continue
        row_isin = parts[0].strip().upper()
        if row_isin in by_quantalys_isin:
            for mapping in by_quantalys_isin[row_isin]:
                alias_isin = mapping["portfolio_isin"]
                base_nom = parts[2].strip()
                alias_nom = f"{base_nom} ({alias_isin})"
                new_parts = [alias_isin, parts[1], alias_nom, parts[3], parts[4]]
                extra_lines.append(";".join(new_parts))

    if not extra_lines:
        return csv_text, 0

    sep = "\r\n" if "\r\n" in csv_text else "\n"
    base_clean = csv_text.rstrip("\r\n")
    return base_clean + sep + sep.join(extra_lines) + sep, len(extra_lines)


def fetch_and_save_quantalys_top10_csv(
    username: str,
    password: str,
    allocation_name: str = "Top 10 test",
    include_structured: bool = False,
    archive_previous: bool = True,
    output_filename: str = DEFAULT_TOP10_CSV_FILENAME,
    progress_callback=None,
) -> dict:
    """
    Automatise la mise à jour complète du fichier d'historique des fonds (`Export_Top_10_test.csv`) :
    1. Récupère tous les fonds utilisés dans le dernier export des supports du portefeuille.
    2. S'authentifie sur Quantalys Optimiz-Portfolio (`https://optimiz-portfolio.quantalys.com/Stellium`).
    3. Résout les supports dans le référentiel Quantalys.
    4. Crée ou met à jour l'allocation iso-weight (`allocation_name`) sur Optimiz-Portfolio.
    5. Télécharge l'historique quotidien des performances en CSV et l'enregistre dans `00_Exports/3_Fonds/`.
    """
    def _notify(step: int, total_steps: int, message: str):
        if progress_callback:
            progress_callback(step, total_steps, message)

    total_steps = 6
    _notify(1, total_steps, "Extraction des supports utilisés dans le portefeuille...")
    extracted = extract_portfolio_funds_from_exports(include_structured=include_structured)
    target_funds = extracted["target_funds"]
    if not target_funds:
        raise RuntimeError("Aucun fonds éligible n'a été trouvé dans l'export des situations détaillées.")

    _notify(2, total_steps, "Authentification CAS sur Quantalys Optimiz-Portfolio...")
    sess = authenticate_quantalys(username, password)

    _notify(
        3,
        total_steps,
        f"Résolution de {len(target_funds)} supports dans le référentiel Quantalys...",
    )
    resolution = _resolve_quantalys_products(sess, target_funds)
    unique_products = resolution["unique_products"]
    if not unique_products:
        raise RuntimeError("Aucun des supports du portefeuille n'a pu être résolu dans Quantalys.")

    _notify(
        4,
        total_steps,
        f"Mise à jour de l'allocation iso-weight « {allocation_name} » ({len(unique_products)} fonds)...",
    )
    ajax_headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": QUANTALYS_STELLIUM_URL,
    }

    # Rechercher si l'allocation existe déjà parmi les allocations personnelles de l'utilisateur
    r_list = sess.post(
        f"{QUANTALYS_BASE_URL}/Stellium/Allocation/List",
        data={"draw": 1, "start": 0, "length": 100, "Nom": ""},
        headers=ajax_headers,
        timeout=30,
    )
    r_list.raise_for_status()
    alloc_items = (r_list.json() or {}).get("data") or []
    target_name_norm = allocation_name.strip().lower()
    existing_alloc = next(
        (
            a
            for a in alloc_items
            if a.get("isMine") and str(a.get("sNom") or "").strip().lower() == target_name_norm
        ),
        None,
    )

    if existing_alloc:
        id_port = int(existing_alloc["ID_Port"])
        # S'assurer que le contrat est positionné sur -1 ("Aucun contrat spécifié") pour accepter tous les fonds
        sess.post(
            f"{QUANTALYS_BASE_URL}/Stellium/Allocation/UpdateAllocationNameAndContrat",
            json={"ID_Port": id_port, "sNom": allocation_name.strip(), "ID_Bassin": "-1"},
            headers={**ajax_headers, "Content-Type": "application/json; charset=UTF-8"},
            timeout=30,
        )
        # Récupérer les lignes actuelles de l'allocation pour les remplacer proprement
        r_compo = sess.get(
            f"{QUANTALYS_BASE_URL}/Portefeuille/ReloadTableauComposition",
            params={"id": id_port},
            headers={"X-Requested-With": "XMLHttpRequest", "Referer": QUANTALYS_STELLIUM_URL},
            timeout=30,
        )
        r_compo.raise_for_status()
        old_rows = re.findall(
            r'class="text-vertical-middle js-ventilation-item"\s+data-produit-id="(\d+)"\s+'
            r'data-produit-type="([^"]+)"\s+data-produit-classe="([^"]+)"[^>]*?'
            r'data-produit-poche="(\d+)"',
            r_compo.text,
            re.S,
        )
        if old_rows:
            lst_to_delete = [
                {
                    "ID_Produit": int(pid),
                    "cTypeFinancialItem": ptype,
                    "cClasseFinancialItem": pcls,
                }
                for pid, ptype, pcls, _ in old_rows
            ]
            lst_poches = [int(poche) for _, _, _, poche in old_rows]
            r_del = sess.post(
                f"{QUANTALYS_BASE_URL}/Portefeuille/DeleteProduits",
                json={
                    "id": id_port,
                    "lstProduitsToDelete": lst_to_delete,
                    "lstIdsPoche": lst_poches,
                },
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Content-Type": "application/json; charset=UTF-8",
                    "Referer": QUANTALYS_STELLIUM_URL,
                },
                timeout=60,
            )
            r_del.raise_for_status()
    else:
        create_payload = {
            "sNom": allocation_name.strip(),
            "sTypePtf": "model",
            "sIdEnveloppe": "-1",
            "sCurrency": "EUR",
            "sTypeCreation": "poids",
            "sEnveloppe": "",
            "bFraisRecurrent": "",
            "sFreqPrelevement": "",
            "dtOuverture": None,
            "sNumero": "",
            "nFrais": None,
            "sCptCible": [],
            "SRRI": "",
            "sNomCptTitre": "",
            "nFraisEntree": None,
            "nFraisArbitrage": None,
        }
        r_create = sess.post(
            f"{QUANTALYS_BASE_URL}/Portefeuille/CreationManuelle",
            json=create_payload,
            headers={**ajax_headers, "Content-Type": "application/json; charset=UTF-8"},
            timeout=30,
        )
        r_create.raise_for_status()
        create_data = r_create.json() or {}
        if not create_data.get("ID_Port"):
            raise RuntimeError(f"Échec de la création de l'allocation Quantalys : {r_create.text[:300]}")
        id_port = int(create_data["ID_Port"])

    # Ajouter tous les fonds résolus dans l'allocation
    lst_produits_add = [
        {
            "ID_Produit": p["ID_Produit"],
            "cTypeFinancialItem": p["cTypeFinancialItem"],
            "cClasseFinancialItem": p["cClasseFinancialItem"],
            "nModeCalcul": 0,
        }
        for p in unique_products
    ]
    r_add = sess.post(
        f"{QUANTALYS_BASE_URL}/Portefeuille/AddProduits",
        json={"id": id_port, "lstProduits": lst_produits_add},
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/json; charset=UTF-8",
            "Referer": QUANTALYS_STELLIUM_URL,
        },
        timeout=90,
    )
    r_add.raise_for_status()

    added_rows = re.findall(
        r'class="text-vertical-middle js-ventilation-item"\s+data-produit-id="(\d+)"\s+'
        r'data-produit-type="([^"]+)"\s+data-produit-classe="([^"]+)"',
        r_add.text,
        re.S,
    )
    if not added_rows:
        r_compo2 = sess.get(
            f"{QUANTALYS_BASE_URL}/Portefeuille/ReloadTableauComposition",
            params={"id": id_port},
            headers={"X-Requested-With": "XMLHttpRequest", "Referer": QUANTALYS_STELLIUM_URL},
            timeout=30,
        )
        r_compo2.raise_for_status()
        added_rows = re.findall(
            r'class="text-vertical-middle js-ventilation-item"\s+data-produit-id="(\d+)"\s+'
            r'data-produit-type="([^"]+)"\s+data-produit-classe="([^"]+)"',
            r_compo2.text,
            re.S,
        )

    if not added_rows:
        raise RuntimeError("Aucun produit n'a pu être ajouté dans l'allocation Quantalys Optimiz-Portfolio.")

    _notify(
        5,
        total_steps,
        f"Application de la pondération iso-weight ({100.0 / len(added_rows):.2f} % par fonds)...",
    )
    n_added = len(added_rows)
    base_bp = 10000 // n_added
    rem_bp = 10000 - (base_bp * n_added)
    list_produits_weights = []
    for idx, (pid, ptype, pcls) in enumerate(added_rows):
        bp = base_bp + (1 if idx < rem_bp else 0)
        list_produits_weights.append(
            {
                "cProduit": {
                    "cProduitIdentifier": {
                        "ID_Produit": int(pid),
                        "cTypeFinancialItem": ptype,
                        "cClasseFinancialItem": pcls,
                    },
                    "sNom": "",
                    "sCodeISIN": "",
                    "sCurrency": "",
                    "nNbEtoile": 0,
                    "nSRRI": 0,
                    "cGroupeCat": 0,
                },
                "nPoids": round(bp / 10000.0, 6),
                "nMontant": 0,
            }
        )

    r_upd = sess.post(
        f"{QUANTALYS_BASE_URL}/Portefeuille/UpdateProduitMontantAndPoids",
        json={"idPort": id_port, "listProduits": list_produits_weights},
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/json; charset=UTF-8",
            "Referer": QUANTALYS_STELLIUM_URL,
        },
        timeout=60,
    )
    r_upd.raise_for_status()

    sess.get(
        f"{QUANTALYS_BASE_URL}/Stellium/Allocation/RemoveFromCache",
        params={"portfolioId": id_port},
        headers=ajax_headers,
        timeout=30,
    )

    _notify(6, total_steps, "Téléchargement de l'historique des performances (CSV)...")
    # Charger la synthèse pour initialiser le calcul du portefeuille côté serveur
    sess.get(
        f"{QUANTALYS_BASE_URL}/Portefeuille/Synthese/{id_port}",
        headers={"Referer": QUANTALYS_STELLIUM_URL},
        timeout=60,
    )
    dt_visu = datetime.now().strftime("%m/%d/%Y 00:00:00")
    r_exp = sess.get(
        f"{QUANTALYS_BASE_URL}/Portefeuille/ExportPerfs",
        params={
            "Areas": "Portefeuille",
            "ID_Port": id_port,
            "cTypeFinancialItem": "PORTEFEUILLE",
            "dtVisualisation": dt_visu,
            "currency": "EUR",
        },
        headers={"Referer": f"{QUANTALYS_BASE_URL}/Portefeuille/Synthese/{id_port}"},
        timeout=90,
    )
    r_exp.raise_for_status()

    raw_csv_bytes = r_exp.content
    csv_text = raw_csv_bytes.decode("utf-8-sig", errors="replace")
    if not csv_text.startswith("Code ISIN;"):
        raise RuntimeError(
            f"Le contenu téléchargé depuis Quantalys n'est pas un export CSV valide : {csv_text[:200]}"
        )

    csv_text, alias_rows_added = _append_alias_isin_rows_to_csv(csv_text, resolution["alias_mappings"])

    fonds_dir = Path(REAL_DATA_FONDS_PATH)
    old_fonds_dir = Path(BASE_EXPORTS_PATH) / "old" / "3_Fonds"
    fonds_dir.mkdir(parents=True, exist_ok=True)
    target_path = fonds_dir / output_filename

    if archive_previous:
        old_fonds_dir.mkdir(parents=True, exist_ok=True)
        for existing_csv in fonds_dir.glob("*.csv"):
            timestamp_suffix = datetime.fromtimestamp(existing_csv.stat().st_mtime).strftime("%Y%m%d_%H%M%S")
            archived_name = f"{existing_csv.stem}_{timestamp_suffix}{existing_csv.suffix}"
            shutil.move(str(existing_csv), str(old_fonds_dir / archived_name))

    # Encoder en latin-1 (sans BOM) pour compatibilité directe avec pd.read_csv(..., encoding='latin-1')
    encoded_bytes = csv_text.encode("latin-1", errors="replace")
    target_path.write_bytes(encoded_bytes)

    lines = csv_text.splitlines()
    portfolio_dates: list[datetime] = []
    for line in lines[1:]:
        if line.startswith("Portefeuille;"):
            parts = line.split(";")
            if len(parts) >= 4:
                try:
                    portfolio_dates.append(datetime.strptime(parts[3].strip(), "%d/%m/%Y"))
                except ValueError:
                    pass

    min_date_str = min(portfolio_dates).strftime("%d/%m/%Y") if portfolio_dates else None
    max_date_str = max(portfolio_dates).strftime("%d/%m/%Y") if portfolio_dates else None

    return {
        "file_path": target_path,
        "size_bytes": len(encoded_bytes),
        "line_count": len(lines),
        "allocation_id": id_port,
        "allocation_name": allocation_name.strip(),
        "source_supports_file": extracted["source_file"],
        "unique_products_count": len(added_rows),
        "resolved_funds": resolution["resolved_funds"],
        "alias_mappings": resolution["alias_mappings"],
        "alias_rows_added": alias_rows_added,
        "excluded_supports": extracted["excluded_supports"],
        "unresolved_funds": resolution["unresolved_funds"],
        "min_portfolio_date": min_date_str,
        "max_portfolio_date": max_date_str,
    }



