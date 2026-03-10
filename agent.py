import json
from typing import Annotated, TypedDict, Literal
from snowflake.snowpark.context import get_active_session
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, AIMessage

# 1. SNOWFLAKE CONNECTION INITIALIZATION
def init_connection():
    try:
        return get_active_session()
    except Exception:
        import streamlit as st
        return st.connection("snowflake").session()

session = init_connection()


# 2. STATE DEFINITION (MEMORY)
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    standalone_query: str     
    context: str              
    is_relevant: bool         
    grader_raw_response: str  
    selected_model: str


# 3. LANGGRAPH NODES DEFINITION
def route_query(state: AgentState) -> Literal["chat", "retrieve_flow"]:
    user_message = state["messages"][-1].content
    
    prompt = f"""You are an intent router for an IT support desk.
    Analyze the following message.
    
    RULES:
    - If it is ONLY a greeting (hello, hi, good morning) or a thank you -> Answer strictly with the word 'chat'
    - If it mentions a problem, error, system (like database, VPN), a request for help, or a technical question -> Answer strictly with the word 'retrieve'
    
    Message: "{user_message}"
    
    MANDATORY INSTRUCTION: Answer with ONLY ONE word: 'chat' or 'retrieve'."""
    
    escaped_prompt = prompt.replace("'", "''")
    # L'agent lit le modèle depuis son état (avec un fallback par défaut)
    model = state.get("selected_model", "llama3.1-70b")
    llm_query = f"SELECT SNOWFLAKE.CORTEX.COMPLETE('{model}', '{escaped_prompt}')"
    
    try:
        response = session.sql(llm_query).collect()[0][0].strip().lower()
        if "chat" in response and "retrieve" not in response:
            return "chat"
    except Exception:
        pass
    return "retrieve_flow"


def basic_chat_node(state: AgentState):
    user_message = state["messages"][-1].content
    prompt = f"""You are a polite IT support assistant. Respond briefly and politely to this message without inventing any technical solution: "{user_message}" """
    escaped_prompt = prompt.replace("'", "''")
    llm_query = f"SELECT SNOWFLAKE.CORTEX.COMPLETE('llama3.1-8b', '{escaped_prompt}')"
    
    try:
        response = session.sql(llm_query).collect()[0][0].strip()
    except Exception:
        response = "Hello! How can I help you with your IT issues today?"
        
    return {
        "messages": [AIMessage(content=response)], 
        "standalone_query": user_message, 
        "context": "N/A", 
        "is_relevant": False,
        "grader_raw_response": "N/A"
    }


def query_rewriter_node(state: AgentState):
    messages = state["messages"]
    if len(messages) <= 1:
        return {"standalone_query": messages[-1].content}
    
    history = "\n".join([f"{'Client' if isinstance(m, HumanMessage) else 'Agent'}: {m.content}" for m in messages[-5:-1]])
    current_question = messages[-1].content
    
    prompt = f"""Here is the history of a conversation with technical support:
    {history}
    
    Last user message: {current_question}
    
    INSTRUCTION: Rewrite the last message so that it can be understood on its own (without the history), keeping all the key technical terms of the problem. 
    If the last message is already clear and standalone, output it exactly as it is.
    Return ONLY the rewritten question, without any introduction or explanation."""
    
    escaped_prompt = prompt.replace("'", "''")
    llm_query = f"SELECT SNOWFLAKE.CORTEX.COMPLETE('llama3.1-8b', '{escaped_prompt}')"
    
    try:
        standalone_query = session.sql(llm_query).collect()[0][0].strip()
    except Exception:
        standalone_query = current_question 
        
    return {"standalone_query": standalone_query}


def retrieve_node(state: AgentState):
    standalone_query = state["standalone_query"]
    search_payload = {
        "query": standalone_query,
        "columns": ["SUBJECT", "BODY", "ANSWER", "PRIORITY", "LANGUAGE"],
        "limit": 3
    }
        
    payload_str = json.dumps(search_payload).replace("'", "''") 
    sql_query = f"SELECT SNOWFLAKE.CORTEX.SEARCH_PREVIEW('support_tickets_search_service', '{payload_str}')"
    
    try:
        result = session.sql(sql_query).collect()[0][0]
        documents = json.loads(result).get("results", [])
    except Exception as e:
        print(f"Retriever Error: {e}") 
        documents = []

    context_str = ""
    for idx, doc in enumerate(documents):
        context_str += f"\n--- Ticket {idx+1} ---\n"
        context_str += f"Subject: {doc.get('SUBJECT')}\n"
        context_str += f"Problem: {doc.get('BODY')}\n"
        context_str += f"Solution: {doc.get('ANSWER')}\n"

    if not context_str:
        context_str = "No similar ticket found."

    return {"context": context_str}


