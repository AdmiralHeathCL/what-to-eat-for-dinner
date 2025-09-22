<h1 align="center">
  <br>
  What to Eat for Dinner - MCP Tool
  <br>
</h1>


## Overview

This project is a Model Context Protocol (MCP) server that helps users decide what to eat by recommending restaurants tailored to their preferences and location. The tool integrates Yelp API to fetch restaurant data (ratings, categories, reviews, etc.) and layers in memory-based conversation to handle follow-ups.

*“What should I eat in Waterloo tonight?”*

*“Make it closer and cheaper, no bananas.”*

*“Search again!”*


## Features

**Restaurant search**: Finds restaurants by location (address or coordination), cuisine, rating, and budget.

**Memory-enabled conversation**: Stores user preferences and last queries to enable follow-up refinements.

**Ranking**: Scores restaurants by rating, reviews, distance, price alignment, and keyword matches.

**Refinement**: Allows follow-up instructions like “closer”, “cheaper”, “not ramen”, “family-friendly”.

**Resources**: Exposes a dinner-memory://<profile> resource to inspect stored state.



## How It Works

**User Preferences** (set_dinner_prefs)
Users can set preferences such as cuisines, dietary restrictions, budget ($ to $$$$), distance, rating threshold, and items to avoid. These are stored in an in-memory STATE keyed by profile.

**Initial Search** (find_dinner)
The tool queries Yelp with merged preferences + user query (e.g., “location=Waterloo, cuisines=sushi, budget=$$”).
Restaurants are scored and sorted using a composite function:

- Rating

- Review count (diminishing returns)

- Distance penalty (further = lower score)

- Price alignment with budget

- Keyword matches (e.g., “spicy”)

**Follow-up Refinement** (refine_dinner)
Follow-up instructions are parsed to adjust the last query. Examples:

- “closer” → reduces max distance

- “cheaper” → lowers budget category

- “not banana” → adds “banana” to avoid list

- “date night” → raises min rating and adds vibe

The tool reranks results and offers the option to search_again for fresh results.

**Memory Resource** (dinner-memory://profile)
Profiles persist while the server is running. Memory includes preferences, last query, and last results, enabling conversational continuity.


## Installation
 
Create a virtual environment and install dependencies:

```bash
uv venv
uv pip install -r pyproject.toml
```

[YELP_API_KEY](https://www.yelp.com/developers) needs to be filled in .env

## Deepchat Setup

* Download and setup [Deepchat](https://deepchat.thinkinai.xyz/)
* Click on Settings > MCP Settings > Add Server > Skip to Manual Configuration
* Configurations:
  - Server Type: Stdio
  - Command: python
  - Arguments: your\path\to\mcp-demo\main.py (**Important:** After enter the path, hit Space or Enter, or it will not be saved)
  - Auto Approve: All
* After successful setup, you should see your mcp server in Server List > Custom Servers
* Click on Start Server button to start your mcp server. You can also start the server by clicking on the "**hammer icon**" inside chatbox.
* After server start, you can find your active functions in tools, prompts and resources. In the case of the code provided, you should see add and get_weather functions in **Tools** and greeting://bim in **Resources**.

For more information please check [Deepchat MCP User Manual](https://github.com/ThinkInAIXYZ/deepchat/wiki/MCP-%E4%BD%BF%E7%94%A8%E6%89%8B%E5%86%8C)
