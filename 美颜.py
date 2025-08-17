# 预设参数配置  
beauty_parameters = {  
    "input_image_path": "input.jpg",            # 输入图像文件  
    "output_image_path": "output.jpg",          # 输出图像文件  
    "shape_model_path": "shape_predictor_68_face_landmarks.dat",  # dlib 特征点模型  
    "smoothing_sigma_color": 80.0,              # 磨皮 双边滤波 sigmaColor  
    "smoothing_sigma_space": 80.0,              # 磨皮 双边滤波 sigmaSpace  
    "inpaint_radius": 4,                        # 祛斑 修复半径  
    "clahe_clip_limit": 2.5,                    # 美白 CLAHE clipLimit  
    "clahe_tile_grid_size": 8,                  # 美白 CLAHE tileGridSize  
    "slimming_strength": 0.18,                  # 瘦脸 力度 [0,1]  
    "lifting_strength": 0.12                    # 提拉 力度 [0,1]  
}  
  
import cv2  
import dlib  
import numpy as np  
  
# 人脸检测与特征点提取  
face_detector = dlib.get_frontal_face_detector()  
landmark_predictor = dlib.shape_predictor(beauty_parameters["shape_model_path"])  
  
def skin_smoothing(input_image, face_landmarks, sigma_color, sigma_space):  
    # 构建脸部掩码，只平滑脸部区域  
    mask_face = np.zeros(input_image.shape[:2], dtype=np.uint8)  
    hull = cv2.convexHull(face_landmarks)  
    cv2.fillConvexPoly(mask_face, hull, 255)  
    # 双边滤波融合  
    filtered = cv2.bilateralFilter(input_image, d=0, sigmaColor=sigma_color, sigmaSpace=sigma_space)  
    smoothed = input_image.copy()  
    smoothed[mask_face == 255] = filtered[mask_face == 255]  
    return smoothed  
  
def spot_removal(input_image, face_landmarks, inpaint_radius):  
    # 构建脸部掩码用于限制祛斑区域  
    mask_face = np.zeros(input_image.shape[:2], dtype=np.uint8)  
    hull = cv2.convexHull(face_landmarks)  
    cv2.fillConvexPoly(mask_face, hull, 255)  
    # 转 HSV 提取亮度通道检测暗斑  
    hsv = cv2.cvtColor(input_image, cv2.COLOR_BGR2HSV)  
    value_channel = hsv[:, :, 2]  
    _, mask_spots = cv2.threshold(value_channel, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)  
    mask_spots = cv2.bitwise_and(mask_spots, mask_spots, mask=mask_face)  
    # Telea 修复  
    inpainted = cv2.inpaint(input_image, mask_spots, inpaintRadius=inpaint_radius, flags=cv2.INPAINT_TELEA)  
    return inpainted  
  
def skin_whitening(input_image, clip_limit, tile_grid_size):  
    # LAB 空间 CLAHE 增强 L 通道  
    lab = cv2.cvtColor(input_image, cv2.COLOR_BGR2LAB)  
    l, a, b = cv2.split(lab)  
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(tile_grid_size, tile_grid_size))  
    l_enhanced = clahe.apply(l)  
    lab_enhanced = cv2.merge((l_enhanced, a, b))  
    whitened = cv2.cvtColor(lab_enhanced, cv2.COLOR_LAB2BGR)  
    return whitened  
  
