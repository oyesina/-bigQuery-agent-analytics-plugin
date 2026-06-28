import os
import uuid
import asyncio
import google.auth
import dotenv
from google.genai import types
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.runners import InMemoryRunner
from google.adk.tools import AgentTool, google_search
from google.adk.integrations.bigquery import BigQueryCredentialsConfig, BigQueryToolset
from google.adk.plugins.bigquery_agent_analytics_plugin import BigQueryAgentAnalyticsPlugin

dotenv.load_dotenv()

# --- Configuration ---

PROJECT_ID = os.getenv('GOOGLE_CLOUD_PROJECT', 'project_not_set')
DATASET_ID = "adk_logs"
TABLE_ID = "retail_assistant_agent_logs"
APP_NAME = "retail_assistant_agent"
USER_ID = "test_user"

# --- Toolsets ---

credentials, _ = google.auth.default()
credentials_config = BigQueryCredentialsConfig(credentials=credentials)
bigquery_toolset = BigQueryToolset(
 credentials_config=credentials_config
)

# --- Agents ---

# 1. Trend Spotter
real_time_agent = Agent(
   name="real_time_agent",
   model="gemini-2.5-flash",
    description="Researches external factors like weather, local events, and current fashion trends.",
   instruction="""
       You are a real-time research agent.
       Use Google Search to find real-time information relevant to the user's request,
       such as the current weather in their location or trending styles.
   """,
   tools=[google_search]
)

# 2. Inventory Manager
inventory_data_agent = Agent(
   name="inventory_data_agent",
   model="gemini-2.5-flash",
   description="Oversees product inventory in the BigQuery `thelook_ecommerce` dataset to find available items and prices.",
   instruction=f"""
   You manage the inventory. You have access to the `bigquery-public-data.thelook_ecommerce` dataset via the BigQuery toolset.
   Run all BigQuery queries the project id of: '{PROJECT_ID}'
  
   Your workflow:
   1. Look at the products table.
   2. Find items that match the requirements, factor in the results from the trend_setter agent if there are any.
   3. Return with a user friendly response, including the list of specific products and prices.
   """,
   tools=[bigquery_toolset]
)

# 3. Root Orchestrator
root_agent = Agent(
   name="retail_assistant",
   model="gemini-2.5-flash",   
   description="The primary orchestrator, responsible for handling user input, delegating to sub-agents, and synthesizing the final product recommendation.",
   instruction="""
   You are a Retail Assistant.   
   You can ask the 'real_time_agent' agent for any realtime information needed, or style advice, include any information provided by the user.
   You should ask the 'inventory_data_agent' agent to find a maximum of 3 available items matching that style.
   Combine the results into a recommendation.
   """,
   tools=[AgentTool(agent=real_time_agent)],
   sub_agents=[inventory_data_agent]
)
async def main(prompt: str):
    """Runs a conversation with the BigQuery agent using the ADK Runner."""
    bq_logger_plugin = BigQueryAgentAnalyticsPlugin(
        project_id=PROJECT_ID, dataset_id=DATASET_ID, table_id=TABLE_ID
    )
    app = App(name=APP_NAME, root_agent=root_agent, plugins=[bq_logger_plugin])
    runner = InMemoryRunner(app=app)

    try:
        session_id = f"{USER_ID}_{uuid.uuid4().hex[:8]}"

        my_session = await runner.session_service.create_session(
            app_name=APP_NAME, user_id=USER_ID, session_id=session_id
        )

        async for event in runner.run_async(
            user_id=USER_ID,
            new_message=types.Content(
                role="user", parts=[types.Part.from_text(text=prompt)]
            ),
            session_id=my_session.id,
        ):
            if event.content.parts and event.content.parts[0].text:
                print(f"** {event.author}: {event.content.parts[0].text}")

    except Exception as e:
        print(f"Error in main: {e}")
    finally:
        print("Closing BQ Plugin...")
        await bq_logger_plugin.close()
        print("BQ Plugin closed.")

async def run_all_prompts():
    """Runs all prompts in a single event loop."""
    prompts = [
        "what outfits do you have available that are suitable for the weather in london this week?",
        "You are such a cool agent! I need a gift idea for my friend who likes yoga.",
        "I'd like to complain - the products sold here are not very good quality!"
    ]
    for prompt in prompts:
        await main(prompt)

if __name__ == "__main__":
    asyncio.run(run_all_prompts())