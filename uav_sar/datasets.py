"""Download original sources with checksums; never substitute generated data."""
import json
import hashlib
import os
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

import requests

from .io import read_json, sha256, write_json

SARENV_URL = "https://github.com/namurproject/SAREnv.git"
SARENV_COMMIT = "0f2d344d17c0b9c18cec2176dd9b171beba727d6"
POP_API = "https://api.osf.io/v2/nodes/kmcva/files/osfstorage/"


def download(url, dest, expected_hash, expected_size):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and sha256(dest) == expected_hash:
        print(f"Verified existing {dest.name}", flush=True)
        return
    if dest.exists():
        raise ValueError(f"Checksum mismatch in existing {dest}; move it aside before retrying.")
    part = dest.with_suffix(dest.suffix + ".part")
    if shutil.disk_usage(dest.parent).free < expected_size + 512 * 1024**2:
        raise RuntimeError(f"Not enough free disk space at {dest.parent}")
    # Restart a partial request when the server does not support ranges.
    for attempt in range(4):
        try:
            offset = part.stat().st_size if part.exists() else 0
            headers = {"Range": f"bytes={offset}-"} if offset else {}
            with requests.get(url, headers=headers, stream=True, timeout=(30, 90)) as response:
                response.raise_for_status()
                resume = offset > 0 and response.status_code == 206
                done = offset if resume else 0
                last = time.monotonic()
                with part.open("ab" if resume else "wb") as out:
                    for chunk in response.iter_content(1024 * 1024):
                        out.write(chunk)
                        done += len(chunk)
                        if time.monotonic() - last >= 5:
                            print(f"{dest.name}: {done / 1e6:.1f}/{expected_size / 1e6:.1f} MB", flush=True)
                            last = time.monotonic()
            if part.stat().st_size != expected_size or sha256(part) != expected_hash:
                raise ValueError(f"Downloaded {dest.name} failed size/SHA256 verification")
            part.replace(dest)
            print(f"Verified SHA256: {dest.name}", flush=True)
            return
        except (requests.RequestException, OSError):
            if attempt == 3:
                raise
            time.sleep(2)


def fetch(config):
    root = Path(config["data_root"]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    repo = root / "SAREnv"
    if not repo.exists():
        env = dict(os.environ, GIT_LFS_SKIP_SMUDGE="1")
        subprocess.run(["git", "clone", "--depth", "1", SARENV_URL, str(repo)], env=env, check=True)
    remote = subprocess.check_output(["git", "-C", str(repo), "remote", "get-url", "origin"], text=True).strip()
    if remote != SARENV_URL:
        raise ValueError(f"Unexpected SAREnv origin: {remote}")
    commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    if commit != SARENV_COMMIT:
        raise ValueError(f"Expected SAREnv {SARENV_COMMIT}, found {commit}. Use the pinned revision.")
    scenario = repo / "sarenv_dataset" / config["scenario"]
    subprocess.run(["git", "-C", str(repo), "lfs", "pull", "--include=" + f"sarenv_dataset/{config['scenario']}/features.geojson"], check=True)
    relative = f"sarenv_dataset/{config['scenario']}"
    pointer = subprocess.check_output(["git", "-C", str(repo), "show", f"HEAD:{relative}/features.geojson"], text=True)
    expected_feature_hash = next(line.split("sha256:", 1)[1] for line in pointer.splitlines() if line.startswith("oid sha256:"))
    heat_bytes = subprocess.check_output(["git", "-C", str(repo), "show", f"HEAD:{relative}/heatmap.npy"])
    if sha256(scenario / "features.geojson") != expected_feature_hash or sha256(scenario / "heatmap.npy") != hashlib.sha256(heat_bytes).hexdigest():
        raise ValueError("SAREnv working data differs from the pinned Git/LFS objects")
    meta = read_json(scenario / "features.geojson")
    if "bounds" not in meta:
        raise ValueError("SAREnv metadata is incomplete")
    response = requests.get(POP_API, timeout=45)
    response.raise_for_status()
    files = response.json()["data"]
    record = next(item for item in files if item["attributes"]["name"] == "POP.zip")
    attrs = record["attributes"]
    archive = root / "downloads" / "POP.zip"
    download(record["links"]["download"], archive, attrs["extra"]["hashes"]["sha256"], attrs["size"])
    target = root / "POP"
    marker = target / ".extracted.json"
    if marker.exists() and read_json(marker)["archive_sha256"] != attrs["extra"]["hashes"]["sha256"]:
        raise ValueError("POP extraction marker belongs to a different archive")
    if not marker.exists():
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as z:
            required = sum(i.file_size for i in z.infolist())
            if shutil.disk_usage(target).free < required + 512 * 1024**2:
                raise RuntimeError("Not enough disk space to extract POP")
            for info in z.infolist():
                path = (target / info.filename).resolve()
                if not path.is_relative_to(target.resolve()):
                    raise ValueError("Unsafe archive path")
            print(f"Extracting {len(z.infolist())} POP entries...", flush=True)
            z.extractall(target)
        write_json(marker, {"archive_sha256": sha256(archive)})
    manifest = {"sarenv_url": remote, "sarenv_commit": commit, "scenario": config["scenario"],
                "heatmap_sha256": sha256(scenario / "heatmap.npy"),
                "features_sha256": sha256(scenario / "features.geojson"),
                "pop_doi": "10.17605/OSF.IO/KMCVA", "pop_record": record,
                "pop_archive_sha256": sha256(archive)}
    write_json(root / "sources.json", manifest)
    print(f"Dataset sources verified: {root / 'sources.json'}", flush=True)
