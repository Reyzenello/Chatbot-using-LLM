import streamlit as st
from streamlit_option_menu import option_menu
import os
import json
import time
import asyncio
from duckduckgo_search import AsyncDDGS
import difflib
from dotenv import load_dotenv
from pygments import highlight
from pygments.lexers import get_lexer_by_name
from pygments.formatters import HtmlFormatter
import base64
from urllib.parse import urlparse
import requests
from PIL import Image
from io import BytesIO
import ollama

# Initialize
load_dotenv()

# Initialize Ollama client
client = ollama.Client()

# Constants and global variables
DEFAULT_MODEL = "llama3.1"
SYSTEM_PROMPT = """You are an incredible developer assistant with the following traits:
- You write clean, efficient code
- You explain concepts with clarity
- You think through problems step-by-step
- You're passionate about helping developers improve

When given an /edit instruction:
- First, after completing the code review, construct a plan for the change
- Then provide specific edit instructions
- Format your response as edit instructions
- Do NOT execute changes yourself"""


# Global variables
added_files = []
undo_history = {}
stored_searches = {}
stored_images = {}
is_diff_on = True

# Function to make API calls to the model
def make_api_call(messages, is_final_answer=False):
    for attempt in range(3):
        try:
            response = client.chat(
                model=DEFAULT_MODEL,
                messages=messages
            )
            return json.loads(response['message']['content'])
        except json.JSONDecodeError:
            # If the response is not valid JSON, return it as-is
            return {"title": "Response", "content": response['message']['content']}
        except Exception as e:
            if attempt == 2:
                if is_final_answer:
                    return {"title": "Error", "content": f"Failed to generate final answer after 3 attempts. Error: {str(e)}"}
                else:
                    return {"title": "Error", "content": f"Failed to generate step after 3 attempts. Error: {str(e)}", "next_action": "final_answer"}
            time.sleep(1)

# Function to generate reasoning steps
def generate_response(prompt):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": "Thank you! I will now think step by step following my instructions, starting at the beginning after decomposing the problem."}
    ]

    steps = []
    step_count = 1
    total_thinking_time = 0

    while True:
        start_time = time.time()
        step_data = make_api_call(messages)
        end_time = time.time()
        thinking_time = end_time - start_time
        total_thinking_time += thinking_time

        steps.append((f"Step {step_count}: {step_data.get('title', 'Thinking')}", step_data['content'], thinking_time))

        messages.append({"role": "assistant", "content": json.dumps(step_data)})

        if step_data.get('next_action') == 'final_answer' or step_count > 25:
            break

        step_count += 1

        yield steps, None

    # Generate final answer
    messages.append({"role": "user", "content": "Please provide the final answer based on your reasoning above."})

    start_time = time.time()
    final_data = make_api_call(messages, is_final_answer=True)
    end_time = time.time()
    thinking_time = end_time - start_time
    total_thinking_time += thinking_time

    steps.append(("Final Answer", final_data['content'], thinking_time))

    yield steps, total_thinking_time
