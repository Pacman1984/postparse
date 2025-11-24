# PostParse CLI

Beautiful command-line interface for social media content extraction and analysis.

## Overview

PostParse CLI provides a modern, colorful terminal interface for all PostParse functionality. Built with Click and Rich, it offers progress bars, tables, and styled output for an excellent user experience.

## Quick Navigation

### 📚 [Getting Started](getting_started.md)
First-time setup, installation, and basic usage.

### 🍳 [Cookbook](cookbook.md)
Practical recipes and common workflows.

### 📖 [Reference](reference.md)
Complete command reference and options.

## Quick Example

```bash
# Check your database
postparse stats

# Check for new content (fast preview)
postparse check

# Extract from Telegram (Saved Messages only)
export TELEGRAM_API_ID=12345678
export TELEGRAM_API_HASH=abc123def456
postparse extract telegram --limit 100

# Search for recipes
postparse search posts --hashtag recipe

# Start API server
postparse serve
```

## Features

- 🎨 **Beautiful Output** - Rich-styled console with colors and panels
- 📊 **Progress Bars** - Real-time tracking with spinners and estimates
- ⚡ **Fast** - Async operations for optimal performance
- 🔧 **Flexible** - Environment variables or command-line options
- 📋 **Organized** - Grouped commands with smart help

## Need Help?

```bash
postparse --help              # All commands
postparse COMMAND --help      # Specific command help
postparse info                # System information
```

---

**Version:** 0.1.0 | **Last Updated:** November 23, 2025

