from dotenv import load_dotenv
load_dotenv()

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
import os

# 1) LLM
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.2
)

# 2) Prompt
summary_prompt = ChatPromptTemplate.from_messages([
    ("system",
     "You summarize a user's daily activity logs. "
     "Write 2-3 reflective sentences. "
     "Focus on learning, mindset, and progress."),
    ("human", "{logs}")
])

# 3) Chain
summary_chain = summary_prompt | llm | StrOutputParser()

# 4) Public function
def summarize_logs(logs_text: str) -> str:
    return summary_chain.invoke({"logs": logs_text})
