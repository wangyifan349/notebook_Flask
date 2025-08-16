from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from pydantic import BaseModel
from typing import Dict, List
import threading
import numpy as np
import face_recognition
import os
from io import BytesIO
from PIL import Image

app = FastAPI()

class BuildDatabaseRequest(BaseModel):
    directory: str
    threshold: float = 0.6

class BuildDatabaseResponse(BaseModel):
    status: str
    entries: int

class CompareResponse(BaseModel):
    similarity: float

class SearchResponseItem(BaseModel):
    filename: str
    similarity: float

class SearchResponse(BaseModel):
    results: List[SearchResponseItem]

face_encoding_database: Dict[str, List[np.ndarray]] = {}
db_lock = threading.Lock()

def default_distance_to_similarity(distance: float) -> float:
    return max(0.0, 1.0 - distance / 0.6)

distance_to_similarity = default_distance_to_similarity

def extract_encodings(upload_file: UploadFile) -> List[np.ndarray]:
    upload_file.file.seek(0)
    data = upload_file.file.read()
    try:
        img = Image.open(BytesIO(data)).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="无法解析上传的图片")
    encodings = face_recognition.face_encodings(np.array(img))
    if not encodings:
        raise HTTPException(status_code=400, detail="未检测到人脸")
    return encodings

@app.post("/build_db/", response_model=BuildDatabaseResponse)
async def build_db(request: BuildDatabaseRequest) -> BuildDatabaseResponse:
    if not os.path.isdir(request.directory):
        raise HTTPException(status_code=400, detail="目录不存在")
    with db_lock:
        face_encoding_database.clear()
        def new_distance_to_similarity(d: float) -> float:
            return max(0.0, 1.0 - d / request.threshold)
        global distance_to_similarity
        distance_to_similarity = new_distance_to_similarity

        for fname in os.listdir(request.directory):
            if not fname.lower().endswith((".jpg", ".jpeg", ".png")):
                continue
            path = os.path.join(request.directory, fname)
            try:
                img = Image.open(path).convert("RGB")
                encs = face_recognition.face_encodings(np.array(img))
                if encs:
                    face_encoding_database[fname] = encs
            except Exception:
                continue

    return BuildDatabaseResponse(status="database_built", entries=len(face_encoding_database))

@app.post("/compare/", response_model=CompareResponse)
async def compare_faces(
    file_one: UploadFile = File(...),
    file_two: UploadFile = File(...)
) -> CompareResponse:
    encs1 = extract_encodings(file_one)
    encs2 = extract_encodings(file_two)
    dist = np.linalg.norm(encs1[0] - encs2[0])
    sim = distance_to_similarity(dist)
    return CompareResponse(similarity=sim)

@app.post("/search/", response_model=SearchResponse)
async def search_faces(
    file_query: UploadFile = File(...),
    top_n: int = Query(5, gt=0, description="最多返回的结果数")
) -> SearchResponse:
    if not face_encoding_database:
        raise HTTPException(status_code=400, detail="数据库为空，请先调用 /build_db/")
    query_encs = extract_encodings(file_query)
    scores: Dict[str, float] = {}
    for qvec in query_encs:
        for fname, enc_list in face_encoding_database.items():
            best_dist = min(np.linalg.norm(qvec - dbvec) for dbvec in enc_list)
            sim = distance_to_similarity(best_dist)
            if sim > scores.get(fname, 0.0):
                scores[fname] = sim
    sorted_items = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_n]
    results = [SearchResponseItem(filename=f, similarity=s) for f, s in sorted_items]
    return SearchResponse(results=results)
