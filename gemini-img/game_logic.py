# game_logic.py

import os
import google.generativeai as genai
import google.auth
import json
import sys
from PIL import Image
import io
import base64 # Needed for image data

# --- NEW: Import Vertex AI ---
try:
    import vertexai
    from vertexai.preview.vision_models import ImageGenerationModel, ImageGenerationResponse
except ImportError:
    print("ERROR: google-cloud-aiplatform library not found or failed to import.")
    print("Please install it: pip install google-cloud-aiplatform --upgrade")
    sys.exit(1)


# --- Constants ---
SAVE_DIR = os.path.expanduser("~/rpg_saves")
os.makedirs(SAVE_DIR, exist_ok=True)

# --- Authentication and Configuration ---
try:
    credentials, project_id = google.auth.default() # project_id is often retrieved here
    if not project_id:
        # Attempt to get project ID from environment variable if not found by default()
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project_id:
             raise ValueError("Could not determine Google Cloud project ID. Set the GOOGLE_CLOUD_PROJECT environment variable or ensure gcloud is configured correctly.")

    # --- NEW: Vertex AI Configuration ---
    VERTEX_AI_PROJECT = project_id
    # Choose a region where Imagen is available, e.g., us-central1
    VERTEX_AI_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

    # Configure Gemini (as before)
    genai.configure(api_key=credentials.token) # Assuming token-based auth for Gemini here

    # --- NEW: Initialize Vertex AI ---
    vertexai.init(project=VERTEX_AI_PROJECT, location=VERTEX_AI_LOCATION, credentials=credentials)

    print(f"Vertex AI initialized for project '{VERTEX_AI_PROJECT}' in location '{VERTEX_AI_LOCATION}'")

except Exception as e:
    print(f"ERROR: Failed during Authentication or Initialization: {e}", file=sys.stderr)
    print("Ensure gcloud CLI is authenticated ('gcloud auth application-default login') and necessary APIs (Vertex AI, Generative Language) are enabled for your project.", file=sys.stderr)
    sys.exit(1)


# --- Model Selection ---
try:
    # Gemini for text generation
    text_model = genai.GenerativeModel('gemini-1.5-flash')

    # --- NEW: Imagen Model Instance ---
    # NOTE: Model names change. 'imagegeneration@006' is a common stable identifier for Imagen 2/3.
    # The specific 'imagen-3.0-generate-002' might require checking Vertex AI docs for the exact SDK identifier.
    # Using 'imagegeneration@006' as a robust fallback. Change if you confirm the exact identifier.
    imagen_model_name = "imagegeneration@006" # Or try the specific one if confirmed available via SDK
    print(f"Using Imagen model: {imagen_model_name}")
    imagen_model = ImageGenerationModel.from_pretrained(imagen_model_name)

except Exception as e:
    print(f"ERROR: Failed to initialize AI models: {e}", file=sys.stderr)
    sys.exit(1)

# --- Gemini Interaction (Keep as is) ---
def get_gemini_response(prompt, model_to_use):
    """Sends a prompt to the specified Gemini model and returns the text response."""
    print("\n🤖 *Gemini is thinking (Text)...*\n")
    try:
        response = model_to_use.generate_content(prompt)
        if response.parts:
            return response.text
        else:
            print(f"WARN: Gemini response was empty or blocked. Feedback: {response.prompt_feedback}")
            return "The way forward seems blocked by an unseen force."
    except Exception as e:
        print(f"Error communicating with Gemini: {e}", file=sys.stderr)
        return f"An error occurred with text generation: {e}"


