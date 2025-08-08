import numpy as np
import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity

# 1. 加载与预处理数据
ratings_dict = {
    'user_id': [1,1,1,2,2,3,3,4,4,5],
    'item_id': [1,2,3,1,3,2,4,2,3,4],
    'rating':  [5,3,4,4,2,2,5,5,3,4]
}
df = pd.DataFrame(ratings_dict)

# 构造用户-物品评分矩阵，并做用户中心化（可选）
ratings_matrix = df.pivot(index='user_id', columns='item_id', values='rating').fillna(0)
R = ratings_matrix.values
user_means = np.where(R.sum(axis=1)!=0, R.sum(axis=1) / (R!=0).sum(axis=1), 0)
R_centered = R - user_means.reshape(-1, 1)

# 2. 计算相似度矩阵
def compute_similarity(matrix, axis=1):
    """
    matrix: 输入矩阵
    axis=1 时计算行（用户）相似度，axis=0 时计算列（物品）相似度
    """
    if axis == 1:
        sim = cosine_similarity(matrix)
    else:
        sim = cosine_similarity(matrix.T)
    np.fill_diagonal(sim, 0)
    return sim

user_sim = compute_similarity(R_centered, axis=1)
item_sim = compute_similarity(R, axis=0)

# 3. 预测函数
def predict_user_based(R, sim, k=3, center=True):
    """
    基于用户的协同过滤预测
    R: 原始评分矩阵
    sim: 用户-用户相似度矩阵
    k: 选取最相似的 k 个用户
    center: 是否使用中心化矩阵（用户均值已去除）
    """
    R_use = R_centered if center else R
    pred = np.zeros(R.shape)
    for u in range(R.shape[0]):
        top_k = np.argsort(sim[u])[-k:]
        denom = np.abs(sim[u, top_k]).sum()
        for i in range(R.shape[1]):
            if R[u, i] == 0:
                numer = sim[u, top_k].dot(R_use[top_k, i])
                score = numer / denom if denom else 0
                pred[u, i] = score + (user_means[u] if center else 0)
    return pred

def predict_item_based(R, sim, k=3):
    """
    基于物品的协同过滤预测
    R: 原始评分矩阵
    sim: 物品-物品相似度矩阵
    k: 选取最相似的 k 个物品
    """
    pred = np.zeros(R.shape)
    for u in range(R.shape[0]):
        for i in range(R.shape[1]):
            if R[u, i] == 0:
                top_k = np.argsort(sim[i])[-k:]
                denom = np.abs(sim[i, top_k]).sum()
                numer = R[u, top_k].dot(sim[i, top_k])
                pred[u, i] = numer / denom if denom else 0
    return pred

# 4. 生成推荐列表
def get_recommendations(pred_matrix, user_index, n_items=5):
    """
    返回对 user_index 推荐评分最高的 n_items 个 item_id（从 1 开始）
    """
    scores = pred_matrix[user_index]
    rec_indices = np.argsort(scores)[-n_items:][::-1]
    return (rec_indices + 1).tolist()

# 5. 示例：为 user_id=1（索引 0）推荐2个物品
user_pred = predict_user_based(R, user_sim, k=2, center=True)
item_pred = predict_item_based(R, item_sim, k=2)

print("User-Based 推荐:", get_recommendations(user_pred, user_index=0, n_items=2))
print("Item-Based 推荐:", get_recommendations(item_pred, user_index=0, n_items=2))
