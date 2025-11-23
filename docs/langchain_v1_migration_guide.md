# LangChain v1 Migration Guide: Using `create_agent` with LiteLLM

## Overview

This guide explains how to migrate from our current class-based LLM provider implementation to LangChain v1's modern `create_agent()` approach, which uses **LangGraph** under the hood. The good news: **it's very easy and fully compatible with our existing LiteLLM setup!**

## Key Information

### What is LangChain v1?

- **Modern agent framework** built on top of LangGraph
- **Graph-based architecture** for state management and control flow
- **Middleware system** for composable behaviors (retry, fallback, caching)
- **Agent factory pattern** using `create_agent()` to assemble components declaratively

### What is LangGraph?

LangGraph is the underlying framework that powers LangChain v1 agents:
- **StateGraph**: Manages agent state across execution
- **Conditional edges**: Dynamic control flow with `jump_to`
- **Persistence**: Built-in checkpointing for conversation state
- **Interrupts**: Human-in-the-loop capabilities
- **Streaming**: Native streaming support for real-time responses

---

## Architecture Comparison

### Current Architecture (Class-Based)

```python
# backend/postparse/llm/provider.py
class LLMProvider(ABC):
    def chat(self, messages: List[Dict[str, str]], **kwargs: Any) -> str:
        pass
    
    def complete(self, prompt: str, **kwargs: Any) -> str:
        pass

class LiteLLMProvider(LLMProvider):
    def _retry_with_backoff(self, func, *args, **kwargs):
        # Manual retry logic
        pass
```

**Characteristics:**
- Linear execution model
- Instance variables for state
- Manual retry/fallback implementation
- Subclassing for extensibility

### Modern Architecture (Graph-Based)

```python
# Using langchain.agents.create_agent
from langchain.agents import create_agent
from langchain_litellm import ChatLiteLLM

agent = create_agent(
    model=ChatLiteLLM(...),  # Our existing LiteLLM setup!
    tools=[],
    middleware=[],  # Composable behaviors
    response_format=RecipeDetails  # Structured output
)

response = agent.invoke({"messages": [("user", "classify this")]})
```

**Characteristics:**
- Loop-based execution with conditional branching
- StateGraph for state management
- Middleware hooks for extensibility
- Built-in retry, fallback, streaming, persistence

---

## Compatibility with Our LiteLLM Setup

### ✅ Perfect Compatibility

**We're already using `ChatLiteLLM`** from `langchain-litellm`:

```python
# backend/postparse/services/analysis/classifiers/llm.py
from langchain_litellm import ChatLiteLLM

self.llm = ChatLiteLLM(**llm_kwargs)
```

**`create_agent` accepts `BaseChatModel`** (which `ChatLiteLLM` is):
- ✅ All our providers work: OpenAI, Anthropic, Ollama, LM Studio
- ✅ Our config.toml system stays unchanged
- ✅ API key management stays the same
- ✅ Local endpoints (LM Studio, Ollama) still work

---

## Migration Example

### Before: Current Implementation

```python
from backend.postparse.llm.provider import get_llm_provider

class RecipeLLMClassifier(BaseClassifier):
    def __init__(self, provider_name: Optional[str] = None):
        # Load config and create LiteLLM provider
        config = get_config()
        llm_config = LLMConfig.from_config_manager(config)
        provider_cfg = get_provider_config(llm_config, provider_name)
        
        # Create LiteLLM instance
        self.llm = ChatLiteLLM(
            model=provider_cfg.model,
            temperature=provider_cfg.temperature,
            api_key=provider_cfg.api_key,
            api_base=provider_cfg.api_base
        )
        
        self.output_parser = PydanticOutputParser(pydantic_object=RecipeDetails)
        self.prompt = PromptTemplate(...)
    
    def predict(self, X: str) -> ClassificationResult:
        formatted_prompt = self.prompt.format(content=X)
        response = self.llm.invoke(formatted_prompt)
        details = self.output_parser.parse(response.content)
        return ClassificationResult(...)
```

