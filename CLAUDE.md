# CLAUDE.md

This file provides guidance for AI assistants working in this repository.

## Project Overview

**hiburi-tools** is a tool management repository for HIBURI株式会社 (HIBURI Corporation). The repository is in its early stages and serves as a central place for managing internal tools.

## Repository Structure

```
hiburi-tools/
├── CLAUDE.md          # AI assistant guidance (this file)
└── README.md          # Project description
```

The repository is newly initialized. Source code, build configuration, and CI/CD have not yet been added.

## Git Conventions

### Branches

- `メイン` — Primary branch (remote default, Japanese naming convention)
- `master` — Local master branch
- Feature branches use the `claude/` prefix when created by AI assistants

### Commits

- Commits are signed using SSH-based GPG signing
- Write clear, descriptive commit messages in English
- Keep commits focused on a single logical change

## Language & Naming

- Repository metadata (branch names, README) uses Japanese where appropriate
- Code and technical documentation should be written in English unless otherwise specified
- Respect existing Japanese naming conventions in the project

## Development Workflow

Since the repository is in early stages, no build system, linter, or test framework is configured yet. When these are added, update this file with:

- Build and run commands
- Test commands and conventions
- Linting and formatting setup
- Environment variable requirements

## Guidelines for AI Assistants

1. **Read before modifying** — Always read existing files before making changes
2. **Minimal changes** — Only make changes that are directly requested
3. **Preserve conventions** — Follow existing naming and style patterns
4. **Update this file** — When adding new tooling, dependencies, or workflows, update this CLAUDE.md accordingly
