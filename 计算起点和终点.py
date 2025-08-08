from transformers import AutoTokenizer, AutoModelForQuestionAnswering
import torch

# 模型和分词器配置
MODEL_NAME = "deepset/roberta-base-squad2"
WINDOW_SIZE = 512          # 窗口大小（包括 question + special tokens）
OVERLAP = 50               # 相邻窗口之间的重叠长度
MAX_ANSWER_LEN = 50        # 最大答案长度（token数）

# 一次性加载分词器和模型
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
model = AutoModelForQuestionAnswering.from_pretrained(MODEL_NAME).eval()

def split_into_windows(question: str,
                       text: str,
                       window_size: int,
                       overlap: int):
    """
    将长文本按照滑动窗口切分，并在每个窗口前加上 question。

    返回列表：[(input_ids, window_offset), ...]
    window_offset 用于标记该窗口在原始文本中的起始位置（token 级）。
    """
    # 不带 special tokens 的 question 和 context 编码
    q_ids = tokenizer.encode(question, add_special_tokens=False)
    t_ids = tokenizer.encode(text, add_special_tokens=False)

    # 留出 [CLS], question, [SEP], ... , [SEP] 的位置
    max_ctx = window_size - len(q_ids) - 3

    windows = []
    start = 0
    while start < len(t_ids):
        end = min(start + max_ctx, len(t_ids))
        # 构造一个完整输入：[CLS] q_ids [SEP] t_ids[start:end] [SEP]
        window_ids = (
            [tokenizer.cls_token_id]
            + q_ids
            + [tokenizer.sep_token_id]
            + t_ids[start:end]
            + [tokenizer.sep_token_id]
        )
        windows.append((window_ids, start))
        if end == len(t_ids):
            break
        # 下一窗口起始：当前窗口末尾 - overlap
        start += max_ctx - overlap

    return windows

def find_best_answer(question: str,
                     context: str,
                     window_size: int = WINDOW_SIZE,
                     overlap: int = OVERLAP,
                     max_answer_len: int = MAX_ANSWER_LEN):
    """
    对每个窗口做推理，计算 start 和 end 的 logits，
    最后选取得分最高的答案，并返回答案文本及其在原文中的位置。
    返回：{
      "answer_text": str,
      "start_token": int,
      "end_token": int
    }
    """
    windows = split_into_windows(question, context, window_size, overlap)

    best_score = float("-inf")
    best_answer = {"answer_text": "", "start_token": None, "end_token": None}

    for window_ids, offset in windows:
        input_ids = torch.tensor([window_ids])
        attention_mask = torch.ones_like(input_ids)

        with torch.no_grad():
            outputs = model(input_ids, attention_mask=attention_mask)

        start_logits = outputs.start_logits[0]
        end_logits = outputs.end_logits[0]

        # 取前5个最可能的起始和结束位置
        top_starts = torch.topk(start_logits, k=5).indices.tolist()
        top_ends = torch.topk(end_logits, k=5).indices.tolist()

        for s in top_starts:
            for e in top_ends:
                # 保证合法 span 且长度不超过 max_answer_len
                if s <= e and (e - s) < max_answer_len:
                    score = start_logits[s].item() + end_logits[e].item()
                    if score > best_score:
                        best_score = score
                        # 解码当前 window 内的答案
                        ans_ids = window_ids[s : e + 1]
                        text = tokenizer.decode(ans_ids, skip_special_tokens=True)
                        # 计算在原始 context 中的 token 位置
                        # 减去 [CLS] + question + [SEP] 这部分的长度
                        question_part_len = len(tokenizer.encode(question, add_special_tokens=True))
                        start_in_ctx = offset + (s - question_part_len)
                        end_in_ctx = offset + (e - question_part_len)
                        best_answer = {
                            "answer_text": text,
                            "start_token": start_in_ctx,
                            "end_token": end_in_ctx
                        }

    return best_answer

if __name__ == "__main__":
    question = "What is the main purpose of the text?"
    context = "（这里替换成你的长文本）"
    result = find_best_answer(question, context)
    print("Answer:", result["answer_text"])
    print("Start token index:", result["start_token"])
    print("End token index:", result["end_token"])
