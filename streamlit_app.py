import streamlit as st
from langchain_core.messages import HumanMessage, AIMessage
from snowflake.snowpark.context import get_active_session
from agent import compiled_agent

# ==========================================
# 1. INITIALISATION DE LA SESSION SNOWFLAKE
# ==========================================
try:
    session = get_active_session()
except Exception:
    session = st.connection("snowflake").session()

if hasattr(st, "user") and st.user.user_name:
    current_user_id = st.user.user_name
else:
    current_user_id = "anonymous_user"

# INTERFACE STREAMLIT
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
    st.markdown(f"**Utilisateur connecté :** `{current_user_id}`")

st.title("🤖 AI Support Agent")

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
                "selected_model": st.session_state.selected_model
            }
            
            # Invocation de l'agent
            final_state = compiled_agent.invoke(initial_state)
            ai_response = final_state["messages"][-1].content
            
            # Récupération des données pour les logs
            standalone_query = final_state.get("standalone_query", "")
            is_relevant = final_state.get("is_relevant", False)
            is_escalated = not is_relevant # Si non pertinent = escaladé
            
            st.markdown(ai_response)
            
            # 3. STORE IN SNOWFLAKE DB
            try:
                safe_user_input = user_input.replace("'", "''")
                safe_ai_response = ai_response.replace("'", "''")
                safe_query = standalone_query.replace("'", "''")
                model_used = st.session_state.selected_model

                log_sql = f"""
                INSERT INTO CONVERSATION_LOGS 
                (USER_ID, USER_MESSAGE, STANDALONE_QUERY, AI_RESPONSE, IS_ESCALATED, MODEL_USED)
                VALUES 
                ('{current_user_id}', '{safe_user_input}', '{safe_query}', '{safe_ai_response}', {is_escalated}, '{model_used}')
                """
                session.sql(log_sql).collect()

                if is_escalated:
                    esc_sql = f"""
                    INSERT INTO ESCALATED_TICKETS 
                    (USER_ID, ORIGINAL_MESSAGE, REWRITTEN_QUERY, STATUS)
                    VALUES 
                    ('{current_user_id}', '{safe_user_input}', '{safe_query}', 'OPEN')
                    """
                    session.sql(esc_sql).collect()
                    
            except Exception as e:
                st.error(f"Erreur lors de la sauvegarde dans Snowflake : {e}")
            
            with st.expander("🛠️ View Agent Traces"):
                st.markdown(f"**1. Original query:** {user_input}")
                if "standalone_query" in final_state and final_state["standalone_query"] != user_input:
                    st.markdown(f"**2. Rewritten query (Memory):** `{final_state['standalone_query']}`")
                
                st.markdown(f"**3. Raw LLM judge response:** `{final_state.get('grader_raw_response', 'N/A')}`")
                st.markdown(f"**4. Final relevance:** {'✅ Validated' if is_relevant else '❌ Rejected (Escalated to DB)'}")
                st.text(final_state.get("context", ""))
            
    st.session_state.chat_history.append(AIMessage(content=ai_response))