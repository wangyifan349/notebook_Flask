# app.py
import os
import io
import json
from typing import List, Any, Optional
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename

import cv2
import dlib
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed

# ----------------------
# Face module (flattened/refactored)
# ----------------------
DETECTOR = None
SHAPE_PREDICTOR = None
FACE_RECOG = None
NUM_WORKERS = 4
INDEX = []  # list of {"id":..., "descriptor": np.ndarray, "meta":...}

def initialize_models(predictor_path: str, recog_model_path: str, detector=None, num_workers: int = 4):
    global DETECTOR, SHAPE_PREDICTOR, FACE_RECOG, NUM_WORKERS
    if not os.path.exists(predictor_path):
        raise FileNotFoundError(predictor_path)
    if not os.path.exists(recog_model_path):
        raise FileNotFoundError(recog_model_path)
    DETECTOR = detector or dlib.get_frontal_face_detector()
    SHAPE_PREDICTOR = dlib.shape_predictor(predictor_path)
    FACE_RECOG = dlib.face_recognition_model_v1(recog_model_path)
    NUM_WORKERS = max(1, int(num_workers))

def ensure_models_ready():
    if DETECTOR is None or SHAPE_PREDICTOR is None or FACE_RECOG is None:
        raise RuntimeError("models not initialized")

def read_image_rgb_from_bytes(b: bytes) -> np.ndarray:
    arr = np.frombuffer(b, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Invalid image bytes")
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

def read_image_rgb_from_path(path: str) -> np.ndarray:
    img = cv2.imread(path)
    if img is None:
        raise FileNotFoundError(path)
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

def detect_faces_in_image(img_rgb: np.ndarray, upsample: int = 1):
    ensure_models_ready()
    return list(DETECTOR(img_rgb, upsample))

def align_face_chip(img_rgb: np.ndarray, rect: dlib.rectangle, size: int = 150):
    ensure_models_ready()
    shape = SHAPE_PREDICTOR(img_rgb, rect)
    return dlib.get_face_chip(img_rgb, shape, size=size)

def compute_descriptor_from_chip(face_chip: np.ndarray) -> np.ndarray:
    ensure_models_ready()
    return np.array(FACE_RECOG.compute_face_descriptor(face_chip), dtype=np.float32)

def l2_normalize(vec: np.ndarray) -> np.ndarray:
    v = np.asarray(vec, dtype=np.float32)
    n = np.linalg.norm(v)
    if n == 0:
        return v
    return v / n

def extract_descriptor_from_image_rgb(img_rgb: np.ndarray, pick_largest: bool = True, size: int = 150) -> Optional[np.ndarray]:
    rects = detect_faces_in_image(img_rgb)
    if not rects:
        return None
    chips = [align_face_chip(img_rgb, r, size=size) for r in rects]
    descs = [compute_descriptor_from_chip(c) for c in chips]
    if pick_largest and len(rects) > 1:
        areas = [r.width() * r.height() for r in rects]
        idx = int(np.argmax(areas))
        return l2_normalize(descs[idx])
    return l2_normalize(descs[0])

def extract_descriptor_from_bytes(image_bytes: bytes, pick_largest: bool = True, size: int = 150) -> Optional[np.ndarray]:
    img = read_image_rgb_from_bytes(image_bytes)
    return extract_descriptor_from_image_rgb(img, pick_largest=pick_largest, size=size)

def extract_descriptor_from_path(path: str, pick_largest: bool = True, size: int = 150) -> Optional[np.ndarray]:
    img = read_image_rgb_from_path(path)
    return extract_descriptor_from_image_rgb(img, pick_largest=pick_largest, size=size)

def extract_descriptors_batch_from_bytes_list(images: List[bytes], pick_largest: bool = True, size: int = 150, max_workers: Optional[int] = None):
    workers = NUM_WORKERS if max_workers is None else max(1, int(max_workers))
    def job(b):
        try:
            return extract_descriptor_from_bytes(b, pick_largest=pick_largest, size=size)
        except Exception:
            return None
    results = [None] * len(images)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = { ex.submit(job, images[i]): i for i in range(len(images)) }
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                results[idx] = fut.result()
            except Exception:
                results[idx] = None
    return results

def build_template_from_descriptors(descriptors: List[np.ndarray]) -> np.ndarray:
    if not descriptors:
        raise ValueError("empty descriptors")
    stacked = np.vstack([np.asarray(d, dtype=np.float32) for d in descriptors])
    mean_vec = np.mean(stacked, axis=0)
    return l2_normalize(mean_vec)

# index management
def index_add(entries: List[dict]):
    global INDEX
    for e in entries:
        if "id" not in e or "descriptor" not in e:
            raise ValueError("entry must have id and descriptor")
        vec = l2_normalize(np.asarray(e["descriptor"], dtype=np.float32))
        INDEX.append({"id": e["id"], "descriptor": vec, "meta": e.get("meta")})

def index_remove(id_value: Any) -> bool:
    global INDEX
    for i, e in enumerate(INDEX):
        if e["id"] == id_value:
            INDEX.pop(i)
            return True
    return False

def index_list():
    return [{"id": e["id"], "meta": e["meta"]} for e in INDEX]

def index_clear():
    global INDEX
    INDEX = []

def brute_force_search_single(query_vec: np.ndarray, top_k: int = 5, metric: str = "cosine"):
    if len(INDEX) == 0:
        raise RuntimeError("index empty")
    q = l2_normalize(np.asarray(query_vec, dtype=np.float32))
    db = np.vstack([e["descriptor"] for e in INDEX])
    ids = [e["id"] for e in INDEX]
    metas = [e["meta"] for e in INDEX]
    if metric == "cosine":
        sims = db.dot(q)
        idxs = np.argsort(-sims)[:top_k]
        return [(ids[int(i)], float(sims[int(i)]), metas[int(i)]) for i in idxs]
    elif metric == "l2":
        dists = np.linalg.norm(db - q, axis=1)
        idxs = np.argsort(dists)[:top_k]
        return [(ids[int(i)], float(dists[int(i)]), metas[int(i)]) for i in idxs]
    else:
        raise ValueError("metric must be 'cosine' or 'l2'")

def compare_cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(l2_normalize(a), l2_normalize(b)))

