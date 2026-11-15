import uvicorn

if __name__ == "__main__":
    uvicorn.run("landing_site_analyzer.app:app", host="127.0.0.1", port=8000, reload=False)