### After: Modern create_agent Approach

```python
from langchain.agents import create_agent
from langchain_litellm import ChatLiteLLM

class RecipeLLMClassifier(BaseClassifier):
    def __init__(self, provider_name: Optional[str] = None):
        # SAME config loading as before
        config = get_config()
        llm_config = LLMConfig.from_config_manager(config)
        provider_cfg = get_provider_config(llm_config, provider_name)
        
        # SAME LiteLLM setup as before
        llm = ChatLiteLLM(
            model=provider_cfg.model,
            temperature=provider_cfg.temperature,
            api_key=provider_cfg.api_key,
            api_base=provider_cfg.api_base
        )
        
        # NEW: Create agent instead of bare LLM
        self.agent = create_agent(
            model=llm,  # Pass our LiteLLM instance!
            tools=[],   # No tools needed for classification
            response_format=RecipeDetails,  # Structured output (replaces parser!)
            system_prompt="You are a recipe classifier. Analyze if content is a recipe and extract details."
        )
    
    def predict(self, X: str) -> ClassificationResult:
        # Invoke agent (uses graph under the hood)
        result = self.agent.invoke({
            "messages": [("user", f"Classify: {X}")]
        })
        
        # Get structured response (automatically parsed!)
        details = result["structured_response"]
        confidence = self._calculate_confidence(details)
        
        return ClassificationResult(
            label="recipe" if details.is_recipe else "not_recipe",
            confidence=confidence,
            details=details.model_dump()
        )
```

**What Changed?**
- ✅ Config system: **UNCHANGED**
- ✅ LiteLLM setup: **UNCHANGED**
- ✅ Multi-provider support: **PRESERVED**
- ✅ Code changes: **~10 lines**

---

## Benefits of Migration

### Immediate Benefits (No Extra Code)

| Feature | Current Implementation | With create_agent |
|---------|----------------------|-------------------|
| **Simple invocation** | ✅ `llm.invoke()` | ✅ `agent.invoke()` |
| **Streaming** | ❌ Not implemented | ✅ `agent.stream()` built-in |
| **Batch processing** | ❌ Manual loops | ✅ `agent.batch()` built-in |
| **Retry logic** | ⚠️ Manual `_retry_with_backoff()` | ✅ Built-in with middleware |
| **Fallback providers** | ❌ Not implemented | ✅ `ModelFallbackMiddleware` |
| **Structured output** | ⚠️ Manual parsing | ✅ Automatic with `response_format` |
| **State persistence** | ❌ Not supported | ✅ LangGraph checkpointer |
| **Tool calling** | ❌ Not supported | ✅ Native support with loops |

### Advanced Features (Optional)

```python
from langchain.agents.middleware import (
    ModelFallbackMiddleware,
    ToolRetryMiddleware,
    HumanInTheLoopMiddleware
)

# Add automatic fallback
agent = create_agent(
    model=llm_primary,
    middleware=[
        ModelFallbackMiddleware(
            llm_fallback_1,  # Try this if primary fails
            llm_fallback_2   # Then try this
        )
    ],
    response_format=RecipeDetails
)

# Add human approval for certain operations
agent = create_agent(
    model=llm,
    tools=[send_email_tool, delete_file_tool],
    middleware=[
        HumanInTheLoopMiddleware(
            interrupt_on={
                "send_email": True,  # Require approval
                "delete_file": True
            }
        )
    ]
)
```

---

## Practical Code Examples

### Example 1: Simple Classification (Minimal Changes)

