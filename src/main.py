import os
from google import genai
from dotenv import load_dotenv

# 1. Load environment variables from the local .env file
load_dotenv()

# 2. Verify that the API key was loaded correctly
if not os.getenv("GOOGLE_API_KEY"):
    raise ValueError("GOOGLE_API_KEY not found! Please check your .env file.")

# 3. Initialize the client (automatically picks up GOOGLE_API_KEY from environment)
client = genai.Client()

# 4. Make a test call
response = client.models.generate_content(
    model="gemini-3.6-flash",
    contents="What is Python.",
)

print(response.text)
