# ComfyUI Sync Translate Node

This custom node allows you to create lipsynced translated videos for a target language. For voice cloning and TTS, ElevenLabs is used. For transcription & translation, OpenAI is used.

## Installation & Usage

After cloning [ComfyUI](https://github.com/comfyanonymous/ComfyUI) and setting up a virtual environment for it, follow these steps:

1. Navigate to the custom nodes directory:  
   `cd /path/to/ComfyUI/custom_nodes/`

2. Clone this repository:  
   `git clone https://github.com/wasilone11/comfyui-sync-translate-node.git`

3. Install the required dependencies:  
   `pip install -r comfyui-sync-translate-node/requirements.txt`

4. Go back to the main ComfyUI directory and run:  
   `cd /path/to/ComfyUI/`  
   `python main.py`

5. A link will be printed in the terminal — open it in your browser to access the ComfyUI GUI.

6. In the ComfyUI interface:  
   - On the left sidebar, go to the **Nodes** tab.  
   - Search for **Sync**.  
   - Open the **Sync** node and locate the translate input and translate worker node. Add them to the UI and join them.
   - Click **Run** to generate the output!
   - The output video link will be saved in the json file along with the job ID.

---

For issues or contributions, feel free to open a pull request or create an issue in this repository. Moreover, you can also refer to: `https://github.com/synchronicity-labs/sync-examples/tree/main/translation/python`

