#!/usr/bin/env python3
"""
face_beauty_fixed_full.py
完整版本：局部瘦脸（三角仿射）、斑点修复、频率分离磨皮、CLAHE美白、眼唇增强，使用软掩码融合。

依赖:
  pip install numpy opencv-python dlib scipy
将 dlib 的 shape_predictor_68_face_landmarks.dat 放在同目录或修改 LANDMARK_MODEL 路径。
"""

import sys
import os
import math
import cv2
import dlib
import numpy as np

# 可调参数
LANDMARK_MODEL = "shape_predictor_68_face_landmarks.dat"  # dlib 模型路径
FACE_SLIM_FACTOR = 0.25           # 0..0.5 建议范围
GAUSSIAN_BLUR_SIGMA_REL = 0.06    # 相对脸宽的 sigma（用于频率分离低通）
CLAHE_CLIP_LIMIT = 2.0
CLAHE_TILE_GRID = (8, 8)
SPOT_THRESHOLD_REL = 0.18         # 相对局部亮度差阈值（0..1）
HIGH_FREQ_ATTENUATION = 0.6       # 高频保留强度 (0..1)
SOFT_MASK_BLUR_RATIO = 0.02       # 软掩码羽化比例（相对于脸宽）
EYE_BRIGHTNESS_SCALE = 1.07
EYE_BRIGHTNESS_ADD = 6
EYE_SHARPEN_ALPHA = 1.2
EYE_SHARPEN_BETA = -0.2
LIP_SATURATION_SCALE = 1.12
LIP_BRIGHTNESS_SCALE = 1.03

# 初始化 dlib
if not os.path.exists(LANDMARK_MODEL):
    raise FileNotFoundError("找不到 dlib 地标模型文件: " + LANDMARK_MODEL)
detector = dlib.get_frontal_face_detector()
predictor = dlib.shape_predictor(LANDMARK_MODEL)


def shape_to_np(shape, dtype="float32"):
    pts = np.zeros((68, 2), dtype=dtype)
    for i in range(68):
        pts[i] = (shape.part(i).x, shape.part(i).y)
    return pts


def get_face_box_and_landmarks(img_bgr):
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    rects = detector(gray, 1)
    if len(rects) == 0:
        return None, None
    rect = rects[0]
    shape = predictor(gray, rect)
    landmarks = shape_to_np(shape)
    return rect, landmarks


def soft_mask_from_polygon(poly_pts, img_shape, feather_radius):
    mask = np.zeros(img_shape[:2], dtype=np.uint8)
    pts_i = np.round(poly_pts).astype(np.int32)
    cv2.fillConvexPoly(mask, pts_i, 255)
    if feather_radius > 0:
        # kernel size must be odd
        k = int(max(3, round(feather_radius)) // 2 * 2 + 1)
        mask = cv2.GaussianBlur(mask.astype(np.float32), (k, k), feather_radius)
        mask = (mask / 255.0).astype(np.float32)
    else:
        mask = (mask / 255.0).astype(np.float32)
    return mask


def build_skin_mask(img_bgr, landmarks):
    h, w = img_bgr.shape[:2]
    face_width = np.linalg.norm(landmarks[0] - landmarks[16])
    jaw = landmarks[0:17]
    topy = landmarks[27]  # 鼻根
    top_pt = np.array([ (landmarks[0,0]+landmarks[16,0])/2.0, max(0, landmarks[27,1] - face_width*0.35) ])
    poly = np.vstack((jaw, top_pt)).astype(np.float32)
    feather_px = max(1.0, face_width * SOFT_MASK_BLUR_RATIO)
    mask_shape = soft_mask_from_polygon(poly, img_bgr.shape, feather_px)

    img_ycrcb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2YCrCb)
    Y, Cr, Cb = cv2.split(img_ycrcb)
    skin_cb_low, skin_cb_high = 77, 127
    skin_cr_low, skin_cr_high = 133, 173
    cb_mask = ((Cb >= skin_cb_low) & (Cb <= skin_cb_high))
    cr_mask = ((Cr >= skin_cr_low) & (Cr <= skin_cr_high))
    cbcr_mask = (cb_mask & cr_mask).astype(np.float32)
    combined = mask_shape * cbcr_mask

    kernel_size = max(3, int(round(face_width * 0.02)) | 1)
    combined_u8 = (np.clip(combined, 0, 1) * 255).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    combined_u8 = cv2.dilate(combined_u8, kernel, iterations=1)
    combined = cv2.GaussianBlur(combined_u8.astype(np.float32)/255.0, (kernel_size, kernel_size), 0)

    return np.clip(combined, 0.0, 1.0)


