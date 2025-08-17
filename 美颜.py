import cv2
import dlib
import numpy as np
from scipy.spatial import Delaunay

# 初始化 dlib 人脸检测器和特征点预测器
face_detector = dlib.get_frontal_face_detector()
landmark_predictor = dlib.shape_predictor("shape_predictor_68_face_landmarks.dat")

# 读取输入图像并转换为灰度。灰度图用于人脸检测和特征点定位
input_image = cv2.imread("input.jpg")
gray_image = cv2.cvtColor(input_image, cv2.COLOR_BGR2GRAY)

# 检测人脸并提取第一个人脸区域的 68 个面部特征点
detected_faces = face_detector(gray_image, 1)
if len(detected_faces) == 0:
    print("未检测到人脸")
    exit()
face_rectangle = detected_faces[0]
landmark_shape = landmark_predictor(gray_image, face_rectangle)
face_landmarks = np.array([[point.x, point.y] for point in landmark_shape.parts()])

# 步骤一：磨皮（使用局部双边滤波平滑肤色）
# 构建面部掩码，只在脸部区域应用双边滤波
face_mask = np.zeros(input_image.shape[:2], dtype=np.uint8)
convex_hull_of_face = cv2.convexHull(face_landmarks)
cv2.fillConvexPoly(face_mask, convex_hull_of_face, 255)
# 对整张图做双边滤波，再与原图融合
bilateral_filtered_image = cv2.bilateralFilter(input_image, d=0, sigmaColor=75, sigmaSpace=75)
smoothed_image = input_image.copy()
smoothed_image[face_mask == 255] = bilateral_filtered_image[face_mask == 255]

# 步骤二：祛斑（检测暗斑并使用图像修复消除）
# 转为 HSV 空间，获得亮度通道用于斑点检测
hsv_image = cv2.cvtColor(smoothed_image, cv2.COLOR_BGR2HSV)
value_channel = hsv_image[:, :, 2]
# Otsu 二值化找到暗斑区域，并限制在脸部范围内
_, dark_spot_mask = cv2.threshold(value_channel, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
dark_spot_mask = cv2.bitwise_and(dark_spot_mask, dark_spot_mask, mask=face_mask)
# 使用 Telea 算法修复斑点
inpainted_image = cv2.inpaint(smoothed_image, dark_spot_mask, inpaintRadius=3, flags=cv2.INPAINT_TELEA)

# 步骤三：美白（在 LAB 颜色空间提升亮度对比度）
# 转到 LAB 空间，分离 L 通道做 CLAHE 对比度限幅自适应直方图均衡
lab_image = cv2.cvtColor(inpainted_image, cv2.COLOR_BGR2LAB)
l_channel, a_channel, b_channel = cv2.split(lab_image)
clahe_operator = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
l_channel_enhanced = clahe_operator.apply(l_channel)
# 合并通道并转换回 BGR
lab_image_enhanced = cv2.merge((l_channel_enhanced, a_channel, b_channel))
whitened_image = cv2.cvtColor(lab_image_enhanced, cv2.COLOR_LAB2BGR)

# 步骤四：瘦脸（基于 Delaunay 三角形网格做仿射变形）
# 四点：面部关键点内移，细化轮廓
left_cheek_point = face_landmarks[2]   # 左侧颧骨点
right_cheek_point = face_landmarks[14] # 右侧颧骨点
face_midline_x = (left_cheek_point[0] + right_cheek_point[0]) // 2
new_face_landmarks = face_landmarks.copy()
slimming_strength = 0.15                # 瘦脸力度
for landmark_index in range(3, 14):
    horizontal_offset = face_landmarks[landmark_index][0] - face_midline_x
    # 向中线方向移动设定比例
    new_face_landmarks[landmark_index][0] = int(face_midline_x + horizontal_offset * (1 - slimming_strength))

# 构建 Delaunay 三角网，确保每个三角形顶点都对应到 68 点索引
image_rectangle = (0, 0, input_image.shape[1], input_image.shape[0])
subdivision = cv2.Subdiv2D(image_rectangle)
for point in face_landmarks:
    subdivision.insert((int(point[0]), int(point[1])))
raw_triangle_list = subdivision.getTriangleList().astype(np.int32)

triangle_indices = []
for triangle in raw_triangle_list:
    triangle_vertices = [(triangle[0], triangle[1]), (triangle[2], triangle[3]), (triangle[4], triangle[5])]
    vertex_indices = []
    # 匹配三角形顶点到特征点索引
    for vertex in triangle_vertices:
        for index, landmark_point in enumerate(face_landmarks):
            if abs(vertex[0] - landmark_point[0]) < 1 and abs(vertex[1] - landmark_point[1]) < 1:
                vertex_indices.append(index)
    if len(vertex_indices) == 3:
        triangle_indices.append(vertex_indices)

# 对每个三角形区域做仿射变换，将原三角贴到新三角位置
output_image = whitened_image.copy()
for indices in triangle_indices:
    source_triangle = [face_landmarks[i] for i in indices]
    destination_triangle = [new_face_landmarks[i] for i in indices]

    # 计算源三角和目标三角的边界矩形
    bounding_rect_source = cv2.boundingRect(np.float32([source_triangle]))
    bounding_rect_destination = cv2.boundingRect(np.float32([destination_triangle]))

    # 计算相对偏移，用于仿射矩阵计算
    source_triangle_offset = [(pt[0] - bounding_rect_source[0], pt[1] - bounding_rect_source[1]) for pt in source_triangle]
    destination_triangle_offset = [(pt[0] - bounding_rect_destination[0], pt[1] - bounding_rect_destination[1]) for pt in destination_triangle]

    # 从输出图像中裁剪源区域并应用仿射变换
    region_of_interest = output_image[bounding_rect_source[1]:bounding_rect_source[1] + bounding_rect_source[3],
                                      bounding_rect_source[0]:bounding_rect_source[0] + bounding_rect_source[2]]
    affine_transformation_matrix = cv2.getAffineTransform(np.float32(source_triangle_offset), np.float32(destination_triangle_offset))
    warped_region = cv2.warpAffine(region_of_interest, affine_transformation_matrix,
                                   (bounding_rect_destination[2], bounding_rect_destination[3]),
                                   flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)

    # 构建三角形遮罩，将变形区域融合回原图
    triangle_mask = np.zeros((bounding_rect_destination[3], bounding_rect_destination[2], 3), dtype=np.uint8)
    cv2.fillConvexPoly(triangle_mask, np.int32(destination_triangle_offset), (1, 1, 1), 16, 0)

    # 在目标位置合成变形结果
    output_slice = output_image[bounding_rect_destination[1]:bounding_rect_destination[1] + bounding_rect_destination[3],
                               bounding_rect_destination[0]:bounding_rect_destination[0] + bounding_rect_destination[2]]
    output_image[bounding_rect_destination[1]:bounding_rect_destination[1] + bounding_rect_destination[3],
                 bounding_rect_destination[0]:bounding_rect_destination[0] + bounding_rect_destination[2]] = \
        output_slice * (1 - triangle_mask) + warped_region * triangle_mask

# 保存并输出最终结果
cv2.imwrite("output.jpg", output_image)
