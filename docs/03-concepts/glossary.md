# Glossary

| Term | Definition |
|------|------------|
| **content_id** | Row ID in `telegram_messages` or `instagram_posts` |
| **content_source** | `'telegram'` or `'instagram'` |
| **content_expanded** | Scraped text from URLs in messages (title, description, body) |
| **classifier_name** | Identifier for classifier type: `recipe_llm`, `multiclass_llm`, `multilabel_llm` |
| **run_id** | UUID grouping multi-label results for the same item |
| **content_analysis** | Table storing classification results |
| **provider_name** | LLM provider from config: `ollama`, `lm_studio`, `openai`, etc. |