def compare_l2(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(np.asarray(a, dtype=np.float32) - np.asarray(b, dtype=np.float32)))

def is_same_person(a: np.ndarray, b: np.ndarray, method: str = "cosine", threshold: Optional[float] = None):
    if method == "cosine":
        score = compare_cosine(a, b)
        thr = 0.45 if threshold is None else threshold
        return score >= thr, score
    elif method == "l2":
        d = compare_l2(a, b)
        thr = 0.6 if threshold is None else threshold
        return d <= thr, d
    else:
        raise ValueError("method must be 'cosine' or 'l2'")

# ----------------------
# Flask app
# ----------------------
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB uploads
UPLOAD_FOLDER = "./uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route("/init_models", methods=["POST"])
def route_init_models():
    """
    JSON body: {"predictor_path": "...", "recog_model_path": "...", "num_workers": 4}
    """
    data = request.get_json(force=True)
    p = data.get("predictor_path")
    r = data.get("recog_model_path")
    nw = data.get("num_workers", 4)
    try:
        initialize_models(p, r, num_workers=nw)
    except Exception as ex:
        app.logger.error("init error: %s", ex)
        return jsonify({"ok": False, "error": str(ex)}), 400
    return jsonify({"ok": True})

@app.route("/extract_from_file", methods=["POST"])
def route_extract_from_file():
    """
    form-data: file=<image>
    returns: {"descriptor": [128 floats]} or {"descriptor": null}
    """
    if 'file' not in request.files:
        return jsonify({"ok": False, "error": "missing file"}), 400
    f = request.files['file']
    filename = secure_filename(f.filename)
    buf = f.read()
    try:
        desc = extract_descriptor_from_bytes(buf)
    except Exception as ex:
        app.logger.error("extract error: %s", ex)
        return jsonify({"ok": False, "error": str(ex)}), 500
    if desc is None:
        return jsonify({"ok": True, "descriptor": None})
    return jsonify({"ok": True, "descriptor": desc.tolist()})

