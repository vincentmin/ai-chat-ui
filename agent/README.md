# Logfire Docs chatbot

## Usage

Make sure you have `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` or `GEMINI_API_KEY` set in your environment variables.

Run the agent backend + pre-packaged frontend:

```bash
cd agent
uv sync
uv run --env-file=../.env.local uvicorn chatbot.server:app
```

Start the Taskiq worker in a separate terminal:

```bash
cd agent
uv run --env-file=../.env.local taskiq worker chatbot.tasks.worker:broker
```

Then open your browser to `http://localhost:8000`.

### Frontend development

Optionally run the frontend in dev mode, which will connect to the running agent backend:

```bash
npm install
npm run dev
```

Then open your browser to `http://localhost:5173`.
