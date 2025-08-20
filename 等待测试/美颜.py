import cv2
import dlib
import numpy as np

# ----- 参数配置 -----
LANDMARK_MODEL = "shape_predictor_68_face_landmarks.dat"  # dlib模型路径

# 瘦脸强度，正数收紧脸部，两边一起调整，范围0-0.5较安全
FACE_SLIM_FACTOR = 0.3

# 磨皮相关参数，高斯模糊sigma，sigma越大磨皮越明显
GAUSSIAN_BLUR_SIGMA = 15

# CLAHE参数
CLAHE_CLIP_LIMIT = 3.0
CLAHE_TILE_GRID_SIZE = (8, 8)

# 斑点检测，亮度差阈值（越小越敏感）
SPOT_THRESHOLD = 20

# 眼唇增强参数
EYE_BRIGHTNESS_SCALE = 1.07
EYE_BRIGHTNESS_ADD = 5
EYE_SHARPEN_ALPHA = 1.2
EYE_SHARPEN_BETA = -0.2
LIP_SATURATION_SCALE = 1.12
LIP_BRIGHTNESS_SCALE = 1.03

# ----- 初始化 dlib 人脸检测和关键点预测 -----
detector = dlib.get_frontal_face_detector()
predictor = dlib.shape_predictor(LANDMARK_MODEL)


# ----- 工具：将dlib关键点转换为numpy数组 -----
def landmarks_to_np(shape):
    coords = np.zeros((68, 2), dtype=np.int32)
    for i in range(68):
        coords[i] = (shape.part(i).x, shape.part(i).y)
    return coords


# ----- 生成皮肤掩码 -----
def generate_skin_mask(image_shape, landmarks):
    h, w = image_shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)

    # 使用全部脸部点生成脸部凸包
    hull = cv2.convexHull(landmarks)
    cv2.fillConvexPoly(mask, hull, 255)

    # 非皮肤区域：眼睛(36-41, 42-47), 眉毛(17-21, 22-26), 嘴巴(48-59), 鼻子(27-35)
    exclude_regions = [
        landmarks[36:42], landmarks[42:48],
        landmarks[17:22], landmarks[22:27],
        landmarks[48:60], landmarks[27:36]
    ]

    for region in exclude_regions:
        hull_sub = cv2.convexHull(region)
        cv2.fillConvexPoly(mask, hull_sub, 0)

    # 膨胀非皮肤区为保护边缘，用椭圆核
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    non_skin = cv2.bitwise_not(mask)
    non_skin = cv2.dilate(non_skin, kernel, iterations=1)
    mask = cv2.bitwise_not(non_skin)

    # 高斯模糊边缘使过渡自然
    mask = cv2.GaussianBlur(mask.astype(np.float32), (21, 21), 0)
    mask = np.where(mask > 40, 255, 0).astype(np.uint8)

    return mask


# ----- 简易斑点检测掩码 -----
def generate_spot_mask(image_bgr, skin_mask):
    # Lab色彩空间
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)
    L = lab[:, :, 0]

    # 计算皮肤区亮度中值
    skin_l_vals = L[skin_mask == 255]
    if skin_l_vals.size == 0:
        return np.zeros_like(skin_mask)

    median_l = np.median(skin_l_vals)
    diff = median_l - L.astype(np.float32)

    # 差异大于阈值认为是斑点
    spot_mask = np.where((diff > SPOT_THRESHOLD) & (skin_mask == 255), 255, 0).astype(np.uint8)

    # 膨胀小面积方便修补
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    spot_mask = cv2.dilate(spot_mask, kernel, iterations=1)

    return spot_mask


# ----- 斑点区域 inpaint 修复 -----
def inpaint_spots(image_bgr, spot_mask):
    return cv2.inpaint(image_bgr, spot_mask, inpaintRadius=3, flags=cv2.INPAINT_TELEA)


