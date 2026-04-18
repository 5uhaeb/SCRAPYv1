from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from scraper_common import run_scrape
from scrape_vijaysales import run as run_vijaysales
from scrape_webscraper_ecom import run as run_webscraper


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScrapeRequest(BaseModel):
    site: str
    keywords: List[str]
    pages: int = 2
    url: Optional[str] = None


@app.get("/")
def home():
    return {"message": "Scraper API is running"}


    try:
        results = []
        if site == "vijaysales":
            results = run_vijaysales(keywords, pages=req.pages, json_out="vijaysales_mobiles.json")
            msg = f"VijaySales: {len(results)} products matched"
        elif site == "webscraper":
            results = run_webscraper(keywords, pages_per_cat=req.pages)
            msg = f"Webscraper: {len(results)} products matched"
        elif site == "gsmarena":
            if not req.url or not req.url.strip():
                raise HTTPException(status_code=400, detail="GSMArena URL is required")
            results = run_scrape("gsmarena", req.url.strip(), keywords, json_out="scraped.json")
            msg = f"GSMArena: {len(results)} products matched"
        else:
            raise HTTPException(status_code=400, detail="Unsupported site")
            
        return {"message": msg, "products": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))