from langchain_core.prompts import PromptTemplate

# Router prompt
router_prompt = PromptTemplate.from_template(
    """You are an expert at routing a user question to a vectorstore or web search.
The vectorstore contains documentation and code for technical libraries and tools.
Use the vectorstore for questions on these topics. For recent events, changelogs, or general information, use web-search.
Provide your decision in a JSON format with a single key 'route' and value either 'vectorstore' or 'web_search'.
Do not provide any explanations or other text.

Question: {question}
"""
)

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
rewriter_prompt = PromptTemplate.from_template(
    """You are an expert question re-writer that converts an input question to a better version that is optimized
for vectorstore retrieval. Look at the input and try to reason about the underlying semantic intent / meaning.

Here is the initial question:
{question}

Formulate an improved question:"""
)
