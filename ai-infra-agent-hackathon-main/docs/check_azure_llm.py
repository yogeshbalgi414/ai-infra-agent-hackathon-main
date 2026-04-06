import os
from dotenv import load_dotenv
from openai import AzureOpenAI
import sys

# Load environment variables
load_dotenv()

API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")

if not API_KEY or not ENDPOINT:
    print("❌ Error: Missing AZURE_OPENAI_API_KEY or AZURE_OPENAI_ENDPOINT in .env")
    sys.exit(1)

# Initialize Azure OpenAI client
client = AzureOpenAI(
    api_key=API_KEY,
    api_version="2024-05-01-preview",
    azure_endpoint=ENDPOINT,
)

def chat_with_llm(user_message: str, system_prompt: str = None) -> str:
    """
    Send user message to LLM and get response.
    
    Args:
        user_message: The user's input
        system_prompt: Optional system prompt (default: helpful assistant)
    
    Returns:
        LLM response text
    """
    if system_prompt is None:
        system_prompt = "You are a helpful assistant."
    
    try:
        response = client.chat.completions.create(
            model="gpt-5.3-chat",
            max_completion_tokens=1000,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        
        return response.choices[0].message.content
    
    except Exception as e:
        return f"❌ Error: {str(e)}"


def main():
    """Main interactive chat loop."""
    print("\n" + "█"*60)
    print("   INTERACTIVE LLM CHAT")
    print("█"*60)
    print("\nType your questions below. Type 'exit' or 'quit' to exit.")
    print("Type 'clear' to reset conversation.\n")
    
    conversation_history = []
    system_prompt = "You are a helpful assistant."
    
    while True:
        try:
            # Get user input
            user_input = input("\n👤 You: ").strip()
            
            # Handle commands
            if user_input.lower() in ['exit', 'quit', 'q']:
                print("\n🔴 Goodbye!\n")
                break
            
            if user_input.lower() == 'clear':
                conversation_history = []
                print("✓ Conversation cleared")
                continue
            
            if user_input.lower().startswith('system:'):
                system_prompt = user_input[7:].strip()
                print(f"✓ System prompt updated: {system_prompt}")
                continue
            
            if not user_input:
                print("⚠️  Please enter a message")
                continue
            
            # Add user message to history
            conversation_history.append({"role": "user", "content": user_input})
            
            # Get LLM response
            print("\n⏳ Waiting for response...", end="", flush=True)
            
            try:
                response = client.chat.completions.create(
                    model="gpt-5.3-chat",
                    max_completion_tokens=1000,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        *conversation_history,
                    ],
                )
                
                # Clear the waiting message
                print("\r" + " "*30 + "\r", end="", flush=True)
                
                assistant_response = response.choices[0].message.content
                
                # Add assistant response to history
                conversation_history.append({"role": "assistant", "content": assistant_response})
                
                # Display response
                print(f"\n🤖 Assistant: {assistant_response}")
                print(f"\n📊 Tokens used: {response.usage.total_tokens}")
                
            except Exception as e:
                print(f"\n❌ API Error: {str(e)}")
        
        except KeyboardInterrupt:
            print("\n\n🔴 Interrupted by user\n")
            break
        except Exception as e:
            print(f"\n❌ Error: {str(e)}")


def demo_mode():
    """Demo mode with predefined questions."""
    print("\n" + "█"*60)
    print("   LLM DEMO MODE")
    print("█"*60 + "\n")
    
    questions = [
        "What is Python?",
        "How does machine learning work?",
        "Explain quantum computing in simple terms",
    ]
    
    for i, question in enumerate(questions, 1):
        print(f"\n{'='*60}")
        print(f"Question {i}: {question}")
        print('='*60)
        
        response = chat_with_llm(question)
        print(f"\nAnswer:\n{response}")


if __name__ == "__main__":
    # Check for command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == "--demo":
            demo_mode()
        elif sys.argv[1] == "--help":
            print("""
Usage:
    python interactive_llm.py              # Interactive mode
    python interactive_llm.py --demo       # Demo mode with sample questions
    python interactive_llm.py --help       # Show this help

Interactive Mode Commands:
    Type your question and press Enter
    'exit' or 'quit'                       # Exit the program
    'clear'                                # Clear conversation history
    'system: <prompt>'                     # Set custom system prompt
            """)
        else:
            # Treat as single question
            question = " ".join(sys.argv[1:])
            print(f"\n👤 You: {question}")
            response = chat_with_llm(question)
            print(f"\n🤖 Assistant: {response}\n")
    else:
        main()