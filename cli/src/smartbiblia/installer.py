"""
Téléchargement depuis le repo GitHub : catalogue et sous-dossiers.

Utilise l'API tarball de GitHub — ni git ni clone complet nécessaires. Le
tarball est mis en cache pour la durée du processus : installer trois skills
d'affilée ne déclenche qu'un seul téléchargement.
"""

from __future__ import annotations

import io
import os
import shutil
import tarfile
from pathlib import Path

import httpx

GITHUB_ORG = os.environ.get("SMARTBIBLIA_GITHUB_ORG", "smartbiblia-solutions")
GITHUB_REPO = os.environ.get("SMARTBIBLIA_GITHUB_REPO", "agentic-stack")
BRANCH = os.environ.get("SMARTBIBLIA_BRANCH", "main")

_TARBALL_URL = f"https://api.github.com/repos/{GITHUB_ORG}/{GITHUB_REPO}/tarball/{BRANCH}"
_CATALOG_URL = (
    f"https://raw.githubusercontent.com/{GITHUB_ORG}/{GITHUB_REPO}"
    f"/{BRANCH}/cli/src/smartbiblia/catalog.toml"
)

# Un seul client poolé pour le processus : httpx.get() reconstruirait un client
# — et refarait la poignée de main TLS — à chaque appel.
HTTP = httpx.Client(timeout=60, follow_redirects=True)

# Tarball mis en cache pour la durée du processus (voir _tarball_bytes).
_TARBALL_CACHE: bytes | None = None


def repo_url() -> str:
    """URL web du repo servant de source."""
    return f"https://github.com/{GITHUB_ORG}/{GITHUB_REPO}"


def raw_url(remote_path: str) -> str:
    """URL raw d'un chemin du repo, sur la branche courante."""
    return (
        f"https://raw.githubusercontent.com/{GITHUB_ORG}/{GITHUB_REPO}"
        f"/{BRANCH}/{remote_path.strip('/')}"
    )


def _auth_headers() -> dict[str, str]:
    """Jeton optionnel : sert uniquement à relever la limite de taux GitHub
    (60 requêtes/heure sans authentification) ou à lire un repo privé."""
    token = os.environ.get("SMARTBIBLIA_GITHUB_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def fetch_catalog_raw() -> str:
    """Retourne le contenu brut du catalog.toml.

    `SMARTBIBLIA_CATALOG` permet de pointer un fichier local : c'est le moyen
    de valider une entrée avant de la pousser, puisque le catalogue en ligne
    est en production dès qu'il est sur la branche.
    """
    local = os.environ.get("SMARTBIBLIA_CATALOG")
    if local:
        return Path(local).read_text(encoding="utf-8")

    resp = HTTP.get(_CATALOG_URL, headers=_auth_headers(), timeout=10)
    resp.raise_for_status()
    return resp.text


def _tarball_bytes() -> bytes:
    global _TARBALL_CACHE
    if _TARBALL_CACHE is None:
        resp = HTTP.get(_TARBALL_URL, headers=_auth_headers())
        resp.raise_for_status()
        _TARBALL_CACHE = resp.content
    return _TARBALL_CACHE


def fetch_path(remote_path: str, dest: Path, *, clean: bool = False) -> list[str]:
    """
    Extrait le sous-dossier `remote_path` du tarball vers `dest`.

    Le tarball GitHub préfixe tous les chemins par "<org>-<repo>-<sha>/" ; ce
    préfixe est retiré à l'extraction. Retourne les chemins relatifs écrits.

    Avec `clean=True`, `dest` est vidé au préalable : une réinstallation ne
    laisse pas traîner un fichier supprimé en amont (un vieux prompt, un
    schéma renommé) que l'agent lirait encore.
    """
    with tarfile.open(fileobj=io.BytesIO(_tarball_bytes()), mode="r:gz") as tar:
        root_prefix = tar.getnames()[0].split("/")[0] + "/"
        target_prefix = root_prefix + remote_path.strip("/") + "/"

        members = [m for m in tar.getmembers() if m.name.startswith(target_prefix)]
        if not members:
            raise FileNotFoundError(
                f"Chemin '{remote_path}' introuvable dans le tarball GitHub "
                f"(branche {BRANCH}). Le catalogue pointe peut-être sur un dossier renommé."
            )

        if clean and dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)

        written: list[str] = []
        for member in members:
            member.name = member.name[len(target_prefix):]
            if not member.name:
                continue
            tar.extract(member, path=dest, filter="data")
            if member.isfile():
                written.append(member.name)

    return written
