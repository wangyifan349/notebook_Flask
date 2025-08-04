import torch
import torch.nn.functional as F
from transformers import AutoTokenizer, AutoModelForQuestionAnswering
class LongContextQA:
    def __init__(self, model_name="bert-large-uncased-whole-word-masking-finetuned-squad",
                 max_length=384, doc_stride=128, max_answer_len=30, device=None):
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForQuestionAnswering.from_pretrained(model_name)
        self.model.eval()
        if device is None:
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = device
        self.model.to(self.device)
        self.max_length = max_length
        self.doc_stride = doc_stride
        self.max_answer_len = max_answer_len
    def answer_question_long(self, question, context, top_n=5):
        encodings = self.tokenizer(
            [question],
            [context],
            max_length=self.max_length,
            truncation="only_second",
            stride=self.doc_stride,
            return_overflowing_tokens=True,
            return_offsets_mapping=True,
            padding="max_length",
            return_tensors="pt"
        )
        all_candidates = []
        for i in range(len(encodings["input_ids"])):
            input_ids = encodings["input_ids"][i].to(self.device).unsqueeze(0)
            token_type_ids = encodings["token_type_ids"][i].to(self.device).unsqueeze(0)
            offset_mapping = encodings["offset_mapping"][i]
            token_type = token_type_ids.squeeze().tolist()
            with torch.no_grad():
                outputs = self.model(input_ids=input_ids, token_type_ids=token_type_ids)
                start_logits = outputs.start_logits[0]  # shape (seq_len,)
                end_logits = outputs.end_logits[0]      # shape (seq_len,)
                # 计算位置概率分布，方便查看置信度
                start_probs = F.softmax(start_logits, dim=0)
                end_probs = F.softmax(end_logits, dim=0)
            # 只考虑上下文部分的token（token_type==1）
            context_indexes = [idx for idx, t in enumerate(token_type) if t == 1]
            for start_idx in context_indexes:
                for end_idx in context_indexes:
                    if end_idx < start_idx or (end_idx - start_idx + 1) > self.max_answer_len:
                        continue
                    start_char = offset_mapping[start_idx][0].item()
                    end_char = offset_mapping[end_idx][1].item()
                    if start_char == 0 and end_char == 0:
                        continue
                    if start_char >= end_char:
                        continue
                    answer_text = context[start_char:end_char]
                    if answer_text.strip() == "":
                        continue
                    # 综合分数
                    score = start_logits[start_idx].item() + end_logits[end_idx].item()
                    # 起止概率
                    start_prob = start_probs[start_idx].item()
                    end_prob = end_probs[end_idx].item()
                    all_candidates.append({
                        "answer": answer_text,
                        "score": score,
                        "start_char": start_char,
                        "end_char": end_char,
                        "start_logit": start_logits[start_idx].item(),
                        "end_logit": end_logits[end_idx].item(),
                        "start_prob": start_prob,
                        "end_prob": end_prob,
                    })
        if not all_candidates:
            return []
        # 按综合分数排序，选top_n
        all_candidates = sorted(all_candidates, key=lambda x: x["score"], reverse=True)[:top_n]
        return all_candidates
if __name__ == "__main__":
    qa = LongContextQA()
    while True:
        context = input("\n请输入上下文（输入exit退出）：\n")
        if context.strip().lower() == "exit":
            break
        question = input("\n请输入问题（输入exit退出）：\n")
        if question.strip().lower() == "exit":
            break
        answers = qa.answer_question_long(question, context, top_n=5)
        if not answers:
            print("未找到有效答案。")
            continue
        print("\n=== Top 预测答案列表 ===")
        for i, ans in enumerate(answers):
            print(f"[{i+1}] 答案文本: {ans['answer']!r}")
            print(f"    起始字符: {ans['start_char']}, 结束字符: {ans['end_char']}")
            print(f"    起始logit: {ans['start_logit']:.3f}, 结束logit: {ans['end_logit']:.3f}")
            print(f"    起始概率: {ans['start_prob']:.5f}, 结束概率: {ans['end_prob']:.5f}")
            print(f"    综合得分: {ans['score']:.3f}")
        print("====================\n")
