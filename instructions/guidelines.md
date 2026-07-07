# Project Guidelines

## Tools and Libraries

- Instaloader for Instagram data extraction
- Langchain for LLM integration
- Ollama Server for local model execution
- OpenAI/Anthropic models for markdown generation

## Coding Standards

- Follow PEP 8 for code style
- Use type hints
- Use inline comments to explain "why" behind the code extensively. Be very verbose.
- Write unit tests
- Document code with docstrings google style. Be very verbose and explain "what" and "why" behind the code, maybe examples.

## Project Structure

## Remember

Scraping

- If some scraping logic is implemented, first be very careful with it and implement safeguards to avoid being blocked.
  - Use specialised packages for scraping (like Instaloader) if possible.
  - Saveguards are: Use sleep between requests, use delays between actions, don't make too many requests in a row.
