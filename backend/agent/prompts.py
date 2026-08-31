from langchain_core.prompts import PromptTemplate

# Router prompt
# Grader prompt
grader_prompt = PromptTemplate.from_template(
    """You are a grader assessing relevance of a retrieved document to a user question.
If the document contains keyword(s) or semantic meaning related to the question, grade it as relevant.
Provide your decision in a JSON format with a single key 'score' and value either 'yes' or 'no'.
Do not provide any explanations or other text.

Retrieved document:
{document}

Question: {question}
"""
)

# Generator prompt
generator_prompt = PromptTemplate.from_template(
    """You are an expert technical assistant for question-answering tasks.
Use the following pieces of retrieved context to answer the question.
If you don't know the answer, just say that you don't know.
Keep the answer concise and clear.
Include the sources you used at the end of your answer in a clear format.

Context:
{context}

Question: {question}

Answer:"""
)

# Rewriter prompt
# 재작성 결과는 그대로 다음 검색 질의가 된다. 형식이 어긋나면 질의가 통째로 오염되므로
# "질문만, 한 줄로" 를 명시한다.
# 실측: 제약이 없던 이전 프롬프트가 "Here's an improved question... **Reasoning:** 1. ..."
# 형태의 1,500자 설명문을 냈고, 그 덩어리가 검색어로 들어갔다.
# 프롬프트만으로는 재발을 막지 못하므로 nodes.py 에서 한 번 더 걸러낸다.
#
rewriter_prompt = PromptTemplate.from_template(
    """You rewrite a search query so that it retrieves better results from a vector store of technical documentation.
Reason silently about the underlying semantic intent, then output one improved question.

Rules:
- Output ONLY the rewritten question. No preamble, no explanation, no reasoning, no labels.
- No markdown, no bullet points, no bold text.
- Exactly one line, under 200 characters.
- Use the same language as the input question.

Input question:
{question}

Rewritten question:"""
)

# Contextualize prompt
contextualize_prompt = PromptTemplate.from_template(
    """Given a chat history and the latest user question which might reference context in the chat history, 
formulate a standalone question which can be understood without the chat history. Do NOT answer the question, 
just reformulate it if needed and otherwise return it as is.

Chat History:
{chat_history}

Latest Question: {question}

Standalone Question:"""
)

# Batch grader prompt
# 문서를 하나씩 채점하면 LLM 왕복이 문서 수만큼 발생한다. Gemini 무료 티어는 분당 5회라
# 질문 한 번이 한도를 넘긴다. 전체 문서를 한 프롬프트에 넣어 1회로 끝낸다.
batch_grader_prompt = PromptTemplate.from_template(
    """You are a strict grader deciding which retrieved documents actually help answer a question.

Rules:
- A document is relevant ONLY if it contains information that directly helps answer the question.
- Belonging to the same project, repository, or general topic is NOT enough.
- Boilerplate, template, or setup documentation unrelated to the question is NOT relevant.
- When in doubt, exclude. Returning fewer, precise documents is better than many vague ones.

Return ONLY a JSON object with a single key 'relevant' whose value is an array of the
index numbers of the relevant documents. Example: {{"relevant": [0, 2]}}
If none are relevant, return {{"relevant": []}}.
Do not provide any explanations or other text.

Question: {question}

Documents:
{documents}
"""
)
