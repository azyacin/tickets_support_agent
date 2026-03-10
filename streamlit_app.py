import streamlit as st
from langchain_core.messages import HumanMessage, AIMessage
from agent import compiled_agent


st.set_page_config(page_title="AI Support Agent Pro", page_icon="🤖", layout="wide")

with st.sidebar:
    st.header("⚙️ Configuration")
    st.session_state.selected_model = st.selectbox(
        "AI Model (Grader & Generation)", 
        ["llama3.1-70b", "mistral-large2", "llama3-70b"]
    )
    
    st.markdown("---")
    
    if st.button("🗑️ Clear Conversation"):
        st.session_state.chat_history = []
        st.rerun()
    
    st.markdown("---")
    st.markdown("### Agentic RAG Architecture\n- **Semantic Router**\n- **Query Rewriting** (Memory)\n- **Retriever** (Cortex Search)\n- **Context Grader**\n- **Fallback Escalation**")

st.title("🤖 AI Support Agent (Reliable & Robust)")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

for msg in st.session_state.chat_history:
    role = "user" if isinstance(msg, HumanMessage) else "assistant"
    with st.chat_message(role):
        st.markdown(msg.content)

if user_input := st.chat_input("Describe your technical issue..."):
    
    st.session_state.chat_history.append(HumanMessage(content=user_input))
    with st.chat_message("user"):
        st.markdown(user_input)
        
    with st.chat_message("assistant"):
        with st.spinner("Searching and analyzing..."):
            initial_state = {
                "messages": st.session_state.chat_history, 
                "standalone_query": "", 
                "context": "", 
                "is_relevant": False,
                "grader_raw_response": "",
                "selected_model": st.session_state.selected_model # Injection du modèle dans l'état
            }
            
            final_state = compiled_agent.invoke(initial_state)
            ai_response = final_state["messages"][-1].content
            
            st.markdown(ai_response)
            
            with st.expander("🛠️ View Agent Traces"):
                st.markdown(f"**1. Original query:** {user_input}")
                if "standalone_query" in final_state and final_state["standalone_query"] != user_input:
                    st.markdown(f"**2. Rewritten query (Memory):** `{final_state['standalone_query']}`")
                
                st.markdown(f"**3. Raw LLM judge response:** `{final_state.get('grader_raw_response', 'N/A')}`")
                st.markdown(f"**4. Final relevance:** {'✅ Validated' if final_state.get('is_relevant') else '❌ Rejected (Escalation)'}")
                st.text(final_state.get("context", ""))
            
    st.session_state.chat_history.append(AIMessage(content=ai_response))