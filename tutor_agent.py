# tutor_agent.py
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# 1) LLM with max output length
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.2,
    max_output_tokens=150  # <-- limit AI response length
)

# 2) Prompt
tutor_prompt = ChatPromptTemplate.from_messages([
    ("system",
     "You are a helpful, friendly AI tutor. "
     "Explain clearly and concisely. "
     "Use simple examples if helpful. "
     "Keep your answer under 150 words."),
    ("system", "Conversation so far:\n{history}"),
    ("human", "{message}")
])

# 3) Chain
tutor_chain = tutor_prompt | llm | StrOutputParser()

# 4) Public function
def run_tutor(message: str, history: str) -> str:
    response = tutor_chain.invoke({
        "message": message,
        "history": history
    })
    # Optional extra truncation if needed
    return response[:500]  # max 500 characters

def build_history(messages, limit=6, max_chars=1000):
    """
    messages: list of {role, content}
    limit: how many recent messages to include
    max_chars: max total characters in history
    """
    recent = messages[-limit:]
    history_lines = []
    total_chars = 0

    for m in recent:
        role = "User" if m["role"] == "user" else "Assistant"
        line = f"{role}: {m['content']}"
        total_chars += len(line)
        if total_chars > max_chars:
            break
        history_lines.append(line)

    return "\n".join(history_lines)
