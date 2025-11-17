# PostParse Documentation

Welcome to the PostParse documentation! This directory contains comprehensive guides and references for using PostParse.

## Documentation Structure

### 📖 [Index](index.md)
Start here for an overview of PostParse, its value proposition, and a quick example to get you started.

### 🚀 [Getting Started](getting_started.md)
Installation instructions, configuration setup, and your first data extraction. Perfect for new users.

**Covers:**
- Installation (pip/uv)
- Configuration files setup
- First Telegram extraction
- First Instagram extraction
- Basic content classification
- Common troubleshooting

### 👨‍🍳 [Cookbook](cookbook.md)
Task-oriented recipes for common workflows. Each recipe is a complete, working example.

**Recipes:**
1. Extract and Store Telegram Messages
2. Batch Process Instagram Posts
3. Classify Content with Recipe Detection
4. Search and Filter Saved Content
5. Build a Content Analysis Pipeline

### 📚 [API Reference](api_reference.md)
Complete reference for all public APIs, organized by module.

**Sections:**
- **Data Storage**: `SocialMediaDatabase` and query methods
- **Telegram Module**: `TelegramParser` and helper functions
- **Instagram Module**: `InstaloaderParser` and `InstagramAPIParser`
- **Analysis Module**: Classifiers (`RecipeClassifier`, `RecipeLLMClassifier`)
- **Configuration Module**: `ConfigManager` and convenience functions
- **Data Models**: `ClassificationResult` and related types
- **Error Handling**: Exception types and usage

## Quick Navigation

**I want to...**

- **Get started quickly** → [Getting Started](getting_started.md)
- **See practical examples** → [Cookbook](cookbook.md)
- **Look up a specific function** → [API Reference](api_reference.md)
- **Understand the project** → [Index](index.md)

## Documentation Philosophy

This documentation follows a three-tier structure:

1. **Easy onboarding** (Getting Started): Step-by-step guides for beginners
2. **Task-oriented** (Cookbook): Practical recipes for specific use cases
3. **Reference** (API Reference): Comprehensive technical documentation

Each section links to the others, so you can easily move between high-level concepts and detailed specifications.

## Contributing to Documentation

If you find errors or want to improve the documentation:

1. Documentation files are in Markdown format
2. Keep examples simple and focused
3. Update all three sections when adding new features
4. Ensure code examples are tested and working

## Additional Resources

- **[Performance Improvements](performance_improvements.md)**: Technical notes on optimization
- **Project Repository**: [github.com/sebpachl/postparse](https://github.com/sebpachl/postparse)
- **Issue Tracker**: Report bugs or request features on GitHub

