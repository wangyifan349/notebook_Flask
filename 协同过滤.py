import numpy as np  # 导入NumPy库
import pandas as pd  # 导入Pandas库
from sklearn.metrics.pairwise import cosine_similarity  # 导入余弦相似度计算函数

# 假设我们有一个用户-商品评分矩阵
data = {
    '用户1': [5, 4, 0, 0, 2],  # 用户1对商品的评分
    '用户2': [0, 0, 4, 5, 0],  # 用户2对商品的评分
    '用户3': [3, 0, 0, 4, 0],  # 用户3对商品的评分
    '用户4': [0, 2, 5, 0, 0],  # 用户4对商品的评分
    '用户5': [1, 0, 0, 0, 3]   # 用户5对商品的评分
}

# 创建 DataFrame，构建用户-商品评分矩阵
ratings = pd.DataFrame(data, index=['商品1', '商品2', '商品3', '商品4', '商品5'])

# 计算用户之间的相似度（基于用户的协同过滤）
user_similarity = cosine_similarity(ratings.fillna(0))  # 计算用户相似度
user_similarity_df = pd.DataFrame(user_similarity, index=ratings.columns, columns=ratings.columns)  # 转换为DataFrame

# 推送商品的函数（基于用户的协同过滤）
def recommend_items_user_based(user, ratings, user_similarity_df, n_recommendations=2):
    similar_users = user_similarity_df[user].sort_values(ascending=False).index[1:]  # 获取与目标用户相似的用户，排除自己
    recommendations = pd.Series()  # 初始化推荐商品的Series

    for similar_user in similar_users:  # 遍历相似用户
        similar_user_ratings = ratings[similar_user]  # 获取相似用户的评分
        recommendations = recommendations.append(similar_user_ratings[similar_user_ratings > 0])  # 收集相似用户评分的商品

    recommendations = recommendations.groupby(recommendations.index).mean()  # 计算推荐商品的平均评分
    recommendations = recommendations[~recommendations.index.isin(ratings[user].dropna().index)]  # 排除目标用户已评分的商品
    return recommendations.nlargest(n_recommendations)  # 返回前n个推荐商品

# 计算商品之间的相似度（基于商品的协同过滤）
item_similarity = cosine_similarity(ratings.T.fillna(0))  # 计算商品相似度
item_similarity_df = pd.DataFrame(item_similarity, index=ratings.columns, columns=ratings.columns)  # 转换为DataFrame

# 推送商品的函数（基于商品的协同过滤）
def recommend_items_item_based(user, ratings, item_similarity_df, n_recommendations=2):
    user_ratings = ratings[user]  # 获取用户的评分
    recommendations = pd.Series()  # 初始化推荐商品的Series

    for item in user_ratings[user_ratings > 0].index:  # 遍历用户评分的商品
        similar_items = item_similarity_df[item]  # 获取与该商品相似的商品
        recommendations = recommendations.append(similar_items * user_ratings[item])  # 加权收集相似商品

    recommendations = recommendations.groupby(recommendations.index).sum()  # 计算推荐商品的总评分
    recommendations = recommendations[~recommendations.index.isin(user_ratings.dropna().index)]  # 排除用户已评分的商品
    return recommendations.nlargest(n_recommendations)  # 返回前n个推荐商品

# 示例：为用户1推荐商品
recommended_items_user_based = recommend_items_user_based('用户1', ratings, user_similarity_df)  # 基于用户的推荐
print("为用户1推荐的商品（基于用户的协同过滤）：")
print(recommended_items_user_based)  # 打印推荐结果

recommended_items_item_based = recommend_items_item_based('用户1', ratings, item_similarity_df)  # 基于商品的推荐
print("为用户1推荐的商品（基于商品的协同过滤）：")
print(recommended_items_item_based)  # 打印推荐结果