```python
from langchain.agents import create_agent
from langchain_litellm import ChatLiteLLM
from backend.postparse.llm.config import get_provider_config, LLMConfig
from backend.postparse.core.utils.config import get_config

def create_recipe_classifier_agent(provider_name: Optional[str] = None):
    """Create a recipe classifier agent using our existing config."""
    # Use our existing configuration system
    config = get_config()
    llm_config = LLMConfig.from_config_manager(config)
    provider_cfg = get_provider_config(
        llm_config, 
        provider_name or llm_config.default_provider
    )
    
    # Create ChatLiteLLM with our config
    llm = ChatLiteLLM(
        model=provider_cfg.model,
        temperature=provider_cfg.temperature,
        api_key=provider_cfg.api_key,
        api_base=provider_cfg.api_base,
        timeout=provider_cfg.timeout,
        max_tokens=provider_cfg.max_tokens
    )
    
    # Create agent with graph-based architecture
    agent = create_agent(
        model=llm,
        tools=[],
        response_format=RecipeDetails,
        system_prompt="""You are a recipe classifier.
        Analyze if the content is a recipe and extract key details:
        - cuisine_type
        - difficulty
        - meal_type
        - ingredients_count
        """
    )
    
    return agent

# Usage
agent = create_recipe_classifier_agent("openai")
result = agent.invoke({"messages": [("user", "Chocolate Chip Cookies recipe...")]})
details = result["structured_response"]  # RecipeDetails object
```

### Example 2: With Fallback Providers

```python
from langchain.agents import create_agent
from langchain.agents.middleware import ModelFallbackMiddleware
from langchain_litellm import ChatLiteLLM

def create_agent_with_fallback():
    """Create agent with automatic fallback to cheaper/local models."""
    config = get_config()
    llm_config = LLMConfig.from_config_manager(config)
    
    # Primary: OpenAI GPT-4
    primary = ChatLiteLLM(
        model="gpt-4o-mini",
        api_key=get_provider_config(llm_config, "openai").api_key
    )
    
    # Fallback 1: Local Ollama
    fallback_local = ChatLiteLLM(
        model="ollama/llama3.2",
        api_base="http://localhost:11434",
        custom_llm_provider="ollama"
    )
    
    # Fallback 2: LM Studio
    fallback_lmstudio = ChatLiteLLM(
        model="gpt-3.5-turbo",  # LM Studio model name
        api_base="http://localhost:1234/v1",
        custom_llm_provider="openai"
    )
    
    agent = create_agent(
        model=primary,
        middleware=[
            ModelFallbackMiddleware(fallback_local, fallback_lmstudio)
        ],
        response_format=RecipeDetails,
        system_prompt="Classify recipes"
    )
    
    return agent

# Automatically tries: GPT-4 → Ollama → LM Studio
result = agent.invoke({"messages": [("user", text)]})
```

### Example 3: Streaming Support

```python
# Create agent
agent = create_recipe_classifier_agent()

# Stream responses in real-time
for chunk in agent.stream({"messages": [("user", "Classify this recipe...")]}):
    if "messages" in chunk:
        for msg in chunk["messages"]:
            print(msg.content, end="", flush=True)

# Final structured response
if "structured_response" in chunk:
    details = chunk["structured_response"]
    print(f"\n\nClassification: {details.is_recipe}")
```

### Example 4: Batch Processing

```python
agent = create_recipe_classifier_agent()

# Process multiple recipes in parallel
texts = [
    "Chocolate chip cookies recipe...",
    "How to fix a leaky faucet...",
    "Spaghetti carbonara recipe..."
]

# Batch invoke
results = agent.batch([
    {"messages": [("user", f"Classify: {text}")]}
    for text in texts
])

for result in results:
    details = result["structured_response"]
    print(f"{details.is_recipe}: {details.cuisine_type}")
```

---

## Integration with Our Existing Services

### TelegramExtractionService Integration