def detect_spot_mask(img_bgr, skin_mask, face_width):
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    win = max(9, int(round(face_width * 0.03)) | 1)
    local_med = cv2.medianBlur(gray.astype(np.uint8), ksize=win)
    diff = (local_med.astype(np.float32) - gray)
    std = max(1.0, np.std(gray[skin_mask > 0]))
    thr = max(8.0, SPOT_THRESHOLD_REL * 255.0)
    thr_eff = thr * max(0.6, (std / 30.0))
    raw_spot = (diff > thr_eff) & (skin_mask > 0.5)
    spot_mask = (raw_spot.astype(np.uint8) * 255)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3,3))
    spot_mask = cv2.morphologyEx(spot_mask, cv2.MORPH_OPEN, kernel, iterations=1)
    spot_mask = cv2.dilate(spot_mask, kernel, iterations=1)
    return spot_mask


def inpaint_spots(img_bgr, spot_mask):
    if np.count_nonzero(spot_mask) == 0:
        return img_bgr.copy()
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(spot_mask, connectivity=8)
    mask_out = np.zeros_like(spot_mask)
    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        comp_mask = (labels == i).astype(np.uint8)*255
        if area < 200:
            mask_out = cv2.bitwise_or(mask_out, comp_mask)
        else:
            kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5,5))
            small = cv2.erode(comp_mask, kern, iterations=1)
            if np.count_nonzero(small) > 0:
                mask_out = cv2.bitwise_or(mask_out, small)
    if np.count_nonzero(mask_out) == 0:
        return img_bgr.copy()
    repaired = cv2.inpaint(img_bgr, mask_out, inpaintRadius=3, flags=cv2.INPAINT_TELEA)
    return repaired


def delaunay_triangles(rect, points):
    try:
        from scipy.spatial import Delaunay
        tri = Delaunay(points)
        triangles = []
        for t in tri.simplices:
            triangles.append((t[0], t[1], t[2]))
        return triangles
    except Exception:
        # fallback simple fan triangulation on convex hull
        hull = cv2.convexHull(points.astype(np.float32))
        if len(hull) >= 3:
            hull_idxs = []
            for hpt in hull:
                d = np.linalg.norm(points - hpt[0], axis=1)
                hull_idxs.append(np.argmin(d))
            triangles = []
            for i in range(1, len(hull_idxs)-1):
                triangles.append((hull_idxs[0], hull_idxs[i], hull_idxs[i+1]))
            return triangles
        return []


