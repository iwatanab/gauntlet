"""python -m gauntlet — start the REST API server."""
import os
import uvicorn

def main():
    uvicorn.run(
        "gauntlet.api:app",
        host=os.environ.get("GAUNTLET_HOST", "0.0.0.0"),
        port=int(os.environ.get("GAUNTLET_PORT", "8000")),
        reload=os.environ.get("GAUNTLET_RELOAD", "false").lower() == "true",
        log_level="info",
    )

if __name__ == "__main__":
    main()
