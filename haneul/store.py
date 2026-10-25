"""학습 자료·설정 저장소. 파일 하나(haneul_data.json)에 컬렉션별로 문서를 담는다.

{"collections": {"examples": {"<id>": {...}}, "config": {"main": {...}}}}
"""

import json
import os
import re
import threading
from pathlib import Path

SEGMENT = re.compile(r"^[A-Za-z0-9_\-.~:@+]{1,200}$")


class StoreError(ValueError):
    pass


def split_doc(path):
    """'config/main' → ('config', 'main'). 문서 경로는 짝수 개 마디."""
    parts = str(path).split("/")
    if len(parts) < 2 or len(parts) % 2 or not all(SEGMENT.match(p) and p not in (".", "..") for p in parts):
        raise StoreError(f"문서 경로가 올바르지 않습니다: {path}")
    return "/".join(parts[:-1]), parts[-1]


def check_collection(path):
    parts = str(path).split("/")
    if len(parts) % 2 == 0 or not all(SEGMENT.match(p) and p not in (".", "..") for p in parts):
        raise StoreError(f"컬렉션 경로가 올바르지 않습니다: {path}")
    return str(path)


def _merge(base, patch):
    out = dict(base)
    for k, v in patch.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


class Store:
    def __init__(self, file):
        self.file = Path(file)
        self.lock = threading.Lock()
        self._dirty = False
        self._timer = None
        self.data = self._load()

    def _load(self):
        try:
            raw = json.loads(self.file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"collections": {}}
        except (OSError, ValueError) as e:
            # 깨진 파일은 덮어쓰지 않고 옆에 남겨 둔다.
            backup = self.file.with_suffix(".broken.json")
            try:
                self.file.replace(backup)
            except OSError:
                pass
            print(f"자료 파일을 읽지 못해 {backup.name}으로 옮겼습니다: {e}")
            return {"collections": {}}
        if not isinstance(raw, dict) or not isinstance(raw.get("collections"), dict):
            return {"collections": {}}
        return raw

    def _save(self):
        """잠금 안에서 부른다. 여러 건을 잇달아 넣을 때 파일 전체를 매번 쓰지 않도록 0.5초 모았다가 쓴다."""
        self._dirty = True
        if self._timer is None:
            self._timer = threading.Timer(0.5, self.flush)
            self._timer.daemon = True
            self._timer.start()

    def flush(self):
        with self.lock:
            self._timer = None
            if not self._dirty:
                return
            tmp = self.file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.file)
            self._dirty = False

    def get(self, path):
        col, doc_id = split_doc(path)
        with self.lock:
            return self.data["collections"].get(col, {}).get(doc_id)

    def set(self, path, body):
        if not isinstance(body, dict):
            raise StoreError("문서는 객체여야 합니다.")
        col, doc_id = split_doc(path)
        with self.lock:
            self.data["collections"].setdefault(col, {})[doc_id] = body
            self._save()

    def update(self, path, patch):
        if not isinstance(patch, dict):
            raise StoreError("문서는 객체여야 합니다.")
        col, doc_id = split_doc(path)
        with self.lock:
            docs = self.data["collections"].setdefault(col, {})
            if doc_id not in docs:
                raise StoreError("없는 문서는 update할 수 없습니다.")
            docs[doc_id] = _merge(docs[doc_id], patch)
            self._save()

    def delete(self, path):
        col, doc_id = split_doc(path)
        with self.lock:
            if self.data["collections"].get(col, {}).pop(doc_id, None) is not None:
                self._save()

    def list(self, collection, order_by=None, direction="asc", limit=None):
        check_collection(collection)
        with self.lock:
            items = [{"id": k, "data": v} for k, v in self.data["collections"].get(collection, {}).items()]
        if order_by:
            have = [d for d in items if d["data"].get(order_by) is not None]
            missing = [d for d in items if d["data"].get(order_by) is None]
            have.sort(key=lambda d: (str(type(d["data"][order_by])), d["data"][order_by]), reverse=direction == "desc")
            items = have + missing
        else:
            items.sort(key=lambda d: d["id"])
        if limit:
            items = items[: max(1, min(int(limit), 1000))]
        return items
