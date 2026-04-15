import os
import subprocess
from dataclasses import dataclass
from anthropic import Anthropic
from dotenv import load_dotenv
from pathlib import Path

os.system('')  # 开启 Windows PowerShell 颜色支持
os.environ["ANSICON"] = "on"
load_dotenv(override=True)
SYSTEM = "You are coding agent at {os.getcwd()}. Use bash to inspect and change the workespace. Act first, then report clearly."
'''
TOOLS = [{
    "name":"BASH",
    "description":"run a command shell",
    "input_schema":{
        "type":"object",
        "properties":{"command":{"type":"string"}},
        "required":["command"],
    }
}]
'''
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
}
TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
]
WORKDIR = Path.cwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]


@dataclass
class Loopstate:
    message: list
    turn_count: int = 1
    transition_reason: str|None = None

def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path

def run_bash(command:str) ->str:
    dangerous = ["rm -rf", "sudo", "shutdown", "reboot"]
    if any(item in command for item in dangerous):
        return "error:dangerous!"
    result = subprocess.run(
        command,
        shell=True,
        #["powershell", "-Command", command],
        cwd=os.getcwd(),
        capture_output=True,
        text=True,
        timeout=120,
        encoding='gbk',
        errors='replace'  
    )
    output = (result.stdout + result.stderr).strip()
    return output[:50000] if output else "(no output)"

def run_read(path: str, limit: int = None) -> str:
    try:
        text = safe_path(path).read_text()
        lines = text.splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"



def excute_tool_calls(response_content) ->list[dict]:
    result = []
    for block in response_content:
        if block.type != "tool_use":
            continue
        """
        command = block.input["command"]    
        #excute cmd
        output = run_bash(command)
        print(output[:200])
        result.append({
            "type":"tool_result",
            "tool_use_id":block.id,
            "content":output
        })
        """
        hanlder = TOOL_HANDLERS.get(block.name)
        output = hanlder(**block.input) if hanlder else  f"Unknown tool: {block.name}"
        print(f">{block.name}:")
        print(output[:200])
        result.append({"type":"tool_result", "tool_use_id":block.id, "content":output})


    return result


def run_one_turn(state: Loopstate)->bool:
    response = client.messages.create(
        model=MODEL,
        system=SYSTEM,
        messages=state.message,
        tools=TOOLS,
        max_tokens=8000,
    )
    #must add client's response
    state.message.append({"role":"assistant","content":response.content})
    
    #if not use tool, return 
    if response.stop_reason != "tool_use":
        state.transition_reason = None
        return False
    #start using tool
    results = excute_tool_calls(response.content)
    if not results:
        state.transition_reason = None
        return False
    state.message.append({"role":"user","content":results})
    state.turn_count += 1
    state.transition_reason = "tool_result"
    return True

def extract_text(content) ->str:
    if not isinstance(content, list):
        return ""
    texts = []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            texts.append(text)
    return "\n".join(texts).strip()

def agent_loop(state: Loopstate) ->None:
    #start one turn
    while run_one_turn(state):
        pass

if __name__ == "__main__":
    history = []
    while True:
        query = input("\u001b[36m请输入 >> \u001b[0m")
        if query.strip().lower() in ("exit"):
            break
        history.append({"role":"user","content":query})
        state = Loopstate(message = history)
        #start agent loop
        agent_loop(state)