# --- NEW: Image Generation with Imagen ---
def generate_image_with_imagen(scene_description):
    """Generates an image based on the scene using Vertex AI Imagen."""
    print("\n🖼️ *Generating image with Imagen...*\n")

    # 1. Create a good prompt for Imagen based on the scene
    # (Could reuse the prompt generation logic, or simplify)
    image_prompt_request = f"""
    Create a concise, descriptive, and visually evocative prompt suitable for an AI image generator based on this RPG scene. Focus on key elements, mood, and style (fantasy art).

    Scene: "{scene_description}"

    Image Prompt:
    """
    image_prompt = get_gemini_response(image_prompt_request, text_model)

    if not image_prompt or "error occurred" in image_prompt.lower():
        print(f"WARN: Could not generate a suitable image prompt from the scene description.")
        # Fallback prompt if Gemini fails
        image_prompt = f"Fantasy RPG scene: {scene_description[:200]}" # Use truncated scene as fallback

    # Refine prompt - remove potential conversational prefixes from Gemini's output
    image_prompt = image_prompt.split("Image Prompt:")[-1].strip()
    print(f"Using Image Prompt: {image_prompt}")


    # 2. Call Imagen Model
    try:
        # Refer to SDK docs for all options: aspect_ratio, style_preset, negative_prompt, etc.
        images: ImageGenerationResponse = imagen_model.generate_images(
            prompt=image_prompt,
            number_of_images=1, # Generate one image
            aspect_ratio="16:9", # Or "1:1", "9:16" etc.
            # seed=12345 # Optional: for reproducibility
            # negative_prompt="text, words, letters, blurry, low quality" # Optional
        )

        if images.images:
            # 3. Process the result - Get Base64 data
            image_obj = images.images[0] # Get the first (and only) image object
            # Access image bytes directly if available
            if hasattr(image_obj, '_blob'):
                 image_bytes = image_obj._blob
                 b64_image_data = base64.b64encode(image_bytes).decode('utf-8')
                 print("Successfully generated image and encoded to base64.")
                 return b64_image_data, None # Return data, no error
            else:
                 print("ERROR: Could not access image bytes (_blob attribute missing). Check SDK version/response structure.")
                 return None, "Failed to process generated image data."

        else:
            # Handle cases where generation might be blocked by safety filters
            # The response object might have safety attributes to check
            print("WARN: Imagen generation resulted in no images. Check safety filters or prompt." ,images._prediction_response)
            # You might want inspect `images._prediction_response` if available for details
            return None, "Image generation failed or was blocked (possibly safety filters)."

    except Exception as e:
        print(f"Error calling Imagen API: {e}", file=sys.stderr)
        # Check for common errors like permissions, quota, invalid arguments
        error_message = f"Error generating image: {e}"
        if "permission denied" in str(e).lower():
            error_message += " (Check Vertex AI permissions for your service account/credentials)"
        elif "quota" in str(e).lower():
             error_message += " (Check Vertex AI Quota for Imagen)"

        return None, error_message


# --- Game State Parsing (Keep as is) ---
def update_game_state_from_response(response_text, current_location, player_inventory):
    # ... (no changes needed here) ...
    new_location = current_location
    new_inventory = list(player_inventory) # Create a copy to modify
    feedback_messages = []
    response_lower = response_text.lower()
    # Detect taking items
    take_keywords = ["you pick up", "you take the", "add ", "acquire the", "find a", "receive a"]
    for keyword in take_keywords:
        if keyword in response_lower:
            try:
                parts = response_lower.split(keyword, 1)[1].split('.')[0].split(',')[0].strip()
                potential_item = parts.replace("your ", "").replace("the ", "").replace("a ", "").replace("an ", "").strip()
                if potential_item and len(potential_item) > 2 and potential_item not in ["it", "nothing", "something"]:
                    if potential_item not in new_inventory:
                        new_inventory.append(potential_item)
                        feedback_messages.append(f"Inventory updated: Added '{potential_item}'")
            except IndexError: pass
    # Detect location changes
    move_keywords = ["you travel to", "you enter the", "you arrive at", "you are now in", "step into the", "reach the", "move to"]
    for keyword in move_keywords:
        if keyword in response_lower:
            try:
                potential_location = response_lower.split(keyword, 1)[1].split('.')[0].split(',')[0].strip()
                potential_location = potential_location.replace("the ", "").replace("a ", "").replace("an ", "").strip()
                if potential_location and len(potential_location) > 3:
                    new_location = potential_location
                    feedback_messages.append(f"Location updated: Now at '{new_location}'")
                    break
            except IndexError: pass
    # Detect dropping/using items
    remove_keywords = ["you drop the", "you use the", "item disappears", "breaks the", "no longer have the", "give the"]
    items_to_remove = []
    for keyword in remove_keywords:
        if keyword in response_lower:
            relevant_part = response_lower.split(keyword, 1)[1][:60]
            for item in new_inventory:
                if item in relevant_part:
                    if item not in items_to_remove: items_to_remove.append(item)
    if items_to_remove:
        for item in items_to_remove:
            if item in new_inventory:
                new_inventory.remove(item)
                feedback_messages.append(f"Inventory updated: Removed '{item}'")
    return new_location, new_inventory, feedback_messages

# --- Save/Load Functions (Keep as is) ---
def save_game(filename, game_state):
    # ... (no changes needed here) ...
    if ".." in filename or "/" in filename or "\\" in filename:
        print(f"Invalid filename characters detected: {filename}")
        return False, f"Invalid filename: '{filename}'. Use alphanumeric characters, underscores, or hyphens."
    filepath = os.path.join(SAVE_DIR, filename + ".json")
    try:
        with open(filepath, 'w') as f: json.dump(game_state, f, indent=4)
        print(f"Game saved successfully to {filepath}!")
        return True, f"Game saved successfully as '{filename}.json' in your saves directory."
    except IOError as e:
        print(f"Error saving game to {filepath}: {e}", file=sys.stderr)
        return False, f"Error saving game: {e}"
    except Exception as e:
        print(f"An unexpected error occurred while saving: {e}", file=sys.stderr)
        return False, f"An unexpected error occurred while saving: {e}"


