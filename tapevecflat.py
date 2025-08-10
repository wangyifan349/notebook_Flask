# tapevecflat.py

import re
import time
import numpy as np
from math import log

# Try to import jieba for Chinese tokenization
try:
    import jieba
    hasJieba = True
except ImportError:
    hasJieba = False

# Configuration section
documentsList = [
    "今天 天气 很好",
    "The weather is great today",
    "今天 我 去 公园",
    "Visiting the park today"
]
methodChoice = "tfidf"          # choose "tf" or "tfidf"
languageMode = "auto"           # choose "zh", "en", or "auto"
speedRepeats = 20               # number of repetitions for speed test
simSentenceOne = "今天 天气 很好"
simSentenceTwo = "The weather is great today"

# Tokenization for all texts including similarity sentences
allTexts = documentsList + [simSentenceOne, simSentenceTwo]
tokenLists = []

for text in allTexts:
    # detect Chinese characters
    containsChinese = bool(re.search(r"[\u4e00-\u9fff]", text))
    useChinese = (languageMode == "zh") or (languageMode == "auto" and containsChinese)
    if useChinese:
        if not hasJieba:
            raise ImportError("Please install jieba: pip install jieba")
        tokens = list(jieba.cut(text))            # Chinese tokenization
    else:
        tokens = re.findall(r"[A-Za-z0-9']+", text.lower())  # simple English tokenization
    tokenLists.append(tokens)

# Separate document tokens from similarity sentence tokens
docTokens = tokenLists[:len(documentsList)]
simTokens = tokenLists[len(documentsList):]

# Build vocabulary and document frequency counts
vocabulary = {}        # maps token to index
documentFrequency = {} # counts in how many documents each token appears
for tokens in docTokens:
    seenTokens = set()
    for token in tokens:
        # add new token to vocabulary
        if token not in vocabulary:
            vocabulary[token] = len(vocabulary)
        # count document frequency only once per document
        if token not in seenTokens:
            documentFrequency[token] = documentFrequency.get(token, 0) + 1
            seenTokens.add(token)

docCount = len(docTokens)

# Compute inverse document frequency for tfidf
idfValues = {}
if methodChoice == "tfidf":
    for token, df in documentFrequency.items():
        idfValues[token] = log(docCount / df)

vocabSize = len(vocabulary)

# Build term frequency matrix and term frequency–inverse document frequency matrix
tfMatrix = np.zeros((docCount, vocabSize), dtype=float)
tfidfMatrix = np.zeros((docCount, vocabSize), dtype=float)

for i, tokens in enumerate(docTokens):
    termCounts = {}
    for token in tokens:
        termCounts[token] = termCounts.get(token, 0) + 1
    for token, count in termCounts.items():
        index = vocabulary[token]
        tfMatrix[i, index] = count                       # fill TF count
        if methodChoice == "tfidf":
            tfidfMatrix[i, index] = count * idfValues.get(token, 0.0)  # fill TFIDF value

# choose result matrix based on method
resultMatrix = tfMatrix if methodChoice == "tf" else tfidfMatrix

# Compute cosine similarity between two given sentences
simMatrix = np.zeros((2, vocabSize), dtype=float)
for idx, tokens in enumerate(simTokens):
    counts = {}
    for token in tokens:
        if token in vocabulary:
            counts[token] = counts.get(token, 0) + 1
    for token, count in counts.items():
        index = vocabulary[token]
        if methodChoice == "tf":
            simMatrix[idx, index] = count
        else:
            simMatrix[idx, index] = count * idfValues.get(token, 0.0)

dotProduct = np.dot(simMatrix[0], simMatrix[1])
normProduct = np.linalg.norm(simMatrix[0]) * np.linalg.norm(simMatrix[1])
cosineSimilarity = float(dotProduct / normProduct) if normProduct else 0.0

# Speed comparison between full build (vocabulary + matrix) and transform only
startFull = time.time()
for _ in range(speedRepeats):
    tempVocab = {}
    tempDf = {}
    # rebuild vocabulary and document frequency
    for tokens in docTokens:
        seenTokens = set()
        for token in tokens:
            if token not in tempVocab:
                tempVocab[token] = len(tempVocab)
            if token not in seenTokens:
                tempDf[token] = tempDf.get(token, 0) + 1
                seenTokens.add(token)
    # compute temporary idf if needed
    tempIdf = {t: log(docCount / tempDf[t]) for t in tempDf} if methodChoice == "tfidf" else {}
    # build temporary matrix
    tempMatrix = np.zeros((docCount, len(tempVocab)), dtype=float)
    for i, tokens in enumerate(docTokens):
        tc = {}
        for token in tokens:
            tc[token] = tc.get(token, 0) + 1
        for token, count in tc.items():
            idxV = tempVocab[token]
            if methodChoice == "tf":
                tempMatrix[i, idxV] = count
            else:
                tempMatrix[i, idxV] = count * tempIdf.get(token, 0.0)
timeFull = (time.time() - startFull) / speedRepeats

startTransform = time.time()
for _ in range(speedRepeats):
    tempMatrix2 = np.zeros((docCount, vocabSize), dtype=float)
    for i, tokens in enumerate(docTokens):
        tc = {}
        for token in tokens:
            tc[token] = tc.get(token, 0) + 1
        for token, count in tc.items():
            idxV = vocabulary[token]
            if methodChoice == "tf":
                tempMatrix2[i, idxV] = count
            else:
                tempMatrix2[i, idxV] = count * idfValues.get(token, 0.0)
timeTransform = (time.time() - startTransform) / speedRepeats

# Print out results
print(f"{methodChoice.upper()} Matrix:\n{resultMatrix}")
print(f"Cosine Similarity: {cosineSimilarity:.4f}")
print(f"Average build+transform time: {timeFull:.6f} seconds")
print(f"Average transform-only time: {timeTransform:.6f} seconds")