@app.route("/extract_from_path", methods=["POST"])
def route_extract_from_path():
    """
    JSON: {"path": "/abs/or/relative/path/to/image"}
    """
    data = request.get_json(force=True)
    path = data.get("path")
    try:
        desc = extract_descriptor_from_path(path)
    except Exception as ex:
        app.logger.error("extract path error: %s", ex)
        return jsonify({"ok": False, "error": str(ex)}), 500
    return jsonify({"ok": True, "descriptor": None if desc is None else desc.tolist()})

@app.route("/batch_extract", methods=["POST"])
def route_batch_extract():
    """
    Multipart form-data: files[] multiple image files
    returns list of descriptors/nulls in same order
    """
    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "error": "no files"}), 400
    bytes_list = [f.read() for f in files]
    results = extract_descriptors_batch_from_bytes_list(bytes_list)
    out = [None if r is None else r.tolist() for r in results]
    return jsonify({"ok": True, "descriptors": out})

@app.route("/index/add", methods=["POST"])
def route_index_add():
    """
    JSON: {"entries": [{"id": "...", "descriptor": [...], "meta": {...}}, ...]}
    """
    data = request.get_json(force=True)
    entries = data.get("entries", [])
    try:
        index_add(entries)
    except Exception as ex:
        app.logger.error("index add error: %s", ex)
        return jsonify({"ok": False, "error": str(ex)}), 400
    return jsonify({"ok": True, "index_size": len(INDEX)})

@app.route("/index/remove", methods=["POST"])
def route_index_remove():
    data = request.get_json(force=True)
    idv = data.get("id")
    if idv is None:
        return jsonify({"ok": False, "error": "missing id"}), 400
    removed = index_remove(idv)
    return jsonify({"ok": True, "removed": removed, "index_size": len(INDEX)})

@app.route("/index/list", methods=["GET"])
def route_index_list():
    return jsonify({"ok": True, "entries": index_list()})

@app.route("/index/clear", methods=["POST"])
def route_index_clear():
    index_clear()
    return jsonify({"ok": True})

@app.route("/search", methods=["POST"])
def route_search():
    """
    JSON: {"descriptor": [...], "top_k": 5, "metric": "cosine"}
    or {"descriptors": [[...], ...], "top_k":5}
    """
    data = request.get_json(force=True)
    q = data.get("descriptor")
    qs = data.get("descriptors")
    top_k = int(data.get("top_k", 5))
    metric = data.get("metric", "cosine")
    try:
        if qs is not None:
            out = []
            for vec in qs:
                res = brute_force_search_single(np.asarray(vec, dtype=np.float32), top_k=top_k, metric=metric)
                out.append([{"id": r[0], "score": r[1], "meta": r[2]} for r in res])
            return jsonify({"ok": True, "results": out})
        if q is None:
            return jsonify({"ok": False, "error": "missing descriptor"}), 400
        res = brute_force_search_single(np.asarray(q, dtype=np.float32), top_k=top_k, metric=metric)
        return jsonify({"ok": True, "results": [{"id": r[0], "score": r[1], "meta": r[2]} for r in res]})
    except Exception as ex:
        app.logger.error("search error: %s", ex)
        return jsonify({"ok": False, "error": str(ex)}), 500

@app.route("/compare", methods=["POST"])
def route_compare():
    """
    JSON: {"a": [...], "b": [...], "method": "cosine"}
    returns {"same": bool, "score": float}
    """
    data = request.get_json(force=True)
    a = data.get("a")
    b = data.get("b")
    method = data.get("method", "cosine")
    if a is None or b is None:
        return jsonify({"ok": False, "error": "missing vectors"}), 400
    try:
        same, score = is_same_person(np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32), method=method)
        return jsonify({"ok": True, "same": bool(same), "score": float(score)})
    except Exception as ex:
        app.logger.error("compare error: %s", ex)
        return jsonify({"ok": False, "error": str(ex)}), 500

# health
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "models_loaded": DETECTOR is not None and SHAPE_PREDICTOR is not None and FACE_RECOG is not None, "index_size": len(INDEX)})

if __name__ == "__main__":
    # simple dev server
    app.run(host="0.0.0.0", port=5000, debug=True)
