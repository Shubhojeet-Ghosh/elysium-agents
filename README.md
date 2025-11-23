# elysium-agents

Core infrastructure and implementation for autonomous AI agents. Modular architecture for building and orchestrating intelligent systems.

## Overview

elysium-agents provides a modular architecture for creating AI agents with customizable behaviors, tool integrations, and orchestration capabilities. Whether you're building chatbots, automation agents, or complex multi-agent systems, this repository offers the foundational components you need.

## Features

- **Modular Architecture**: Build agents with reusable, composable components
- **Orchestration Framework**: Coordinate multiple agents and manage workflows
- **Tool Integration**: Easy integration with external APIs and services
- **Extensible Design**: Add custom behaviors and capabilities
- **Production-Ready**: Built with scalability and reliability in mind

## Getting Started

### Prerequisites

- Python 3.11+ (as specified in `pyproject.toml`)
- [uv](https://github.com/astral-sh/uv) for package management

### Installation

1. **Clone the repository** (if applicable):

   ```bash
   git clone <repository-url>
   cd elysium-agents
   ```

2. **Install dependencies using uv**:

   ```bash
   uv sync
   ```

   This will install all Python dependencies including Playwright.

3. **Install Playwright browsers**:
   After installing the Python package, you need to install the browser binaries:

   ```bash
   uv run playwright install chromium
   ```

   For production environments, you may want to install only the system dependencies:

   ```bash
   uv run playwright install-deps chromium
   ```

   ```bash
   playwright install-deps
   ```

   ```bash
   playwright install
   ```
