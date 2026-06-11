"""
Télécharge un sous-dossier du repo GitHub et l'installe localement.
Utilise l'API tarball de GitHub — pas besoin de git ni de clone complet.
"""

from __future__ import annotations

import io
import os
import tarfile
from pathlib import Path

import httpx

GITHUB_ORG = "smartbiblia-solutions"
GITHUB_REPO = "agentic-stack"   # à mettre à jour si le repo est renommé
BRANCH = "main"

_TARBALL_URL = (
    f"https://api.github.com/repos/{GITHUB_ORG}/{GITHUB_REPO}/tarball/{BRANCH}"
)
_CATALOG_URL = (
    f"https://raw.githubusercontent.com/{GITHUB_ORG}/{GITHUB_REPO}"
    f"/{BRANCH}/cli/src/smartbiblia/catalog.toml"
)


def _auth_headers() -> dict[str, str]:
    token = os.environ.get("SMARTBIBLIA_GITHUB_TOKEN")
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def fetch_catalog_raw() -> str:
    """Retourne le contenu brut du catalog.toml depuis GitHub."""
    resp = httpx.get(_CATALOG_URL, headers=_auth_headers(), timeout=10, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def fetch_path(remote_path: str, dest: Path) -> None:
    """
    Télécharge le tarball du repo et extrait uniquement le sous-dossier
    `remote_path` vers `dest`.

    Le tarball GitHub préfixe tous les chemins par "<org>-<repo>-<sha>/",
    ce préfixe est retiré à l'extraction.
    """
    resp = httpx.get(
        _TARBALL_URL,
        headers=_auth_headers(),
        timeout=60,
        follow_redirects=True,
    )
    resp.raise_for_status()

    with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tar:
        root_prefix = tar.getnames()[0].split("/")[0] + "/"
        target_prefix = root_prefix + remote_path.strip("/") + "/"

        members = [m for m in tar.getmembers() if m.name.startswith(target_prefix)]

        if not members:
            raise FileNotFoundError(
                f"Chemin '{remote_path}' introuvable dans le tarball GitHub. "
                "Vérifiez que le nom correspond bien à un dossier du repo."
            )

        dest.mkdir(parents=True, exist_ok=True)

        for member in members:
            member.name = member.name[len(target_prefix):]
            if not member.name:
                continue
            tar.extract(member, path=dest, filter="data")