```python
# backend/postparse/api/services/extraction_service.py
from langchain.agents import create_agent
from langchain_litellm import ChatLiteLLM

class TelegramExtractionService:
    def __init__(self, job_manager, ws_manager, db):
        self.job_manager = job_manager
        self.ws_manager = ws_manager
        self.db = db
        
        # Create classification agent
        self.classifier_agent = self._create_classifier_agent()
    
    def _create_classifier_agent(self):
        """Create agent using our LiteLLM config."""
        config = get_config()
        llm_config = LLMConfig.from_config_manager(config)
        provider_cfg = get_provider_config(llm_config, llm_config.default_provider)
        
        llm = ChatLiteLLM(
            model=provider_cfg.model,
            temperature=provider_cfg.temperature,
            api_key=provider_cfg.api_key,
            api_base=provider_cfg.api_base
        )
        
        return create_agent(
            model=llm,
            tools=[],
            response_format=RecipeDetails,
            system_prompt="Classify social media posts as recipes"
        )
    
    async def classify_message(self, content: str) -> dict:
        """Classify message using agent."""
        result = await self.classifier_agent.ainvoke({
            "messages": [("user", f"Classify: {content}")]
        })
        return result["structured_response"].model_dump()
```

---

## Installation

### Required Packages

```bash
# Install langchain v1 with LangGraph
pip install langchain langgraph langchain-litellm

# Or with uv
uv pip install langchain langgraph langchain-litellm
```

### Package Versions

- `langchain` (v1.0.5+) - Modern agent framework
- `langgraph` (≥1.0.2, <1.1.0) - Graph engine (auto-installed)
- `langchain-core` (≥1.0.4, <2.0.0) - Core abstractions (auto-installed)
- `langchain-litellm` - LiteLLM integration for LangChain

---

## Configuration

### Our Existing config.toml Works As-Is!

```toml
# config/config.toml
[llm]
default_provider = "openai"
enable_fallback = true
cache_responses = false

[[llm.providers]]
name = "openai"
model = "gpt-4o-mini"
temperature = 0.7
max_tokens = 2000
timeout = 60
max_retries = 3

[[llm.providers]]
name = "ollama"
model = "llama3.2"
api_base = "http://localhost:11434"
temperature = 0.7

[[llm.providers]]
name = "lm_studio"
model = "gpt-3.5-turbo"
api_base = "http://localhost:1234/v1"
temperature = 0.7
```

**No changes needed** - just wrap the LiteLLM instance in `create_agent()`.

---

## Middleware: Composable Behaviors

One of the biggest advantages of `create_agent` is middleware. Here are useful middleware for our use cases:

### 1. ModelFallbackMiddleware

```python
from langchain.agents.middleware import ModelFallbackMiddleware

# Automatically try multiple providers
agent = create_agent(
    model=primary_llm,
    middleware=[
        ModelFallbackMiddleware(
            fallback_ollama,     # Try local Ollama if primary fails
            fallback_lmstudio    # Then try LM Studio
        )
    ]
)

# Agent automatically falls back on errors!
```

### 2. ContextEditingMiddleware

```python
from langchain.agents.middleware import ContextEditingMiddleware
from langchain.agents.middleware.context_editing import ClearToolUsesEdit

# Automatically clear old messages to stay under token limits
agent = create_agent(
    model=llm,
    middleware=[
        ContextEditingMiddleware(
            edits=[
                ClearToolUsesEdit(
                    trigger=100_000,  # Token threshold
                    keep=3,           # Keep last 3 tool results
                    placeholder="[cleared]"
                )
            ]
        )
    ]
)
```

### 3. Custom Middleware with Decorators

```python
from langchain.agents.middleware import before_model, after_model, wrap_model_call

# Log every model call
@before_model
def log_model_call(state, runtime):
    print(f"Calling model with {len(state['messages'])} messages")
    return None

# Add retry with custom logic
@wrap_model_call
def custom_retry(request, handler):
    for attempt in range(3):
        try:
            return handler(request)
        except Exception as e:
            if attempt == 2:
                raise
            print(f"Retry {attempt + 1}/3")
    return None

agent = create_agent(
    model=llm,
    middleware=[log_model_call, custom_retry]
)
```

---

## Advanced Features

### 1. Structured Output (Automatic Parsing)