def load_game(filename):
    # ... (no changes needed here) ...
    if ".." in filename or "/" in filename or "\\" in filename:
        print(f"Invalid filename characters detected: {filename}")
        return None, f"Invalid filename: '{filename}'. Use alphanumeric characters, underscores, or hyphens."
    filepath = os.path.join(SAVE_DIR, filename + ".json")
    if not os.path.exists(filepath):
         return None, f"Save file '{filename}.json' not found in saves directory."
    try:
        with open(filepath, 'r') as f: game_state = json.load(f)
        if all(k in game_state for k in ["current_location", "player_inventory", "last_scene", "chat_history"]):
            print(f"Game loaded successfully from {filepath}!")
            return game_state, f"Game loaded successfully from '{filename}.json'!"
        else:
            print(f"Save file {filepath} seems corrupted.", file=sys.stderr)
            return None, f"Save file '{filename}.json' appears corrupted. Cannot load."
    except (IOError, json.JSONDecodeError) as e:
        print(f"Error loading game from {filepath}: {e}", file=sys.stderr)
        return None, f"Error loading game '{filename}.json': {e}"
    except Exception as e:
        print(f"An unexpected error occurred while loading: {e}", file=sys.stderr)
        return None, f"An unexpected error occurred while loading: {e}"

# --- Initial Game Setup (Keep as is) ---
def start_new_game(initial_player_prompt):
    # ... (no changes needed here) ...
    current_location = "an unknown starting point"
    player_inventory = []
    chat_history = [{"role": "user", "content": initial_player_prompt}]
    full_initial_prompt = f"""
    Roleplay: You are the Dungeon Master for a text-based fantasy RPG.
    Task: Start a new adventure based on the player's first action or thought.
    Player's input: '{initial_player_prompt}'
    Instructions:
    1. Describe the initial location ({current_location}) vividly.
    2. Set the scene and atmosphere (e.g., dark forest, bustling market, ancient ruin).
    3. Hint at possible first actions or observations for the player.
    4. The player starts with no items in their inventory.
    5. Respond only with the narrative description for the player. Do not add instructions like "What do you do?". That prompt will come from the game interface.
    """
    scene_description = get_gemini_response(full_initial_prompt, text_model)
    if scene_description and "error occurred" not in scene_description.lower():
        chat_history.append({"role": "model", "content": scene_description})
        game_state = { "current_location": current_location, "player_inventory": player_inventory, "last_scene": scene_description, "chat_history": chat_history }
        parsed_loc, _, _ = update_game_state_from_response(scene_description, current_location, player_inventory)
        game_state["current_location"] = parsed_loc
        return game_state, "New adventure started!"
    else:
        error_msg = scene_description if scene_description else "Failed to get the initial scene description from Gemini."
        return None, error_msg


# --- Process Player Turn (Keep as is) ---
def process_player_action(player_action, game_state):
    # ... (no changes needed here) ...
    current_location = game_state["current_location"]
    player_inventory = game_state["player_inventory"]
    last_scene = game_state["last_scene"]
    chat_history = game_state["chat_history"]
    chat_history.append({"role": "user", "content": player_action})
    history_context = ""
    limit = 10
    for entry in chat_history[-(limit+1):-1]:
         history_context += f"\n{entry['role'].capitalize()}: {entry['content']}"
    prompt = f"""
    Roleplay: You are the Dungeon Master for a text-based fantasy RPG.
    Task: Narrate the outcome of the player's action based on the current situation and history.
    Current Location: {current_location}
    Player Inventory: {', '.join(player_inventory) or 'nothing'}
    Recent History: {history_context.strip()}
    Player's Action: "{player_action}"
    Instructions:
    1. Describe the results of the player's action creatively and consistently.
    2. Update the scene description based on the action's outcome.
    3. If the player's action logically leads to picking up an item, finding something new, or moving to a distinctly new area, mention it naturally within the narrative (e.g., "You pocket the glowing gem.", "You step cautiously into the echoing cavern.").
    4. Maintain a fantasy RPG tone.
    5. Respond *only* with the narrative description for the player. Do not add instructions like "What do you do next?".
    """
    response_text = get_gemini_response(prompt, text_model)
    feedback_messages = []
    if response_text and "error occurred" not in response_text.lower():
        chat_history.append({"role": "model", "content": response_text})
        new_location, new_inventory, parse_feedback = update_game_state_from_response(
            response_text, current_location, player_inventory
        )
        feedback_messages.extend(parse_feedback)
        game_state["current_location"] = new_location
        game_state["player_inventory"] = new_inventory
        game_state["last_scene"] = response_text
        game_state["chat_history"] = chat_history
        return game_state, response_text, feedback_messages
    else:
        chat_history.pop() # Remove failed user action
        game_state["chat_history"] = chat_history
        error_message = response_text if response_text else "The AI seems unresponsive. Please try your action again."
        feedback_messages.append(error_message)
        return game_state, game_state["last_scene"], feedback_messages