# ----- 多点瘦脸变形 -----
def slim_face(image_bgr, landmarks, factor):
    h, w = image_bgr.shape[:2]

    # 控制点构造，添加9网格基础点 + 6脸颊关键点
    base_points = np.array([
        [0, 0], [w // 2, 0], [w - 1, 0],
        [0, h // 2], [w // 2, h // 2], [w - 1, h // 2],
        [0, h - 1], [w // 2, h - 1], [w - 1, h - 1]
    ], dtype=np.float32)

    cheek_indices = [2, 3, 4, 12, 13, 14]
    cheek_points = landmarks[cheek_indices].astype(np.float32)

    src_points = np.vstack((base_points, cheek_points))

    # 计算脸宽和脸中心x坐标
    face_left = landmarks[0]
    face_right = landmarks[16]
    center_x = (face_left[0] + face_right[0]) / 2
    face_width = np.linalg.norm(face_right - face_left)

    # 计算脸颊点x方向挤压距离
    move_dist = factor * face_width * 0.08

    dst_points = src_points.copy()

    # 脸颊点向脸中心移动
    for i in range(len(base_points), len(dst_points)):
        x, y = dst_points[i]
        if x < center_x:
            dst_points[i][0] = x + abs(move_dist)  # 左脸颊向右
        else:
            dst_points[i][0] = x - abs(move_dist)  # 右脸颊向左

    # 使用PiecewiseAffineTransform做网格仿射变形
    try:
        import skimage.transform as sktf
    except ImportError:
        raise ImportError("请安装skimage模块：pip install scikit-image")

    tform = sktf.PiecewiseAffineTransform()
    success = tform.estimate(src_points, dst_points)

    if not success:
        print("[警告] 瘦脸变形失败，返回原图")
        return image_bgr

    warped = sktf.warp(image_bgr, tform, output_shape=(h, w))
    warped = (warped * 255).astype(np.uint8)

    return warped


# ----- 频率分离磨皮 -----
def frequency_separation(image_bgr, skin_mask, blur_sigma):
    img_float = image_bgr.astype(np.float32)

    # 低频层用高斯模糊实现
    low_freq = cv2.GaussianBlur(img_float, (0, 0), sigmaX=blur_sigma, sigmaY=blur_sigma)

    # 高频层是原图减低频层细节
    high_freq = img_float - low_freq

    # 融合层，低频用磨皮图，非皮肤区用原图低频
    mask_3c = cv2.merge([skin_mask / 255.0] * 3)

    # 低频层磨皮：这里就是低频层，已经高斯平滑
    combined_low = low_freq * mask_3c + img_float * (1 - mask_3c)

    # 叠加高频细节，保留皮肤细节
    result = combined_low + high_freq

    # 裁剪范围，转换uint8
    result = np.clip(result, 0, 255).astype(np.uint8)

    return result


# ----- CLAHE美白（在皮肤区域） -----
def clahe_whitening(image_bgr, skin_mask, clip_limit, tile_grid):
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)
    L, A, B = cv2.split(lab)

    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=tile_grid)
    L_new = L.copy()

    # 仅对皮肤区L通道做CLAHE增强
    skin_inds = np.where(skin_mask == 255)
    if skin_inds[0].size > 0:
        L_skin = L[skin_inds]
        L_skin_enhanced = clahe.apply(L_skin)
        L_new[skin_inds] = L_skin_enhanced

    lab_new = cv2.merge([L_new, A, B])
    result = cv2.cvtColor(lab_new, cv2.COLOR_LAB2BGR)

    return result


# ----- 眼睛嘴唇细节增强 -----
def enhance_eyes_lips(image_bgr, landmarks):
    result = image_bgr.copy()

    # 眼睛区域（36-41, 42-47）
    eye_regions = [landmarks[36:42], landmarks[42:48]]

    for region in eye_regions:
        x, y, w, h = cv2.boundingRect(region)
        pad = 6
        x0 = max(x - pad, 0)
        y0 = max(y - pad, 0)
        x1 = min(x + w + pad, image_bgr.shape[1])
        y1 = min(y + h + pad, image_bgr.shape[0])

        roi = result[y0:y1, x0:x1]

        # 转HSV，调整亮度
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 2] = np.clip(hsv[:, :, 2] * EYE_BRIGHTNESS_SCALE + EYE_BRIGHTNESS_ADD, 0, 255)

        roi_br = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

        # 锐化，增强眼部细节
        blur = cv2.GaussianBlur(roi_br, (0, 0), 3)
        sharp = cv2.addWeighted(roi_br, EYE_SHARPEN_ALPHA, blur, EYE_SHARPEN_BETA, 0)

        result[y0:y1, x0:x1] = sharp

    # 嘴唇区域（48-59）
    lips = landmarks[48:60]
    x, y, w, h = cv2.boundingRect(lips)
    pad = 4
    x0 = max(x - pad, 0)
    y0 = max(y - pad, 0)
    x1 = min(x + w + pad, image_bgr.shape[1])
    y1 = min(y + h + pad, image_bgr.shape[0])

    roi = result[y0:y1, x0:x1]

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV).astype(np.float32)

    # 增加饱和度和亮度
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * LIP_SATURATION_SCALE, 0, 255)
    hsv[:, :, 2] = np.clip(hsv[:, :, 2] * LIP_BRIGHTNESS_SCALE, 0, 255)

    result[y0:y1, x0:x1] = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    return result


# ----- 主处理函数 -----
def process_image(input_path, output_path):
    # 读取图像
    image_bgr = cv2.imread(input_path)
    if image_bgr is None:
        raise FileNotFoundError(f"图片文件读取失败: {input_path}")

    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)

    # 人脸检测
    faces = detector(image_rgb, 1)
    if len(faces) == 0:
        raise RuntimeError("未检测到人脸")

    # 目前只处理第一张人脸
    face = faces[0]

    # 关键点检测
    shape = predictor(image_rgb, face)
    landmarks = landmarks_to_np(shape)

    # 生成皮肤掩码
    skin_mask = generate_skin_mask(image_bgr.shape, landmarks)

    # 生成斑点掩码并修复瑕疵
    spot_mask = generate_spot_mask(image_bgr, skin_mask)
    img_no_spot = inpaint_spots(image_bgr, spot_mask)

    # 瘦脸
    img_slimmed = slim_face(img_no_spot, landmarks, FACE_SLIM_FACTOR)

    # 频率分离磨皮
    img_smoothed = frequency_separation(img_slimmed, skin_mask, GAUSSIAN_BLUR_SIGMA)

    # CLAHE美白
    img_whitened = clahe_whitening(img_smoothed, skin_mask, CLAHE_CLIP_LIMIT, CLAHE_TILE_GRID_SIZE)

    # 眼睛嘴唇细节增强
    img_enhanced = enhance_eyes_lips(img_whitened, landmarks)

    # 融合：脸部皮肤区域用增强图，其它区域用原图（斑点去除后瘦脸磨皮图）
    mask_3c = cv2.merge([skin_mask, skin_mask, skin_mask])
    mask_inv = cv2.bitwise_not(mask_3c)
    bg = cv2.bitwise_and(img_no_spot, mask_inv)
    fg = cv2.bitwise_and(img_enhanced, mask_3c)
    final_img = cv2.add(bg, fg)

    # 保存结果
    cv2.imwrite(output_path, final_img)
    print(f"处理完成，保存至: {output_path}")


# ---------- 运行入口 ----------
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("用法: python face_beauty.py 输入图片路径 输出图片路径")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]

    try:
        process_image(input_file, output_file)
    except Exception as e:
        print(f"处理失败: {e}")
        sys.exit(1)