def affine_warp_triangle(src_img, dst_img, t_src, t_dst):
    r1 = cv2.boundingRect(np.float32([t_src]))
    r2 = cv2.boundingRect(np.float32([t_dst]))
    t1_rect = []
    t2_rect = []
    t2_rect_int = []
    for i in range(3):
        t1_rect.append(((t_src[i][0] - r1[0]), (t_src[i][1] - r1[1])))
        t2_rect.append(((t_dst[i][0] - r2[0]), (t_dst[i][1] - r2[1])))
        t2_rect_int.append((int(t_dst[i][0] - r2[0]), int(t_dst[i][1] - r2[1])))
    r1_w = r1[2]; r1_h = r1[3]; r2_w = r2[2]; r2_h = r2[3]
    if r1_w <=0 or r1_h <=0 or r2_w <=0 or r2_h <=0:
        return
    src_rect = src_img[r1[1]:r1[1]+r1_h, r1[0]:r1[0]+r1_w]
    mat = cv2.getAffineTransform(np.float32(t1_rect), np.float32(t2_rect))
    warped = cv2.warpAffine(src_rect, mat, (r2_w, r2_h), None, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
    mask = np.zeros((r2_h, r2_w), dtype=np.float32)
    pts = np.int32(np.array([t2_rect_int]))
    cv2.fillConvexPoly(mask, pts, 1.0, 16, 0)
    dst_slice = dst_img[r2[1]:r2[1]+r2_h, r2[0]:r2[0]+r2_w]
    dst_slice[:] = dst_slice * (1 - mask[..., None]) + warped * (mask[..., None])


def slim_face_local(img_bgr, landmarks, factor):
    h, w = img_bgr.shape[:2]
    face_left = landmarks[0]; face_right = landmarks[16]
    face_center_x = (face_left[0] + face_right[0]) / 2.0
    face_width = np.linalg.norm(face_right - face_left)
    roi_w = int(min(w, max(100, face_width * 1.6)))
    roi_h = int(min(h, roi_w * 1.2))
    cx = int(np.clip(face_center_x, roi_w//2, w - roi_w//2))
    cy = int(np.clip(int(landmarks[27,1]), roi_h//2, h - roi_h//2))
    x0 = cx - roi_w//2; y0 = cy - roi_h//2; x1 = x0 + roi_w; y1 = y0 + roi_h
    roi = img_bgr[y0:y1, x0:x1].copy()
    lm_roi = landmarks.copy(); lm_roi[:,0] -= x0; lm_roi[:,1] -= y0
    boundary_pts = np.array([[0,0],[roi_w-1,0],[roi_w-1,roi_h-1],[0,roi_h-1]], dtype=np.float32)
    ctrl_pts = np.vstack((lm_roi, boundary_pts))
    dst_pts = ctrl_pts.copy()
    move_dist = factor * face_width * 0.06
    for idx in range(0,17):
        x,y = dst_pts[idx]
        if x < (face_center_x - x0):
            dst_pts[idx,0] = x + abs(move_dist)
        else:
            dst_pts[idx,0] = x - abs(move_dist)
    rect = (0,0,roi_w,roi_h)
    triangles = delaunay_triangles(rect, ctrl_pts)
    if len(triangles) == 0:
        return img_bgr.copy(), landmarks.copy()
    warped_roi = roi.copy()
    for tri in triangles:
        t_src = np.array([ctrl_pts[tri[0]], ctrl_pts[tri[1]], ctrl_pts[tri[2]]], dtype=np.float32)
        t_dst = np.array([dst_pts[tri[0]], dst_pts[tri[1]], dst_pts[tri[2]]], dtype=np.float32)
        affine_warp_triangle(roi, warped_roi, t_src, t_dst)
    feather = max(3, int(round(face_width * SOFT_MASK_BLUR_RATIO)))
    mask_rect = np.zeros((roi_h, roi_w), dtype=np.uint8)
    cv2.rectangle(mask_rect, (0,0), (roi_w-1, roi_h-1), 255, -1)
    mask_rect = cv2.GaussianBlur(mask_rect.astype(np.float32), (feather|1, feather|1), feather).astype(np.float32)/255.0
    mask_3c = cv2.merge([mask_rect, mask_rect, mask_rect])
    blended_roi = (warped_roi.astype(np.float32)*mask_3c + roi.astype(np.float32)*(1-mask_3c)).astype(np.uint8)
    out = img_bgr.copy(); out[y0:y1, x0:x1] = blended_roi
    lm_warped = landmarks.copy()
    tri_inv_list = []
    for tri in triangles:
        t_src = np.array([ctrl_pts[tri[0]], ctrl_pts[tri[1]], ctrl_pts[tri[2]]], dtype=np.float32)
        t_dst = np.array([dst_pts[tri[0]], dst_pts[tri[1]], dst_pts[tri[2]]], dtype=np.float32)
        try:
            M = cv2.getAffineTransform(t_dst, t_src)
            tri_inv_list.append((tri, M, t_dst))
        except Exception:
            continue
    for i in range(len(landmarks)):
        p = np.array([landmarks[i,0]-x0, landmarks[i,1]-y0])
        mapped = None
        for (tri, M, t_dst) in tri_inv_list:
            a = t_dst[0]; b = t_dst[1]; c = t_dst[2]
            mat = np.array([[b[0]-a[0], c[0]-a[0]],[b[1]-a[1], c[1]-a[1]]])
            try:
                inv = np.linalg.inv(mat)
            except np.linalg.LinAlgError:
                continue
            v = p - a
            bary = inv.dot(v)
            u, v2 = bary[0], bary[1]
            if u >= -0.001 and v2 >= -0.001 and (u+v2) <= 1.001:
                src_xy = cv2.transform(np.array([[[p[0], p[1]]]], dtype=np.float32), M)
                src_xy = src_xy[0,0]
                mapped = src_xy + np.array([x0, y0])
                break
        if mapped is None:
            dists = np.linalg.norm(dst_pts[:len(landmarks)] - (landmarks[i] - np.array([x0,y0])), axis=1)
            idx = np.argmin(dists)
            delta = dst_pts[idx] - ctrl_pts[idx]
            mapped = landmarks[i] - delta
        lm_warped[i] = mapped
    return out, lm_warped


def frequency_separation(img_bgr, skin_mask, face_width, blur_sigma_rel=GAUSSIAN_BLUR_SIGMA_REL, hf_att=HIGH_FREQ_ATTENUATION):
    sigma = max(0.5, blur_sigma_rel * face_width)
    img_f = img_bgr.astype(np.float32)
    low = cv2.GaussianBlur(img_f, (0,0), sigmaX=sigma, sigmaY=sigma)
    high = img_f - low
    mask_3c = cv2.merge([skin_mask, skin_mask, skin_mask]).astype(np.float32)
    combined_low = low * mask_3c + low * (1-mask_3c)
    high_adj = high * hf_att
    res = np.clip(combined_low + high_adj, 0, 255).astype(np.uint8)
    return res


def clahe_whiten(img_bgr, skin_mask, clip_limit=CLAHE_CLIP_LIMIT, tile_grid=CLAHE_TILE_GRID):
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
    L, A, B = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=tile_grid)
    L_clahe = clahe.apply(L)
    mask3 = cv2.merge([skin_mask, skin_mask, skin_mask]).astype(np.float32)
    lab_clahe = cv2.merge([L_clahe, A, B])
    img_clahe = cv2.cvtColor(lab_clahe, cv2.COLOR_LAB2BGR)
    blended = (img_clahe.astype(np.float32) * mask3 + img_bgr.astype(np.float32) * (1.0 - mask3)).astype(np.uint8)
    return blended


def enhance_eyes_lips(img_bgr, landmarks, face_width):
    out = img_bgr.copy()
    h, w = img_bgr.shape[:2]
    feather = max(1, int(round(face_width * 0.02)))
    def poly_mask_for(pts):
        m = np.zeros((h,w), dtype=np.uint8)
        cv2.fillConvexPoly(m, np.round(pts).astype(np.int32), 255)
        m = cv2.GaussianBlur(m.astype(np.float32), (feather*2+1, feather*2+1), feather)
        return (m/255.0).astype(np.float32)
    eye_groups = [landmarks[36:42], landmarks[42:48]]
    for eg in eye_groups:
        mask = poly_mask_for(eg)
        x,y,w_box,h_box = cv2.boundingRect(np.round(eg).astype(np.int32))
        pad = max(6, int(round(face_width*0.02)))
        x0 = max(0, x-pad); y0 = max(0, y-pad); x1 = min(img_bgr.shape[1], x+ w_box + pad); y1 = min(img_bgr.shape[0], y + h_box + pad)
        roi = out[y0:y1, x0:x1]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:,:,2] = np.clip(hsv[:,:,2]*EYE_BRIGHTNESS_SCALE + EYE_BRIGHTNESS_ADD, 0, 255)
        roi_br = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
        blur = cv2.GaussianBlur(roi_br, (0,0), 3)
        sharp = cv2.addWeighted(roi_br, EYE_SHARPEN_ALPHA, blur, EYE_SHARPEN_BETA, 0)
        local_mask = mask[y0:y1, x0:x1]
        local_mask_3 = cv2.merge([local_mask, local_mask, local_mask])
        out[y0:y1, x0:x1] = (sharp.astype(np.float32)*local_mask_3 + roi.astype(np.float32)*(1-local_mask_3)).astype(np.uint8)
    lips = landmarks[48:60]
    mask_lips = poly_mask_for(lips)
    x,y,w_box,h_box = cv2.boundingRect(np.round(lips).astype(np.int32))
    pad = max(4, int(round(face_width*0.015)))
    x0 = max(0, x-pad); y0 = max(0, y-pad); x1 = min(img_bgr.shape[1], x+ w_box + pad); y1 = min(img_bgr.shape[0], y + h_box + pad)
    roi = out[y0:y1, x0:x1]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:,:,1] = np.clip(hsv[:,:,1] * LIP_SATURATION_SCALE, 0, 255)
    hsv[:,:,2] = np.clip(hsv[:,:,2] * LIP_BRIGHTNESS_SCALE, 0, 255)
    roi_new = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    local_mask = mask_lips[y0:y1, x0:x1]
    local_mask_3 = cv2.merge([local_mask, local_mask, local_mask])
    out[y0:y1, x0:x1] = (roi_new.astype(np.float32)*local_mask_3 + roi.astype(np.float32)*(1-local_mask_3)).astype(np.uint8)
    return out


def process_image(input_path, output_path, save_intermediate=False):
    img_bgr = cv2.imread(input_path)
    if img_bgr is None:
        raise FileNotFoundError("无法读取输入图片: " + input_path)
    rect, landmarks = get_face_box_and_landmarks(img_bgr)
    if landmarks is None:
        raise RuntimeError("未检测到人脸或关键点")
    landmarks = landmarks.astype(np.float32)
    face_width = np.linalg.norm(landmarks[0] - landmarks[16])
    skin_mask = build_skin_mask(img_bgr, landmarks)
    spot_mask = detect_spot_mask(img_bgr, skin_mask, face_width)
    img_no_spot = inpaint_spots(img_bgr, spot_mask)
    img_slimmed, landmarks_warped = slim_face_local(img_no_spot, landmarks, FACE_SLIM_FACTOR)
    skin_mask2 = build_skin_mask(img_slimmed, landmarks_warped)
    img_smoothed = frequency_separation(img_slimmed, skin_mask2, face_width)
    img_clahe = clahe_whiten(img_smoothed, skin_mask2)
    img_enhanced = enhance_eyes_lips(img_clahe, landmarks_warped, face_width)
    mask3 = cv2.merge([skin_mask2, skin_mask2, skin_mask2]).astype(np.float32)
    final = (img_enhanced.astype(np.float32) * mask3 + img_slimmed.astype(np.float32) * (1.0 - mask3)).astype(np.uint8)
    cv2.imwrite(output_path, final)
    if save_intermediate:
        cv2.imwrite("debug_skin_mask.png", (skin_mask2*255).astype(np.uint8))
        cv2.imwrite("debug_spot_mask.png", spot_mask)
        cv2.imwrite("debug_no_spot.png", img_no_spot)
        cv2.imwrite("debug_slimmed.png", img_slimmed)
        cv2.imwrite("debug_smoothed.png", img_smoothed)
        cv2.imwrite("debug_clahe.png", img_clahe)
        cv2.imwrite("debug_enhanced.png", img_enhanced)
    print("处理完成，保存至:", output_path)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python face_beauty_fixed_full.py 输入.jpg 输出.jpg [save_intermediate(0/1)]")
        sys.exit(1)
    inp = sys.argv[1]; outp = sys.argv[2]
    save_dbg = False
    if len(sys.argv) >= 4 and sys.argv[3] in ("1", "true", "True"):
        save_dbg = True
    try:
        process_image(inp, outp, save_intermediate=save_dbg)
    except Exception as e:
        print("处理失败:", e)
        raise
