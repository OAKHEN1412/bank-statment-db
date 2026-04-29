"""
updater.py — Self-update module for Bank Statement DB
Downloads latest release from GitHub and applies it.
"""
import json
import os
import shutil
import tempfile
import zipfile
import urllib.request
import urllib.error

VERSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'version.json')

# Files/folders that must NOT be overwritten during update
EXCLUDED = {
    'bank_statements.db',
    'uploads',
    'version.json',
    '__pycache__',
    '.env',
}


def get_config() -> dict:
    """Return contents of version.json (version + github_repo)."""
    if not os.path.exists(VERSION_FILE):
        return {'version': '1.0.0', 'github_repo': ''}
    with open(VERSION_FILE, encoding='utf-8') as f:
        return json.load(f)


def save_config(github_repo: str) -> None:
    """Persist github_repo setting to version.json."""
    config = get_config()
    config['github_repo'] = github_repo.strip()
    with open(VERSION_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def update_version_number(new_version: str) -> None:
    """Persist new version number to version.json after successful update."""
    config = get_config()
    config['version'] = new_version
    with open(VERSION_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def _version_tuple(v: str):
    try:
        return tuple(int(x) for x in str(v).lstrip('v').split('.'))
    except Exception:
        return (0,)


def check_for_update() -> dict:
    """
    Query GitHub Releases API for the latest release.
    Returns a dict with keys:
      has_update, current, latest, download_url,
      release_name, release_notes, published_at
    OR:
      error (str), current (str)
    """
    config = get_config()
    repo = config.get('github_repo', '').strip()
    current = config.get('version', '1.0.0')

    if not repo or '/' not in repo:
        repo = 'OAKHEN1412/bank-statment-db'

    url = f'https://api.github.com/repos/{repo}/releases/latest'
    req = urllib.request.Request(url, headers={
        'User-Agent': 'BankStatementDB-Updater/1.0',
        'Accept': 'application/vnd.github.v3+json',
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {'error': 'no_releases', 'current': current}
        return {'error': f'GitHub API error: HTTP {e.code}', 'current': current}
    except Exception as e:
        return {'error': str(e), 'current': current}

    latest = data.get('tag_name', '').lstrip('v')
    download_url = data.get('zipball_url', '')
    has_update = _version_tuple(latest) > _version_tuple(current)

    return {
        'current': current,
        'latest': latest,
        'has_update': has_update,
        'download_url': download_url,
        'release_name': data.get('name') or f'v{latest}',
        'release_notes': data.get('body', ''),
        'published_at': data.get('published_at', ''),
    }


def apply_update(download_url: str) -> tuple[bool, str]:
    """
    Download zip from download_url, extract, and copy files to app directory.
    Files in EXCLUDED set are never overwritten.
    Returns (success: bool, message: str).
    """
    if not download_url:
        return False, 'No download URL provided'

    app_dir = os.path.dirname(os.path.abspath(__file__))
    tmp_zip = os.path.join(tempfile.gettempdir(), 'bsdb_update.zip')
    tmp_dir = os.path.join(tempfile.gettempdir(), 'bsdb_extract')

    # ── Download ──────────────────────────────────────────────────────────────
    req = urllib.request.Request(download_url, headers={
        'User-Agent': 'BankStatementDB-Updater/1.0',
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as resp, \
             open(tmp_zip, 'wb') as f:
            shutil.copyfileobj(resp, f)
    except Exception as e:
        return False, f'Download failed: {e}'

    # ── Extract ───────────────────────────────────────────────────────────────
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir)
    try:
        with zipfile.ZipFile(tmp_zip, 'r') as z:
            z.extractall(tmp_dir)
    except Exception as e:
        _cleanup(tmp_zip, tmp_dir)
        return False, f'Extract failed: {e}'

    # GitHub zipball: top-level folder is "owner-repo-sha/"
    # If repo root == web_app content, files are directly there.
    # If repo has web_app/ subfolder, go one level deeper.
    src_root = tmp_dir
    entries = os.listdir(tmp_dir)
    if len(entries) == 1 and os.path.isdir(os.path.join(tmp_dir, entries[0])):
        candidate = os.path.join(tmp_dir, entries[0])
        # Check if there's a nested web_app/ folder
        web_app_sub = os.path.join(candidate, 'web_app')
        if os.path.exists(web_app_sub):
            src_root = web_app_sub
        else:
            src_root = candidate

    # ── Copy files ────────────────────────────────────────────────────────────
    errors = []
    for item in os.listdir(src_root):
        if item in EXCLUDED:
            continue
        src = os.path.join(src_root, item)
        dst = os.path.join(app_dir, item)
        try:
            if os.path.isdir(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
        except Exception as e:
            errors.append(f'{item}: {e}')

    _cleanup(tmp_zip, tmp_dir)

    if errors:
        return False, 'Some files could not be updated: ' + ', '.join(errors)
    return True, 'Update applied successfully'


def _cleanup(tmp_zip: str, tmp_dir: str) -> None:
    try:
        if os.path.exists(tmp_zip):
            os.remove(tmp_zip)
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)
    except Exception:
        pass
