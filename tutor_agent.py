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
tutor_prompt = ChatPromptTemplate.from_messages([
    ("system",
     "You are a helpful, friendly AI tutor. "
     "Explain clearly and concisely. "
     "Use simple examples if helpful."),
    ("human", "{message}")
])

# 3) Chain
tutor_chain = tutor_prompt | llm | StrOutputParser()

# 4) Public function (IMPORTANT)
def run_tutor(message: str) -> str:
    return tutor_chain.invoke({"message": message})