def face_slim_and_lift(input_image, face_landmarks, slim_strength, lift_strength):  
    # 计算水平中线与垂直中线坐标  
    left_cheek = face_landmarks[2]  
    right_cheek = face_landmarks[14]  
    mid_x = (left_cheek[0] + right_cheek[0]) // 2  
    chin = face_landmarks[8]  
    forehead = face_landmarks[27]  
    mid_y = (chin[1] + forehead[1]) // 2  
    # 复制特征点并应用瘦脸和提拉偏移  
    new_landmarks = face_landmarks.copy()  
    for i in range(3, 14):  # 瘦脸：脸颊点向中线移动  
        dx = face_landmarks[i][0] - mid_x  
        new_landmarks[i][0] = int(mid_x + dx * (1 - slim_strength))  
    for i in range(5, 12):  # 提拉：下半脸点向上移动  
        dy = face_landmarks[i][1] - mid_y  
        new_landmarks[i][1] = int(face_landmarks[i][1] - dy * lift_strength)  
    # Delaunay 三角形划分并仿射变形  
    h, w = input_image.shape[:2]  
    subdiv = cv2.Subdiv2D((0, 0, w, h))  
    for pt in face_landmarks: subdiv.insert((int(pt[0]), int(pt[1])))  
    triangle_list = subdiv.getTriangleList().astype(np.int32)  
    triangle_indices = []  
    for tri in triangle_list:  
        verts = [(tri[0],tri[1]),(tri[2],tri[3]),(tri[4],tri[5])]  
        idxs = []  
        for vx, vy in verts:  
            for j, lm in enumerate(face_landmarks):  
                if abs(vx-lm[0])<1 and abs(vy-lm[1])<1: idxs.append(j)  
        if len(idxs)==3: triangle_indices.append(idxs)  
    output = input_image.copy()  
    for idxs in triangle_indices:  
        src_tri = [face_landmarks[i] for i in idxs]  
        dst_tri = [new_landmarks[i] for i in idxs]  
        r_src = cv2.boundingRect(np.float32([src_tri]))  
        r_dst = cv2.boundingRect(np.float32([dst_tri]))  
        src_offset = [(p[0]-r_src[0],p[1]-r_src[1]) for p in src_tri]  
        dst_offset = [(p[0]-r_dst[0],p[1]-r_dst[1]) for p in dst_tri]  
        roi = output[r_src[1]:r_src[1]+r_src[3], r_src[0]:r_src[0]+r_src[2]]  
        mat_affine = cv2.getAffineTransform(np.float32(src_offset), np.float32(dst_offset))  
        warped = cv2.warpAffine(roi, mat_affine, (r_dst[2], r_dst[3]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)  
        mask_tri = np.zeros((r_dst[3], r_dst[2], 3), dtype=np.uint8)  
        cv2.fillConvexPoly(mask_tri, np.int32(dst_offset), (1,1,1), 0)  
        dst_region = output[r_dst[1]:r_dst[1]+r_dst[3], r_dst[0]:r_dst[0]+r_dst[2]]  
        output[r_dst[1]:r_dst[1]+r_dst[3], r_dst[0]:r_dst[0]+r_dst[2]] = dst_region*(1-mask_tri)+warped*mask_tri  
    return output  
  
# 主流程执行（按预设参数）  
# 1. 读取图像并检测关键点  
original_image = cv2.imread(beauty_parameters["input_image_path"])  
gray_image = cv2.cvtColor(original_image, cv2.COLOR_BGR2GRAY)  
faces = face_detector(gray_image, 1)  
if not faces:  
    print("未检测到人脸，程序退出")  
    exit()  
shape = landmark_predictor(gray_image, faces[0])  
landmarks_array = np.array([[pt.x, pt.y] for pt in shape.parts()])  
  
# 2. 磨皮  
smoothed_image = skin_smoothing(  
    original_image,  
    landmarks_array,  
    beauty_parameters["smoothing_sigma_color"],  
    beauty_parameters["smoothing_sigma_space"]  
)  
  
# 3. 祛斑  
unspotted_image = spot_removal(  
    smoothed_image,  
    landmarks_array,  
    beauty_parameters["inpaint_radius"]  
)  
  
# 4. 美白  
whitened_image = skin_whitening(  
    unspotted_image,  
    beauty_parameters["clahe_clip_limit"],  
    beauty_parameters["clahe_tile_grid_size"]  
)  
  
# 5. 瘦脸与提拉  
final_image = face_slim_and_lift(  
    whitened_image,  
    landmarks_array,  
    beauty_parameters["slimming_strength"],  
    beauty_parameters["lifting_strength"]  
)  
  
# 6. 保存结果  
cv2.imwrite(beauty_parameters["output_image_path"], final_image)  
print("美颜处理完成，结果已保存：", beauty_parameters["output_image_path"])
