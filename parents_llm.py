# parents_llm.py
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
import re
from dotenv import load_dotenv
# -----------------------------
# 1) LLM (LOW VARIANCE)
# -----------------------------
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.2
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
    Handles both dashboard interpretation and direct chat questions.
    """
    # 1. Format the narrative features into a bulleted string
    narrative_text = "\n".join(f"- {f}" for f in narrative_features)
    
    # 2. Determine if this is a general interpretation or a specific chat question
    is_chat = question is not None
    query = question or "Provide a general interpretation of the learning flow and a brief rationale."

    # 3. Guardrail: Check for forbidden keywords (data privacy)
    forbidden_keywords = ["number", "minutes", "spent", "log", "date", "time", "statistics", "detail"]
    if any(word in query.lower() for word in forbidden_keywords):
        msg = ("I can't share specific activity details. My role is to explain the overall "
               "interpretation rather than provide raw records.")
        return {"answer": msg, "current_guidance": msg, "interpretation_rationale": "Privacy Guardrail"}

    # 4. Call the LLM
    try:
        raw_output = parent_chain.invoke({
            "narrative": narrative_text,
            "question": query
        })
        print("✅ Raw LLM Output:", raw_output)
    except Exception as e:
        print(f"❌ LLM Invoke Error: {e}")

        error_msg = "I'm having trouble interpreting the data right now."
        return {"answer": error_msg, "current_guidance": error_msg, "interpretation_rationale": "Error"}

    # 5. Clean output
    answer = raw_output.strip()
    # Remove common LLM prefixes if they exist
    answer = re.sub(r"^(Current Guidance[:\*]*|Interpretation[:\*]*|Answer[:\*]*|\d+\)|-)\s*", "", answer, flags=re.IGNORECASE)

    rationale_text = "\n".join(f"- {f}" for f in narrative_features) or "No recent activity recorded."

    # 7. Return based on chat vs dashboard
    if is_chat:
        return {"answer": answer}
    else:
        return {
            "current_guidance": answer,
            "interpretation_rationale": rationale_text
        }