import requests
import os

# --- Configuration: UPDATE THESE VALUES ---

# 1. Get this from the API Gateway console after deploying your API (Step 6 in the guide).
#    It should look like: https://xxxxxxxxx.execute-api.us-east-1.amazonaws.com/v1
API_GATEWAY_URL = "YOUR_API_GATEWAY_INVOKE_URL" 

# 2. This is the API key you generated for a test participant (Step 6).
API_KEY = "ga6AmUXEjh4IslS1RpC3E3mQxF9wtsxg2IRfPCN2"

# 3. Path to the submission file you want to upload.
SUBMISSION_FILE_PATH = os.path.join("submissions", "submission.csv")

# --- End of Configuration ---


def submit_to_pipeline(api_url: str, api_key: str, file_path: str):
    """
    Reads a submission file and sends it to the AWS evaluation pipeline.
    """
    # --- 1. Validate Inputs ---
    if "YOUR_API_GATEWAY" in api_url or "YOUR_PARTICIPANT_API_KEY" in api_key:
        print("ERROR: Please update the API_GATEWAY_URL and API_KEY variables in the script.")
        return

    if not os.path.exists(file_path):
        print(f"ERROR: Submission file not found at '{file_path}'")
        print("Please generate a submission file first by running one of the src/ scripts.")
        return

    # --- 2. Prepare the Request ---
    # The endpoint is the base URL + the resource path
    submit_url = f"{api_url.rstrip('/')}/submit"
    
    # Set the required header for authentication
    headers = {
        'x-api-key': api_key,
        'Content-Type': 'text/csv' # Specify the content type
    }

    # Read the content of the CSV file to be sent as the request body
    with open(file_path, 'r') as f:
        file_content = f.read()

    print(f"Sending submission from '{file_path}' to '{submit_url}'...")

    # --- 3. Send the POST Request ---
    try:
        response = requests.post(submit_url, headers=headers, data=file_content)
        
        # Raise an exception for bad status codes (4xx or 5xx)
        response.raise_for_status()

        print("\n--- Success! ---")
        print(f"Status Code: {response.status_code}")
        print("Response from server:")
        print(response.json())

    except requests.exceptions.HTTPError as http_err:
        print(f"\n--- HTTP Error Occurred ---")
        print(f"Status Code: {http_err.response.status_code}")
        print("Response from server:")
        try:
            print(http_err.response.json())
        except ValueError:
            print(http_err.response.text)
    except requests.exceptions.RequestException as err:
        print(f"\n--- An Error Occurred ---")
        print(err)


if __name__ == "__main__":
    submit_to_pipeline(API_GATEWAY_URL, API_KEY, SUBMISSION_FILE_PATH)

