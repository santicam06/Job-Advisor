import os, sys
from pydantic import BaseModel, Field
from typing import cast, Literal
from tavily import TavilyClient
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
tavily = TavilyClient(api_key=TAVILY_API_KEY)
TAVILY_SEARCH_DEPTH = cast(Literal['basic', 'advanced', 'fast', 'ultra-fast'], os.getenv("TAVILY_SEARCH_DEPTH", "basic"))
TAVILY_MAX_RESULTS = int(os.getenv("TAVILY_MAX_RESULTS", "4"))


# Performs web_search and cleans content to be LLM friendly
# To be used in schema below
def get_web_results(query: str) -> str:

    # Web search with model's query
    raw_response = tavily.search(
        query=query,
        search_depth=TAVILY_SEARCH_DEPTH,
        max_results=TAVILY_MAX_RESULTS,
        include_answer=True,
        include_raw_content=False,
        include_images=False
    )

    print(f"[DEBUG]     web_search tool called with query: {query}", file=sys.stderr)
    
    results = raw_response.get("results", [])
    result_count = len(results)
    top_url = results[0]["url"] if results else "N/A"
    print(f"[DEBUG] Search returned {result_count} results, top: {top_url}", file=sys.stderr)

    # Initialize response pack for LLM
    web_results = [f"Web search for query: {raw_response['query']}\n"]

    # If answer attribute is not null in dictionary param
    if raw_response.get("answer"):
        web_results.append(f"Summary: {raw_response['answer']}\n")

    web_results.append("Sources:")
    for i, result in enumerate(raw_response["results"], 1):
        web_results.append(
            f"\n{i}. {result['title']}\n"
            f"   URL: {result['url']}\n"
            f"   Content: {result['content']}\n"
            f"   Relevance score: {result['score']:.2f}"
        )

    return "\n".join(web_results)


class web_search(BaseModel):
    """Tool used to search in the web for relevant information about a company, job roles and related topics to a job posting in order to help an applicant for it"""
    query: str = Field(description="The search query to use based on the desired information to fetch in the web")
    