# Helper functions for file operations, searches, etc.
def read_file_content(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as file:
            return file.read()
    except Exception as e:
        return f"❌ Error reading {filepath}: {e}"

def write_file_content(filepath, content):
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    except Exception:
        return False

def display_diff(original, edited):
    diff = difflib.unified_diff(
        original.splitlines(), edited.splitlines(), lineterm='', n=0
    )
    diff_text = '\n'.join(diff)
    return diff_text

async def perform_search(query):
    results = []
    async with AsyncDDGS() as ddgs:
        async for result in ddgs.text(query):
            results.append(result)
            if len(results) >= 5:
                break
    return results

# Custom CSS for styling (embedded within the script)
def set_custom_css():
    st.markdown("""
    <style>
    /* Custom CSS */
    body {
        background-color: #f5f5f5;
    }
    .header {
        text-align: center;
        padding: 20px;
    }
    .header h1 {
        font-size: 3em;
        color: #3A7BD5;
    }
    .header p {
        font-size: 1.2em;
        color: #3A7BD5;
    }
    .stButton>button {
        background-color: #3A7BD5;
        color: white;
        border-radius: 8px;
    }
    .stTextInput>div>div>input {
        border: 1px solid #3A7BD5;
        border-radius: 4px;
    }
    .stTextArea textarea {
        border: 1px solid #3A7BD5;
        border-radius: 4px;
    }
    .stAlert {
        border-radius: 8px;
    }
    </style>
    """, unsafe_allow_html=True)

# Main Streamlit app
def main():
    # Apply custom CSS
    set_custom_css()

    st.markdown("""
        <div class="header">
            <h1>🧠 AI Assistant</h1>
            <p>Developer Assistant with Step-by-Step Reasoning</p>
        </div>
    """, unsafe_allow_html=True)

    # Sidebar menu
    with st.sidebar:
        selected = option_menu(
            menu_title="Main Menu",
            options=["Home", "Commands", "Settings", "About"],
            icons=["house", "code", "gear", "info-circle"],
            menu_icon="cast",
            default_index=0,
        )

    if selected == "Home":
        st.write("")
    elif selected == "Commands":
        print_help()
    elif selected == "Settings":
        change_model()
    elif selected == "About":
        st.markdown("""
        **AI Assistant** is a powerful tool that combines developer assistance with step-by-step reasoning, all within a sleek and modern interface.
        """)
        st.markdown("---")
        st.markdown("**Developed by:** Your Name")
        st.markdown("**Contact:** your.email@example.com")
        st.markdown("**Version:** 1.0.0")
        return

    # Text input for user query
    user_query = st.text_input("Enter your command or query:", placeholder="e.g., /add my_script.py")

    if user_query:
        # Handle commands starting with '/'
        if user_query.startswith('/'):
            # Process the command
            process_command(user_query)
        else:
            st.write("Generating response...")

            # Create empty elements to hold the generated text and total time
            response_container = st.empty()
            time_container = st.empty()

            # Generate and display the response
            for steps, total_thinking_time in generate_response(user_query):
                with response_container.container():
                    for i, (title, content, thinking_time) in enumerate(steps):
                        if title.startswith("Final Answer"):
                            st.markdown(f"### {title}")
                            st.markdown(content.replace('\n', '<br>'), unsafe_allow_html=True)
                        else:
                            with st.expander(title, expanded=True):
                                st.markdown(content.replace('\n', '<br>'), unsafe_allow_html=True)

                # Only show total time when it's available at the end
                if total_thinking_time is not None:
                    time_container.markdown(f"**Total thinking time: {total_thinking_time:.2f} seconds**")

# Function to process commands
def process_command(command):
    # Split the command and arguments
    parts = command.strip().split()
    cmd = parts[0]
    args = parts[1:]

    if cmd == '/add':
        handle_add_command(args)
    elif cmd == '/edit':
        handle_edit_command(args)
    elif cmd == '/new':
        handle_new_command(args)
    elif cmd == '/search':
        asyncio.run(handle_search_command(' '.join(args)))
    elif cmd == '/image':
        handle_image_command(args)
    elif cmd == '/clear':
        handle_clear_command()
    elif cmd == '/reset':
        handle_reset_command()
    elif cmd == '/diff':
        toggle_diff()
    elif cmd == '/history':
        handle_history_command()
    elif cmd == '/save':
        handle_save_command()
    elif cmd == '/load':
        handle_load_command()
    elif cmd == '/undo':
        handle_undo_command(args)
    elif cmd == '/help':
        print_help()
    elif cmd == '/model':
        show_current_model()
    elif cmd == '/change_model':
        change_model()
    elif cmd == '/show':
        handle_show_command(args)
    else:
        st.error(f"Unknown command: {cmd}")

# Implement the command handling functions
def handle_add_command(paths):
    global added_files
    for path in paths:
        content = read_file_content(path)
        if not content.startswith("❌"):
            added_files.append({'path': path, 'content': content})
            st.success(f"Added {path} to context.")
        else:
            st.error(content)

def handle_edit_command(paths):
    st.write("### Editing Files")
    for path in paths:
        content = read_file_content(path)
        if content.startswith("❌"):
            st.error(content)
            continue

        st.write(f"**Current content of {path}:**")
        st.code(content, language='python')

        user_request = st.text_area(f"What would you like to change in {path}?", height=150)

        if user_request:
            # Generate edit instructions
            instructions_prompt = f"User wants: {user_request}\nProvide LINE-BY-LINE edit instructions for the following code:\n```python\n{content}\n```"
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": instructions_prompt}
            ]
            response = make_api_call(messages, 500, is_final_answer=True)
            st.write("**Edit instructions:**")
            st.markdown(response['content'])

            # Here you would apply the edit instructions to the code
            # For simplicity, we just display the instructions

