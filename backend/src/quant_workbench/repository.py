"""Local SQLite catalog with immutable Parquet inputs and atomic result files."""

import hashlib
import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import joblib
import pandas as pd
from sklearn import __version__ as sklearn_version

from quant_workbench.market_data import normalize_bars


class Repository:
    def __init__(self, root: Path | None = None):
        self.root = root or Path(os.environ.get("QUANT_DATA_DIR", "data")).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "datasets").mkdir(exist_ok=True)
        (self.root / "results").mkdir(exist_ok=True)
        (self.root / "models").mkdir(exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS datasets(id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS experiments(id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS deployments(
                    id TEXT PRIMARY KEY, experiment_id TEXT UNIQUE NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS simulations(
                    id TEXT PRIMARY KEY, scope TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS run_progress(
                    experiment_id TEXT, phase TEXT, body TEXT NOT NULL,
                    PRIMARY KEY(experiment_id, phase));
                CREATE TABLE IF NOT EXISTS runs(
                    experiment_id TEXT, phase TEXT, status TEXT, error TEXT,
                    exposed INTEGER DEFAULT 0,
                    PRIMARY KEY(experiment_id, phase));
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / "catalog.sqlite", timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def path(self, collection: str, identifier: str, suffix: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}(?:-(?:train|validation|test))?", identifier):
            raise KeyError("记录ID无效")
        return self.root / collection / (identifier + suffix)

    def save_dataset(self, frame: pd.DataFrame, name: str, source: str, synthetic=False, timeframe="1Min"):
        from quant_workbench.daily_data import normalize_daily
        if timeframe not in {"1Min", "1Day"}:
            raise ValueError("不支持的数据周期")
        frame = normalize_daily(frame) if timeframe == "1Day" else normalize_bars(frame)
        identifier = uuid.uuid4().hex
        dest = self.path("datasets", identifier, ".parquet")
        temporary = dest.with_suffix(".tmp")
        frame.to_parquet(temporary, index=False, compression="zstd")
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        temporary.replace(dest)
        dates = sorted(
            set(frame.day) if timeframe == "1Day" else set(frame.timestamp.dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d"))
        )
        info = {
            "id": identifier,
            "name": name[:120],
            "source": source,
            "synthetic": synthetic,
            "sha256": digest,
            "rows": len(frame),
            "symbols": sorted(frame.symbol.unique().tolist()),
            "dates": dates,
            "start": dates[0],
            "end": dates[-1],
            "bytes": dest.stat().st_size,
            "created_at": datetime.now(UTC).isoformat(),
            "timeframe": timeframe,
            "timestamp_convention": "session_date" if timeframe == "1Day" else "minute_end",
        }
        with self.connect() as db:
            db.execute("INSERT INTO datasets VALUES (?,?)", (identifier, json.dumps(info)))
        return info

    def list_records(self, table: str) -> list[dict]:
        if table not in {"datasets", "experiments", "deployments"}:
            raise ValueError("invalid table")
        with self.connect() as db:
            return [
                json.loads(row[0])
                for row in db.execute(f"SELECT body FROM {table} ORDER BY rowid DESC")
            ]

    def get(self, table: str, identifier: str) -> dict:
        if table not in {"datasets", "experiments", "deployments"}:
            raise ValueError("invalid table")
        with self.connect() as db:
            row = db.execute(f"SELECT body FROM {table} WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise KeyError("记录不存在")
        return json.loads(row[0])

    def load_dataset(self, identifier: str) -> pd.DataFrame:
        info = self.get("datasets", identifier)
        path = self.path("datasets", identifier, ".parquet")
        if hashlib.sha256(path.read_bytes()).hexdigest() != info["sha256"]:
            raise ValueError("数据快照被修改，哈希校验失败")
        return pd.read_parquet(path)

    def save_experiment(self, info: dict):
        with self.connect() as db:
            db.execute("INSERT INTO experiments VALUES (?,?)", (info["id"], json.dumps(info)))

    def runs(self, identifier: str) -> list[dict]:
        self.get("experiments", identifier)
        with self.connect() as db:
            return [
                {**dict(r), "progress": self.run_progress(identifier, r["phase"])}
                for r in db.execute("SELECT * FROM runs WHERE experiment_id=?", (identifier,))
            ]

    def set_run_progress(self, identifier, phase, body):
        with self.connect() as db:
            db.execute(
                "INSERT INTO run_progress VALUES (?,?,?) ON CONFLICT(experiment_id,phase) "
                "DO UPDATE SET body=excluded.body",
                (identifier, phase, json.dumps(body)),
            )

    def run_progress(self, identifier, phase):
        with self.connect() as db:
            row = db.execute(
                "SELECT body FROM run_progress WHERE experiment_id=? AND phase=?",
                (identifier, phase),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def save_result(self, identifier: str, phase: str, result: dict):
        path = self.path("results", f"{identifier}-{phase}", ".json")
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8"
        )
        temporary.replace(path)
        with self.connect() as db:
            db.execute(
                "UPDATE runs SET status='completed',error=NULL WHERE experiment_id=? AND phase=?",
                (identifier, phase),
            )

    def result(self, identifier: str, phase: str) -> dict:
        self.get("experiments", identifier)
        path = self.path("results", f"{identifier}-{phase}", ".json")
        if not path.exists():
            raise KeyError("结果尚未生成")
        return json.loads(path.read_text(encoding="utf-8"))

    def recover(self):
        with self.connect() as db:
            for row in db.execute("SELECT id,body FROM operations").fetchall():
                body = json.loads(row["body"])
                if body["status"] in {"queued", "running"}:
                    body.update(
                        status="failed",
                        error="服务重启中断，请重新提交",
                        finished_at=datetime.now(UTC).isoformat(),
                    )
                    db.execute(
                        "UPDATE operations SET body=? WHERE id=?", (json.dumps(body), row["id"])
                    )
            for row in db.execute("SELECT id,body FROM simulations").fetchall():
                body = json.loads(row["body"])
                if body["status"] in {"queued", "running"}:
                    body.update(status="failed", error="服务重启中断，请重新模拟")
                    db.execute(
                        "UPDATE simulations SET body=? WHERE id=?", (json.dumps(body), row["id"])
                    )
            db.execute(
                "UPDATE runs SET status='failed',error='服务重启中断，可重试' "
                "WHERE status='running'"
            )

    def save_model(self, identifier: str, model, phase: str | None = None) -> dict:
        key = identifier if phase is None else f"{identifier}-{phase}"
        path = self.path("models", key, ".joblib")
        temporary = path.with_suffix(".tmp")
        joblib.dump(model, temporary, compress=3)
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        temporary.replace(path)
        artifact = {"sha256": digest, "sklearn_version": sklearn_version}
        metadata = getattr(model, "metadata", {})
        if metadata.get("torch_version"):
            artifact["torch_version"] = metadata["torch_version"]
        return artifact

    def load_model(self, identifier: str, artifact: dict):
        path = self.path("models", identifier, ".joblib")
        if artifact.get("torch_version"):
            try:
                import torch
            except ImportError as exc:
                raise ValueError("此模型需要PyTorch，请运行 uv sync --extra neural") from exc
            if torch.__version__.split("+")[0] != artifact["torch_version"]:
                raise ValueError("PyTorch版本变化，请重新训练或使用模型对应版本")
        if artifact["sklearn_version"] != sklearn_version:
            raise ValueError("模型依赖版本变化，请用当前版本重新创建实验")
        if hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
            raise ValueError("模型快照被修改，哈希校验失败")
        # Only artifacts generated by this repository; never deserialize user uploads.
        return joblib.load(path)
