# README.md - Speakr

## Overview

Speakr is a Python application that records audio from a microphone and transcribes it to text using Azure Speech-to-Text services. It also includes Text-to-Speech functionality using Azure OpenAI TTS. The transcribed text is copied to the clipboard and pasted into the active application. It runs in the system tray for easy access.

## Installation

1. **Install Dependencies**:
   Open a terminal and run:
   ```bash
   pip install -r requirements.txt
   ```

2. **Set Azure API Details**:
   Copy [`config.yaml-template`](config.yaml-template) to `config.yaml` and fill in your Azure credentials there.
   

3. **Provide Sound Files**:
   Add short WAV files for feedback sounds ([`start.wav`](start.wav ), [`stop.wav`](stop.wav ), [`cancel.wav`](cancel.wav ), [`send.wav`](send.wav )) in the same directory as the script.

4. **Run the App**:
   In the terminal, execute:
   ```bash
   python speakr.py
   ```

## Usage

### Speech-to-Text
- The application runs in the system tray.
- Press **Alt + B** to start recording.
- Release or press **Alt + B** again to stop recording and transcribe the audio.
- Press **Esc** during recording to cancel.
- Right-click the tray icon to select a microphone or exit the application.

### Text-to-Speech
- Copy or highlight text that you want to hear spoken.
- Press **Alt + Windows key** to hear it (it may take a few seconds).
- Press **Esc ** to cancel the sound playback.
- Right-click the tray icon and select **TTS Voice** to choose from available voices (alloy, ash, ballad, coral, echo, fable, onyx, nova, sage, shimmer, verse).

### Proofread (LLM)
- Highlight text in any app.
- Press **Ctrl + Windows key**.
- The selected text is copied, sent to Azure LLM with `azure.proofread.system_prompt`, and the corrected version is pasted back.

## Building an Executable

To create a standalone executable, use PyInstaller with the following command:
```bash
pyinstaller --noconfirm --onefile --windowed --icon=speaking.ico --add-data "start.wav;." --add-data "stop.wav;." --add-data "cancel.wav;." --add-data "send.wav;." --add-data "speaking.ico;." speakr.py
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.