```python
from pydantic import BaseModel, Field

class RecipeDetails(BaseModel):
    is_recipe: bool
    cuisine_type: Optional[str]
    difficulty: Optional[str]

# Agent automatically returns parsed Pydantic model!
agent = create_agent(
    model=llm,
    response_format=RecipeDetails  # No manual parsing needed
)

result = agent.invoke({"messages": [("user", "Classify this")]})
details = result["structured_response"]  # RecipeDetails instance
print(details.cuisine_type)  # Direct access to fields
```

### 2. State Persistence

```python
from langgraph.checkpoint.memory import MemorySaver

# Persist conversation state across invocations
checkpointer = MemorySaver()
agent = create_agent(
    model=llm,
    checkpointer=checkpointer
)

# First conversation
thread_id = {"thread_id": "user123"}
result1 = agent.invoke(
    {"messages": [("user", "Classify this recipe")]},
    config={"configurable": thread_id}
)

# Second conversation (remembers context!)
result2 = agent.invoke(
    {"messages": [("user", "What was the last recipe?")]},
    config={"configurable": thread_id}
)
```

### 3. Tool Calling (If Needed)

```python
from langchain_core.tools import tool

@tool
def search_recipe_database(query: str) -> str:
    """Search our recipe database for similar recipes."""
    # Your search logic
    return f"Found 5 similar recipes for {query}"

agent = create_agent(
    model=llm,
    tools=[search_recipe_database],  # Agent can use tools!
    response_format=RecipeDetails
)

# Agent automatically decides when to call tools
result = agent.invoke({
    "messages": [("user", "Is this similar to any recipes we have?")]
})
```

---

## Migration Checklist

### Step 1: Install Dependencies
```bash
uv pip install langchain langgraph langchain-litellm
```

### Step 2: Update Imports
```python
# Add new imports
from langchain.agents import create_agent
from langchain_litellm import ChatLiteLLM  # Already using this!
```

### Step 3: Wrap LLM in create_agent
```python
# Instead of:
self.llm = ChatLiteLLM(...)

# Do:
llm = ChatLiteLLM(...)
self.agent = create_agent(model=llm, tools=[], response_format=YourModel)
```

### Step 4: Update Invocation
```python
# Instead of:
response = self.llm.invoke(prompt)

# Do:
result = self.agent.invoke({"messages": [("user", prompt)]})
details = result["structured_response"]
```

### Step 5: Update Tests
```python
# Test agents return dict with "messages" and "structured_response"
result = agent.invoke({"messages": [("user", "test")]})
assert "structured_response" in result
assert isinstance(result["structured_response"], RecipeDetails)
```

---

## Migration Effort Estimate

### Time Investment

| Task | Estimated Time | Complexity |
|------|---------------|------------|
| Install packages | 5 minutes | ⭐☆☆☆☆ |
| Update one classifier | 30 minutes | ⭐⭐☆☆☆ |
| Update all classifiers | 2-3 hours | ⭐⭐☆☆☆ |
| Update tests | 1-2 hours | ⭐⭐☆☆☆ |
| Add middleware (optional) | 1-3 hours | ⭐⭐⭐☆☆ |
| **Total (basic migration)** | **4-6 hours** | **⭐⭐☆☆☆** |

---

## Key Differences: Graph vs. Class

| Aspect | Class-Based (Current) | Graph-Based (create_agent) |
|--------|----------------------|---------------------------|
| **Execution** | Linear method calls | Loop with conditional branching |
| **State** | Instance variables | StateGraph channels |
| **Retry** | Manual `_retry_with_backoff()` | Middleware |
| **Extensibility** | Subclassing | Middleware composition |
| **Control flow** | Fixed sequence | Dynamic with `jump_to` |
| **Persistence** | None | LangGraph checkpointer |
| **Streaming** | Manual | Built-in |
| **Tool loops** | N/A | Automatic |

---

## When to Migrate vs. When to Keep Current

### ✅ Migrate to create_agent If:

