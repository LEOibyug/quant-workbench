"""Complete referenced historical submission indexes without changing original caches."""

import json
from pathlib import Path

import httpx


def main():
    root = Path("artifacts/research/earnings-events")
    root.mkdir(parents=True, exist_ok=True)
    manifest = {}
    with httpx.Client(
        timeout=30, headers={"User-Agent": "QuantWorkbench financial research local client"}
    ) as client:
        for source in sorted(Path("artifacts/research/sec-quality").glob("*-submission.json")):
            d = json.loads(source.read_text())
            r = d["filings"]["recent"]
            archives = []
            for info in d["filings"].get("files", []):
                if info["filingTo"] < "2022-09-01" or info["filingFrom"] >= "2026-09-01":
                    continue
                path = root / info["name"]
                if not path.exists():
                    response = client.get("https://data.sec.gov/submissions/" + info["name"])
                    response.raise_for_status()
                    payload = response.json()
                    path.write_text(json.dumps(payload))
                extra = json.loads(path.read_text())
                if not set(r).issubset(extra):
                    raise ValueError("Archive schema mismatch")
                for key in r:
                    r[key].extend(extra[key])
                archives.append(info["name"])
                print(source.stem, info["name"], len(extra["form"]), flush=True)
            if len(set(r["accessionNumber"])) != len(r["accessionNumber"]):
                raise ValueError("Duplicate accession")
            (root / source.name).write_text(json.dumps(d))
            manifest[source.name] = dict(
                archives=archives, rows=len(r["form"]), earliest=min(r["filingDate"])
            )
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
