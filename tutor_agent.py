# tutor_agent.py

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser


# 1) LLM (less restrictive, more stable)
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.3,
    max_output_tokens=300
)


# 2) Prompt (SAFE structure)
tutor_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are a helpful and friendly AI tutor. "
        "Explain concepts clearly and concisely using simple examples. "
        "If the question is unclear or missing information, ask one short clarifying question. "
        "Do NOT refuse unless the request is truly impossible."
    ),
    ("human", "{history}"),
    ("human", "{message}")
])


# 3) Chain
tutor_chain = tutor_prompt | llm | StrOutputParser()


# 4) Public function
def run_tutor(message: str, history: str) -> str:
    if not history or not history.strip():
        history = "No prior conversation."

    response = tutor_chain.invoke({
        "message": message,
        "history": history
    })

    return response.strip()


def build_history(messages, limit=6, max_chars=1000):
    """
    messages: list of dicts -> {role: 'user'|'assistant', content: str}
    limit: how many recent messages to include
    max_chars: max total characters in history
    """
    recent = messages[-limit:]
    history_lines = []
    total_chars = 0

    for m in recent:
        role = "User" if m["role"] == "user" else "Assistant"
        line = f"{role}: {m['content']}"
        if total_chars + len(line) > max_chars:
            break
        history_lines.append(line)
        total_chars += len(line)

    return "\n".join(history_lines)
