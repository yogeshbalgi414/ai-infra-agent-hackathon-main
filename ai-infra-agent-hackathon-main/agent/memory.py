"""
agent/memory.py — ConversationBufferMemory setup.
Owner: Person 3
Status: IMPLEMENTED (Epic 7)
"""

from langchain.memory import ConversationBufferMemory


def create_memory() -> ConversationBufferMemory:
    """
    Create and return a LangChain ConversationBufferMemory instance
    configured with memory_key='chat_history' and return_messages=True.
    """
    return ConversationBufferMemory(
        memory_key="chat_history",
        return_messages=True,
    )