def handle_new_command(paths):
    for path in paths:
        if os.path.exists(path):
            st.warning(f"File {path} already exists.")
        else:
            with open(path, 'w') as f:
                f.write('')  # Create an empty file
            st.success(f"Created new file {path}.")

async def handle_search_command(query):
    st.write(f"### Searching for: {query}")
    results = await perform_search(query)
    for result in results:
        st.markdown(f"- **[{result['title']}]({result['href']})**: {result['body']}")

def handle_image_command(paths):
    for path in paths:
        if os.path.exists(path):
            st.image(path)
            st.success(f"Displayed image {path}.")
        else:
            st.error(f"Image {path} not found.")

def handle_clear_command():
    global added_files, undo_history, stored_searches, stored_images
    added_files = []
    undo_history = {}
    stored_searches = {}
    stored_images = {}
    st.success("Cleared assistant's context.")

def handle_reset_command():
    handle_clear_command()
    st.success("Assistant has been reset.")

def toggle_diff():
    global is_diff_on
    is_diff_on = not is_diff_on
    st.info(f"Diff display is now {'on' if is_diff_on else 'off'}.")

def handle_history_command():
    st.info("Displaying history is not yet implemented.")

def handle_save_command():
    st.info("Save history is not yet implemented.")

def handle_load_command():
    st.info("Load history is not yet implemented.")

def handle_undo_command(paths):
    st.info("Undoing changes is not yet implemented.")

def print_help():
    st.markdown("""
    ### Available Commands:
    - `/add <file_path>`: Add files to the assistant's context.
    - `/edit <file_path>`: Edit files.
    - `/new <file_path>`: Create new files.
    - `/search <query>`: Perform a web search.
    - `/image <image_path>`: Display images.
    - `/clear`: Clear the assistant's context.
    - `/reset`: Reset the assistant.
    - `/diff`: Toggle diff display.
    - `/history`: Display history.
    - `/save`: Save history.
    - `/load`: Load history.
    - `/undo <file_path>`: Undo changes to a file.
    - `/help`: Show help message.
    - `/model`: Show current model.
    - `/change_model`: Change the model.
    - `/show <file_path>`: Show file content.
    """)

def show_current_model():
    st.info(f"Current model: {DEFAULT_MODEL}")

def change_model():
    global DEFAULT_MODEL
    st.write("### Change Model")
    new_model = st.text_input("Enter new model name:", value=DEFAULT_MODEL)
    if st.button("Change Model"):
        DEFAULT_MODEL = new_model
        st.success(f"Model changed to: {DEFAULT_MODEL}")

def handle_show_command(paths):
    for path in paths:
        content = read_file_content(path)
        if content.startswith("❌"):
            st.error(content)
        else:
            st.write(f"**Content of {path}:**")
            st.code(content, language='python')

if __name__ == "__main__":
    main()