def grade_documents_node(state: AgentState):
    query = state["standalone_query"]
    context = state["context"]
    
    if context == "No similar ticket found.":
        return {"is_relevant": False, "grader_raw_response": "No context found."}
        
    prompt = f"""You are a relevance evaluator for an IT support system.
    Check if the following CONTEXT contains useful clues, solutions, OR troubleshooting questions (like asking for hardware models, error codes, or connection types) that match the QUESTION.
    It doesn't have to be a perfect fix, just helpful enough to guide the user or investigate further.
    
    QUESTION: {query}
    CONTEXT: {context}
    
    MANDATORY INSTRUCTION: Answer ONLY with a single word: "YES" if it's helpful or contains relevant diagnostic questions, or "NO" if it's completely unrelated."""
    
    escaped_prompt = prompt.replace("'", "''")
    model = state.get("selected_model", "llama3.1-70b")
    llm_query = f"SELECT SNOWFLAKE.CORTEX.COMPLETE('{model}', '{escaped_prompt}')"
    
    try:
        raw_response = session.sql(llm_query).collect()[0][0]
        response = raw_response.strip().upper()
    except Exception as e:
        raw_response = f"SQL Error: {str(e)}"
        response = "NO"
        
    is_relevant = "YES" in response or "TRUE" in response
    return {"is_relevant": is_relevant, "grader_raw_response": raw_response}

def check_relevance(state: AgentState) -> Literal["generate", "escalate"]:
    return "generate" if state.get("is_relevant") else "escalate"

def escalate_node(state: AgentState):
    return {"messages": [AIMessage(content="⚠️ I cannot find a confirmed solution for this exact issue in our database. I have escalated your ticket to a human technician.")]}

def generate_node(state: AgentState):
    query = state["standalone_query"]
    context = state["context"]
    model = state.get("selected_model", "llama3.1-70b")
    
    prompt = f"""You are an expert IT Level 1 support agent. 
    Use the following CONTEXT from past tickets to help the user. 
    
    RULES:
    1. If the CONTEXT contains a direct solution, give it to the user clearly.
    2. If the CONTEXT contains troubleshooting questions asked by previous technicians (e.g., asking for a model number, error code, or connection type), ASK those same questions to the user to investigate their issue.
    3. Do not mention that you are reading from a context or past tickets. Just act as the helpful agent.
    
    CONTEXT: {context}
    QUESTION: {query}
    """
    escaped_prompt = prompt.replace("'", "''")
    llm_query = f"SELECT SNOWFLAKE.CORTEX.COMPLETE('{model}', '{escaped_prompt}')"
    
    try:
        response = session.sql(llm_query).collect()[0][0]
    except Exception as e:
        response = f"Generation Error: {str(e)}"
        
    return {"messages": [AIMessage(content=response)]}

# 4. LANGGRAPH ASSEMBLY
graph_builder = StateGraph(AgentState)

graph_builder.add_node("basic_chat", basic_chat_node)
graph_builder.add_node("query_rewriter", query_rewriter_node)
graph_builder.add_node("retrieve", retrieve_node)
graph_builder.add_node("grade", grade_documents_node)
graph_builder.add_node("escalate", escalate_node)
graph_builder.add_node("generate", generate_node)

graph_builder.add_conditional_edges(START, route_query, {"chat": "basic_chat", "retrieve_flow": "query_rewriter"})
graph_builder.add_edge("basic_chat", END)
graph_builder.add_edge("query_rewriter", "retrieve")
graph_builder.add_edge("retrieve", "grade")
graph_builder.add_conditional_edges("grade", check_relevance, {"generate": "generate", "escalate": "escalate"})
graph_builder.add_edge("generate", END)
graph_builder.add_edge("escalate", END)

compiled_agent = graph_builder.compile()