- You want **streaming support** for real-time responses
- You need **automatic fallback** between providers
- You want **tool calling** capabilities (search, API calls, etc.)
- You need **state persistence** across API calls
- You want **simpler structured output** handling
- You're building **multi-step workflows**

### ⏸️ Keep Current Architecture If:

- You're doing **simple, single-shot LLM calls**
- You don't need **streaming or batching**
- You don't need **tool calling**
- Current implementation **works perfectly**
- Team is **unfamiliar with agent patterns**

---

## Comparison: Direct LiteLLM vs. LangChain Integration

### Option A: Our Current LiteLLMProvider (Standalone)

**Pros:**
- ✅ Simple, straightforward
- ✅ Works with any provider
- ✅ Full control over implementation
- ✅ No framework dependencies

**Cons:**
- ❌ No streaming support
- ❌ No batch processing
- ❌ Manual retry logic
- ❌ No state persistence
- ❌ No tool calling

### Option B: LangChain's ChatLiteLLM + create_agent

**Pros:**
- ✅ All the above PLUS:
- ✅ Streaming built-in
- ✅ Batch processing built-in
- ✅ Middleware for retry/fallback
- ✅ State persistence with checkpointer
- ✅ Tool calling support
- ✅ Structured output simplified
- ✅ **Still works with all LiteLLM providers**

**Cons:**
- ⚠️ Framework dependency (langchain + langgraph)
- ⚠️ Learning curve for advanced features
- ⚠️ More complex for simple use cases

---

## Common Questions

### Q: Do we need to change our config.toml?
**A:** No! Your existing config system works perfectly. Just wrap the ChatLiteLLM instance.

### Q: Will Ollama/LM Studio still work?
**A:** Yes! All providers supported by LiteLLM work with `create_agent`.

### Q: Can we mix providers in one agent?
**A:** Yes! Use `ModelFallbackMiddleware` to try multiple providers.

### Q: Do we need tools for simple classification?
**A:** No! Pass `tools=[]` for simple LLM calls without tool calling.

### Q: What about our custom retry logic?
**A:** Can keep it or use built-in middleware. Both work.

### Q: Is the graph-based approach slower?
**A:** No - the graph overhead is negligible. You get the same performance with more features.

---

## Next Steps

### Recommended Migration Path

1. **Phase 1: Proof of Concept** (1 day)
   - Migrate one classifier (e.g., `RecipeLLMClassifier`)
   - Test with all providers (OpenAI, Ollama, LM Studio)
   - Verify structured output works

2. **Phase 2: Core Services** (2-3 days)
   - Migrate remaining classifiers
   - Update extraction services
   - Add streaming support where beneficial

3. **Phase 3: Advanced Features** (optional, 1-2 weeks)
   - Add middleware for retry/fallback
   - Implement tool calling if needed
   - Add state persistence for conversations
   - Implement human-in-the-loop for sensitive operations

---

## References

- **LangChain v1 Documentation**: https://docs.langchain.com/
- **LangGraph Documentation**: https://langchain-ai.github.io/langgraph/
- **LiteLLM Documentation**: https://docs.litellm.ai/
- **Our LLM Provider Guide**: `docs/llm_providers.md`
- **DeepWiki LangChain**: https://deepwiki.com/search/what-is-langgraph-and-how-does

---

## Conclusion

**The modern `create_agent()` approach is a drop-in enhancement for our LiteLLM setup:**

✅ **Easy Migration**: 4-6 hours for basic migration  
✅ **Full Compatibility**: All LiteLLM providers work  
✅ **Config Preserved**: No changes to config.toml  
✅ **Incremental Adoption**: Can migrate one service at a time  
✅ **Powerful Features**: Streaming, batching, middleware, tools, persistence  

**Bottom line**: You get the modern graph-based architecture (with all its benefits) while keeping your flexible LiteLLM multi-provider setup. Best of both worlds!

---

*Last Updated: 2025-11-23*  
*Version: 1.0*  
*Author: PostParse Team*

