# parents_llm.py
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
import re

# -----------------------------
# 1) LLM (LOW VARIANCE)
# -----------------------------
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.15
)

# -----------------------------
# 2) Prompt (STRICT ROLE)
# -----------------------------
parent_prompt = ChatPromptTemplate.from_messages([
    ("system",
     "You explain a child's recent learning flow to a parent.\n\n"
     "CRITICAL RULES:\n"
     "- You do NOT see raw data\n"
     "- You do NOT see logs, numbers, dates, or titles\n"
     "- You explain patterns, not events\n"
     "- You avoid judgment, diagnosis, or urgency\n"
     "- You never suggest punishment or pressure\n"
     "- You speak calmly and reassuringly\n"
     "- You frame all conclusions as interpretations, not facts\n"
     "- If a parent asks for numbers, dates, or specific logs, politely refuse to share them and explain your role"
    ),
    ("system",
     "The following are abstract narrative features prepared by the backend.\n"
     "They already reflect a 14-day rolling interpretation.\n"
     "Do NOT attempt to reconstruct or infer concrete details.\n\n"
     "{narrative}"
    ),
    ("user", "Parent Question: {question}\n\nGenerate a single concise answer in plain text.")
])

# -----------------------------
# 3) Chain
# -----------------------------
parent_chain = parent_prompt | llm | StrOutputParser()

# -----------------------------
# 4) Public function (ONLY ENTRY)
# -----------------------------
def run_parent_interpretation(narrative_features, question=None):
    """
    Generates a parent-friendly answer based on narrative features.
    - Returns plain text in 'answer'.
    - Avoids any raw numbers or logs.
    """
    # 1. Format the narrative features into a bulleted string
    narrative_text = "\n".join(f"- {f}" for f in narrative_features)
    
    # 2. Default question if none provided
    query = question or "Please provide a general interpretation of the child's learning flow."

    # 3. Check if the question asks for numbers or logs
    forbidden_keywords = [
        "number", "minutes", "spent", "log", "date", "time", "statistics", "detail"
    ]
    if any(word in query.lower() for word in forbidden_keywords):
        return {
            "answer": (
                "I can't share specific activity details. "
                "My role is to explain the overall interpretation and what it means for support, "
                "rather than provide records or measurements."
            )
        }

    # 4. Call the LLM chain for normal interpretation questions
    try:
        raw_output = parent_chain.invoke({
            "narrative": narrative_text,
            "question": query
        })
    except Exception as e:
        print(f"❌ LLM Invoke Error: {e}")
        return {
            "answer": "I'm sorry, I'm having trouble interpreting the data right now."
        }

    # 5. Clean output (just in case LLM adds headers or bullets)
    answer = raw_output.strip()
    answer = re.sub(r"^(Current Guidance[:\*]*|Interpretation[:\*]*|\d+\)|-)\s*", "", answer)

    return {"answer": answer}
